from copy import deepcopy
import json
import time

import pytest
from architecture_iq.kb.store import write_json_atomic
from architecture_iq.studio.jobs import JobStore
from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.rule_refinement.budget import BudgetLedger, BudgetExceeded, UncertainOperation
from rule_refinement_fixtures import limits
from test_studio_generation import config
from test_studio_pair_generation import request
from test_studio_dataset_generation import staged_result


def setup(tmp_path, *, duration=60):
    from architecture_iq.studio.rule_refinement.challenges import prepare_challenge
    jobs=JobStore(tmp_path/'state')
    parent=jobs.create('workflow',{'protocol':'rule_refinement_v1','generation':config(), 'limits':limits(wall_time_seconds=duration)})
    ledger=BudgetLedger(jobs.directory(parent['id'])/'refinement',parent['config']['limits'],clock=time.time)
    frozen=prepare_challenge(config(),attempt_index=1,questions_per_batch=16)
    return jobs,parent,ledger,frozen


def test_sixteen_questions_becomes_eight_complete_pairs():
    from architecture_iq.studio.rule_refinement.challenges import prepare_challenge
    first=prepare_challenge(request(n_seeds=2),attempt_index=1,questions_per_batch=16)
    second=prepare_challenge(request(n_seeds=2),attempt_index=2,questions_per_batch=16)
    assert first['num_questions']==8 and first['requested_question_count']==16
    assert first['candidate_seed_runs']==16*3*2
    assert {p['seed'] for p in first['pair_plan']}.isdisjoint({p['seed'] for p in second['pair_plan']})
    with pytest.raises(ValueError): prepare_challenge(request(),attempt_index=1,questions_per_batch=15)
    with pytest.raises(ValueError): prepare_challenge(config(split='final'),attempt_index=1,questions_per_batch=16)
    bad=deepcopy(first);bad['profile_hash']='changed'
    with pytest.raises(ValueError): prepare_challenge(bad,attempt_index=1,questions_per_batch=16)


def test_child_cost_is_reserved_before_launch_and_attempt_is_idempotent(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import challenges
    jobs,parent,ledger,frozen=setup(tmp_path)
    launched=[]
    def launch(child):
        assert ledger.snapshot()['candidate_seed_runs']==frozen['candidate_seed_runs']
        assert ledger.snapshot()['generation_attempts']==1
        challenges.read_parent_binding(jobs,child)
        launched.append(child)
        jobs.update(child,status='complete')
    monkeypatch.setattr(jobs,'launch',launch)
    monkeypatch.setattr(challenges,'recover_challenge',lambda jobs,catalog,child_id,parent_id: dict(child_id=child_id,requested_question_count=16,question_keys=[],pairs=[],outcome='insufficient',receipt_ref='challenges/result.json'))
    result=challenges.run_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    again=challenges.run_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    assert again['child_id']==result['child_id'] and launched==[result['child_id']]
    assert ledger.snapshot()['new_questions']==0
    assert ledger.snapshot()['candidate_seed_runs']==frozen['candidate_seed_runs']
    changed=deepcopy(frozen);changed['seed']+=1
    with pytest.raises(ValueError): challenges.run_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=changed,ledger=ledger)


def test_recover_terminal_manifest_without_rerunning_gt(tmp_path,monkeypatch):
    from architecture_iq.studio.dataset_generation import completed_generation_result
    c,jobs,_,_,job,_,manifest=staged_result(tmp_path)
    monkeypatch.setattr(jobs,'launch',lambda *_: pytest.fail('recovery must be read-only'))
    before=manifest.read_bytes()
    result=completed_generation_result(jobs,c,job['id'])
    assert len(result['question_keys'])==1 and result['outcome']=='complete'
    assert completed_generation_result(jobs,c,job['id'])==result and manifest.read_bytes()==before
    value=json.loads(before);value['status']='running';manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError): completed_generation_result(jobs,c,job['id'])


