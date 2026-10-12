"""Shortcut seeds keep the exact knowledge and question that were being read."""
from copy import deepcopy
import json

import pytest

from test_task_evolution_integration import evolution_case
from test_studio_tasks import task, preview


def observation(case):
    return case['client'].get('/api/studio/kb-loop').json()['observation']


def select(case, token, **fields):
    return case['client'].post('/api/studio/tasks/evolution/selection',
                               json={'observation': token, **fields})


def test_shortcut_carries_only_viewed_claim_and_creates_no_task_or_run(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    other = {**deepcopy(case['value']['claims'][0]), 'id': 'C2'}
    other['rules'][0]['predict'] = {'lower_better': 'width'}
    case['value']['claims'].append(other)
    case['observer'].poll_once()
    token = observation(case)
    response = select(case, token, question_id='q_generated', claim_ref={'id': 'C1', 'version': 2})
    assert response.status_code == 200, response.text
    seed = response.json()
    assert seed['mode'] == 'rules' and seed['question_key'] == case['question_key']
    assert seed['kb']['source_claim_id'] == 'C1' and seed['kb']['source_claim_version'] == 2
    assert seed['kb']['name'] == '知识演化 · C1'
    assert seed['kb_selection']['mode'] == 'manual'
    snapshot = case['app'].state.task_sources.resolve_kb(seed['kb_selection']['ref'])['snapshot']
    assert {r['source_refs'][0]['source_claim_id'] for r in snapshot['rules']} == {'C1'}
    assert case['client'].get('/api/studio/tasks').json()['items'] == []
    assert not case['jobs'].list()
    card = task(case, mode='rules', model_id=None, kb_selection=seed['kb_selection'])
    assert preview(case, card)['prediction']['answer_letter'] == 'A'
    assert 'SECRET_GT' not in json.dumps(seed) and '/private/' not in json.dumps(seed)


def test_old_question_context_freezes_old_kb_without_changing_current_head(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    token = observation(case)
    case['value']['claims'][0]['version'] = 3
    case['value']['claims'][0]['rules'][0]['predict'] = {'lower_better': 'width'}
    case['observer'].poll_once()
    bridge = case['app'].state.task_sources
    current = bridge.inventory()['items'][0]
    response = select(case, token, question_id='q_generated')
    assert response.status_code == 200, response.text
    seed = response.json()
    old = bridge.resolve_kb(seed['kb_selection']['ref'])
    assert old['version'] != current['version']
    assert old['snapshot']['rules'][0]['source_refs'][0]['source_revision'] == 2
    assert bridge.inventory()['items'][0] == current
    assert select(case, token, question_id='q_generated').json() == seed


def test_snapshot_claim_and_round_tokens_match_their_persisted_capture(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    before = observation(case)
    assert case['client'].get('/api/studio/kb-loop/claims/C1').json()['observation'] == before
    case['value']['round']['build']['ok'] += 1
    case['observer'].poll_once()
    after = case['client'].get('/api/studio/kb-loop/rounds/1').json()['observation']
    assert after['source_identity'] == before['source_identity'] and after['sequence'] > before['sequence']
    assert case['observer'].capture(**before)['round']['build']['ok'] == 1


@pytest.mark.parametrize('change', ['source', 'sequence', 'claim', 'question_hash'])
def test_changed_or_unknown_view_reference_is_rejected_without_fallback(tmp_path, monkeypatch, change):
    case = evolution_case(tmp_path, monkeypatch)
    token = observation(case)
    fields = {'question_id': 'q_generated', 'claim_ref': {'id': 'C1', 'version': 2}}
    if change == 'source': token['source_identity'] = '0' * 64
    elif change == 'sequence': token['sequence'] = 999999
    elif change == 'claim': fields['claim_ref']['version'] = 5
    else: fields['expected_question_hash'] = '0' * 64
    response = select(case, token, **fields)
    assert response.status_code == 409, response.text
    assert '请' in response.json()['detail']
    assert case['client'].get('/api/studio/tasks').json()['items'] == []
    assert not case['jobs'].list()


def test_cached_offline_question_handoff_keeps_exact_source_hash(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    token = observation(case)
    public = case['client'].get('/api/studio/kb-loop/questions/q_generated').json()
    def fail(*args):
        raise RuntimeError('private offline endpoint')
    case['observer'].reader = fail
    case['observer'].question_reader = fail
    assert not case['observer'].poll_once()
    result = select(case, token, question_id='q_generated',
                    expected_question_hash=public['observation']['content_hash'])
    assert result.status_code == 200, result.text
    assert result.json()['question_key'] == case['question_key']


def test_skipped_claim_remains_a_selected_empty_kb_with_clear_reason(tmp_path, monkeypatch):
    case = evolution_case(tmp_path, monkeypatch)
    case['value']['claims'][0]['status'] = 'flagged'
    case['observer'].poll_once()
    seed = select(case, observation(case), claim_ref={'id': 'C1', 'version': 2})
    assert seed.status_code == 200, seed.text
    seed = seed.json()
    assert seed['question_key'] is None
    assert seed['kb']['skipped_claims'][0]['reason'] == 'source_flagged'
    card = task(case, mode='rules', model_id=None, kb_selection=seed['kb_selection'])
    result = preview(case, card)
    assert result['prediction']['status'] == 'uncovered'
    assert not result['prediction']['explanation']['edges']


@pytest.mark.parametrize('fields', [
    {}, {'expected_question_hash': 'a' * 64},
    {'claim_ref': {'id': 'C1', 'version': True}},
    {'question_id': 'q_generated', 'inline_rules': []},
])
def test_shortcut_rejects_incomplete_or_inline_inputs(tmp_path, monkeypatch, fields):
    case = evolution_case(tmp_path, monkeypatch)
    assert select(case, observation(case), **fields).status_code == 422


@pytest.mark.parametrize('token', [
    {'source_identity': None, 'sequence': None},
    {'source_identity': '0' * 64, 'sequence': True},
    {'source_identity': '0' * 64, 'sequence': 0},
    {'source_identity': 'unsafe/path', 'sequence': 1},
])
def test_invalid_observation_token_never_defaults_to_latest(tmp_path, monkeypatch, token):
    case = evolution_case(tmp_path, monkeypatch)
    assert select(case, token, question_id='q_generated').status_code == 422
