"""Frozen Task inputs from read-only knowledge evolution observations."""
from copy import deepcopy
import json
import sqlite3

import pytest

from architecture_iq.kb.store import canonical_hash
from architecture_iq.studio.loop_observer import LoopObserver
from architecture_iq.studio.evolution_task_sources import EvolutionTaskSources
from architecture_iq.studio.rule_refinement.artifacts import validate_snapshot
from architecture_iq.studio.rule_refinement.pool import _case
from architecture_iq.studio.rule_refinement.prediction import predict_question
from rule_refinement_fixtures import raw_case, rule_entry
from test_studio_loop_observer import capture, configuration


def observed_question(identifier='q_generated'):
    value = raw_case(qid=identifier)
    return {'metadata': {'id': identifier, 'family': value['family'], 'dataset_id': value['datasetId']},
            'public': {'id': identifier, 'family': value['family'], 'dataset_id': value['datasetId'],
                       'prompt': 'Compare the candidate architectures.',
                       'choices': [{'id': c['candidateId'], 'letter': c['letter'], 'view': {}}
                                   for c in value['detail']['choices']]},
            'detail': value['detail'], 'feedback': {'correct_letter': 'SECRET_GT'}}


def observed_capture():
    value = capture()
    value['claims'] = [{
        'id': 'C1', 'version': 2, 'text': 'Greater width wins in scope',
        'rules': [rule_entry()['rule']], 'status': 'candidate', 'registered_round': 1,
        'parent': {'id': 'C0', 'version': 1}, 'needs_revision': False,
        'consistency': {'consistent': True},
    }]
    value['round_details']['1']['generation'] = {'items': [
        {'item_id': 'one', 'question_id': 'q_generated', 'status': 'ok',
         'family': 'xor_classification', 'question_type': 'architecture_only', 'purpose': 'target'},
        {'item_id': 'repeat', 'question_id': 'q_generated', 'status': 'ok', 'family': 'xor_classification'},
        {'item_id': 'pending', 'status': 'pending'},
        {'item_id': 'failed', 'status': 'failed', 'question_id': 'q_failed'},
    ]}
    return value


@pytest.fixture
def bridge(tmp_path):
    value = observed_capture()
    calls = []
    def question_reader(_config, identifier):
        calls.append(identifier)
        return observed_question(identifier)
    observer = LoopObserver(tmp_path, config=configuration(artifact_root='/private/artifacts'),
                            reader=lambda _: value, question_reader=question_reader)
    assert observer.poll_once()
    return EvolutionTaskSources(tmp_path, observer), observer, value, calls


def test_listing_only_completed_deduped_questions_without_remote_artifact_reads(bridge):
    source, observer, _, calls = bridge
    result = source.list_questions()
    assert result['total'] == 1 and result['source']['connected'] is True
    row = result['items'][0]
    assert row['id'] == 'q_generated' and row['round_index'] == 1
    assert row['source_kind'] == 'knowledge_evolution' and row['cached'] is False
    assert row['type'] == row['question_type'] == 'architecture_only'
    assert calls == []
    assert source.list_questions(search='no match')['total'] == 0
    assert source.list_questions(offset=1)['items'] == []


def test_freeze_public_question_then_read_offline_and_after_source_switch(bridge, tmp_path):
    source, observer, _, calls = bridge
    first = source.freeze_question('q_generated')
    assert first['metadata']['key'].startswith('evolution_')
    assert first['metadata']['rag_ready'] is True
    assert first['metadata']['evaluation_ready'] is False
    assert first['provenance']['round_index'] == 1
    assert predict_question(_case(first), source.inventory()['items'][0]['snapshot'])['answer_id'] == 'c_A'
    assert source.freeze_question('q_generated') == first and calls == ['q_generated']
    assert source.list_questions()['items'][0]['cached'] is True
    assert 'feedback' not in first and 'correct_letter' not in json.dumps(first)
    assert '/private/' not in json.dumps(first)
    switched = EvolutionTaskSources(tmp_path, LoopObserver(tmp_path))
    assert switched.get_question(first['metadata']['key']) == first
    assert switched.inventory()['items'] == []
    other = LoopObserver(tmp_path, config=configuration(root='/different', artifact_root='/private/artifacts'),
                         reader=lambda _: observed_capture(), question_reader=lambda *_: observed_question())
    other.poll_once()
    second = EvolutionTaskSources(tmp_path, other).freeze_question('q_generated')
    assert second['metadata']['key'] != first['metadata']['key']
    assert switched.get_question(first['metadata']['key']) == first


