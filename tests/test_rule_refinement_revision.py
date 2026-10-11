from copy import deepcopy
import json
import multiprocessing
import time
from types import SimpleNamespace

import pytest
from architecture_iq.kb.roles import RoleCaller, read_receipt
from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
from architecture_iq.studio.rule_refinement.budget import BudgetLedger, BudgetExceeded, UncertainOperation
from rule_refinement_fixtures import limits, rule_entry, public_case, raw_case
from test_rule_refinement_scoring import setup_batch, evaluate
from test_kb_workflow_roles import Model


class Provider:
    max_retries = 0
    def __init__(self, response=None, *, fail=False, hang=False, finish='stop'):
        self.count = multiprocessing.get_context('fork').Value('i', 0)
        self.response, self.fail, self.hang, self.finish = response, fail, hang, finish
    def complete(self, prompt, model):
        with self.count.get_lock():
            self.count.value += 1
        if self.fail:
            raise TimeoutError('secret-provider-sentinel')
        if self.hang:
            while True:
                time.sleep(.01)
        return SimpleNamespace(raw={'model': model.name, 'choices':[{'message':{'content':json.dumps(self.response)}}]},
                               usage={'prompt_tokens':50,'completion_tokens':20}, finish_reason=self.finish)


def material(root):
    from architecture_iq.studio.rule_refinement.revision import build_revision_payload
    pool,kb,gt = setup_batch(root, entries=[rule_entry(),rule_entry(lower=True)])
    score = evaluate(root,pool,kb,gt)
    payload = build_revision_payload(kb,score,seen_case_refs=[],max_input_bytes=30000,grouping=['type','rule','family'])
    return kb,score,payload


def proposer(root, provider, **changes):
    return (RoleCaller(root,provider,Model(),fingerprint='fake',max_context=100000,max_tokens=200000),
            BudgetLedger(root,limits(**changes),clock=time.time))


def test_conflicts_and_rule_counterexamples_share_revision_queue(tmp_path):
    kb,score,payload = material(tmp_path)
    assert {'conflict','rule_counterexample'} <= {p['type'] for p in payload['full_index']}
    assert len(payload['case_refs']) == len(score['problems'])
    assert payload['material']['kb'] == kb
    assert payload['remaining_count'] == 0


