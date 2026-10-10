"""Single-question practice has real receipts but no scientific admission route."""
import copy
import json
from pathlib import Path

import pytest

from architecture_iq.kb.experience import ExperienceStore
from architecture_iq.kb.orchestrator import prepare_run, run_round
from architecture_iq.kb.roles import read_receipt
from architecture_iq.kb.store import KBStore
from architecture_iq.studio.workflow import compile_workflow, default_workflow, validate_workflow
from test_kb_workflow_orchestrator import inputs, Backend
from test_kb_experience import MemoryClient


def practice_inputs(**settings):
    config, questions, private, legacy = inputs()
    config.update(compile_workflow(default_workflow())['config'])
    config.update(settings)
    return config, questions, private, legacy


def test_default_has_a_distinct_two_call_manual_practice_route():
    spec = default_workflow()
    frozen = compile_workflow(spec)
    assert frozen['method']['id'] == 'basic_learning'
    assert frozen['execution_order'] == ['input', 'solver', 'commit', 'reveal',
        'experience_curator', 'experience_save', 'loop', 'end']
    assert frozen['config']['max_calls_per_round'] == 2
    assert frozen['config']['max_rounds'] == 2
    assert frozen['config']['use_previous_experience'] is True
    assert frozen['config']['record_conditions'] is True
    assert frozen['config']['loop_mode'] == 'manual'
    assert not frozen['config']['enable_confirmation']
    assert not frozen['config']['enable_evaluation']
    assert frozen['method']['publication_policy'] == 'unverified_experience_only'
    assert compile_workflow(default_workflow('scientific'))['method']['id'] == 'scientific'


@pytest.mark.parametrize('setting,value', [('loop_mode','automatic'), ('discovery_per_round',2),
    ('packet_size',2), ('max_calls_per_round',3), ('use_previous_experience','yes'),
    ('record_conditions',0), ('enable_evaluation',True), ('kb_path','old.json')])
def test_practice_rejects_incompatible_settings(setting, value):
    spec = default_workflow()
    spec['settings'][setting] = value
    assert not validate_workflow(spec)['valid']


def test_practice_does_not_accept_disguised_scientific_or_feedback_bypass_routes():
    spec = default_workflow()
    spec['edges'] = default_workflow('scientific')['edges']
    assert not validate_workflow(spec)['valid']
    spec = default_workflow()
    next(e for e in spec['edges'] if e['target'] == 'reveal')['source'] = 'solver'
    assert not validate_workflow(spec)['valid']


def test_single_question_is_repeated_only_for_explicit_practice(tmp_path):
    config, questions, private, legacy = practice_inputs()
    manifest = prepare_run(tmp_path, config, questions, private, legacy)
    assert manifest['round_questions'] == {'1':['q1'], '2':['q1']}
    assert manifest['practice']['independent_evaluation'] is False
    scientific = compile_workflow(default_workflow('scientific'))['config']
    config.update(scientific, max_rounds=2)
    with pytest.raises(ValueError, match='Need 2 discovery'):
        prepare_run(tmp_path / 'scientific', config, questions, private, legacy)


