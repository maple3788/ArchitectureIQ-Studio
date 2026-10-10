"""Shared drafts survive restarts and cannot silently overwrite another browser."""
from copy import deepcopy
import json
import multiprocessing

from fastapi.testclient import TestClient
import pytest

from architecture_iq.studio.workflow import default_workflow
from services.kb_workflow_api.app import create_app


def client_for(root):
    return TestClient(create_app(state_root=root, allowed_roots=[root], execution_enabled=False))


def body(workflow, revision=1, advanced=None):
    return {"expected_revision": revision, "workflow": workflow, "advanced_backup": advanced}


def test_new_browsers_share_basic_draft_and_server_restart_preserves_edits(tmp_path):
    first = client_for(tmp_path)
    second = client_for(tmp_path)
    initial = first.get('/api/studio/workflow/draft')
    assert initial.status_code == 200
    initial = initial.json()
    assert initial['workflow']['settings']['method_id'] == 'basic_learning'
    assert initial['revision'] == 1
    assert initial['advanced_backup'] is None
    assert second.get('/api/studio/workflow/draft').json() == initial
    edited = deepcopy(initial['workflow'])
    edited['name'] = ''  # Empty text and partial numeric input are legitimate drafts.
    edited['settings'].update(max_rounds='', model_id='registered-model', question_set_id='selected-set')
    advanced = default_workflow('scientific')
    saved = first.put('/api/studio/workflow/draft', json=body(edited, advanced=advanced))
    assert saved.status_code == 200, saved.text
    assert saved.json()['revision'] == 2
    assert saved.json()['updated_at'] >= initial['updated_at']
    assert saved.json()['workflow'] == edited
    assert saved.json()['advanced_backup'] == advanced
    assert second.get('/api/studio/workflow/draft').json() == saved.json()
    assert client_for(tmp_path).get('/api/studio/workflow/draft').json() == saved.json()
    # Mutable autosaves must never create or mutate an execution-frozen workflow.
    assert first.get('/api/studio/workflows').json()['items'] == []


def test_stale_browser_conflicts_and_identical_retry_is_idempotent(tmp_path):
    client = client_for(tmp_path)
    initial = client.get('/api/studio/workflow/draft').json()
    changed = deepcopy(initial['workflow'])
    changed['name'] = 'Browser A'
    saved = client.put('/api/studio/workflow/draft', json=body(changed)).json()
    conflict = client.put('/api/studio/workflow/draft', json=body(initial['workflow']))
    assert conflict.status_code == 409
    assert client.get('/api/studio/workflow/draft').json() == saved
    retried = client.put('/api/studio/workflow/draft', json=body(changed))
    assert retried.status_code == 200
    assert retried.json() == saved
    backups = client.get('/api/studio/workflow/draft/backups').json()
    assert backups['total'] == 1
    assert backups['items'][0]['workflow'] == initial['workflow']
    assert backups['items'][0]['source'] == 'revision'


def test_legacy_backup_is_deduplicated_without_activating_old_browser_state(tmp_path):
    client = client_for(tmp_path)
    initial = client.get('/api/studio/workflow/draft').json()
    legacy = default_workflow('scientific')
    request = {'workflow': legacy, 'source': 'legacy_browser'}
    first = client.post('/api/studio/workflow/draft/backups', json=request)
    assert first.status_code == 200, first.text
    again = client.post('/api/studio/workflow/draft/backups', json=request)
    assert first.json() == again.json()
    assert first.json()['workflow'] == legacy
    assert first.json()['source'] == 'legacy_browser'
    assert client.get('/api/studio/workflow/draft').json() == initial
    assert client.get('/api/studio/workflow/draft/backups').json()['total'] == 1


def test_revision_history_recovers_advanced_backup_even_after_switching_methods(tmp_path):
    client = client_for(tmp_path)
    basic = client.get('/api/studio/workflow/draft').json()['workflow']
    scientific = default_workflow('scientific')
    client.put('/api/studio/workflow/draft', json=body(scientific))
    client.put('/api/studio/workflow/draft', json=body(basic, 2, scientific))
    edited = deepcopy(basic)
    edited['name'] = 'Edited basic'
    client.put('/api/studio/workflow/draft', json=body(edited, 3, None))
    history = client.get('/api/studio/workflow/draft/backups').json()['items']
    assert len(history) == 3
    previous = next(item for item in history if item['revision'] == 3)
    assert previous['workflow'] == basic
    assert previous['advanced_backup'] == scientific


