import copy
import json
import pytest

from rag_fixtures import make_rag_case


def case_for_api(tmp_path, monkeypatch, enabled=False):
    case = make_rag_case(tmp_path, monkeypatch, execution_enabled=enabled)
    monkeypatch.setattr('architecture_iq.studio.knowledge.knowledge_inventory', lambda *a: case['inventory'])
    case['launches'] = []
    def launch(identifier):
        case['launches'].append(identifier)
        case['jobs'].update(identifier, status='starting')
    monkeypatch.setattr(case['jobs'], 'launch', launch)
    return case


def preview(case, selection=None):
    return case['client'].post('/api/studio/rag/preview', json=selection or case['selection'])


def start(case, p=None, **changes):
    p = p or preview(case).json()
    return case['client'].post('/api/studio/rag/runs', json={**case['selection'], 'preview_hash': p['preview_hash'], **changes},
                              headers={'Idempotency-Key': 'rag-one'})


def test_preview_is_public_and_creates_no_job_or_call(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch)
    response = preview(case)
    assert response.status_code == 200, response.text
    assert response.json()['sent'] is False and response.json()['can_answer'] is True
    assert 'correct_letter' not in response.text
    assert not case['jobs'].list() and not case['calls']


@pytest.mark.parametrize('changes', [{'knowledge_limit': x} for x in (False, 0, 13)] +
                         [{'snapshot': {}}, {'path': '/tmp'}, {'knowledge': []}, {'unknown': 1}])
def test_preview_rejects_invalid_limit_extra_fields_and_inline_knowledge(tmp_path, monkeypatch, changes):
    case = case_for_api(tmp_path, monkeypatch)
    assert preview(case, {**case['selection'], **changes}).status_code == 422


def test_run_requires_authorized_execution(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch)
    assert start(case).status_code == 409
    assert not case['jobs'].list() and not case['launches']


@pytest.mark.parametrize('change', ['inventory', 'source', 'model', 'limit', 'fingerprint'])
def test_stale_preview_rejects_before_job_or_launch(tmp_path, monkeypatch, change):
    case = case_for_api(tmp_path, monkeypatch, True)
    p = preview(case).json()
    changes = {}
    if change == 'inventory': case['inventory']['items'] = []
    if change == 'source': case['inventory']['items'][0]['snapshot']['lessons'][0]['text'] = 'changed'
    if change == 'model':
        model = case['models'].get('glm'); model.pop('revision'); model['parameters']['max_tokens'] += 1
        case['models'].save(model)
    if change == 'limit': changes['knowledge_limit'] = 1
    if change == 'fingerprint': monkeypatch.setattr('architecture_iq.studio.jobs.source_fingerprint', lambda: 'changed')
    response = start(case, p, **changes)
    assert response.status_code == 409, response.text
    assert not case['jobs'].list() and not case['launches']


def test_duplicate_submission_returns_one_job_and_one_launch(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch, True)
    p = preview(case).json()
    first, second = start(case, p), start(case, p)
    assert first.status_code == second.status_code == 200
    assert first.json()['id'] == second.json()['id']
    assert len(case['jobs'].list()) == len(case['launches']) == 1
    fresh = preview(case, {**case['selection'], 'knowledge_limit': 1}).json()
    assert start(case, fresh, knowledge_limit=1).status_code == 409


def test_no_match_cannot_create_rag_job(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch, True)
    case['inventory']['items'] = []
    assert start(case).status_code == 409
    assert not case['jobs'].list()
