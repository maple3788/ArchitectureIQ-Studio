"""Streaming tests use only synthetic local HTTP; never a model server."""
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools.llm_eval.llm_client import LLMClient, LLMClientError, ModelConfig, build_request_payload


def chunk(delta=None, finish=None, **extra):
    return {'id': 'response1', 'model': 'fake', 'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}], **extra}


def frame(value):
    return ('data: ' + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)) + '\n\n').encode()


class Reply(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def test_stream_exact_request_unicode_usage_and_original_frames(monkeypatch):
    wire, observed, sends = [], [], []
    values = [chunk({'role': 'assistant', 'reasoning_content': '推理'}), chunk({'content': '答'}), chunk({'content': '案'}, 'stop'),
              {'id': 'response1', 'model': 'fake', 'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 3}}]
    def send(request, **_):
        assert wire and not observed
        sends.append(json.loads(request.data))
        return Reply(b': heartbeat\n\n' + b''.join(frame(v) for v in values) + frame('[DONE]'))
    monkeypatch.setattr('urllib.request.urlopen', send)
    client = LLMClient(base_url='http://fake/v1', api_key='unused', stream=True, request_observer=wire.append, chunk_observer=observed.append)
    model = ModelConfig('fake', max_tokens=20)
    result = client.complete('public', model)
    expected = build_request_payload([{'role': 'user', 'content': 'public'}], model, stream=True)
    assert sends == [expected] and wire[0]['payload'] == expected
    assert expected['stream_options'] == {'include_usage': True}
    assert result.raw['choices'][0]['message'] == {'role': 'assistant', 'reasoning_content': '推理', 'content': '答案'}
    assert result.raw['response_format'] == 'assembled_from_sse'
    assert result.usage == {'prompt_tokens': 12, 'completion_tokens': 3}
    assert [v['chunk'] for v in observed if v['kind'] == 'chunk'] == values
    assert observed[-1]['kind'] == 'done'
    assert client.max_retries == 0


@pytest.mark.parametrize('ending', ['eof', 'missing_finish', 'bad_json', 'wrong_model', 'changed_id'])
def test_incomplete_or_invalid_stream_never_retries(monkeypatch, ending):
    sent, observed = [], []
    payload = frame(chunk({'content': 'partial'}))
    if ending == 'missing_finish': payload += frame('[DONE]')
    elif ending == 'bad_json': payload += b'data: {broken}\n\n'
    elif ending == 'wrong_model': payload += frame({**chunk({}, 'stop'), 'model': 'other'}) + frame('[DONE]')
    elif ending == 'changed_id': payload += frame({**chunk({}, 'stop'), 'id': 'other'}) + frame('[DONE]')
    def send(*args, **kwargs): sent.append(True); return Reply(payload)
    monkeypatch.setattr('urllib.request.urlopen', send)
    client = LLMClient(base_url='http://fake/v1', api_key='unused', max_retries=4, stream=True, chunk_observer=observed.append)
    with pytest.raises(LLMClientError): client.complete('public', ModelConfig('fake'))
    assert len(sent) == 1
    assert observed[0]['chunk']['choices'][0]['delta']['content'] == 'partial'


def test_durable_stream_cursor_and_terminal_sse_replay(tmp_path):
    from fastapi.testclient import TestClient
    from architecture_iq.studio.jobs import JobStore
    from services.kb_workflow_api.app import create_app
    store = JobStore(tmp_path)
    job = store.create('evaluation', {'transport': {'stream': True}})
    store.reserve(job['id'], 'call-1', {})
    first = store.append_stream(job['id'], 'call-1', {'node_id': 'solver'}, {'kind': 'chunk', 'chunk': chunk({'content': '一'}), 'data': 'original'})
    second = store.append_stream(job['id'], 'call-1', {'node_id': 'solver'}, {'kind': 'done', 'data': '[DONE]'})
    assert (first['seq'], second['seq']) == (1, 2)
    assert store.stream_events(job['id'], after=1) == [second]
    assert store.get(job['id'])['records'][0]['status'] == 'pending'
    store.update(job['id'], status='uncertain', error='connection interrupted')
    app = create_app(state_root=tmp_path, allowed_roots=[tmp_path], execution_enabled=False)
    client = TestClient(app)
    response = client.get(f"/api/studio/runs/{job['id']}/stream", headers={'Last-Event-ID': '1'})
    assert response.status_code == 200
    assert 'id: 2' in response.text and 'id: 1\n' not in response.text
    assert 'event: terminal' in response.text and 'uncertain' in response.text
    assert 'original' not in response.text
    assert client.get(f"/api/studio/runs/{job['id']}").json()['transport']['stream'] is True


def test_legacy_job_sse_is_explicitly_unavailable(tmp_path):
    from fastapi.testclient import TestClient
    from architecture_iq.studio.jobs import JobStore
    from services.kb_workflow_api.app import create_app
    store = JobStore(tmp_path); job = store.create('evaluation', {})
    client = TestClient(create_app(state_root=tmp_path, allowed_roots=[tmp_path], execution_enabled=False))
    response = client.get(f"/api/studio/runs/{job['id']}/stream")
    assert 'event: unavailable' in response.text
    assert client.get(f"/api/studio/runs/{job['id']}").json()['transport']['legacy'] is True
    assert 'transport' not in store.definition(job['id'])['config']


def test_role_receipt_stays_pending_until_real_http_stream_finishes(tmp_path):
    from architecture_iq.kb.roles import RoleCaller, read_receipt
    from architecture_iq.studio.jobs import JobStore
    store = JobStore(tmp_path / 'studio')
    job = store.create('workflow', {'transport': {'stream': True}})
    arrived, release = threading.Event(), threading.Event()
    received_requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            received_requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            self.wfile.write(frame(chunk({'content': '{"hypothesis":'}))); self.wfile.flush()
            assert release.wait(5)
            self.wfile.write(frame(chunk({'content': 'null}'}, 'stop')) + frame('[DONE]')); self.wfile.flush()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def wire(value):
        store.reserve(job['id'], 'wire-0', {'node_id': 'discoverer'})
        store.update_record(job['id'], 'wire-0', {'actual_request': value})
    def receive(value):
        store.append_stream(job['id'], 'wire-0', {'node_id': 'discoverer', 'round_index': 1, 'operation_key': 'packet-0'}, value)
        arrived.set()
    client = LLMClient(base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key='unused', stream=True, request_observer=wire, chunk_observer=receive)
    caller = RoleCaller(tmp_path / 'workflow', client, ModelConfig('fake', max_tokens=50), fingerprint='fixture')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(caller.call, 'discoverer', {}, key='packet-0', round_index=1)
            assert arrived.wait(3)
            assert not future.done()
            assert store.stream_events(job['id'])[0]['chunk']['choices'][0]['delta']['content'] == '{"hypothesis":'
            receipt = next((tmp_path / 'workflow/calls').glob('*.json'))
            assert read_receipt(receipt)['status'] == 'pending'
            release.set()
            assert future.result(timeout=3) == {'hypothesis': None}
            assert read_receipt(receipt)['status'] == 'complete'
        assert len(received_requests) == 1 and received_requests[0]['stream'] is True
    finally:
        release.set(); server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_multiline_sse_event_and_crlf_are_parsed_as_one_chunk(monkeypatch):
    value = chunk({'content': '中文'}, 'stop')
    data = '\r\n'.join('data: ' + line for line in json.dumps(value, ensure_ascii=False, indent=2).splitlines())
    payload = (': keepalive\r\n\r\n' + data + '\r\n\r\ndata: [DONE]\r\n\r\n').encode()
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Reply(payload))
    received = []
    client = LLMClient(base_url='http://fake/v1', api_key='unused', stream=True, chunk_observer=received.append)
    assert client.complete('question', ModelConfig('fake')).assistant_message['content'] == '中文'
    assert len(received) == 2 and received[0]['chunk'] == value


def test_streaming_evaluation_matches_preview_and_commits_only_final_result(tmp_path, monkeypatch):
    from architecture_iq.studio.execution import execute_evaluation, preview_evaluation
    from architecture_iq.studio.jobs import JobStore
    model = {'id': 'm', 'model': 'fake', 'revision': 'frozen', 'base_url': 'http://fake/v1',
             'parameters': {'temperature': 0, 'max_tokens': 100, 'extra': {}}, 'context_size': 32768}
    config = {'transport': {'stream': True}, 'models': [model], 'max_calls': 2, 'max_tokens': 10000,
              'question_set': {'id': 'set', 'questions': [{'id': 'q', 'prompt': 'public', 'choices': [{'id': x, 'letter': x, 'view': {}} for x in 'ABC']}],
                               'feedback': {'q': {'correct_letter': 'B'}}}}
    preview = preview_evaluation(config)
    store = JobStore(tmp_path); job = store.create('evaluation', config)
    observed = []
    def send(request, **_):
        observed.append(json.loads(request.data))
        raw = '{"ranking":["B","A","C"],"citations":[],"rationale":"test"}'
        return Reply(frame(chunk({'content': raw}, 'stop')) + frame('[DONE]'))
    monkeypatch.setattr('urllib.request.urlopen', send)
    result = execute_evaluation(store, job['id'], config)
    assert observed == [preview['requests'][0]['payload']]
    assert observed[0]['stream'] is True
    assert result['scores']['m']['correct'] == 1
    record = store.get(job['id'])['records'][0]
    assert record['status'] == 'complete' and record['answer']['ranking'][0] == 'B'
    frames = store.stream_events(job['id'])
    assert frames[0]['operation_key'] == 'q' and frames[-1]['kind'] == 'done'
    assert all('feedback' not in entry for entry in frames)


def test_preview_api_defaults_to_frozen_stream_and_rejects_override(tmp_path):
    from fastapi.testclient import TestClient
    from services.kb_workflow_api.app import create_app
    app = create_app(state_root=tmp_path / 'state', allowed_roots=[tmp_path], execution_enabled=False)
    path = tmp_path / 'questions.json'
    path.write_text(json.dumps([{'id': 'q', 'family': 'univariate_regression', 'dataset_id': 'd', 'lineage_id': 'd', 'prompt': 'public',
                                 'choices': [{'id': 'c' + x, 'letter': x, 'view': {}} for x in 'ABC'], 'feedback': {'correct_letter': 'B'}}]))
    app.state.catalog.import_source(path)
    key = app.state.catalog.list_questions()['items'][0]['key']
    selected = app.state.catalog.create_question_set('test', [key])
    app.state.models.save({'id': 'm', 'name': 'Fake', 'model': 'fake', 'base_url': 'http://localhost:1/v1', 'parameters': {'max_tokens': 100}})
    client = TestClient(app)
    body = {'kind': 'evaluation', 'question_set_id': selected['id'], 'model_ids': ['m']}
    response = client.post('/api/studio/runs/preview', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['requests'][0]['payload']['stream'] is True
    assert client.post('/api/studio/runs/preview', json={**body, 'transport': {'stream': False}}).status_code == 422


def test_disconnect_preserves_pending_role_receipt_and_refuses_retry(tmp_path, monkeypatch):
    from architecture_iq.kb.roles import RoleCaller, read_receipt
    attempts = []
    def send(*args, **kwargs):
        attempts.append(True)
        return Reply(frame(chunk({'content': '{"hypothesis":null}'}, 'stop')))
    monkeypatch.setattr('urllib.request.urlopen', send)
    client = LLMClient(base_url='http://fake/v1', api_key='unused', stream=True)
    caller = RoleCaller(tmp_path, client, ModelConfig('fake', max_tokens=100), fingerprint='test')
    with pytest.raises(LLMClientError, match='before'):
        caller.call('discoverer', {}, key='packet-0', round_index=1)
    receipt = read_receipt(next((tmp_path / 'calls').glob('*.json')))
    assert receipt['status'] == 'pending' and 'result' not in receipt
    with pytest.raises(RuntimeError, match='pending'):
        caller.call('discoverer', {}, key='packet-0', round_index=1)
    assert len(attempts) == 1


def test_workflow_evaluation_stream_uses_evaluate_stage_identity(tmp_path, monkeypatch):
    import copy
    from architecture_iq.kb import cli
    from architecture_iq.kb.store import canonical_hash
    from architecture_iq.studio import execution
    from architecture_iq.studio.jobs import JobStore
    from test_studio_execution import fixture_config
    from test_studio_workflow import default_workflow, enable_optional, inputs, Client
    spec = default_workflow("scientific")
    spec["settings"]["loop_mode"] = "automatic"
    enable_optional(spec, 'evaluate', 'loop', 'end', 'done')
    _, questions, private, _ = inputs()
    q = copy.deepcopy(questions[0]); q.update(id='eval-q', dataset_id='eval-d', lineage_id='eval-l', split='final')
    questions.append(q); private['eval-q'] = copy.deepcopy(private['q1'])
    config = fixture_config(); config.update(workflow=spec, transport={'stream': True})
    lock = tmp_path / 'runtime.json'; lock.write_text('{}')
    config['models'][0].update(runtime_lock_path=str(lock), runtime_fingerprint=canonical_hash({}))
    config['question_set'].update(questions=questions, feedback=private)
    monkeypatch.setattr(cli, 'read_runtime_lock', lambda *a, **k: None)
    monkeypatch.setattr(cli, 'verify_live_runtime', lambda *a, **k: None)
    # Mock only the external transport; actual observers, RoleCaller, workflow
    # events, receipt seals and evaluation phases run through production code.
    def factory(profile, observer, **kwargs):
        return LLMClient(base_url='http://fake/v1', api_key='unused', request_observer=observer, **kwargs)
    monkeypatch.setattr(execution, 'create_client', factory)
    fake = Client()
    def send(request, **_):
        body = json.loads(request.data)
        response = fake.complete(body['messages'][0]['content'], ModelConfig(body['model']))
        return Reply(frame({'id': 'response1', 'model': body['model'], 'choices': [{'index': 0, 'delta': response.raw['choices'][0]['message'], 'finish_reason': 'stop'}]}) + frame('[DONE]'))
    monkeypatch.setattr('urllib.request.urlopen', send)
    store = JobStore(tmp_path / 'studio'); job = store.create('workflow', config)
    result = execution.execute_workflow(store, job['id'], config)
    assert result['evaluation']['scores']['current']['correct'] == 1
    rows = [v for v in store.stream_events(job['id']) if v['node_id'] == 'evaluate']
    assert rows and {v['round_index'] for v in rows} == {1000}
    assert {v['arm'] for v in rows} == {'clean', 'initial', 'current'}
    assert all(v['operation_key'].startswith('eval-final-') and v['question_key'] == 'eval-q' for v in rows)


def test_workflow_text_step_attribution_and_seal_follow_role_validation(tmp_path, monkeypatch):
    # Reuse the existing full local streaming coordinator fixture, retaining
    # every production journal and RoleCaller seal.
    test_workflow_evaluation_stream_uses_evaluate_stage_identity(tmp_path, monkeypatch)
    from architecture_iq.studio.jobs import JobStore
    store = JobStore(tmp_path / 'studio'); job = store.list()[0]
    records = store.get(job['id'])['records']
    task_records = [record for record in records if record['inputs']['node_id'] == 'evaluate']
    assert task_records and all(record['inputs']['step_id'] == 'evaluate' for record in task_records)
    assert all(record['inputs']['stage_id'] == 'task' for record in task_records)
    events = store.events(job['id'])
    sealed = [event for event in events if event['type'] == 'output_sealed' and event['node_id'] == 'evaluate']
    assert len(sealed) == 3 and all(event['artifact_refs'] for event in sealed)
    assert all(event['sequence'] > next(row['sequence'] for row in events
        if row['type'] == 'request_sent' and row['attempt_id'] == event['attempt_id']) for event in sealed)
