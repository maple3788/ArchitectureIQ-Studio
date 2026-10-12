"""Human answer disclosure is isolated from all public solver inputs."""
from copy import deepcopy
import json
import sqlite3

import pytest

from architecture_iq.studio.loop_observer import LoopObserver
from test_studio_loop_observer import configuration
from test_studio_loop_observer_api import client_for
from test_studio_evolution_task_sources import observed_capture, observed_question
from test_studio_knowledge_questions import api_case
from rule_refinement_fixtures import raw_case


def post(client, source, answer='c_B', **extra):
    return client.post('/api/studio/questions/review', json={'source': source, 'answer_id': answer, **extra})


def feedback():
    return {'correct_letter': 'A', 'candidate_metrics': {
        'c_A': {'selection_metric': 'test_mse', 'mean_test_mse': 1.5, 'std_test_mse': .5, 'n_seeds': 2,
                'environment': {'secret': '/private/server'}}},
        'reveal': {'correctLetter': 'A', 'curves': [
            {'candidateId': 'c_A', 'letter': 'A', 'metric': 'test_mse', 'samples': [4, 8],
             'mean': [3, 1.5], 'std': [1, .5], 'secret': 'PRIVATE_RESULT'}],
            'files': {'secret': 'PRIVATE_RESULT'}}}


def test_catalog_review_requires_valid_answer_and_returns_only_saved_results(tmp_path, monkeypatch):
    raw = raw_case()
    raw['feedback'] = feedback()
    raw['reveal'] = feedback()['reveal']
    case = api_case(tmp_path, monkeypatch, records=[raw])
    client, catalog = case['client'], case['app'].state.catalog
    key = catalog.list_questions()['items'][0]['key']
    before = client.get('/api/studio/tasks/questions/' + key).json()
    response = post(client, {'kind': 'catalog', 'key': key})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['selected_answer'] == {'id': 'c_B', 'letter': 'B'}
    assert value['correct_answer'] == {'id': 'c_A', 'letter': 'A'} and value['correct'] is False
    assert value['feedback']['reveal']['curves'][0]['samples'] == [4, 8]
    assert value['feedback']['reveal']['curves'][0]['mean'] == [3, 1.5]
    assert all(secret not in response.text for secret in ('PRIVATE_RESULT', '/private/', 'environment'))
    assert client.get('/api/studio/tasks/questions/' + key).json() == before
    assert 'correct_letter' not in json.dumps(before)
    assert not case['app'].state.jobs.list() and not case['app'].state.tasks.list()
    assert post(client, {'kind': 'catalog', 'key': key}, answer='c_A').json()['correct'] is True


@pytest.mark.parametrize('answer', [None, '', 'A', 'not-a-choice', ['c_A']])
def test_invalid_answer_cannot_read_catalog_feedback(tmp_path, monkeypatch, answer):
    case = api_case(tmp_path, monkeypatch)
    catalog = case['app'].state.catalog
    key = catalog.list_questions()['items'][0]['key']
    original = catalog.get_question
    def guarded(key, *, include_private=False):
        assert not include_private, 'Invalid answer attempted private feedback access'
        return original(key, include_private=include_private)
    monkeypatch.setattr(catalog, 'get_question', guarded)
    assert post(case['client'], {'kind': 'catalog', 'key': key}, answer).status_code == 422


def test_missing_stored_answer_and_curve_axis_are_not_invented(tmp_path, monkeypatch):
    raw = raw_case()
    raw['reveal'] = {'curves': [{'letter': 'A', 'mean': [3, 2, 1]}]}
    case = api_case(tmp_path, monkeypatch, records=[raw])
    key = case['app'].state.catalog.list_questions()['items'][0]['key']
    response = post(case['client'], {'kind': 'catalog', 'key': key})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['correct'] is None and value['correct_answer'] is None
    assert value['feedback']['reveal']['curves'] == [] and value['notice']


@pytest.fixture
def evolution(tmp_path):
    source = observed_capture()
    result = observed_question()
    result['feedback'] = feedback()
    calls = []
    def review(_config, qid):
        calls.append(qid)
        return deepcopy(result)
    observer = LoopObserver(tmp_path, config=configuration(artifact_root='/private/artifacts'),
        reader=lambda _: source, question_reader=lambda *_: observed_question(), practice_reader=review)
    observer.poll_once()
    client = client_for(tmp_path, observer)
    public = client.get('/api/studio/kb-loop/questions/q_generated').json()
    ref = {'kind': 'knowledge_evolution', 'question_id': 'q_generated',
           'observation': observer.snapshot()['observation'],
           'expected_question_hash': public['observation']['content_hash']}
    return client, observer, ref, result, calls


