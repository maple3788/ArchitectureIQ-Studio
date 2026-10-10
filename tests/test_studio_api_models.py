"""API connections use private credentials and honest configuration identities."""
import json
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from architecture_iq.studio.models import ModelRegistry
from architecture_iq.studio.workflow import default_workflow


def api_profile():
    return {"id": "cloud", "name": "Cloud GLM", "model": "glm",
            "base_url": "https://models.example.test/v1", "connection_type": "api",
            "parameters": {"max_tokens": 64}}


def test_api_key_is_private_versioned_and_never_returned(tmp_path):
    from services.kb_workflow_api.app import create_app
    app = create_app(state_root=tmp_path, allowed_roots=[tmp_path], execution_enabled=False)
    client = TestClient(app)
    first = client.post('/api/studio/models', json={**api_profile(), 'api_key': 'first-private-key'})
    assert first.status_code == 200, first.text
    profile = first.json()
    assert 'first-private-key' not in first.text
    assert 'api_key' not in profile
    assert profile['credential_ref']
    secret_files = list((tmp_path/'credentials').glob('*.key'))
    assert len(secret_files) == 1
    assert stat.S_IMODE(secret_files[0].stat().st_mode) == 0o600
    assert app.state.models.credential(profile) == 'first-private-key'
    second = client.post('/api/studio/models', json={**api_profile(), 'api_key': 'second-private-key'})
    assert second.status_code == 200
    assert second.json()['revision'] != profile['revision']
    assert app.state.models.credential(profile) == 'first-private-key'
    unchanged = client.post('/api/studio/models', json=api_profile())
    assert unchanged.json()['revision'] == second.json()['revision']
    for path in tmp_path.rglob('*.json'):
        assert 'private-key' not in path.read_text()
    listing = client.get('/api/studio/models').text
    assert 'private-key' not in listing
    moved = client.post('/api/studio/models', json={**api_profile(), 'base_url': 'https://other.example.test/v1'})
    assert moved.status_code == 422
    assert app.state.models.get('cloud')['base_url'] == api_profile()['base_url']


@pytest.mark.parametrize('value', [
    {'connection_type': 'other'},
    {'connection_type': 'api', 'runtime_lock_path': '/some/lock'},
    {'connection_type': 'api', 'api_key_env': 'MISSING_KEY'},
])
def test_api_profile_cannot_silently_bypass_credentials_or_attestation(tmp_path, value):
    with pytest.raises(ValueError):
        ModelRegistry(tmp_path).save({**api_profile(), **value})


def test_api_check_and_transport_use_private_key_without_leaking_errors(tmp_path, monkeypatch):
    from architecture_iq.studio.execution import create_client
    from tools.llm_eval.llm_client import ModelConfig
    import urllib.error
    registry = ModelRegistry(tmp_path)
    profile = registry.save(api_profile(), api_key='private-transport-key')
    sent = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self):
            return json.dumps({'model': 'glm', 'choices': [{'message': {'content': 'A'}, 'finish_reason': 'stop'}]}).encode()
    def open_request(request, **kwargs):
        sent.append(request)
        return Reply()
    monkeypatch.setattr('urllib.request.urlopen', open_request)
    capture = []
    client = create_client(profile, capture.append, credential_root=tmp_path/'credentials')
    assert client.complete('public prompt', ModelConfig(name='glm', max_tokens=64)).content == 'A'
    assert sent[0].get_header('Authorization') == 'Bearer private-transport-key'
    assert 'private-transport-key' not in json.dumps(capture)
    def failed(*args, **kwargs):
        raise urllib.error.URLError('provider reflected private-transport-key')
    monkeypatch.setattr('urllib.request.urlopen', failed)
    with pytest.raises(Exception) as caught:
        client.complete('public prompt', ModelConfig(name='glm', max_tokens=64))
    assert 'private-transport-key' not in str(caught.value)
    health = registry.check('cloud')
    assert health['status'] == 'offline' and health['verified'] is False
    assert 'private-transport-key' not in json.dumps(health)


def test_api_metadata_check_does_not_attest_weights(tmp_path, monkeypatch):
    import io
    registry = ModelRegistry(tmp_path)
    registry.save(api_profile(), api_key='metadata-private-key')
    def opened(request, **kwargs):
        assert request.get_header('Authorization') == 'Bearer metadata-private-key'
        return io.BytesIO(b'{"data":[{"id":"glm"}]}')
    monkeypatch.setattr('urllib.request.urlopen', opened)
    health = registry.check('cloud')
    assert health['status'] == 'reachable'
    assert health['verified'] is False


