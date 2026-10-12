"""Historical Task reading never re-solves or reveals uncommitted answers."""
from copy import deepcopy

import pytest

from test_studio_tasks import rules_case, task, preview, run
from test_studio_rag_api import case_for_api
from test_task_evolution_integration import evolution_case
from rule_refinement_fixtures import rule_entry, raw_case
from test_studio_catalog import bakefile
from test_studio_human_practice import feedback
from test_studio_evolution_task_sources import observed_question


def detail(case, card, answer):
    return case['client'].get(f"/api/studio/tasks/{card['id']}/runs/{answer['id']}")


def committed_rule(case):
    card = task(case, mode='rules', model_id=None)
    answer = run(case, card, preview(case, card)).json()
    return card, answer


def test_rule_history_reads_frozen_question_and_kb_after_current_inputs_change(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    card, answer = committed_rule(case)
    receipt = deepcopy(case['app'].state.tasks.history(card['id'])[0])
    case['inventory']['items'] = []
    case['catalog'].import_source(bakefile(tmp_path / 'new.json', [raw_case(widths=(8, 16, 32), correct='C')]))
    case['client'].put('/api/studio/tasks/' + card['id'], json={'expected_revision': 1, 'name': 'Changed'})
    response = detail(case, card, answer)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['question_record']['detail']['choices'][0]['files']['candidate_spec.json']['model']['width'] == 32
    assert value['result']['prediction'] == answer['result']['prediction']
    assert value['task_revision'] == 1
    assert value['review']['status'] == 'revealed' and value['review']['feedback_released'] is True
    assert value['review']['selected_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert value['review']['correct_answer'] == {'id': 'c_A', 'letter': 'A'}
    assert value['review']['correct'] is True
    assert case['app'].state.tasks.history(card['id'])[0] == receipt
    assert not case['jobs'].list()
    for private in ('/private/', 'base_url', 'source_snapshot', 'seed_results'):
        assert private not in response.text


@pytest.mark.parametrize('entries,status', [
    ([[rule_entry(), rule_entry(lower=True)]], 'conflict'),
    ([[rule_entry((999,))]], 'uncovered'),
])
def test_rule_abstentions_never_read_private_feedback(tmp_path, monkeypatch, entries, status):
    case = rules_case(tmp_path, monkeypatch, entries)
    card, answer = committed_rule(case)
    def forbidden(*args, **kwargs):
        pytest.fail('History of an abstention must not load question or GT')
    monkeypatch.setattr(case['catalog'], 'get_question', forbidden)
    value = detail(case, card, answer).json()
    assert value['result']['prediction']['status'] == status
    assert value['review']['status'] == 'not_committed'
    assert value['review']['feedback_released'] is False and 'feedback' not in value['review']


def test_pending_model_answer_never_reads_feedback(tmp_path, monkeypatch):
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case)
    answer = run(case, card, preview(case, card)).json()
    monkeypatch.setattr(case['catalog'], 'get_question', lambda *a, **kw: pytest.fail('Pending GT read'))
    value = detail(case, card, answer).json()
    assert value['question_record']['public'] == case['public']
    assert value['review']['status'] == 'not_committed' and not value['review']['feedback_released']


def test_completed_model_answer_uses_persisted_commit_and_exact_mapping(tmp_path, monkeypatch):
    from architecture_iq.studio.execution import worker
    from rag_fixtures import rag_client
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case)
    answer = run(case, card, preview(case, card)).json()
    case['config'] = case['jobs'].definition(answer['job_id'])['config']
    monkeypatch.setattr('architecture_iq.studio.execution.create_client', rag_client(case, ranking=['A', 'C', 'B']))
    worker(case['state_root'], answer['job_id'])
    response = detail(case, card, answer)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['review']['status'] == 'revealed'
    assert value['review']['selected_answer'] == next({k: c[k] for k in ('id', 'letter')}
        for c in case['public']['choices'] if c['letter'] == 'A')
    assert value['review']['correct'] is False
    assert value['result']['provided_sources'] == value['result']['used_sources']
    assert len(case['calls']) == 1
    for private in ('base_url', 'models.example.test', 'runtime_lock_path', 'seed_results'):
        assert private not in response.text
    # A terminal-looking state/result without its committed call cannot reveal GT.
    for path in (case['jobs'].directory(answer['job_id']) / 'records').glob('*.json'):
        path.unlink()
    monkeypatch.setattr(case['catalog'], 'get_question', lambda *a, **kw: pytest.fail('Uncommitted GT read'))
    assert detail(case, card, answer).json()['review']['status'] == 'not_committed'