@pytest.mark.parametrize('variant', ['empty', 'multiple', 'held_out', 'legacy'])
def test_practice_requires_one_discovery_question_and_empty_initial_memory(tmp_path, variant):
    config, questions, private, legacy = practice_inputs()
    if variant == 'empty':
        questions, private = [], {}
    elif variant == 'multiple':
        questions.append({**copy.deepcopy(questions[0]), 'id':'q2', 'dataset_id':'d2', 'lineage_id':'l2'})
        private['q2'] = copy.deepcopy(private['q1'])
    elif variant == 'held_out':
        questions[0]['split'] = 'final'
    else:
        legacy = [{'id':'legacy'}]
    with pytest.raises(ValueError):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_real_receipts_two_calls_empty_first_memory_replay_and_prior_practice(tmp_path):
    config, questions, private, legacy = practice_inputs()
    prepare_run(tmp_path, config, questions, private, legacy)
    client, backend, events = MemoryClient(), Backend(), []
    first = run_round(tmp_path, client, backend, round_index=1, stage_observer=events.append)
    assert len(client.prompts) == 2
    assert backend.calls == 0
    assert 'GT_SECRET' not in client.prompts[0]
    first_payload = json.loads(client.prompts[0].split('DATA:\n')[1])
    assert first_payload['experience']['lessons'] == []
    assert first_payload['experience']['examples'] == []
    assert first['kb_before'] == first['kb_after']
    assert first['patch']['operations'] == []
    assert first['candidates'] == [] and first['evidence_count'] == 0
    assert first['practice']['independent_evaluation'] is False
    assert {e['node_id'] for e in events} == {'input','solver','commit','reveal','experience_curator','experience_save','loop'}
    assert events.index(next(e for e in events if e['node_id']=='commit' and e['state']=='complete')) < events.index(next(e for e in events if e['node_id']=='reveal' and e['state']=='complete'))
    assert read_receipt(tmp_path/'rounds/1/result.json')['result'] == first
    assert run_round(tmp_path, client, backend, round_index=1) == first
    assert len(client.prompts) == 2
    snapshot = ExperienceStore(tmp_path/'experience').current()
    assert snapshot['lessons'][0]['scientific_status'] == 'unverified'
    second = run_round(tmp_path, client, backend, round_index=2)
    assert len(client.prompts) == 4 and backend.calls == 0
    second_payload = json.loads(client.prompts[2].split('DATA:\n')[1])
    assert second_payload['experience']['lesson_ids'] == [snapshot['lessons'][0]['id']]
    assert second_payload['experience']['practice'] == 'same_question_practice'
    assert second['experience']['before'] == snapshot['version']
    assert second['experience']['after'] != snapshot['version']
    assert KBStore(tmp_path/'kb').current()['claims'] == []


def test_settings_change_real_injection_and_stored_conditions(tmp_path):
    config, questions, private, legacy = practice_inputs(use_previous_experience=False, record_conditions=False)
    prepare_run(tmp_path, config, questions, private, legacy)
    client = MemoryClient()
    run_round(tmp_path, client, Backend(), round_index=1)
    run_round(tmp_path, client, Backend(), round_index=2)
    payload = json.loads(client.prompts[2].split('DATA:\n')[1])
    assert 'experience' not in payload
    extraction = json.loads(client.prompts[1].split('DATA:\n')[1])
    assert extraction['record_conditions'] is False
    lesson = ExperienceStore(tmp_path/'experience').current()['lessons'][0]
    assert lesson['conditions'] == [] and lesson['exceptions'] == []


def test_default_template_endpoint_and_schema(tmp_path):
    from fastapi.testclient import TestClient
    from services.kb_workflow_api.app import create_app
    import jsonschema
    api = TestClient(create_app(state_root=tmp_path, execution_enabled=False))
    assert api.get('/api/studio/workflow/default').json()['settings']['method_id'] == 'basic_learning'
    advanced = api.get('/api/studio/workflow/default?method_id=scientific').json()
    assert advanced['settings']['method_id'] == 'scientific'
    schema = json.loads((Path(__file__).parents[1]/'contracts/kb_workflow.schema.json').read_text())
    for spec in [default_workflow(), advanced]:
        jsonschema.validate(spec, schema)


