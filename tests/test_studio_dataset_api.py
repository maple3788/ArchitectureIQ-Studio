import json
import pytest

from test_studio_api import make_client
from test_studio_catalog import baked, bakefile

PREFIX = '/api/studio'


def create(client, name='A', **extra):
    response = client.post(PREFIX + '/datasets', json={'name': name, **extra}, headers={'Idempotency-Key': name})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('revision', [[], {}, None, 1, '', True])
def test_import_rejects_malformed_revision_without_mutating_dataset(tmp_path, revision):
    client, source = make_client(tmp_path)
    path = bakefile(source / 'in.json', [baked()])
    imported = client.post(PREFIX + '/sources/import', json={'path': str(path)}).json()
    dataset = create(client)
    base = PREFIX + f"/datasets/{dataset['collection_id']}"
    response = client.post(base + '/imports', json={
        'source_id': imported['source_id'], 'expected_revision': revision}, headers={'Idempotency-Key': 'bad'})
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'invalid_dataset_request'
    assert client.get(base).json() == dataset


def test_dataset_api_is_available_locally_and_returns_structured_conflict(tmp_path):
    client, _ = make_client(tmp_path)
    a = create(client)
    path = PREFIX + f"/datasets/{a['collection_id']}/revisions"
    body = {'expected_revision': a['revision'], 'changes': {'name': 'B'}}
    assert client.post(path, json=body, headers={'Idempotency-Key': 'edit'}).status_code == 200
    body['changes'] = {'name': 'C'}
    response = client.post(path, json=body, headers={'Idempotency-Key': 'stale'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'dataset_revision_conflict'
    assert response.json()['detail']['current_revision']
    assert client.get(PREFIX + '/datasets/absent').status_code == 404
    bad = client.post(PREFIX + '/datasets', json={'name': 'X', 'feedback': {}}, headers={'Idempotency-Key': 'x'})
    assert bad.status_code == 422 and bad.json()['detail']['code'] == 'invalid_dataset_request'


def test_bank_membership_and_import_retries_preserve_original_question_counts(tmp_path):
    client, source = make_client(tmp_path)
    path = bakefile(source / 'in.json', [baked('q1'), baked('q2')])
    imported = client.post(PREFIX + '/sources/import', json={'path': str(path)}).json()
    a, b = create(client), create(client, name='B')
    for dataset in (a, b):
        url = PREFIX + f"/datasets/{dataset['collection_id']}/imports"
        body = {'source_id': imported['source_id'], 'expected_revision': dataset['revision']}
        first = client.post(url, json=body, headers={'Idempotency-Key': 'import'})
        second = client.post(url, json=body, headers={'Idempotency-Key': 'import'})
        assert first.status_code == 200, first.text
        assert first.json() == second.json()
        assert len(first.json()['keys']) == 1
    assert client.get(PREFIX + '/questions').json()['total'] == 2
    bank = client.get(PREFIX + '/question-bank').json()
    assert bank['total'] == 1 and len(bank['items'][0]['datasets']) == 2
    assert 'correct_letter' not in json.dumps(bank)
    assert client.get(PREFIX + '/question-bank?limit=0').status_code == 422
    assert client.get(PREFIX + '/question-bank?feedback=true').status_code == 422
    assert client.post(PREFIX + '/sources/import', json={'path': str(tmp_path / 'outside.json')}).status_code == 422
    selected = client.get(PREFIX + f"/datasets/{a['collection_id']}").json()
    members = client.get(PREFIX + f"/datasets/{a['collection_id']}/questions", params={'revision': selected['revision']}).json()
    assert members['total'] == 1


def test_dataset_selection_preview_and_freeze_do_not_expose_feedback(tmp_path):
    client, source = make_client(tmp_path)
    path = bakefile(source / 'in.json', [baked()])
    imported = client.post(PREFIX + '/sources/import', json={'path': str(path)}).json()
    a = create(client, keys=[imported['entries'][0]['key']])
    base = PREFIX + f"/datasets/{a['collection_id']}"
    body = {'revision': a['revision'], 'purpose': 'research', 'method_id': 'basic_learning'}
    preview = client.post(base + '/selection-preview', json=body)
    assert preview.status_code == 200 and preview.json()['can_apply']
    frozen = client.post(base + '/question-set', json={**body, 'preview_hash': preview.json()['preview_hash']})
    assert frozen.status_code == 200 and frozen.json()['dataset_binding']['revision'] == a['revision']
    assert 'feedback' not in frozen.text
    assert client.post(base + '/question-set', json={**body, 'preview_hash': 'stale'}).status_code == 409


def test_local_attachment_api_and_job_projection_use_persisted_results(tmp_path):
    from test_studio_dataset_generation import staged_result
    c, store, datasets, target, job, _, _ = staged_result(tmp_path)
    client, _ = make_client(tmp_path)
    url = PREFIX + f"/generations/{job['id']}/dataset-attachment"
    response = client.post(url, json={'target': target}, headers={'Idempotency-Key': 'attach'})
    assert response.status_code == 200 and response.json()['status'] == 'attached'
    assert client.get(url).json() == response.json()
    assert client.get(PREFIX + f"/runs/{job['id']}").json()['dataset_attachment'] == response.json()
    assert client.post(PREFIX + '/generations', json=job['config']).status_code == 409
    assert client.post(url, json={'target': target, 'keys': []}, headers={'Idempotency-Key': 'bad'}).status_code == 422


def test_generation_preview_binds_target_and_detects_edits(tmp_path):
    from test_studio_generation import config
    client, _ = make_client(tmp_path)
    a = create(client)
    target = {k: a[k] for k in ('collection_id', 'revision')}
    response = client.post(PREFIX + '/generations/preview', json=config(dataset_target=target))
    assert response.status_code == 200 and response.json()['dataset_preview_hash']
    changed = client.post(PREFIX + f"/datasets/{a['collection_id']}/revisions", json={
        'expected_revision': a['revision'], 'changes': {'name': 'Changed'}}, headers={'Idempotency-Key': 'edit'})
    assert changed.status_code == 200
    assert client.post(PREFIX + '/generations/preview', json=config(dataset_target=target)).status_code == 409
