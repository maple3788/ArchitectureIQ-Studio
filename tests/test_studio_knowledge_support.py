"""Library support is exact-version, distinct-question evidence, never coverage."""
from copy import deepcopy
import pytest

from architecture_iq.studio.loop_source import collect
from architecture_iq.studio.knowledge_support import score_question_outcomes
from test_studio_loop_source import source, rows
from test_studio_evolution_task_sources import observed_capture
from test_studio_loop_observer import configuration
from test_studio_loop_observer_api import client_for
from architecture_iq.studio.loop_observer import LoopObserver


def test_collector_counts_unique_questions_before_truncation_and_keeps_contradictions(source):
    evidence = [{'claim_id': 'C1', 'version': 2, 'question_id': f'q_{index}', 'round': 2,
                 'outcome': 'support', 'pairs': [['a', 'b', True], ['a', 'c', True]]}
                for index in range(120)]
    rows(source, 'ledger.jsonl', evidence + evidence + [
        {**evidence[0], 'outcome': 'refute', 'round': 3}, evidence[0],
        {**evidence[1], 'outcome': 'inconclusive'},
        {**evidence[2], 'question_id': 'q_old', 'version': 1, 'outcome': 'support'},
        {**evidence[2], 'question_id': 'q_registration', 'round': 1, 'outcome': 'support'},
    ])
    detail = collect(source)['claim_details']['C1']
    assert detail['evidence_truncated'] is True
    assert detail['support_summary'] == {
        'claim_id': 'C1', 'version': 2, 'unit': 'distinct_questions', 'complete': True,
        'support_questions': 118, 'refute_questions': 1, 'unknown_questions': 1,
    }


def test_sealed_score_uses_exact_rule_assertions_not_pair_counts_or_overall_answer():
    rule = {'rule_id': 'R1:0', 'revision': 'r1', 'metadata': {'claim_id': 'R1'}}
    assertion = {'rule_ref': {'rule_id': 'R1:0', 'revision': 'r1'}, 'verdict': 'correct'}
    row = {'question_ref': {'key': 'q1', 'hash': 'hash1'}, 'scorable': True,
           'correct': False, 'assertions': [assertion, assertion]}
    score = {'kb_version': 'v1', 'per_rule': {'R1:0': {'correct': 200}},
             'per_question': {'q1': row, 'alias': deepcopy(row),
                'q2': {**row, 'question_ref': {'key': 'q2', 'hash': 'hash2'},
                       'assertions': [assertion, {**assertion, 'verdict': 'wrong'}]},
                'q3': {**row, 'question_ref': {'key': 'q3', 'hash': 'hash3'},
                       'assertions': [{**assertion, 'rule_ref': {'rule_id': 'R1:0', 'revision': 'old'}}]}}}
    result = score_question_outcomes({'version': 'v1', 'rules': [rule]}, [score])
    assert result['R1'] == {'hash1': {'support'}, 'hash2': {'support', 'refute'}}
    assert score_question_outcomes({'version': 'v2', 'rules': [rule]}, [score]) == {}


def test_unscorable_predicted_rules_are_unknown_even_without_assertions():
    rule = {'rule_id': 'R1:0', 'revision': 'r1', 'metadata': {'claim_id': 'R1'}}
    edge = {'winner': 'a', 'loser': 'b', 'rules': [{'rule_id': 'R1:0', 'revision': 'r1'},
                                               {'rule_id': 'R2:0', 'revision': 'old'}]}
    row = {'question_ref': {'key': 'q_missing', 'hash': 'hash_missing'}, 'scorable': False,
           'assertions': [], 'prediction': {'edges': [edge, deepcopy(edge)]}}
    score = {'kb_version': 'v1', 'per_question': {'q_missing': row, 'duplicate': deepcopy(row)}}
    snapshot = {'version': 'v1', 'rules': [rule, {'rule_id': 'R2:0', 'revision': 'new', 'metadata': {'claim_id': 'R2'}}]}
    assert score_question_outcomes(snapshot, [score]) == {'R1': {'hash_missing': {'unknown'}}}


