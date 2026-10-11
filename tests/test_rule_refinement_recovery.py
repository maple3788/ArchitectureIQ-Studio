import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from architecture_iq.kb.roles import read_receipt
from test_rule_refinement_runner import setup_run,execute


@pytest.mark.parametrize('boundary',['prediction','score','proposal','decision','checkpoint','child','first_test','promotion'])
def test_crash_recovery_preserves_commits_and_never_repeats_external_work(tmp_path,monkeypatch,boundary):
    from architecture_iq.studio.rule_refinement import runner
    args=setup_run(tmp_path,monkeypatch)
    targets={'prediction':(runner,'seal_predictions'),'score':(runner,'score_sealed_batch'),
             'proposal':(runner,'propose_patch'),'decision':(runner,'_save_decision'),
             'checkpoint':(runner,'_checkpoint'),'child':(runner,'run_challenge'),
             'first_test':(runner.PoolStore,'record_first_test'),'promotion':(runner.PoolStore,'promote')}
    owner,name=targets[boundary];original=getattr(owner,name);fired=[]
    def crash(*a,**kw):
        result=original(*a,**kw)
        if not fired:
            fired.append(True);raise SystemExit('crash after persisted boundary')
        return result
    monkeypatch.setattr(owner,name,crash)
    with pytest.raises(SystemExit):execute(args)
    monkeypatch.setattr(owner,name,original)
    result=execute(args)
    assert result['outcome']=='target_reached',result
    assert args[3].count.value==2 and args[-1]['generation']==3
    events=args[0].events(args[2]['id'])
    identities=[e['refinement_event_id'] for e in events if 'refinement_event_id' in e]
    assert len(identities)==len(set(identities))
    assert result['budget']['revision_attempts']==2 and result['budget']['generation_attempts']==3


def test_two_recovery_requests_launch_only_one_worker(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import runner
    args=setup_run(tmp_path,monkeypatch)
    original=runner.propose_patch
    def crash(*a,**kw):
        result=original(*a,**kw);raise SystemExit('response saved')
    monkeypatch.setattr(runner,'propose_patch',crash)
    with pytest.raises(SystemExit):execute(args)
    jobs,_,job,_,_,_=args;jobs.update(job['id'],status='interrupted')
    launched=[]
    def launch(identifier):launched.append(identifier);jobs.update(identifier,status='starting');return 123
    monkeypatch.setattr(jobs,'launch',launch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:runner.recover_refinement(jobs,job['id']),range(2)))
    assert launched==[job['id']] and all(r['status']=='starting' for r in results)


def test_uncertain_role_cannot_be_reissued_by_recovery(tmp_path,monkeypatch):
    from architecture_iq.studio.rule_refinement import runner
    from architecture_iq.kb.store import write_json_atomic
    from architecture_iq.kb.roles import _seal
    args=setup_run(tmp_path,monkeypatch)
    original=runner.propose_patch
    def crash(caller,ledger,**kw):
        result=original(caller,ledger,**kw)
        root=ledger.root
        (root/'proposals'/(kw['attempt_id']+'.json')).unlink()
        path=caller.root/result['call_ref'].split('roles/')[-1]
        receipt=read_receipt(path);receipt['status']='pending';write_json_atomic(path,_seal(receipt))
        raise SystemExit('response uncertain')
    monkeypatch.setattr(runner,'propose_patch',crash)
    with pytest.raises(SystemExit):execute(args)
    jobs,_,job,provider,_,_=args;jobs.update(job['id'],status='interrupted')
    monkeypatch.setattr(jobs,'launch',lambda _:pytest.fail('uncertain call cannot restart'))
    result=runner.recover_refinement(jobs,job['id'])
    assert result['status']=='uncertain' and provider.count.value==1
