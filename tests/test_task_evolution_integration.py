from copy import deepcopy
import json

from fastapi.testclient import TestClient

from services.kb_workflow_api.app import create_app
from architecture_iq.studio.loop_observer import LoopObserver
from test_studio_loop_observer import configuration
from test_studio_evolution_task_sources import observed_capture, observed_question
from test_studio_tasks import task, preview, run


def evolution_case(tmp_path, monkeypatch, enabled=False):
    state = tmp_path / 'state'
    value = observed_capture()
    observer = LoopObserver(state, config=configuration(artifact_root='/private/artifacts'),
                            reader=lambda _: value, question_reader=lambda _, qid: observed_question(qid))
    assert observer.poll_once()
    app = create_app(state_root=state, allowed_roots=[tmp_path], execution_enabled=enabled, loop_observer=observer)
    monkeypatch.setattr('architecture_iq.studio.knowledge.knowledge_inventory', lambda *args: {'items': []})
    monkeypatch.setattr('architecture_iq.kb.cli.require_execution_host', lambda *args: None)
    models = app.state.models
    models.save({'id': 'glm', 'name': 'Test model', 'model': 'glm',
                 'base_url': 'http://models.example.test/v1', 'parameters': {'max_tokens': 64}, 'context_size': 32768})
    client = TestClient(app)
    frozen = client.post('/api/studio/tasks/evolution/questions/q_generated')
    assert frozen.status_code == 200, frozen.text
    return {'app': app, 'client': client, 'question_key': frozen.json()['key'],
            'observer': observer, 'value': value, 'state_root': state, 'jobs': app.state.jobs}


def test_evolution_question_and_kb_are_selectable_with_executable_trace(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    client = case['client']
    listing = client.get('/api/studio/tasks/evolution/questions').json()
    assert listing['total'] == 1 and listing['items'][0]['id'] == 'q_generated'
    record = client.get('/api/studio/tasks/questions/' + case['question_key']).json()
    assert record['metadata']['rag_ready'] and record['public']['choices'][0]['view']
    kbs = client.get('/api/studio/tasks/kbs?mode=rules').json()['items']
    assert kbs[0]['source_kind'] == 'knowledge_evolution'
    card = task(case, mode='rules', model_id=None, kb_selection={'mode': 'manual', 'ref': {k: kbs[0][k] for k in ('id','version')}})
    shown = preview(case, card)
    assert shown['prediction']['answer_letter'] == 'A'
    explanation = shown['prediction']['explanation']
    assert explanation['edges'][0]['rules'][0]['claim_ids'] == ['C1']
    assert explanation['edges'][0]['rules'][0]['source_refs'][0]['source_revision'] == 2
    response = run(case, card, shown)
    assert response.status_code == 200, response.text
    assert response.json()['result']['prediction']['explanation'] == explanation
    assert not case['jobs'].list()
    assert 'SECRET_GT' not in json.dumps([shown,response.json(),record])


def test_manual_snapshot_remains_fixed_but_auto_preview_tracks_revision(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    kb = case['client'].get('/api/studio/tasks/kbs?mode=rules').json()['items'][0]
    reference = {k: kb[k] for k in ('id','version')}
    manual = task(case, mode='rules', model_id=None, kb_selection={'mode': 'manual', 'ref': reference})
    auto = task(case, name='Automatic', mode='rules', model_id=None)
    old_manual, old_auto = preview(case,manual), preview(case,auto)
    case['value']['claims'][0]['version'] += 1
    case['value']['claims'][0]['rules'][0]['predict'] = {'lower_better':'width'}
    case['observer'].poll_once()
    assert run(case,auto,old_auto).status_code == 409
    listed = case['client'].get('/api/studio/tasks/kbs',params={'mode':'rules','kb_id':reference['id'],
                                                              'kb_version':reference['version']}).json()['items']
    assert any(item['version']==reference['version'] for item in listed)
    fixed = preview(case,manual)
    assert fixed['preview_hash'] == old_manual['preview_hash']
    assert fixed['prediction']['answer_letter'] == 'A'
    assert run(case,manual,fixed).status_code == 200
    reloaded = create_app(state_root=case['state_root'], allowed_roots=[tmp_path], execution_enabled=False,
                          loop_observer=LoopObserver(case['state_root']))
    response = TestClient(reloaded).post(f"/api/studio/tasks/{manual['id']}/preview",json={'expected_revision':1})
    assert response.status_code == 200, response.text
    assert response.json()['prediction']['answer_letter'] == 'A'


def test_model_task_freezes_provided_rules_and_only_marks_actual_citations_used(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch, enabled=True)
    monkeypatch.setattr(case['jobs'], 'launch', lambda identifier: None)
    card = task(case)
    shown = preview(case,card)
    assert shown['can_answer'] and shown['retrieval']['provenance'][0]['source_claim_ids'] == ['C1']
    response = run(case,card,shown)
    assert response.status_code == 200, response.text
    identifier=response.json()['job_id']
    config=case['jobs'].definition(identifier)['config']
    assert config['retrieval']['knowledge'][0]['scientific_status']=='research_hypothesis'
    provided=shown['retrieval']['provenance']
    assert response.json()['result']['provided_sources']==provided
    assert response.json()['result']['used_sources']==[]
    from rag_fixtures import rag_client
    from architecture_iq.studio.execution import worker
    case.update(config=config,calls=[])
    monkeypatch.setattr('architecture_iq.studio.execution.create_client',rag_client(case))
    worker(case['state_root'],identifier)
    history=case['client'].get(f"/api/studio/tasks/{card['id']}/runs").json()['items'][0]
    assert history['result']['used_sources']==provided
    for secret in ('SECRET_GT','base_url','models.example.test','/private/artifacts'):
        assert secret not in json.dumps([shown,response.json(),history])