def observation_with_evidence():
    capture = observed_capture()
    capture['claim_details']['C1'] = {
        'claim': deepcopy(capture['claims'][0]), 'history': [], 'evidence': [],
        'evidence_total': 23, 'evidence_truncated': True,
        'support_summary': {'claim_id': 'C1', 'version': 2, 'unit': 'distinct_questions',
                            'complete': True, 'support_questions': 21, 'refute_questions': 2,
                            'unknown_questions': 0},
    }
    return capture


def test_kb_library_adds_exact_evolution_versions_without_mutating_task_inventory(tmp_path):
    capture = observation_with_evidence()
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: capture,
                            question_reader=lambda *_: (_ for _ in ()).throw(AssertionError('No remote questions')))
    assert observer.poll_once()
    client = client_for(tmp_path, observer)
    first = client.get('/api/studio/kb').json()
    evolved = next(item for item in first['items'] if item.get('source_kind') == 'knowledge_evolution')
    assert evolved['evidence_summary']['kb_ref'] == {key: evolved[key] for key in ('id', 'version')}
    assert evolved['evidence_summary']['claims']['C1']['support_questions'] == 21
    assert evolved['evidence_summary']['claims']['C1']['refute_questions'] == 2
    assert all(item['evidence_summary']['claims']['R1']['support_questions'] is None
               for item in first['items'] if item['id'].startswith('builtin:'))
    capture['claims'][0].update(version=3, text='New version')
    capture['claim_details']['C1']['claim'] = deepcopy(capture['claims'][0])
    capture['claim_details']['C1']['support_summary'].update(version=3, support_questions=2)
    assert observer.poll_once()
    items = [item for item in client.get('/api/studio/kb').json()['items'] if item.get('source_kind') == 'knowledge_evolution']
    assert len(items) == 2 and len({item['library']['id'] for item in items}) == 1
    old = next(item for item in items if item['version'] == evolved['version'])
    assert old['snapshot'] == evolved['snapshot']
    assert old['evidence_summary']['claims']['C1']['support_questions'] == 21
    assert len(client.app.state.task_sources.inventory()['items']) == 1
    assert all('evidence_summary' not in item for item in client.app.state.task_sources.inventory()['items'])


def test_legacy_truncated_or_wrong_revision_summary_remains_unknown(tmp_path):
    capture = observation_with_evidence()
    capture['claim_details']['C1']['support_summary']['version'] = 1
    capture['claims'][0]['evidence'] = {'support': 500, 'refute': 0, 'applicable': 500}
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: capture)
    observer.poll_once()
    response = client_for(tmp_path, observer).get('/api/studio/kb')
    item = next(item for item in response.json()['items'] if item.get('source_kind') == 'knowledge_evolution')
    result = item['evidence_summary']['claims']['C1']
    assert result['support_questions'] is None and result['complete'] is False
    assert result['notice']


@pytest.mark.parametrize('status', ['flagged', 'retired'])
def test_human_library_preserves_excluded_claims_without_reenabling_task_rules(tmp_path, status):
    capture = observation_with_evidence()
    capture['claims'][0]['status'] = status
    capture['claim_details']['C1']['claim'] = deepcopy(capture['claims'][0])
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: capture)
    observer.poll_once()
    client = client_for(tmp_path, observer)
    item = next(item for item in client.get('/api/studio/kb').json()['items'] if item.get('source_kind') == 'knowledge_evolution')
    claim = item['reading_claims'][0]
    assert (claim['id'], claim['version'], claim['status'], claim['text']) == ('C1', 2, status, 'Greater width wins in scope')
    assert item['evidence_summary']['claims']['C1']['support_questions'] == 21
    assert item['evidence_summary']['claims']['C1']['refute_questions'] == 2
    frozen = client.app.state.task_sources.resolve_kb({key: item[key] for key in ('id', 'version')})
    assert item['snapshot'] == frozen['snapshot'] and frozen['snapshot']['rules'] == []
    assert 'reading_claims' not in frozen and 'evidence_summary' not in frozen