def test_partial_and_duplicate_batch_never_counts_as_pass(tmp_path):
    from architecture_iq.studio.dataset_generation import completed_generation_result
    c,jobs,_,_,job,_,manifest=staged_result(tmp_path)
    value=json.loads(manifest.read_text());value['status']='partial';manifest.write_text(json.dumps(value))
    result=completed_generation_result(jobs,c,job['id'])
    assert result['outcome']=='partial' and 'batch_passed' not in result
    assert result['question_keys']==completed_generation_result(jobs,c,job['id'])['question_keys']


def test_incomplete_generated_directory_is_uncertain_and_never_launched(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import challenges
    jobs,parent,ledger,frozen=setup(tmp_path)
    binding=challenges.bind_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    (jobs.directory(binding['child_id'])/'generated').mkdir()
    monkeypatch.setattr(jobs,'launch',lambda *_:pytest.fail('must not replay'))
    with pytest.raises(UncertainOperation):
        challenges.run_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    assert ledger.snapshot()['candidate_seed_runs']==frozen['candidate_seed_runs']


def test_bound_generation_pause_checks_parent_stop_and_deadline(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import challenges
    jobs,parent,ledger,frozen=setup(tmp_path)
    binding=challenges.bind_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    bound=challenges.BoundGenerationStore(jobs.state_root)
    control=ledger.root/'control.json'
    write_json_atomic(control,{'action':'pause'})
    def stop(_): write_json_atomic(control,{'action':'stop'})
    monkeypatch.setattr(challenges.time,'sleep',stop)
    with pytest.raises(challenges.RefinementStopped): bound.boundary(binding['child_id'],{'stage':'candidate'})
    write_json_atomic(control,{'action':'pause'})
    monkeypatch.setattr(challenges.time,'time',lambda: ledger.snapshot()['deadline'])
    with pytest.raises(BudgetExceeded): bound.boundary(binding['child_id'])


def test_watchdog_checks_binding_pid_stamp_and_only_kills_owned_group(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import challenges
    jobs,parent,ledger,frozen=setup(tmp_path)
    binding=challenges.bind_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    child=binding['child_id'];jobs.update(child,status='running',pid=456,process_stamp='birth')
    monkeypatch.setattr(challenges,'process_stamp',lambda pid: 'birth')
    monkeypatch.setattr(challenges.os,'getpgid',lambda pid:pid)
    monkeypatch.setattr(challenges,'_group_members',lambda pid: {456:'birth',789:'descendant'})
    killed=[]
    monkeypatch.setattr(challenges.os,'killpg',lambda pid,sig:killed.append(pid))
    monkeypatch.setattr(challenges.os,'kill',lambda *a:None)
    deadline=ledger.snapshot()['deadline']
    monkeypatch.setattr(challenges.time,'time',lambda:deadline)
    challenges.enforce_child_deadline(jobs,child,deadline)
    assert killed==[456]
    assert json.loads((jobs.directory(child)/'state.json').read_text())['status']=='uncertain'
    # A different process has reused the PID; never signal it.
    jobs.update(child,status='running',pid=456,process_stamp='birth')
    monkeypatch.setattr(challenges,'process_stamp',lambda pid:'reused')
    challenges.enforce_child_deadline(jobs,child,deadline)
    assert killed==[456]


def test_binding_tamper_blocks_child_before_any_gt(tmp_path):
    from architecture_iq.studio.rule_refinement import challenges
    jobs,parent,ledger,frozen=setup(tmp_path)
    binding=challenges.bind_challenge(jobs,parent_id=parent['id'],attempt_index=1,frozen_config=frozen,ledger=ledger)
    path=jobs.directory(binding['child_id'])/'refinement_parent.json'
    value=json.loads(path.read_text());value['parent_id']='wrong';path.write_text(json.dumps(value))
    with pytest.raises(ValueError): challenges.read_parent_binding(jobs,binding['child_id'])