@pytest.mark.parametrize('transform', [
    lambda request: {**request, 'expected_revision': True},
    lambda request: {**request, 'expected_revision': 0},
    lambda request: {key: value for key, value in request.items() if key != 'advanced_backup'},
    lambda request: {**request, 'workflow': []},
    lambda request: {**request, 'advanced_backup': {'name': 'missing shape'}},
    lambda request: {**request, 'workflow': {**request['workflow'], 'nodes': ['not an object']}},
])
def test_invalid_shape_is_rejected_without_changing_draft(tmp_path, transform):
    client = client_for(tmp_path)
    initial = client.get('/api/studio/workflow/draft').json()
    response = client.put('/api/studio/workflow/draft', json=transform(body(initial['workflow'])))
    assert response.status_code == 422
    assert client.get('/api/studio/workflow/draft').json() == initial


def test_oversized_and_nonfinite_json_rejected_without_saving(tmp_path):
    client = client_for(tmp_path)
    initial = client.get('/api/studio/workflow/draft').json()
    large = deepcopy(initial['workflow'])
    large['settings']['notes'] = 'x' * (1024 * 1024)
    response = client.put('/api/studio/workflow/draft', json=body(large))
    assert response.status_code == 413
    raw = json.dumps(body(initial['workflow'])).replace('"expected_revision": 1', '"expected_revision": NaN')
    assert client.put('/api/studio/workflow/draft', content=raw, headers={'content-type': 'application/json'}).status_code == 422
    assert client.get('/api/studio/workflow/draft').json() == initial


@pytest.mark.parametrize('source', ['unknown', {}, [], None])
def test_invalid_backup_source_is_validation_error(tmp_path, source):
    client = client_for(tmp_path)
    response = client.post('/api/studio/workflow/draft/backups',
                           json={'workflow': default_workflow(), 'source': source})
    assert response.status_code == 422


def test_existing_corrupt_draft_is_never_replaced_with_default(tmp_path):
    from architecture_iq.studio.drafts import DraftStore
    store = DraftStore(tmp_path)
    store.get()
    broken = b'{"revision": 3, "workflow": '
    store.path.write_bytes(broken)
    response = client_for(tmp_path).get('/api/studio/workflow/draft')
    assert response.status_code == 422
    assert store.path.read_bytes() == broken


def test_failed_replacement_keeps_current_and_recoverable_history(tmp_path, monkeypatch):
    from architecture_iq.studio import drafts
    store = drafts.DraftStore(tmp_path)
    initial = store.get()
    changed = deepcopy(initial['workflow'])
    changed['name'] = 'new'
    original_write = drafts.write_json_atomic

    def fail_replacement(path, value):
        if path == store.path:
            raise OSError('disk unavailable')
        original_write(path, value)

    monkeypatch.setattr(drafts, 'write_json_atomic', fail_replacement)
    with pytest.raises(OSError):
        store.save(expected_revision=1, workflow=changed, advanced_backup=None)
    assert store.get() == initial
    assert store.backups()['items'][0]['workflow'] == initial['workflow']


def _write_at_once(root, event, queue, name):
    from architecture_iq.studio.drafts import DraftStore
    store = DraftStore(root)
    draft = store.get()
    workflow = draft['workflow']
    workflow['name'] = name
    event.wait(10)
    try:
        queue.put(('saved', store.save(expected_revision=1, workflow=workflow, advanced_backup=None)))
    except RuntimeError:
        queue.put(('conflict', None))


def test_concurrent_processes_cannot_overwrite_each_other(tmp_path):
    from architecture_iq.studio.drafts import DraftStore
    initial = DraftStore(tmp_path).get()
    context = multiprocessing.get_context('spawn')
    event, queue = context.Event(), context.Queue()
    processes = [context.Process(target=_write_at_once, args=(tmp_path, event, queue, name)) for name in ('A', 'B')]
    for process in processes:
        process.start()
    event.set()
    results = [queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert sorted(result[0] for result in results) == ['conflict', 'saved']
    assert DraftStore(tmp_path).get()['revision'] == 2
    assert DraftStore(tmp_path).backups()['items'][0]['workflow'] == initial['workflow']