@pytest.mark.parametrize('identifier', ['q_failed', 'q_missing', '../q_generated'])
def test_freeze_accepts_only_saved_successful_generation(bridge, identifier):
    source, _, _, calls = bridge
    with pytest.raises(KeyError):
        source.freeze_question(identifier)
    assert not calls


def test_frozen_kb_persists_and_retains_source_status_without_promotion(bridge, tmp_path):
    source, observer, value, _ = bridge
    value['claims'].extend([
        {**deepcopy(value['claims'][0]), 'id': 'C2', 'status': 'verified'},
        {**deepcopy(value['claims'][0]), 'id': 'C3', 'status': 'flagged'},
        {**deepcopy(value['claims'][0]), 'id': 'C4', 'status': 'retired'},
        {**deepcopy(value['claims'][0]), 'id': 'C5', 'rules': [{'predict': {'mystery': 'width'}}]},
    ])
    observer.poll_once()
    item = source.inventory()['items'][0]
    assert item['kind'] == 'research_rules' and item['source_kind'] == 'knowledge_evolution'
    assert item['name'] == '知识演化 · 第 1 轮'
    assert item['source_status_counts'] == {'candidate': 2, 'verified': 1, 'flagged': 1, 'retired': 1}
    assert len(item['snapshot']['rules']) == 2
    assert {r['source_refs'][0]['source_status'] for r in item['snapshot']['rules']} == {'candidate', 'verified'}
    assert {r['metadata']['validity_status'] for r in item['snapshot']['rules']} == {'proposed'}
    assert all(r['metadata']['validation_origin'] == 'source_reported' for r in item['snapshot']['rules'])
    assert {x['claim_id'] for x in item['skipped_claims']} == {'C3', 'C4', 'C5'}
    assert item['snapshot']['source_document']['source_claims'][0]['parent'] == {'id': 'C0', 'version': 1}
    validate_snapshot(item['snapshot'])
    assert '/private/' not in json.dumps(item)
    reference = {k: item[k] for k in ('id', 'version')}
    value['round']['build']['ok'] += 1
    observer.poll_once()
    assert source.inventory()['items'][0]['version'] == item['version']
    value['claims'][0]['status'] = 'flagged'
    observer.poll_once()
    current = source.inventory()['items'][0]
    assert current['version'] != item['version']
    assert source.resolve_kb(reference) == item
    assert len(source.inventory(reference=reference)['items']) == 2
    reopened = EvolutionTaskSources(tmp_path, LoopObserver(tmp_path))
    assert reopened.resolve_kb(reference) == item


def test_disconnected_source_keeps_last_real_snapshot(bridge):
    source, observer, _, _ = bridge
    item = source.inventory()['items'][0]
    observer.reader = lambda *_: (_ for _ in ()).throw(RuntimeError('PRIVATE_ERROR'))
    assert not observer.poll_once()
    assert source.inventory()['items'][0] == item
    listing = source.list_questions()
    assert listing['source']['connected'] is False and listing['total'] == 1
    assert 'PRIVATE_ERROR' not in json.dumps(listing)


def test_invalid_cache_keys_and_tampered_frozen_question_are_rejected(bridge):
    source, _, _, _ = bridge
    first = source.freeze_question('q_generated')
    with pytest.raises(KeyError):
        source.get_question('../../private')
    with sqlite3.connect(source.database) as conn:
        conn.execute("UPDATE questions SET content_hash='tampered' WHERE key=?", (first['metadata']['key'],))
    with pytest.raises(ValueError, match='完整性'):
        source.get_question(first['metadata']['key'])


