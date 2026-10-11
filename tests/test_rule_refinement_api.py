from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from architecture_iq.studio.datasets import DatasetStore
from architecture_iq.studio.rule_refinement.workflow import default_rule_workflow
from rule_refinement_fixtures import limits,raw_case
from test_studio_catalog import bakefile
from test_studio_generation import config
from test_rule_refinement_runner import setup_run,execute


def api_fixture(tmp_path,monkeypatch):
    from services.kb_workflow_api.app import create_app
    args=setup_run(tmp_path,monkeypatch);execute(args)
    app=create_app(state_root=tmp_path/'state',execution_enabled=False)
    client=TestClient(app)
    app.state.models.save(dict(id='fake',name='Fixture',connection_type='api',model='mock-rules',base_url='http://example.invalid/v1',
                               context_size=100000,parameters={'max_tokens':1000}),api_key='CREDENTIAL_SENTINEL')
    items=client.get('/api/studio/kb').json()['items']
    item=next(i for i in items if i['kind']=='research_rules')
    kb_ref={'id':item['id'],'version':item['version']}
    binding=args[2]['config']['dataset_binding'];ref={k:binding[k] for k in ('collection_id','revision')}
    spec=default_rule_workflow();spec['settings']['limits']=limits();spec['settings']['generation']=config()
    next(n for n in spec['nodes'] if n['id']=='revise')['config']['model_id']='fake'
    body={'workflow':spec,'dataset_ref':ref,'selection':{},'initial_kb_ref':kb_ref}
    return client,app,args,body,kb_ref


