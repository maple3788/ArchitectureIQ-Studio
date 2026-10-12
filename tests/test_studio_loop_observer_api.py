import asyncio
import json

from fastapi.testclient import TestClient

from architecture_iq.studio.loop_observer import LoopObserver
from services.kb_workflow_api.app import create_app
from services.kb_workflow_api.loop_observer_routes import observation_events
from test_studio_loop_observer import capture, configuration


def client_for(tmp_path, observer):
    return TestClient(create_app(state_root=tmp_path, allowed_roots=[tmp_path],
                                 execution_enabled=False, loop_observer=observer))


def test_observer_api_projects_snapshots_and_details_without_paths(tmp_path):
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: capture())
    observer.poll_once()
    client = client_for(tmp_path, observer)
    assert client.get('/api/studio/bootstrap').json()['service']['knowledge_loop_configured'] is True
    for path in ['/kb-loop', '/kb-loop/claims/C1', '/kb-loop/rounds/1']:
        response = client.get('/api/studio' + path)
        assert response.status_code == 200
        assert all(secret not in response.text for secret in ['authorized.test', '/private/', 'researcher'])
    snapshot = client.get('/api/studio/kb-loop').json()
    assert 'claim_details' not in snapshot and 'round_details' not in snapshot
    assert client.get('/api/studio/kb-loop/claims/missing').status_code == 404
    assert client.get('/api/studio/kb-loop/rounds/0').status_code == 422
    assert client.post('/api/studio/kb-loop/start').status_code in {404, 405}


def test_unconfigured_stream_finishes_without_network(tmp_path):
    observer = LoopObserver(tmp_path)
    client = client_for(tmp_path, observer)
    result = client.get('/api/studio/kb-loop/stream')
    assert result.status_code == 200 and 'event: sync' in result.text
    assert 'unconfigured' in result.text
    assert client.get('/api/studio/kb-loop').json()['configured'] is False
    assert client.get('/api/studio/kb-loop/stream?after=-1').status_code == 422
    for value in ['invalid', '-1', '1.2', str(2**63)]:
        assert client.get('/api/studio/kb-loop/stream', headers={'Last-Event-ID': value}).status_code == 400
    assert client.get('/api/studio/kb-loop/stream?after=' + str(2**63)).status_code == 422


def test_sse_replays_durable_snapshots_after_cursor_then_sync(tmp_path):
    value = [capture()]
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value[0])
    observer.poll_once()
    value[0] = capture(2)
    observer.poll_once()
    value[0] = capture(3)
    observer.poll_once()
    class Request:
        async def is_disconnected(self):
            return False
    async def receive():
        stream = observation_events(observer, Request(), after=1)
        frames = [await anext(stream) for _ in range(3)]
        await stream.aclose()
        return frames
    frames = asyncio.run(receive())
    assert 'event: sync' in frames[0]
    assert 'id: 2\nevent: snapshot' in frames[1]
    assert 'id: 3\nevent: snapshot' in frames[2]
    assert json.loads(frames[2].split('data: ', 1)[1])['round']['build']['ok'] == 3
    assert observer.snapshot()['sequence'] == 3


def test_lifespan_starts_and_stops_observer_once(tmp_path, monkeypatch):
    observer = LoopObserver(tmp_path)
    calls = []
    monkeypatch.setattr(observer, 'start', lambda: calls.append('start'))
    monkeypatch.setattr(observer, 'stop', lambda: calls.append('stop'))
    with client_for(tmp_path, observer) as client:
        assert client.get('/api/studio/kb-loop').status_code == 200
    assert calls == ['start', 'stop']
