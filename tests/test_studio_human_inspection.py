"""Explicit human inspection reads saved results without recording an answer."""
from copy import deepcopy
import json

import pytest

from test_studio_human_practice import evolution, feedback
from test_studio_knowledge_questions import api_case
from rule_refinement_fixtures import raw_case


def inspect(client, source, **extra):
    return client.post('/api/studio/questions/inspect', json={'source': source, **extra})


def test_catalog_inspection_reveals_saved_result_without_answer_or_solver_mutation(tmp_path, monkeypatch):
    raw = raw_case()
    raw['feedback'], raw['reveal'] = feedback(), feedback()['reveal']
    case = api_case(tmp_path, monkeypatch, records=[raw])
    client, catalog = case['client'], case['app'].state.catalog
    key = catalog.list_questions()['items'][0]['key']
    before = client.get('/api/studio/tasks/questions/' + key).json()
    response = inspect(client, {'kind': 'catalog', 'key': key})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['scope'] == 'human_inspection'
    assert value['correct_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert not {'answer_id', 'selected_answer', 'correct', 'committed'} & value.keys()
    assert value['feedback']['reveal']['curves'][0]['samples'] == [4, 8]
    assert all(secret not in response.text for secret in ('PRIVATE_RESULT', '/private/', 'environment'))
    assert client.get('/api/studio/tasks/questions/' + key).json() == before
    assert 'correct_letter' not in json.dumps(before)
    assert not case['app'].state.jobs.list() and not case['app'].state.tasks.list()


def test_observed_inspection_preserves_source_binding_and_existing_practice(evolution):
    client, observer, ref, _, calls = evolution
    public = client.get('/api/studio/kb-loop/questions/q_generated').json()
    events = observer.events()
    response = inspect(client, ref)
    assert response.status_code == 200, response.text
    assert response.json()['correct_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert calls == ['q_generated']
    assert observer.events() == events
    assert client.get('/api/studio/kb-loop/questions/q_generated').json() == public
    assert client.post('/api/studio/questions/review', json={'source': ref}).status_code == 422
    assert client.post('/api/studio/questions/review', json={'source': ref, 'answer_id': 'c_B'}).json()['correct'] is False
    assert client.get('/api/studio/tasks').json()['items'] == []


@pytest.mark.parametrize('change', ['source', 'sequence', 'hash', 'question'])
def test_invalid_observed_identity_never_reads_saved_results(evolution, change):
    client, _, ref, _, calls = evolution
    ref = deepcopy(ref)
    if change == 'source': ref['observation']['source_identity'] = '0' * 64
    elif change == 'sequence': ref['observation']['sequence'] = 999
    elif change == 'hash': ref['expected_question_hash'] = '0' * 64
    else: ref['question_id'] = 'q_unknown'
    assert inspect(client, ref).status_code == 409
    assert not calls


def test_inspection_rejects_client_answers_and_feedback(evolution):
    client, _, ref, _, calls = evolution
    assert inspect(client, ref, answer_id='c_A').status_code == 422
    assert inspect(client, ref, feedback={'correct_letter': 'A'}).status_code == 422
    assert not calls


def test_missing_answer_or_real_curve_axis_is_explicit(evolution):
    client, _, ref, result, _ = evolution
    result['feedback'] = {'reveal': {'curves': [{'letter': 'A', 'mean': [3, 2, 1]}]}}
    response = inspect(client, ref)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['correct_answer'] is None and value['feedback']['reveal']['curves'] == []
    assert '正确答案' in value['notice'] and '真实横轴' in value['notice']


def test_changed_results_question_or_conflicting_correct_answer_is_rejected(evolution):
    client, _, ref, result, _ = evolution
    result['feedback']['reveal']['correctLetter'] = 'B'
    assert inspect(client, ref).status_code == 409
    result['feedback'] = feedback()
    result['public']['prompt'] = 'A different source question'
    assert inspect(client, ref).status_code == 409


def test_frozen_evolution_catalog_key_reads_only_original_source_results(evolution):
    client, observer, ref, _, _ = evolution
    seed = client.post('/api/studio/tasks/evolution/selection', json={
        'observation': ref['observation'], 'question_id': 'q_generated'}).json()
    source = {'kind': 'catalog', 'key': seed['question_key']}
    before = client.get('/api/studio/tasks/questions/' + seed['question_key']).json()
    response = inspect(client, source)
    assert response.status_code == 200, response.text
    assert response.json()['correct_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert client.get('/api/studio/tasks/questions/' + seed['question_key']).json() == before
    from test_studio_loop_observer import configuration
    observer.config = configuration(artifact_root='/different/source')
    assert inspect(client, source).status_code == 409


def test_missing_catalog_result_is_404(evolution):
    client, _, _, _, _ = evolution
    assert inspect(client, {'kind': 'catalog', 'key': 'missing'}).status_code == 404


def test_inspection_does_not_unlock_pending_task_or_change_frozen_receipt(tmp_path, monkeypatch):
    from test_studio_rag_api import case_for_api
    from test_studio_tasks import task, preview, run
    from test_studio_task_run_review import detail
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case)
    answer = run(case, card, preview(case, card)).json()
    receipt = deepcopy(case['app'].state.tasks.history(card['id'])[0])
    before = detail(case, card, answer).json()
    response = inspect(case['client'], {'kind': 'catalog', 'key': receipt['config']['question_key']})
    assert response.status_code == 200, response.text
    assert response.json()['correct_answer'] is not None
    assert detail(case, card, answer).json() == before
    assert before['review']['status'] == 'not_committed' and not before['review']['feedback_released']
    assert case['app'].state.tasks.history(card['id'])[0] == receipt
    assert not case['calls']


def test_catalog_public_private_identity_change_rejects_mismatched_result(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    catalog = case['app'].state.catalog
    key = catalog.list_questions()['items'][0]['key']
    original = catalog.get_question
    def changed(key, *, include_private=False):
        result = original(key, include_private=include_private)
        if include_private:
            result['public']['prompt'] = 'A changed source question'
        return result
    monkeypatch.setattr(catalog, 'get_question', changed)
    assert inspect(case['client'], {'kind': 'catalog', 'key': key}).status_code == 409


def test_unreadable_saved_result_returns_503_without_an_answer(evolution):
    client, observer, ref, _, _ = evolution
    def unavailable(*args, **kwargs):
        raise OSError('Private source location must not be returned')
    observer.practice_reader = unavailable
    response = inspect(client, ref)
    assert response.status_code == 503
    assert 'Private source location' not in response.text