def test_api_preview_freezes_one_question_and_two_call_budget(tmp_path, monkeypatch):
    from test_studio_api import task_preview_setup
    client, app, body, data, _ = task_preview_setup(tmp_path, monkeypatch, enabled=False, execute=True)
    body['workflow'] = default_workflow()
    body['workflow']['settings'].update(model_id='glm', question_set_id=data['id'])
    response = client.post('/api/studio/runs/preview', json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['learning']['max_calls_per_round'] == 2
    assert preview['learning']['max_calls_all_rounds'] == 4
    assert preview['learning']['practice']['independent_evaluation'] is False
    assert preview['request_count'] == 1
    assert 'PRIVATE' not in response.text and 'correct_letter' not in response.text
    assert app.state.jobs.list() == []
    response = client.post('/api/studio/runs', json={**body, 'expected_config_hash':preview['config_hash']})
    assert response.status_code == 200, response.text
    assert response.json()['config']['method']['id'] == 'basic_learning'


def test_basic_solver_preview_matches_actual_first_request(tmp_path):
    from architecture_iq.studio.execution import preview_evaluation
    from test_studio_execution import fixture_config
    config = fixture_config()
    config['workflow'] = default_workflow()
    config['method'] = compile_workflow(config['workflow'])['method']
    config['question_set']['questions'][0]['split'] = 'discovery'
    config['prompt'] = ''
    expected = preview_evaluation(config)['requests'][0]['payload']['messages'][0]['content']
    native = compile_workflow(config['workflow'])['config']
    native.update(model={'name':'glm','max_tokens':64,'temperature':0.0,'top_p':1.0,'extra':{}}, runtime_fingerprint='test')
    prepare_run(tmp_path, native, config['question_set']['questions'], config['question_set']['feedback'], [])
    client = MemoryClient()
    run_round(tmp_path, client, Backend(), round_index=1)
    assert client.prompts[0] == expected


def test_basic_manual_continue_and_nodes_use_real_sealed_artifacts(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from architecture_iq.kb import cli
    from architecture_iq.kb.store import canonical_hash
    from architecture_iq.studio import execution
    from architecture_iq.studio.jobs import JobStore
    from architecture_iq.studio.observations import node_observations
    from test_studio_execution import fixture_config
    from test_studio_round_decisions import await_waiting
    config = fixture_config()
    config['workflow'] = default_workflow()
    config['question_set']['questions'][0]['split'] = 'discovery'
    lock = tmp_path/'runtime.json'; lock.write_text('{}')
    config['models'][0].update(runtime_lock_path=str(lock),runtime_fingerprint=canonical_hash({}))
    monkeypatch.setattr(cli,'read_runtime_lock',lambda *a,**k: None)
    monkeypatch.setattr(cli,'verify_live_runtime',lambda *a,**k: None)
    client = MemoryClient()
    monkeypatch.setattr(execution,'create_client',lambda *a,**k: client)
    store = JobStore(tmp_path/'state'); job = store.create('workflow',config); identifier=job['id']
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execution.execute_workflow,store,identifier,config)
        try:
            first = await_waiting(store,identifier,future)
            assert first['round_decision']['next_question_ids'] == ['q1']
            assert first['round_decision']['available_actions'] == ['continue','finish']
            assert len(client.prompts) == 2
            assert not (store.directory(identifier)/'workflow/rounds/2/start.json').exists()
            rows = node_observations(first,store.directory(identifier))
            extraction = next(r for r in rows if r['node_id']=='experience_curator' and r['round_index']==1)
            saved = next(r for r in rows if r['node_id']=='experience_save' and r['round_index']==1)
            assert extraction['availability'] == saved['availability'] == 'available'
            assert saved['output']['lessons'][0]['scientific_status'] == 'unverified'
            store.decide_round(identifier,round_index=1,action='continue')
            store.decide_round(identifier,round_index=1,action='continue')
            deadline = time.monotonic()+5
            while store.get(identifier).get('round_decision_index') != 2 and time.monotonic()<deadline:
                if future.done():future.result()
                time.sleep(0.01)
            second=store.get(identifier)
            assert second['round_decision']['available_actions'] == ['finish']
            assert len(client.prompts)==4
            store.decide_round(identifier,round_index=2,action='finish')
            result=future.result(timeout=5)
            assert result['experience']['scientific_status']=='unverified'
            assert result['kb']['claims']==[] and result['evaluation'] is None
            assert result['practice']['independent_evaluation'] is False
        finally:
            current=store.get(identifier)
            if not future.done() and current.get('round_decision',{}).get('status')=='waiting':
                store.decide_round(identifier,round_index=current['round_decision_index'],action='finish')


def test_reveal_event_follows_persisted_feedback_and_practice_episodes_are_labelled(tmp_path):
    from architecture_iq.kb.store import canonical_hash
    config, questions, private, legacy = practice_inputs()
    prepare_run(tmp_path,config,questions,private,legacy)
    def observe(event):
        if event['node_id']=='reveal' and event['state']=='complete':
            saved=read_receipt(tmp_path/f"rounds/1/revealed/{canonical_hash('q1')}.json")
            assert saved['result']['feedback']==private['q1']
    run_round(tmp_path,MemoryClient(),Backend(),round_index=1,stage_observer=observe)
    episode=ExperienceStore(tmp_path/'experience').current()['episodes'][0]
    assert episode['relationship']['type']=='same_question_practice'
    assert episode['relationship']['independent_evaluation'] is False


def test_uncertain_extraction_is_not_reissued_and_cannot_publish(tmp_path):
    config, questions, private, legacy = practice_inputs()
    prepare_run(tmp_path,config,questions,private,legacy)
    class Interrupted(MemoryClient):
        def complete(self,prompt,model):
            if 'You are the experience_curator in' in prompt:
                self.prompts.append(prompt)
                raise ConnectionError('response unknown')
            return super().complete(prompt,model)
    client=Interrupted()
    with pytest.raises(ConnectionError):run_round(tmp_path,client,Backend(),round_index=1)
    with pytest.raises(RuntimeError,match='pending/uncertain'):
        run_round(tmp_path,client,Backend(),round_index=1)
    assert len(client.prompts)==2
    assert ExperienceStore(tmp_path/'experience').current()['lessons']==[]
    assert not (tmp_path/'rounds/1/result.json').exists()


def test_crash_after_experience_storage_replays_without_duplicate_calls(tmp_path,monkeypatch):
    config, questions, private, legacy = practice_inputs()
    prepare_run(tmp_path,config,questions,private,legacy)
    original=ExperienceStore.publish
    def crash_once(self,*a,**k):
        original(self,*a,**k)
        raise OSError('crash after storage')
    monkeypatch.setattr(ExperienceStore,'publish',crash_once)
    client=MemoryClient()
    with pytest.raises(OSError):run_round(tmp_path,client,Backend(),round_index=1)
    frozen=ExperienceStore(tmp_path/'experience').current()
    monkeypatch.setattr(ExperienceStore,'publish',original)
    result=run_round(tmp_path,client,Backend(),round_index=1)
    assert len(client.prompts)==2
    assert result['experience']['after']==frozen['version']
    assert len(ExperienceStore(tmp_path/'experience').current()['episodes'])==1


def test_single_selection_preserves_pair_origin_without_executing_paired_protocol(tmp_path):
    config, questions, private, legacy = practice_inputs()
    questions[0]['pair_id'] = 'source-pair'
    original = copy.deepcopy(questions)
    manifest = prepare_run(tmp_path, config, questions, private, legacy)
    assert manifest['round_questions'] == {'1':['q1'], '2':['q1']}
    assert questions == original
    stored = json.loads((tmp_path/'public_questions.json').read_text())
    assert stored[0]['pair_id'] == 'source-pair'
    assert stored[0]['lineage_id'] == original[0]['lineage_id']
    assert manifest['config']['learning_protocol'] == 'single'
    client, backend = MemoryClient(), Backend()
    result = run_round(tmp_path, client, backend, round_index=1)
    assert result['practice']['independent_evaluation'] is False
    assert len(client.prompts) == 2 and backend.calls == 0
    assert 'GT_SECRET' not in client.prompts[0]
    assert 'learning_traces' not in result


def test_basic_api_previews_one_catalog_question_with_pair_source_metadata(tmp_path, monkeypatch):
    from test_studio_api import task_preview_setup
    client, app, body, _, _ = task_preview_setup(tmp_path, monkeypatch, enabled=False)
    records = json.loads((tmp_path/'input.json').read_text())
    records[0].update(id='paired-origin-single',pair_id='historical-pair')
    path = tmp_path/'paired-origin.json'
    path.write_text(json.dumps([records[0]]))
    app.state.catalog.import_source(path)
    item = next(row for row in app.state.catalog.list_questions()['items'] if row['id']=='paired-origin-single')
    selected = app.state.catalog.create_question_set('Single item with source pair', [item['key']])
    body['workflow'] = default_workflow()
    body['workflow']['settings'].update(model_id='glm',question_set_id=selected['id'])
    response = client.post('/api/studio/runs/preview',json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['request_count'] == 1 and preview['learning']['max_calls_per_round'] == 2
    assert 'historical-pair' in preview['requests'][0]['payload']['messages'][0]['content']
    assert 'PRIVATE' not in response.text and 'correct_letter' not in response.text
    assert app.state.jobs.list() == []