def test_local_match_needs_no_model_and_never_reads_gt(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    original=app.state.catalog.get_question
    def public_only(key,**kwargs):
        assert not kwargs.get('include_private'), 'GT was read during matching'
        return original(key,**kwargs)
    monkeypatch.setattr(app.state.catalog,'get_question',public_only)
    result=client.post('/api/studio/rule-refinement/match?offset=0&limit=1',json={k:body[k] for k in ('dataset_ref','selection')}|{'kb_ref':kb})
    assert result.status_code==200,result.text
    assert result.json()['items'][0]['status']=='answered'
    assert result.json()['total']==1 and result.json()['limit']==1
    assert 'correct_letter' not in result.text


def test_previews_and_queued_jobs_never_expose_gt_or_credentials(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    preview=client.post('/api/studio/rule-refinement/preview',json=body)
    assert preview.status_code==200 and preview.json()['can_run'],preview.text
    for token in ('CREDENTIAL_SENTINEL','credential_ref','correct_letter','runtime_lock_path'):
        assert token not in preview.text
    start=client.post('/api/studio/rule-refinement/runs',json={**body,'preview_hash':preview.json()['preview_hash']},headers={'Idempotency-Key':'local'})
    assert start.status_code==409 and isinstance(start.json()['detail'],dict)
    from architecture_iq.studio.rule_refinement.inputs import prepare_refinement
    frozen,_=prepare_refinement(app.state.catalog,app.state.datasets,app.state.models,client.get('/api/studio/kb').json(),body)
    frozen['private_marker']='GT_SENTINEL'
    job=app.state.jobs.create('rule_refinement',frozen)
    app.state.jobs.update(job['id'],error='CREDENTIAL_SENTINEL')
    for path in ('/api/studio/runs','/api/studio/runs/'+job['id']):
        response=client.get(path)
        assert response.status_code==200
        for token in ('GT_SENTINEL','CREDENTIAL_SENTINEL','credential_ref','runtime_lock_path'):
            assert token not in response.text
    denied=client.get(f'/api/studio/rule-refinement/runs/{job["id"]}/artifacts/private_marker')
    assert denied.status_code in (404,422)


def test_source_health_change_invalidates_preview(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    from architecture_iq.studio.rule_refinement.inputs import prepare_refinement
    _,first=prepare_refinement(app.state.catalog,app.state.datasets,app.state.models,client.get('/api/studio/kb').json(),body)
    key=args[2]['config']['dataset_binding']['keys'][0]
    with app.state.catalog._connect() as conn:conn.execute('UPDATE aliases SET blocked=1 WHERE key=?',(key,))
    second=client.post('/api/studio/rule-refinement/preview',json=body).json()
    assert not second['can_run'] and second['preview_hash']!=first['preview_hash']
    assert any(b['code']=='question_unavailable' for b in second['blockers'])


def test_two_choice_readiness_is_specific_to_new_method(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    from architecture_iq.studio.dataset_inputs import DatasetInputs
    record=raw_case('two','two_data',widths=(32,16),losses=(1,2))
    report=app.state.catalog.import_source(bakefile(tmp_path/'two.json',[record]));key=report['entries'][0]['key']
    collection=app.state.datasets.create(name='Two',keys=[key],operation_id='two')
    ref={k:collection[k] for k in ('collection_id','revision')}
    inputs=DatasetInputs(app.state.catalog,app.state.datasets)
    new=inputs.preview(ref,{},purpose='research',method_id='rule_refinement')
    assert new['can_apply'],new
    assert not inputs.preview(ref,{},purpose='research',method_id='scientific')['can_apply']
    frozen=inputs.materialize(ref,{},purpose='research',method_id='rule_refinement',preview_hash=new['preview_hash'])
    assert frozen['keys']==[key]


def test_bound_child_cannot_leak_unsealed_winners_on_generic_routes(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    from architecture_iq.studio.rule_refinement.inputs import prepare_refinement
    from architecture_iq.studio.rule_refinement.budget import BudgetLedger
    from architecture_iq.studio.rule_refinement.challenges import prepare_challenge,bind_challenge
    from architecture_iq.kb.store import write_json_atomic
    frozen,_=prepare_refinement(app.state.catalog,app.state.datasets,app.state.models,client.get('/api/studio/kb').json(),body)
    parent=app.state.jobs.create('rule_refinement',frozen)
    ledger=BudgetLedger(app.state.jobs.directory(parent['id'])/'refinement',frozen['limits'])
    challenge=prepare_challenge(frozen['generation'],attempt_index=1,questions_per_batch=16)
    bound=bind_challenge(app.state.jobs,parent_id=parent['id'],attempt_index=1,frozen_config=challenge,ledger=ledger)
    child=bound['child_id']
    write_json_atomic(app.state.jobs.directory(child)/'result.json',{'changed_winner_pairs':'GT_SENTINEL','stable_winner_pairs':4})
    app.state.jobs.event(child,{'type':'generation','winner':'GT_SENTINEL'})
    for path in ('/api/studio/runs','/api/studio/runs/'+child,'/api/studio/runs/'+child+'/stream'):
        response=client.get(path)
        assert response.status_code==200,response.text
        assert 'GT_SENTINEL' not in response.text and 'stable_winner_pairs' not in response.text
    assert client.post('/api/studio/runs/'+child+'/resume').status_code==409


def test_unknown_fields_and_paths_are_structured_errors(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    response=client.post('/api/studio/rule-refinement/preview',json={**body,'path':'/secret'})
    assert response.status_code==422 and response.json()['detail']['code']=='invalid_refinement_request'
    response=client.post('/api/studio/rule-refinement/match',json={'dataset_ref':body['dataset_ref'],'selection':{},'kb_ref':{'path':'/secret'}})
    assert response.status_code==422


def test_accepted_rules_have_readable_artifacts_but_rejected_candidates_are_not_inventory(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
    from rule_refinement_fixtures import rule_entry
    root=app.state.jobs.directory(args[2]['id'])/'refinement'
    rejected=RuleArtifactStore(root).import_rules({'rules':[rule_entry((99,100))]},source_ref={'kind':'rejected'})
    inventory=client.get('/api/studio/kb').json()
    assert rejected['version'] not in [i['version'] for i in inventory['items']]
    detail=client.get('/api/studio/runs/'+args[2]['id']).json()
    assert detail['artifacts']
    item=next(a for a in detail['artifacts'] if a['kind']=='score')
    response=client.get(f'/api/studio/rule-refinement/runs/{args[2]["id"]}/artifacts/{item["id"]}')
    assert response.status_code==200 and 'per_question' in response.json()['value']


def test_model_revision_change_invalidates_preview(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    first=client.post('/api/studio/rule-refinement/preview',json=body).json()
    app.state.models.save(dict(id='fake',name='Changed',connection_type='api',model='new-model',base_url='http://example.invalid/v1',context_size=100000,parameters={'max_tokens':1000}))
    second=client.post('/api/studio/rule-refinement/preview',json=body).json()
    assert second['preview_hash']!=first['preview_hash']
    assert client.post('/api/studio/runs/'+args[2]['id']+'/round-decision',json={'round_index':1,'action':'continue'}).status_code==409


def test_public_live_checkpoint_includes_accounted_budget(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    root=app.state.jobs.directory(args[2]['id'])/'refinement'
    (root/'result.json').unlink()
    public=client.get('/api/studio/runs/'+args[2]['id']).json()
    assert public['refinement']['budget']['model_calls']==args[3].count.value==2
    assert public['refinement']['budget']['limits']['max_tokens']>0
    assert 'operations' not in public['refinement']['budget']
