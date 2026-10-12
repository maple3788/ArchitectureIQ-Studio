import copy
import json

import pytest

from test_studio_rag_api import case_for_api
from rule_refinement_fixtures import raw_case, rule_entry
from test_studio_catalog import bakefile
from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore


def task(case, **changes):
    response = case['client'].post('/api/studio/tasks', json={
        'name': 'Compare architectures', 'question_key': case['question_key'],
        'model_id': 'glm', **changes})
    assert response.status_code == 200, response.text
    return response.json()


def preview(case, card):
    response = case['client'].post(f"/api/studio/tasks/{card['id']}/preview",
                                 json={'expected_revision': card['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def run(case, card, shown, key='one'):
    return case['client'].post(f"/api/studio/tasks/{card['id']}/runs", json={
        'expected_revision': card['revision'], 'preview_hash': shown['preview_hash']},
        headers={'Idempotency-Key': key})


def rules_case(tmp_path, monkeypatch, entries=None):
    case = case_for_api(tmp_path, monkeypatch)
    case['catalog'].import_source(bakefile(tmp_path / 'rules-questions.json', [raw_case()]))
    case['question_key'] = next(q['key'] for q in case['catalog'].list_questions()['items'] if q['id'] == 'q_rule')
    case['inventory']['items'] = []
    for index, rules in enumerate(entries or [[rule_entry()]]):
        snapshot = RuleArtifactStore(tmp_path / f'kb-{index}').import_rules(
            {'rules': rules}, source_ref={'id': f'kb-{index}'})
        case['inventory']['items'].append({'id': f'kb-{index}', 'version': snapshot['version'],
            'name': f'KB {index}', 'kind': 'research_rules', 'snapshot': snapshot,
            'sources': [{'id': f'kb-{index}', 'kind': 'run', 'path': '/private/should-not-leak'}],
            'source': '/private/should-not-leak', 'summary': 'Research hypothesis'})
    return case


def test_cards_are_durable_independent_and_compare_and_swap(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch)
    before = case['client'].get('/api/studio/workflow/draft').json()
    first, second = task(case), task(case, name='Second')
    edited = case['client'].put('/api/studio/tasks/' + first['id'], json={
        'expected_revision': first['revision'], 'name': 'Changed'})
    assert edited.status_code == 200 and edited.json()['revision'] == 2
    stale = case['client'].put('/api/studio/tasks/' + first['id'], json={
        'expected_revision': first['revision'], 'name': 'Stale'})
    assert stale.status_code == 409
    listed = case['client'].get('/api/studio/tasks').json()['items']
    assert len(listed) == 2 and next(c for c in listed if c['id'] == second['id'])['name'] == 'Second'
    assert case['client'].get('/api/studio/workflow/draft').json() == before
    from architecture_iq.studio.tasks import TaskStore
    assert TaskStore(case['state_root']).get(first['id'])['name'] == 'Changed'


def test_model_preview_and_history_do_not_leak_private_configuration(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case)
    shown = preview(case, card)
    assert shown['can_run'] and shown['selected_kbs'] and shown['request']['payload']['messages']
    first = run(case, card, shown)
    again = run(case, card, shown)
    assert first.status_code == again.status_code == 200
    assert first.json()['id'] == again.json()['id'] and first.json()['job_id']
    history = case['client'].get(f"/api/studio/tasks/{card['id']}/runs").json()
    assert len(history['items']) == len(case['launches']) == 1
    text = json.dumps([shown, first.json(), history])
    for forbidden in ('models.example.test', 'base_url', 'runtime_lock_path', 'correct_letter', str(tmp_path)):
        assert forbidden not in text


def test_model_run_guard_still_applies(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch)
    card = task(case)
    assert run(case, card, preview(case, card)).status_code == 409
    assert not case['jobs'].list()


@pytest.mark.parametrize('change', ['card', 'inventory', 'model', 'fingerprint'])
def test_changed_inputs_reject_frozen_preview(tmp_path, monkeypatch, change):
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case); shown = preview(case, card)
    if change == 'card':
        case['client'].put('/api/studio/tasks/' + card['id'], json={'expected_revision': 1, 'name': 'Renamed'})
    elif change == 'inventory':
        case['inventory']['items'] = []
    elif change == 'model':
        model = case['models'].get('glm'); model.pop('revision'); model['parameters']['max_tokens'] += 1
        case['models'].save(model)
    else:
        monkeypatch.setattr('architecture_iq.studio.jobs.source_fingerprint', lambda: 'changed')
    assert run(case, card, shown).status_code == 409
    assert not case['jobs'].list()


def test_manual_kb_ref_is_frozen_and_not_silently_replaced(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch)
    item = case['inventory']['items'][0]
    card = task(case, kb_selection={'mode': 'manual', 'ref': {k: item[k] for k in ('id', 'version')}})
    assert preview(case, card)['selected_kbs'][0]['id'] == item['id']
    case['inventory']['items'] = []
    assert case['client'].post(f"/api/studio/tasks/{card['id']}/preview", json={'expected_revision': 1}).status_code == 422


def test_rule_answer_never_reads_gt_or_calls_model_and_is_persisted(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    original = case['catalog'].get_question
    def only_public(key, *, include_private=False):
        assert not include_private
        return original(key, include_private=False)
    monkeypatch.setattr(case['catalog'], 'get_question', only_public)
    monkeypatch.setattr('architecture_iq.studio.execution.create_client', lambda *a, **k: pytest.fail('No model'))
    card = task(case, mode='rules', model_id=None)
    shown = preview(case, card)
    assert shown['prediction']['answer_letter'] == 'A' and shown['can_run']
    result = run(case, card, shown)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'complete'
    assert result.json()['result']['prediction']['answer_id'] == 'c_A'
    assert run(case, card, shown).json()['id'] == result.json()['id']
    assert not case['jobs'].list() and not (case['state_root'] / 'rule_evaluations').exists()
    text = json.dumps([shown, result.json()])
    assert 'correct_letter' not in text and '/private/' not in text
    assert shown['selected_kbs'][0]['kind'] == 'research_rules'


@pytest.mark.parametrize('entries', [
    [[rule_entry()], [rule_entry(lower=True)]],
    [[rule_entry()], [rule_entry((16, 8)), rule_entry((16, 8), lower=True)]],
])
def test_auto_rule_conflicts_abstain_across_kbs(tmp_path, monkeypatch, entries):
    case = rules_case(tmp_path, monkeypatch, entries)
    shown = preview(case, task(case, mode='rules', model_id=None))
    assert shown['prediction']['status'] == 'conflict'
    assert shown['prediction']['answer_id'] is None and not shown['can_answer']
    assert shown['can_run']


def test_opposing_partial_kbs_are_still_a_conflict(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch, [[rule_entry((32, 16))], [rule_entry((32, 16), lower=True)]])
    shown = preview(case, task(case, mode='rules'))
    assert shown['prediction']['status'] == 'conflict'


def test_formal_rules_use_original_status_and_pair_scope(tmp_path, monkeypatch):
    from architecture_iq.studio.task_answers import formal_rule_admission
    from test_kb_workflow_rules import scoped_pair
    question, claim, a, b = scoped_pair()
    claim.update(id='claim', status='replicated_in_scope', enabled=True, rule=rule_entry()['rule'])
    item = {'snapshot': {'claims': [claim]}}
    rule = {'rule': claim['rule'], 'source_refs': [{'source_claim_id': 'claim'}]}
    admit = formal_rule_admission(question, item)
    assert admit(rule, a, b)
    assert not admit(rule, a, {**b, 'budget': b['budget'] + 1})
    claim['enabled'] = False
    assert not admit(rule, a, b)
    claim.update(enabled=True, status='legacy_unverified')
    assert not admit(rule, a, b)


def test_formal_split_clause_does_not_inherit_sibling_authority():
    from architecture_iq.studio.task_answers import formal_rule_admission
    from test_kb_workflow_rules import scoped_pair
    question, claim, a, b = scoped_pair()
    rule_body = {'predict': {'higher_better': 'width'}}
    first = {**claim, 'id': 'original', 'source_claim_id': 'original', 'source_clause_index': 1,
             'rule': rule_body, 'status': 'replicated_in_scope', 'enabled': True}
    second = {**first, 'id': 'second', 'source_clause_index': 2, 'enabled': False}
    rule = {'rule': rule_body, 'source_refs': [{'source_claim_id': 'original', 'source_clause_index': 2}]}
    assert not formal_rule_admission(question, {'snapshot': {'claims': [first, second]}})(rule, a, b)


def test_canonical_prediction_hook_is_optional_and_gates_pairs(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    from rule_refinement_fixtures import public_case
    kb = RuleArtifactStore(tmp_path).import_rules({'rules': [rule_entry()]}, source_ref={'id': 'fixture'})
    normal = predict_question(public_case(), kb)
    assert normal['status'] == 'answered'
    assert predict_question(public_case(), kb, rule_admission=lambda *args: True) == normal
    denied = predict_question(public_case(), kb, rule_admission=lambda *args: False)
    assert denied['status'] == 'uncovered' and denied['edges'] == []


def test_unusable_rule_source_is_warned_without_faking_validation(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    case['inventory']['items'][0]['snapshot']['rules'][0]['text'] = 'tampered'
    shown = preview(case, task(case, mode='rules'))
    assert shown['warnings'][0]['code'] == 'kb_unavailable'
    assert shown['prediction']['answer_id'] is None and shown['selected_kbs'] == []


def test_retry_of_committed_answer_survives_card_edits_and_keeps_original(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    card = task(case, mode='rules'); shown = preview(case, card)
    committed = run(case, card, shown).json()
    case['client'].put('/api/studio/tasks/' + card['id'], json={'expected_revision': 1, 'name': 'Next experiment'})
    assert run(case, card, shown).json() == committed


def test_model_task_runs_through_existing_worker_and_history_updates(tmp_path, monkeypatch):
    from architecture_iq.studio.execution import worker
    from rag_fixtures import rag_client
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case); shown = preview(case, card)
    started = run(case, card, shown).json()
    case['config'] = case['jobs'].definition(started['job_id'])['config']
    monkeypatch.setattr('architecture_iq.studio.execution.create_client', rag_client(case))
    worker(case['state_root'], started['job_id'])
    saved = case['client'].get(f"/api/studio/tasks/{card['id']}/runs").json()['items'][0]
    assert saved['status'] == 'complete' and saved['result']['answer']['ranking'] == ['A', 'B', 'C']
    assert len(case['calls']) == 1 and 'models.example.test' not in json.dumps(saved)


def test_committed_queued_model_task_can_recover_dispatch_once(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case); shown = preview(case, card)
    launch = case['jobs'].launch
    def interrupted(identifier):
        raise OSError('Interrupted before dispatch')
    monkeypatch.setattr(case['jobs'], 'launch', interrupted)
    assert run(case, card, shown).status_code == 422
    monkeypatch.setattr(case['jobs'], 'launch', launch)
    retry = run(case, card, shown)
    assert retry.status_code == 200 and retry.json()['status'] == 'starting'
    assert len(case['launches']) == 1
    assert run(case, card, shown).json()['id'] == retry.json()['id']
    assert len(case['launches']) == 1


def test_concurrent_task_edits_have_only_one_winner(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from architecture_iq.studio.tasks import TaskStore, TaskConflict
    case = case_for_api(tmp_path, monkeypatch)
    card = task(case)
    def save(name):
        try:
            return TaskStore(case['state_root']).save(card['id'], expected_revision=1, changes={'name': name})
        except TaskConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ['First', 'Second']))
    assert sum(result is not None for result in results) == 1


def test_rule_uncovered_is_not_a_fake_answer_and_catalog_filters_modes(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch, [[rule_entry((32, 16))]])
    shown = preview(case, task(case, mode='rules'))
    assert shown['prediction']['status'] == 'uncovered' and not shown['can_answer']
    assert len(case['client'].get('/api/studio/tasks/kbs?mode=rules').json()['items']) == 1
    assert case['client'].get('/api/studio/tasks/kbs?mode=llm').json()['items'] == []


@pytest.mark.parametrize('body', [
    {'mode': 'shell'}, {'knowledge_limit': True}, {'knowledge_limit': 13},
    {'kb_selection': {'mode': 'manual', 'ref': {'path': '/tmp/secret'}}},
    {'model_id': {'secret': 'x'}}, {'config': {}},
])
def test_task_request_shapes_are_bounded(tmp_path, monkeypatch, body):
    case = case_for_api(tmp_path, monkeypatch)
    assert case['client'].post('/api/studio/tasks', json=body).status_code == 422
