from copy import deepcopy
from pathlib import Path
import json
import pytest
from architecture_iq.kb.store import write_json_atomic
from test_rule_refinement_api import api_fixture
from test_rule_refinement_runner import distinct_case
from test_studio_catalog import bakefile


def holdout(app,tmp_path,*,instance=999,name='holdout'):
    raw=distinct_case(name,instance);raw['split']='final'
    report=app.state.catalog.import_source(bakefile(tmp_path/(name+'.json'),[raw]));key=report['entries'][0]['key']
    collection=app.state.datasets.create(name=name,keys=[key],operation_id=name)
    return {k:collection[k] for k in ('collection_id','revision')}


def test_task_overlap_is_rejected_without_pool_mutation(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    ref=holdout(app,tmp_path,instance=1) # New ID, same underlying research instance/specs.
    result=client.post('/api/studio/rule-refinement/evaluations/preview',json={'kb_ref':kb,'dataset_ref':ref,'selection':{},'phase':'final'})
    assert result.status_code==200 and not result.json()['can_run'],result.text
    assert any(b['code']=='research_overlap' for b in result.json()['blockers'])


def test_local_rule_evaluation_never_uses_model_or_changes_research_pool(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    ref=holdout(app,tmp_path)
    request={'kb_ref':kb,'dataset_ref':ref,'selection':{},'phase':'final'}
    preview=client.post('/api/studio/rule-refinement/evaluations/preview',json=request)
    assert preview.status_code==200 and preview.json()['can_run'],preview.text
    assert preview.json()['independence']=='unknown_prior_exposure' # fixture imported nonempty KB has unknown prehistory.
    monkeypatch.setattr(app.state.jobs,'launch',lambda _:None)
    submit={**request,'preview_hash':preview.json()['preview_hash']};headers={'Idempotency-Key':'evaluation-once'}
    started=client.post('/api/studio/rule-refinement/evaluations',json=submit,headers=headers)
    assert started.status_code==200,started.text
    identifier=started.json()['id']
    again=client.post('/api/studio/rule-refinement/evaluations',json=submit,headers=headers)
    assert again.status_code==200 and again.json()['id']==identifier
    root=app.state.jobs.directory(args[2]['id'])/'refinement'
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*.json')}
    from architecture_iq.studio import execution
    from architecture_iq.kb import cli
    monkeypatch.setattr(cli,'require_execution_host',lambda *_:pytest.fail('pure evaluation needs no real execution host'))
    monkeypatch.setattr(execution,'create_client',lambda *a,**k:pytest.fail('pure evaluation needs no model'))
    execution.worker(app.state.jobs.state_root,identifier)
    detail=client.get('/api/studio/runs/'+identifier)
    assert detail.status_code==200 and detail.json()['result']['score']['all_pass'],detail.text
    assert {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*.json')}==before
    repeated=client.post('/api/studio/rule-refinement/evaluations/preview',json=request).json()
    assert repeated['independence']=='repeated_evaluation' and repeated['can_run']


def test_evaluation_unknown_fields_and_stale_preview_do_not_launch(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    request={'kb_ref':kb,'dataset_ref':holdout(app,tmp_path),'selection':{},'phase':'final'}
    extra=client.post('/api/studio/rule-refinement/evaluations/preview',json={**request,'model_id':'fake'})
    assert extra.status_code==422
    monkeypatch.setattr(app.state.jobs,'launch',lambda _:pytest.fail('stale preview must not launch'))
    response=client.post('/api/studio/rule-refinement/evaluations',json={**request,'preview_hash':'old'},headers={'Idempotency-Key':'stale'})
    assert response.status_code==409 and response.json()['detail']['code']=='preview_changed'


def test_evaluation_rejects_changed_ancestor_exposure_before_prediction(tmp_path,monkeypatch):
    client,app,args,body,kb=api_fixture(tmp_path,monkeypatch)
    request={'kb_ref':kb,'dataset_ref':holdout(app,tmp_path),'selection':{},'phase':'final'}
    preview=client.post('/api/studio/rule-refinement/evaluations/preview',json=request).json()
    monkeypatch.setattr(app.state.jobs,'launch',lambda _:None)
    result=client.post('/api/studio/rule-refinement/evaluations',json={**request,'preview_hash':preview['preview_hash']},headers={'Idempotency-Key':'changed-ancestor'})
    identifier=result.json()['id']
    from architecture_iq.studio.rule_refinement import inputs,runner
    original=inputs.research_exposure
    def changed(*a,**kw):
        pool,known,runs=original(*a,**kw)
        pool['members']+=app.state.jobs.definition(identifier)['config']['pool']['members']
        return pool,known,runs
    monkeypatch.setattr(inputs,'research_exposure',changed)
    monkeypatch.setattr(runner,'_score',lambda *a,**kw:pytest.fail('changed exposure must block scoring'))
    with pytest.raises(ValueError,match='exposure'):
        runner.execute_rule_evaluation(app.state.jobs,identifier,app.state.jobs.definition(identifier)['config'],catalog=app.state.catalog)