def test_kb_rejects_tampered_source_capture(bridge):
    source, observer, _, _ = bridge
    with sqlite3.connect(observer.database) as conn:
        conn.execute("UPDATE captures SET digest='tampered'")
    with pytest.raises(ValueError, match='integrity'):
        source.inventory()


def test_public_choice_views_are_bound_to_original_candidate_ids(bridge):
    source, _, _, _ = bridge
    record = source.freeze_question('q_generated')
    assert {choice['id']: choice['view']['width'] for choice in record['public']['choices']} == {
        'c_A': 32, 'c_B': 16, 'c_C': 8}


def test_invalid_sibling_clause_does_not_renumber_original_rules(bridge):
    source, observer, value, _ = bridge
    value['claims'][0]['rules'] = [{'predict': {'mystery': 'width'}}, rule_entry()['rule']]
    observer.poll_once()
    rule = source.inventory()['items'][0]['snapshot']['rules'][0]
    assert rule['source_refs'][0]['source_clause_index'] == 2
    assert rule['metadata']['clause_index'] == 2


def test_nullable_consistency_from_actual_source_is_accepted(bridge):
    source, observer, value, _ = bridge
    value['claims'][0]['consistency'] = None
    observer.poll_once()
    assert len(source.inventory()['items'][0]['snapshot']['rules']) == 1


def test_selected_question_aligns_source_specs_with_public_choice_order(bridge):
    source, observer, _, _ = bridge
    def reversed_details(_config, identifier):
        value = observed_question(identifier)
        value['detail']['choices'].reverse()
        return value
    observer.question_reader = reversed_details
    record = source.freeze_question('q_generated')
    predicted = predict_question(_case(record), source.inventory()['items'][0]['snapshot'])
    assert predicted['status'] == 'answered' and predicted['answer_id'] == 'c_A'


def test_source_revision_required_before_executable_claim_can_be_frozen(bridge):
    source, observer, value, _ = bridge
    value['claims'][0]['version'] = None
    observer.poll_once()
    item = source.inventory()['items'][0]
    assert item['snapshot']['rules'] == []
    assert item['skipped_claims'][0]['reason'] == 'invalid_identity'


def test_evidence_question_outside_recent_generation_window_can_be_carried(bridge):
    source, observer, value, _ = bridge
    value['round_details']['1']['generation']['items'] = []
    value['claim_details']['C1']['evidence'] = [{
        'question_id': 'q_generated', 'round': 1, 'outcome': 'support',
        'question': {'family': 'univariate_regression', 'type': 'architecture_only'},
    }]
    observer.poll_once()
    token = observer.snapshot()['observation']
    result = source.selection({'observation': token, 'question_id': 'q_generated',
                               'claim_ref': {'id': 'C1', 'version': 2}})
    assert source.get_question(result['question_key'])['public']['id'] == 'q_generated'


def test_saved_counterexample_outside_recent_windows_can_be_carried_without_its_outcome(bridge):
    source, observer, value, _ = bridge
    value['round_details']['1']['generation']['items'] = []
    value['claim_details']['C1']['counterexamples'] = {'items': [{
        'question_id': 'q_generated', 'round': 1, 'outcome': 'refute',
        'question': {'family': 'univariate_regression', 'type': 'architecture_only',
                     'winner': 'SECRET_GT'},
    }], 'total': 1, 'truncated': False}
    observer.poll_once()
    result = source.selection({'observation': observer.snapshot()['observation'],
                               'question_id': 'q_generated', 'claim_ref': {'id': 'C1', 'version': 2}})
    record = source.get_question(result['question_key'])
    assert record['public']['id'] == 'q_generated'
    assert 'SECRET_GT' not in json.dumps(result) and 'SECRET_GT' not in json.dumps(record)
    assert 'outcome' not in json.dumps(record)