def test_observed_human_result_is_separate_cached_and_bound_to_seen_public_artifact(evolution):
    client, observer, ref, result, calls = evolution
    public = client.get('/api/studio/kb-loop/questions/q_generated').json()
    events = observer.events()
    response = post(client, ref)
    assert response.status_code == 200, response.text
    assert response.json()['correct_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert calls == ['q_generated']
    observer.practice_reader = lambda *_: pytest.fail('Offline review should use stored result')
    assert post(client, ref).json() == response.json()
    assert client.get('/api/studio/kb-loop/questions/q_generated').json() == public
    assert observer.events() == events
    seed = client.post('/api/studio/tasks/evolution/selection', json={
        'observation': ref['observation'], 'question_id': 'q_generated'}).json()
    task_question = client.get('/api/studio/tasks/questions/' + seed['question_key']).json()
    assert 'correct_letter' not in json.dumps(task_question) and 'feedback' not in task_question
    assert client.get('/api/studio/tasks').json()['items'] == []


@pytest.mark.parametrize('bucket', ['evidence', 'counterexamples'])
def test_archived_round_question_review_uses_exact_capture_membership(evolution, bucket):
    client, observer, ref, _, calls = evolution
    source = observed_capture()
    source['claim_details'] = {}
    for detail in source['round_details'].values():
        detail['generation'] = {'items': []}
    saved = {'evidence': [], 'counterexamples': {'items': []}}
    rows = saved['evidence'] if bucket == 'evidence' else saved['counterexamples']['items']
    rows.append({'question_id': 'q_generated', 'round': 1})
    source['round_details']['1']['claim_details'] = {'C1': {'1': saved}}
    observer.reader = lambda _: source
    assert observer.poll_once()
    ref = {**ref, 'observation': observer.snapshot()['observation']}

    assert post(client, ref, answer='no-such-option').status_code == 422
    assert post(client, {**ref, 'expected_question_hash': '0' * 64}).status_code == 409
    assert post(client, {**ref, 'question_id': 'q_unknown'}).status_code == 409
    assert not calls

    # Later captures cannot add or remove membership from the viewed record.
    source['round_details']['1']['claim_details'] = {}
    assert observer.poll_once()
    latest = {**ref, 'observation': observer.snapshot()['observation']}
    assert post(client, latest).status_code == 409
    assert not calls
    response = post(client, ref)
    assert response.status_code == 200, response.text
    assert response.json()['correct_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert calls == ['q_generated']


@pytest.mark.parametrize('change,status', [('answer',422),('source',409),('sequence',409),('hash',409),('question',409)])
def test_observed_invalid_references_are_rejected_before_private_reader(evolution, change, status):
    client, _, ref, _, calls = evolution
    ref = deepcopy(ref)
    answer = 'c_B'
    if change == 'answer': answer = 'no-such-option'
    elif change == 'source': ref['observation']['source_identity'] = '0' * 64
    elif change == 'sequence': ref['observation']['sequence'] = 999
    elif change == 'hash': ref['expected_question_hash'] = '0' * 64
    else: ref['question_id'] = 'q_unknown'
    assert post(client, ref, answer).status_code == status
    assert not calls


def test_source_question_rewrite_does_not_rebind_old_human_results(evolution):
    client, _, ref, result, _ = evolution
    result['public']['prompt'] = 'Changed question'
    assert post(client, ref).status_code == 409


def test_curve_mismatched_candidate_mapping_is_not_relabelled(evolution):
    client, _, ref, result, _ = evolution
    result['feedback']['reveal']['curves'][0]['letter'] = 'B'
    response = post(client, ref)
    assert response.status_code == 200, response.text
    assert response.json()['feedback']['reveal']['curves'] == []
    assert response.json()['notice']


def test_partial_saved_curves_are_explicit_and_cache_corruption_is_rejected(evolution):
    client, observer, ref, _, _ = evolution
    response = post(client, ref)
    assert response.status_code == 200
    assert '部分候选' in response.json()['notice']
    with sqlite3.connect(observer.database) as conn:
        conn.execute("UPDATE human_question_results SET content_hash='tampered'")
    assert post(client, ref).status_code == 409


def test_multiwinner_answer_record_is_not_forced_to_a_single_correct_choice(evolution):
    client, _, ref, result, _ = evolution
    result['feedback']['reveal']['correctLetter'] = 'B'
    assert post(client, ref).status_code == 409