def test_question_identity_change_is_explicit_without_losing_frozen_reading(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    card, answer = committed_rule(case)
    original = case['catalog'].get_question
    def changed(key, *, include_private=False):
        assert not include_private
        value = original(key)
        value['public']['prompt'] = 'NEW QUESTION'
        return value
    monkeypatch.setattr(case['catalog'], 'get_question', changed)
    value = detail(case, card, answer).json()
    assert value['review']['status'] == 'identity_conflict' and not value['review']['feedback_released']
    assert value['question_record']['public']['prompt'] != 'NEW QUESTION'
    assert value['review']['selected_answer']['letter'] == 'A'


def test_missing_source_keeps_history_and_reports_feedback_unavailable(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    card, answer = committed_rule(case)
    def missing(*args, **kwargs):
        raise KeyError('private path is not exposed')
    monkeypatch.setattr(case['catalog'], 'get_question', missing)
    response = detail(case, card, answer)
    assert response.status_code == 200
    assert response.json()['review']['status'] == 'unavailable'
    assert 'private path' not in response.text


def test_legacy_rule_history_reconstructs_only_frozen_case(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    card, _ = committed_rule(case)
    old = deepcopy(case['app'].state.tasks.history(card['id'])[0])
    old['config'].pop('question_record')
    for field in ('id', 'created_at', 'request_hash', 'receipt_hash'):
        old.pop(field)
    answer = case['app'].state.tasks.record(card['id'], 'legacy', {}, old)
    value = detail(case, card, answer).json()
    assert value['question_record']['detail']['choices'][0]['files']['candidate_spec.json']['model']['width'] == 32
    assert value['question_notice'] and value['review']['status'] == 'revealed'


def test_legacy_model_history_uses_frozen_public_without_claiming_current_detail(tmp_path, monkeypatch):
    from architecture_iq.studio.execution import worker
    from rag_fixtures import rag_client
    case = case_for_api(tmp_path, monkeypatch, True)
    card = task(case)
    run(case, card, preview(case, card))
    old = deepcopy(case['app'].state.tasks.history(card['id'])[0])
    old['config'].pop('question_record')
    job = case['jobs'].create('rag', old['config'])
    old['job_id'] = job['id']
    for field in ('id', 'created_at', 'request_hash', 'receipt_hash'):
        old.pop(field)
    answer = case['app'].state.tasks.record(card['id'], 'legacy-model', {}, old)
    case['config'] = old['config']
    monkeypatch.setattr('architecture_iq.studio.execution.create_client', rag_client(case))
    worker(case['state_root'], job['id'])
    value = detail(case, card, answer).json()
    assert value['question_record']['public'] == old['config']['question']
    assert 'detail' not in value['question_record'] and value['question_notice']
    assert value['review']['status'] == 'revealed'
    assert len(case['calls']) == 1


def test_missing_correct_answer_is_never_invented(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    raw = raw_case(qid='no_saved_answer')
    raw.pop('reveal')
    case['catalog'].import_source(bakefile(tmp_path / 'no-answer.json', [raw]))
    case['question_key'] = next(row['key'] for row in case['catalog'].list_questions()['items']
                                if row['id'] == 'no_saved_answer')
    card, answer = committed_rule(case)
    review = detail(case, card, answer).json()['review']
    assert review['status'] == 'revealed' and review['feedback_released'] is True
    assert review['correct_answer'] is None and review['correct'] is None
    assert review['notice'] and 'correct_letter' not in review['feedback']


def test_tampered_receipt_is_rejected_before_any_feedback_read(tmp_path, monkeypatch):
    import json
    case = rules_case(tmp_path, monkeypatch)
    card, answer = committed_rule(case)
    path = next((case['app'].state.tasks.directory(card['id']) / 'runs').glob('*.json'))
    value = json.loads(path.read_text())
    value['config']['question_record']['public']['prompt'] = 'Unsealed edit'
    path.write_text(json.dumps(value))
    monkeypatch.setattr(case['catalog'], 'get_question', lambda *a, **kw: pytest.fail('Corrupt receipt read GT'))
    assert detail(case, card, answer).status_code == 422


def test_evolution_review_requires_exact_source_and_public_hash(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    calls = []
    def stored(_config, qid):
        calls.append(qid)
        return {**observed_question(qid), 'feedback': feedback()}
    case['observer'].practice_reader = stored
    card, answer = committed_rule(case)
    value = detail(case, card, answer).json()
    assert value['review']['status'] == 'revealed' and value['review']['correct'] is True
    assert calls == ['q_generated']
    from test_studio_loop_observer import configuration
    case['observer'].config = configuration(artifact_root='/different/source')
    changed = detail(case, card, answer).json()
    assert changed['review']['status'] == 'identity_conflict'
    assert calls == ['q_generated']


def test_answer_identity_cannot_be_read_from_another_task(tmp_path, monkeypatch):
    case = rules_case(tmp_path, monkeypatch)
    card, answer = committed_rule(case)
    other = task(case, mode='rules')
    assert detail(case, other, answer).status_code == 404
    assert detail(case, card, {'id': 'answer_' + '0' * 16}).status_code == 404
