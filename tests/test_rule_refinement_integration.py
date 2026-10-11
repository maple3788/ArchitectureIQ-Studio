"""Public API/worker integration; all provider and generation side effects are mocked."""
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from architecture_iq.kb.roles import read_receipt,_seal
from architecture_iq.kb.store import write_json_atomic
from architecture_iq.studio import execution
from architecture_iq.studio.rule_refinement import runner
from rule_refinement_fixtures import rule_entry
from test_rule_refinement_runner import setup_run
from test_rule_refinement_evaluation import holdout


def scenario(tmp_path,monkeypatch):
    from architecture_iq.kb import cli
    from services.kb_workflow_api.app import create_app
    args=setup_run(tmp_path,monkeypatch)
    jobs,catalog,seed,provider,factory,counts=args
    seed_config=deepcopy(seed['config']);seed_config['initial_rules']={'rules':[rule_entry(),rule_entry(lower=True)]}
    seed=jobs.create('rule_refinement',seed_config)
    runner.request_refinement_control(jobs,seed['id'],'stop')
    runner.execute_refinement(jobs,seed['id'],seed_config,catalog=catalog,client_factory=factory)
    monkeypatch.setattr(cli,'require_execution_host',lambda *_:None)
    app=create_app(state_root=jobs.state_root,execution_enabled=True);client=TestClient(app)
    app.state.models.save(dict(id='fake',name='Mock provider',connection_type='api',model='mock-rules',base_url='http://example.invalid/v1',context_size=100000,parameters={'max_tokens':1000}),api_key='MOCK_ONLY')
    inventory=client.get('/api/studio/kb').json()['items'];kb=next(i for i in inventory if i['kind']=='research_rules')
    spec=deepcopy(seed_config['workflow']);next(n for n in spec['nodes'] if n['id']=='initialize')['config']['source']={'id':kb['id'],'version':kb['version']}
    binding=seed_config['dataset_binding'];body={'workflow':spec,'dataset_ref':{k:binding[k] for k in ('collection_id','revision')},'selection':{}}
    preview=client.post('/api/studio/rule-refinement/preview',json=body);assert preview.status_code==200 and preview.json()['can_run'],preview.text
    submitted={**body,'preview_hash':preview.json()['preview_hash']};headers={'Idempotency-Key':'integration-once'}
    monkeypatch.setattr(app.state.jobs,'launch',lambda _:None)
    start=client.post('/api/studio/rule-refinement/runs',json=submitted,headers=headers);assert start.status_code==200,start.text
    original=runner.execute_refinement
    monkeypatch.setattr(runner,'execute_refinement',lambda jobs,identifier,config,**kw:original(jobs,identifier,config,**kw,client_factory=factory))
    return client,app,start.json()['id'],provider,counts,submitted,headers


def test_api_worker_conflict_repair_challenges_and_frozen_evaluation(tmp_path,monkeypatch):
    client,app,identifier,provider,counts,request,headers=scenario(tmp_path,monkeypatch)
    root=app.state.jobs.directory(identifier)/'refinement'
    original_score=runner.score_sealed_batch;releases=[]
    def guarded(root,*,pool,prediction_receipt,feedback_loader):
        predictions=read_receipt(root/prediction_receipt)
        assert len(predictions['predictions'])==len(pool['members'])
        def loader(ref):
            assert (root/prediction_receipt).exists();releases.append(ref['key']);return feedback_loader(ref)
        return original_score(root,pool=pool,prediction_receipt=prediction_receipt,feedback_loader=loader)
    monkeypatch.setattr(runner,'score_sealed_batch',guarded)
    execution.worker(app.state.jobs.state_root,identifier)
    detail=client.get('/api/studio/runs/'+identifier).json();result=detail['result']
    assert result['outcome']=='target_reached',detail
    assert result['score']['correct']==result['score']['selected']==4
    assert [b['first_score']['all_pass'] for b in result['fresh_batches']]==[False,True,True]
    assert result['budget']['model_calls']==provider.count.value==2
    assert result['budget']['generation_attempts']==counts['generation']==3
    assert result['budget']['candidate_seed_runs']==9 and result['budget']['new_questions']==3
    assert releases and any(read_receipt(p)['conflicts'] for p in (root/'scores').glob('*.json'))
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*.json')}
    again=client.post('/api/studio/rule-refinement/runs',json=request,headers=headers)
    assert again.json()['id']==identifier and provider.count.value==2
    inventory=client.get('/api/studio/kb').json()['items'];kb=next(i for i in inventory if i['version']==result['best_kb']['version'])
    evaluate={'kb_ref':{k:kb[k] for k in ('id','version')},'dataset_ref':holdout(app,tmp_path),'selection':{},'phase':'final'}
    p=client.post('/api/studio/rule-refinement/evaluations/preview',json=evaluate).json();assert p['can_run'],p
    e=client.post('/api/studio/rule-refinement/evaluations',json={**evaluate,'preview_hash':p['preview_hash']},headers={'Idempotency-Key':'final-eval'}).json()
    execution.worker(app.state.jobs.state_root,e['id'])
    assert client.get('/api/studio/runs/'+e['id']).json()['result']['score']['all_pass']
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*.json')}


def test_api_recovery_after_saved_proposal_does_not_reissue_calls(tmp_path,monkeypatch):
    client,app,identifier,provider,counts,request,headers=scenario(tmp_path,monkeypatch)
    original=runner.propose_patch
    def crash(*a,**kw):original(*a,**kw);raise SystemExit('persisted response, worker disconnected')
    monkeypatch.setattr(runner,'propose_patch',crash)
    with pytest.raises(SystemExit):execution.worker(app.state.jobs.state_root,identifier)
    assert provider.count.value==1
    app.state.jobs.update(identifier,status='interrupted',pid=None,process_stamp=None)
    monkeypatch.setattr(runner,'propose_patch',original)
    assert client.post('/api/studio/rule-refinement/runs',json=request,headers=headers).json()['id']==identifier
    recovered=client.post('/api/studio/rule-refinement/runs/'+identifier+'/recover',json={})
    assert recovered.status_code==200,recovered.text
    execution.worker(app.state.jobs.state_root,identifier)
    assert provider.count.value==2 and counts['generation']==3
    public=client.get('/api/studio/runs/'+identifier).json()
    assert public['result']['outcome']=='target_reached'
    ids=[e['refinement_event_id'] for e in public['events'] if 'refinement_event_id' in e]
    assert len(ids)==len(set(ids))


def test_uncommitted_checkpoint_journal_never_advances_public_events(tmp_path,monkeypatch):
    args=setup_run(tmp_path,monkeypatch);jobs,catalog,job,provider,factory,_=args
    original=runner._checkpoint
    def crash(*a,**kw):original(*a,**kw);raise SystemExit('initial checkpoint saved')
    monkeypatch.setattr(runner,'_checkpoint',crash)
    with pytest.raises(SystemExit):runner.execute_refinement(jobs,job['id'],job['config'],catalog=catalog,client_factory=factory)
    root=jobs.directory(job['id'])/'refinement';cp=read_receipt(root/'checkpoint.json')
    orphan=_seal({**cp,'revision':cp['revision']+1,'phase':'initialize'})
    write_json_atomic(root/'checkpoints'/f'{orphan["revision"]:08d}.json',orphan)
    runner._sync_events(jobs,job['id'],root)
    assert all(e.get('refinement_event_id')!='checkpoint-'+str(orphan['revision']) for e in jobs.events(job['id']))
