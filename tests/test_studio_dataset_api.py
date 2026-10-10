import json

from test_studio_api import make_client
from test_studio_catalog import baked, bakefile

PREFIX = '/api/studio'


def create(client, name='A', **extra):
    response = client.post(PREFIX + '/datasets', json={'name': name, **extra}, headers={'Idempotency-Key': name})
    assert response.status_code == 200, response.text
    return response.json()


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