def test_context_chunking_preserves_full_index_and_seen_ledger(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import build_revision_payload
    kb,score,payload = material(tmp_path)
    size = len(json.dumps(payload['material'],ensure_ascii=False,sort_keys=True).encode())
    first = build_revision_payload(kb,score,seen_case_refs=[],max_input_bytes=size-100,grouping=['type','rule','family'])
    assert 0 < len(first['case_refs']) < len(first['full_index'])
    second = build_revision_payload(kb,score,seen_case_refs=first['case_refs'],max_input_bytes=size-100,grouping=['type','rule','family'])
    assert set(second['case_refs']) - set(first['case_refs'])
    assert first['full_index'] == second['full_index']
    with pytest.raises(ValueError,match='context'):
        build_revision_payload(kb,score,seen_case_refs=[],max_input_bytes=10,grouping=[])


@pytest.mark.parametrize('defect', ['unknown_field','stale','unknown_case','illegal_rule','truncated'])
def test_invalid_patch_still_charged_once(tmp_path,defect):
    from architecture_iq.studio.rule_refinement.revision import propose_patch
    kb,score,payload = material(tmp_path)
    patch = dict(base_version=kb['version'],operations=[dict(op='add',entry=rule_entry())],rationale='claim success',case_refs=payload['case_refs'])
    if defect == 'unknown_field': patch['budget'] = 0
    if defect == 'stale': patch['base_version'] = '0'*64
    if defect == 'unknown_case': patch['case_refs'] = ['invented']
    if defect == 'illegal_rule': patch['operations'][0]['entry']['rule'] = {'predict':{'higher_better':'correct_letter'}}
    provider = Provider(patch,finish='length' if defect=='truncated' else 'stop')
    caller,ledger = proposer(tmp_path,provider)
    result = propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert result['outcome'] == 'invalid'
    assert result == propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert provider.count.value == 1 and ledger.snapshot()['revision_attempts'] == 1
    assert result['seen_case_refs'] == payload['case_refs']
    assert caller.usage(0)['calls'] == 1
    assert not (tmp_path/'accepted.json').exists()


def test_valid_candidate_is_saved_but_never_accepted(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import propose_patch
    kb,score,payload=material(tmp_path)
    patch=dict(base_version=kb['version'],operations=[dict(op='retire',rule_id=kb['rules'][1]['rule_id'],revision=kb['rules'][1]['revision'])],rationale='',case_refs=payload['case_refs'])
    provider=Provider(patch)
    caller,ledger=proposer(tmp_path,provider)
    result=propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert result['outcome']=='proposed'
    assert RuleArtifactStore(tmp_path).get(result['candidate_version'])['parent_version']==kb['version']
    assert not (tmp_path/'accepted.json').exists()
    assert read_receipt(tmp_path/result['index_ref'])['cases']==payload['full_index']


def test_lost_response_never_reissues_request_or_leaks_error(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import propose_patch
    kb,_,payload=material(tmp_path)
    provider=Provider(fail=True)
    caller,ledger=proposer(tmp_path,provider)
    with pytest.raises(UncertainOperation):
        propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    with pytest.raises(UncertainOperation):
        propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert provider.count.value==1 and ledger.snapshot()['model_calls']==1
    assert all('secret-provider-sentinel' not in p.read_text() for p in tmp_path.rglob('*.json'))


def test_total_deadline_kills_streaming_operation_and_does_not_retry(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import propose_patch
    kb,_,payload=material(tmp_path)
    provider=Provider(hang=True)
    caller,ledger=proposer(tmp_path,provider,wall_time_seconds=1)
    before=time.monotonic()
    with pytest.raises(UncertainOperation):
        propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert time.monotonic()-before < 3
    assert provider.count.value==1
    assert ledger.snapshot()['operations']['revision-1']['outcome']=='uncertain'


def test_token_preflight_does_not_call_provider(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import propose_patch
    kb,_,payload=material(tmp_path)
    provider=Provider({})
    caller,ledger=proposer(tmp_path,provider,max_tokens=1)
    with pytest.raises(BudgetExceeded):
        propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert provider.count.value==0


def test_initialization_has_public_cases_only_and_cannot_reuse_scored_material(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import build_initial_payload, propose_patch
    kb,_,scored=material(tmp_path)
    payload=build_initial_payload(kb,[public_case()],max_input_bytes=20000)
    assert 'feedback' not in json.dumps(payload) and 'correct_letter' not in json.dumps(payload)
    caller,ledger=proposer(tmp_path,Provider({}))
    with pytest.raises(ValueError):
        propose_patch(caller,ledger,attempt_id='initialize',kb=kb,payload=scored,initialize=True)


def test_revision_requires_matching_persisted_score(tmp_path):
    from architecture_iq.studio.rule_refinement.revision import propose_patch
    kb,score,payload=material(tmp_path)
    (tmp_path/score['receipt_ref']).unlink()
    caller,ledger=proposer(tmp_path,Provider({}))
    with pytest.raises((ValueError,FileNotFoundError)):
        propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)


def test_client_timeout_is_optional_and_bounded(monkeypatch):
    from architecture_iq.studio import execution
    class Client:
        def __init__(self, **kwargs): self.options=kwargs
        def complete_conversation(self): pass
    monkeypatch.setattr(execution,'_tools',lambda: (Client,None,None))
    monkeypatch.setattr(execution,'read_credential',lambda *_: 'secret')
    profile={'base_url':'http://example.invalid'}
    assert execution.create_client(profile,None).options['timeout_s']==900
    assert execution.create_client(profile,None,timeout_s=2).options['timeout_s']==2
    with pytest.raises(ValueError): execution.create_client(profile,None,timeout_s=0)


def test_crash_after_reservation_before_send_is_not_replayed(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import revision
    kb,_,payload=material(tmp_path)
    caller,ledger=proposer(tmp_path,Provider({}))
    original=ledger.reserve
    def crashed(*args,**kwargs):
        original(*args,**kwargs)
        raise SystemExit('simulated crash before network')
    monkeypatch.setattr(ledger,'reserve',crashed)
    with pytest.raises(SystemExit):
        revision.propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    monkeypatch.setattr(ledger,'reserve',original)
    with pytest.raises(UncertainOperation):
        revision.propose_patch(caller,ledger,attempt_id='revision-1',kb=kb,payload=payload)
    assert caller.client.count.value==0