def test_api_basic_preview_freezes_config_and_scientific_still_requires_lock(tmp_path):
    from services.kb_workflow_api.app import create_app
    app = create_app(state_root=tmp_path/'state', allowed_roots=[tmp_path], execution_enabled=False)
    client = TestClient(app)
    app.state.models.save(api_profile(), api_key='workflow-private-key')
    questions = [{'id': 'q', 'family': 'univariate_regression', 'dataset_id': 'd',
                  'lineage_id': 'd', 'split': 'discovery', 'prompt': 'PUBLIC',
                  'choices': [{'id': 'c'+x, 'letter': x, 'view': {}} for x in 'ABC'],
                  'feedback': {'correct_letter': 'B'}}]
    path = tmp_path/'questions.json'; path.write_text(json.dumps(questions))
    app.state.catalog.import_source(path)
    key = app.state.catalog.list_questions()['items'][0]['key']
    selected = app.state.catalog.create_question_set('one', [key])
    workflow = default_workflow()
    workflow['settings'].update(model_id='cloud', question_set_id=selected['id'])
    body = {'kind': 'workflow', 'workflow': workflow, 'model_ids': ['cloud'], 'question_set_id': selected['id']}
    preview = client.post('/api/studio/runs/preview', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['learning']['model_weights_fixed'] is False
    assert preview.json()['learning']['model_identity']['kind'] == 'api_configuration'
    assert 'workflow-private-key' not in preview.text
    app.state.models.save(api_profile(), api_key='rotated-workflow-key')
    fresh = client.post('/api/studio/runs/preview', json=body)
    assert fresh.json()['config_hash'] != preview.json()['config_hash']
    scientific = default_workflow('scientific')
    scientific['settings'].update(workflow['settings'], method_id='scientific')
    blocked = client.post('/api/studio/runs/preview', json={**body, 'workflow': scientific})
    assert blocked.status_code == 422
    assert 'API' in blocked.text


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('response_model', ['glm', 'glm-provider-version'])
def test_api_basic_executes_canonical_learning_with_sealed_receipts(tmp_path, monkeypatch, stream, response_model):
    from architecture_iq.studio import execution
    from architecture_iq.studio.models import api_identity
    from architecture_iq.kb.store import canonical_hash
    from architecture_iq.studio.jobs import JobStore
    from test_studio_execution import fixture_config
    from test_studio_round_decisions import await_waiting
    from test_kb_experience import MemoryClient
    config = fixture_config()
    config['workflow'] = default_workflow()
    config['question_set']['questions'][0]['split'] = 'discovery'
    profile = ModelRegistry(tmp_path).save(api_profile(), api_key='learning-private-key')
    profile['service_identity'] = api_identity(profile)
    profile['runtime_fingerprint'] = canonical_hash(profile['service_identity'])
    config['models'] = [profile]
    config['transport'] = {'stream': stream}
    client = MemoryClient()
    import io
    from tools.llm_eval.llm_client import ModelConfig
    sent = []
    def opened(request, **kwargs):
        sent.append(request)
        assert request.get_header('Authorization') == 'Bearer learning-private-key'
        payload = json.loads(request.data)
        response = client.complete(payload['messages'][0]['content'], ModelConfig(name=payload['model']))
        content = response.raw['choices'][0]['message']['content']
        if stream:
            chunk = {'id': 'reply', 'model': response_model, 'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': 'stop'}], 'usage': response.usage}
            return io.BytesIO(('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode())
        return io.BytesIO(json.dumps({**response.raw, 'model': response_model, 'usage': response.usage,
                                     'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen', opened)
    store = JobStore(tmp_path); job = store.create('workflow', config)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execution.execute_workflow, store, job['id'], config)
        try:
            await_waiting(store, job['id'], future)
            store.decide_round(job['id'], round_index=1, action='finish')
            result = future.result(timeout=5)
            assert len(client.prompts) == 2
            assert len(sent) == 2
            assert result['experience']['scientific_status'] == 'unverified'
            assert result['model_identity']['weights_verified'] is False
            manifest = json.loads((store.directory(job['id'])/'workflow/manifest.json').read_text())
            assert manifest['config']['runtime_identity']['kind'] == 'api_configuration'
            receipts = list((store.directory(job['id'])/'workflow/calls').glob('*.json'))
            assert receipts
            assert all(json.loads(p.read_text())['raw']['model'] == response_model for p in receipts)
            assert 'learning-private-key' not in json.dumps(result)
            if stream:
                stream_text = (store.directory(job['id'])/'stream.jsonl').read_text()
                assert 'learning-private-key' not in stream_text
                assert 'chunk' in stream_text
        finally:
            current = store.get(job['id'])
            if not future.done() and current.get('round_decision', {}).get('status') == 'waiting':
                store.decide_round(job['id'], round_index=current['round_decision_index'], action='finish')


def test_reflected_secret_in_sse_error_never_reaches_observer(tmp_path, monkeypatch):
    import io
    from architecture_iq.studio.execution import create_client
    from tools.llm_eval.llm_client import ModelConfig
    registry = ModelRegistry(tmp_path)
    profile = registry.save(api_profile(), api_key='sse-private-key')
    from architecture_iq.studio.jobs import JobStore
    from services.kb_workflow_api.app import create_app
    store = JobStore(tmp_path)
    job = store.create('workflow', {'transport': {'stream': True}})
    store.reserve(job['id'], 'wire', {'prompt': 'public'})
    def opened(*args, **kwargs):
        return io.BytesIO(b'data: {"error":{"message":"invalid sse-private-key"}}\n\n')
    monkeypatch.setattr('urllib.request.urlopen', opened)
    client = create_client(profile, lambda _: None, stream=True,
                           chunk_observer=lambda event: store.append_stream(job['id'], 'wire', {'node_id': 'solver'}, event),
                           credential_root=tmp_path/'credentials')
    with pytest.raises(Exception) as caught:
        client.complete('public', ModelConfig(name='glm', max_tokens=64))
    assert 'sse-private-key' not in str(caught.value)
    events = store.stream_events(job['id'])
    assert events and 'sse-private-key' not in json.dumps(events)
    assert 'sse-private-key' not in (store.directory(job['id'])/'stream.jsonl').read_text()
    store.update(job['id'], status='failed')
    app = create_app(state_root=tmp_path, allowed_roots=[tmp_path], execution_enabled=False)
    stream = TestClient(app).get('/api/studio/runs/'+job['id']+'/stream')
    assert '[redacted]' in stream.text and 'sse-private-key' not in stream.text


def test_api_alias_still_rejects_within_stream_model_change(tmp_path, monkeypatch):
    import io
    from architecture_iq.studio.execution import create_client
    from tools.llm_eval.llm_client import ModelConfig
    profile = ModelRegistry(tmp_path).save(api_profile(), api_key='alias-private-key')
    chunks = [ {'id': 'one', 'model': model, 'choices': [{'index': 0, 'delta': {'content': 'A'}, 'finish_reason': None}]} for model in ['provider-v1', 'provider-v2'] ]
    body = ''.join('data: '+json.dumps(chunk)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n'
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: io.BytesIO(body.encode()))
    client = create_client(profile, lambda _: None, stream=True, credential_root=tmp_path/'credentials')
    with pytest.raises(Exception, match='changed model'):
        client.complete('public', ModelConfig(name='glm', max_tokens=64))


@pytest.mark.parametrize('field', ['content', 'reasoning_content'])
def test_stream_redaction_buffers_split_secret_and_preserves_other_text(tmp_path, monkeypatch, field):
    import io
    from architecture_iq.studio.execution import create_client
    from architecture_iq.studio.jobs import JobStore
    from tools.llm_eval.llm_client import ModelConfig
    profile = ModelRegistry(tmp_path).save(api_profile(), api_key='split-private-key')
    store = JobStore(tmp_path)
    job = store.create('evaluation', {'transport': {'stream': True}})
    store.reserve(job['id'], 'wire', {})
    pieces = ['hello split-', 'private-key world s', 'plit-']
    chunks = [{'model':'glm', 'choices':[{'index':0, 'delta':{field:piece}, 'finish_reason':None}]} for piece in pieces]
    chunks.append({'model':'glm', 'choices':[{'index':0, 'finish_reason':'stop'}]})
    body = ''.join('data: '+json.dumps(chunk)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n'
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: io.BytesIO(body.encode()))
    client = create_client(profile, lambda _: None, stream=True, credential_root=tmp_path/'credentials')
    # Evaluation assigns its observer after client construction.
    client.chunk_observer = lambda event: store.append_stream(job['id'], 'wire', {}, event)
    client.complete('public', ModelConfig(name='glm', max_tokens=64))
    frames = [event['chunk'] for event in store.stream_events(job['id']) if 'chunk' in event]
    visible = ''.join(choice.get('delta', {}).get(field, '') for frame in frames for choice in frame.get('choices', []))
    assert visible == 'hello [redacted] world split-'
    serialized_frames = [json.loads(event['data']) for event in store.stream_events(job['id']) if event.get('kind') == 'chunk']
    serialized_visible = ''.join(choice.get('delta', {}).get(field, '') for frame in serialized_frames for choice in frame.get('choices', []))
    assert serialized_visible == visible
