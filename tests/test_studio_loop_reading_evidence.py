"""Human-readable evidence stays separate from public Task inference inputs."""
from copy import deepcopy
import json

import pytest

from architecture_iq.studio.loop_observer import LoopObserver
from test_studio_loop_observer import configuration
from test_studio_evolution_task_sources import observed_capture
from test_studio_loop_observer_api import client_for
from test_studio_loop_source import source, rows
from architecture_iq.studio.loop_source import collect


def evidence(qid='q_generated', outcome='refute'):
    return {'claim_id': 'C1', 'version': 2, 'question_id': qid, 'round': 2,
            'outcome': outcome, 'pairs': [['source_candidate_beta', 'source_candidate_alpha', False]],
            'conflicts': 0, 'question': {'question_id': qid, 'family': 'xor_classification',
               'candidates': {'source_candidate_beta': {'width': 16}, 'source_candidate_alpha': {'width': 32}},
               'winner': 'source_candidate_beta'}}


@pytest.fixture
def reading(tmp_path):
    value = observed_capture()
    value['claims'][0]['evidence'] = {'applicable': 2, 'support': 1, 'refute': 1, 'conflicts': 0}
    value['claim_details']['C1'] = {'claim': deepcopy(value['claims'][0]), 'history': [],
        'evidence': [evidence(), evidence('q_other', 'support')], 'evidence_total': 2, 'evidence_truncated': False}
    value['round_details']['1']['generation']['items'][0]['targets'] = ['C1']
    observer = LoopObserver(tmp_path, config=configuration(), reader=lambda _: value,
                            question_reader=lambda *_: pytest.fail('Evidence reads must not fetch remote questions'))
    assert observer.poll_once()
    return client_for(tmp_path, observer), observer, value


def get(client, token, qid='q_generated', **extra):
    return client.get(f'/api/studio/kb-loop/questions/{qid}/evidence', params={**token, **extra})


def test_selected_kb_and_real_refute_pair_are_exact_saved_human_evidence(reading):
    client, observer, _ = reading
    response = get(client, observer.snapshot()['observation'], claim_id='C1', claim_version=2)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['question_id'] == 'q_generated'
    entry = result['claims'][0]
    assert entry['relation'] == 'selected' and entry['claim']['id'] == 'C1'
    assert entry['current_evidence'][0]['outcome'] == 'refute'
    assert entry['current_evidence'][0]['pairs'] == [['source_candidate_beta', 'source_candidate_alpha', False]]
    assert entry['counterexamples']['items'][0]['question_id'] == 'q_generated'
    assert entry['counterexamples']['total'] == 1 and entry['counterexamples']['truncated'] is False
    assert client.get('/api/studio/tasks').json()['items'] == []
    assert client.get('/api/studio/runs').json()['items'] == []
    for private in ('/private/', 'authorized.test', 'researcher'):
        assert private not in response.text


def test_reading_stays_on_seen_capture_after_source_claim_changes(reading):
    client, observer, value = reading
    token = observer.snapshot()['observation']
    value['claims'][0]['version'] = 3
    value['claim_details']['C1']['claim']['version'] = 3
    value['claim_details']['C1']['evidence'] = []
    observer.poll_once()
    result = get(client, token, claim_id='C1', claim_version=2)
    assert result.status_code == 200
    assert result.json()['claims'][0]['claim']['version'] == 2
    assert result.json()['claims'][0]['current_evidence'][0]['outcome'] == 'refute'


def test_generated_question_association_uses_only_saved_targets_or_evidence(reading):
    client, observer, value = reading
    value['claims'].append({**deepcopy(value['claims'][0]), 'id': 'C2'})
    value['claim_details']['C2'] = {'claim': deepcopy(value['claims'][1]), 'history': [],
        'evidence': [], 'evidence_total': 0, 'evidence_truncated': False}
    result = get(client, observer.snapshot()['observation']).json()
    assert [entry['claim']['id'] for entry in result['claims']] == ['C1']
    assert result['claims'][0]['relation'] == 'evidence'
    value['claim_details']['C1']['evidence'] = []
    observer.poll_once()
    result = get(client, observer.snapshot()['observation']).json()
    assert [entry['claim']['id'] for entry in result['claims']] == ['C1']
    assert result['claims'][0]['relation'] == 'target'
    assert result['claims'][0]['current_evidence'] == []
    value['round_details']['1']['generation']['items'][0]['targets'] = []
    observer.poll_once()
    result = get(client, observer.snapshot()['observation']).json()
    assert result['claims'] == [] and result['notice']


def test_old_capture_never_claims_missing_older_counterexamples_do_not_exist(reading):
    client, observer, value = reading
    value['claim_details']['C1']['claim']['evidence']['refute'] = 8
    value['claim_details']['C1']['evidence_truncated'] = True
    value['claim_details']['C1']['evidence_total'] = 170
    observer.poll_once()
    result = get(client, observer.snapshot()['observation']).json()['claims'][0]
    assert result['counterexamples']['total'] == 8
    assert len(result['counterexamples']['items']) == 1 and result['counterexamples']['truncated'] is True


@pytest.mark.parametrize('change,status', [('source',409),('sequence',409),('claim_version',409),
                                           ('unknown_question',200),('missing_version',422)])
def test_stale_or_unbound_evidence_requests_are_rejected(reading, change, status):
    client, observer, _ = reading
    token = observer.snapshot()['observation']
    extra = {'claim_id': 'C1', 'claim_version': 2}
    qid = 'q_generated'
    if change == 'source': token['source_identity'] = '0' * 64
    elif change == 'sequence': token['sequence'] = 999
    elif change == 'claim_version': extra['claim_version'] = 9
    elif change == 'unknown_question': qid = 'q_unknown'
    else: del extra['claim_version']
    assert get(client, token, qid, **extra).status_code == status


def test_refute_window_survives_many_newer_supporting_questions(source):
    failures = [{'claim_id': 'C1', 'version': 2, 'question_id': 'q_refute', 'round': 2,
                 'outcome': 'refute', 'pairs': [['c_left', 'c_right', False]]}]
    successes = [{'claim_id': 'C1', 'version': 2, 'question_id': f'q_support_{i}', 'round': 3,
                  'outcome': 'support'} for i in range(120)]
    rows(source, 'ledger.jsonl', failures + successes)
    detail = collect(source)['claim_details']['C1']
    assert all(row['outcome'] == 'support' for row in detail['evidence'])
    counterexamples = detail['counterexamples']
    assert counterexamples['items'][0]['question_id'] == 'q_refute'
    assert counterexamples['total'] == 1 and counterexamples['truncated'] is False


def test_counterexample_window_is_bounded_deduped_and_current_revision_only(source):
    failures = [{'claim_id': 'C1', 'version': 2, 'question_id': f'q_refute_{i}', 'round': 2,
                 'outcome': 'refute'} for i in range(130)]
    rows(source, 'ledger.jsonl', failures + failures + [
        {'claim_id': 'C1', 'version': 1, 'question_id': 'q_old', 'round': 2, 'outcome': 'refute'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q_registration', 'round': 1, 'outcome': 'refute'}])
    result = collect(source)['claim_details']['C1']['counterexamples']
    assert result['total'] == 130 and len(result['items']) == 100 and result['truncated'] is True
    assert all(item['question_id'] not in {'q_old', 'q_registration'} for item in result['items'])


def test_counterexample_window_supplies_current_question_without_recent_manifest(reading):
    client, observer, value = reading
    detail = value['claim_details']['C1']
    detail['evidence'] = [evidence('q_other', 'support')]
    detail['counterexamples'] = {'items': [evidence()], 'total': 1, 'truncated': False}
    value['round_details']['1']['generation']['items'] = []
    observer.poll_once()
    result = get(client, observer.snapshot()['observation']).json()
    assert result['claims'][0]['current_evidence'][0]['question_id'] == 'q_generated'
    assert result['claims'][0]['relation'] == 'evidence'


def test_missing_legacy_counterexample_count_is_unknown_not_zero(reading):
    client, observer, value = reading
    detail = value['claim_details']['C1']
    detail['claim'].pop('evidence')
    detail['evidence_truncated'] = True
    observer.poll_once()
    counterexamples = get(client, observer.snapshot()['observation']).json()['claims'][0]['counterexamples']
    assert counterexamples['total'] is None and counterexamples['truncated'] is True


def test_reading_does_not_mix_claim_revision_or_drop_saved_rounds(reading):
    client, observer, value = reading
    detail = value['claim_details']['C1']
    detail['evidence'] = [evidence(), {**evidence(), 'round': 3},
                          {**evidence(), 'version': 1, 'outcome': 'support'}]
    observer.poll_once()
    current = get(client, observer.snapshot()['observation']).json()['claims'][0]['current_evidence']
    assert [row['round'] for row in current] == [2, 3]
    assert all(row['version'] == 2 for row in current)


def test_unbound_internal_read_cannot_fall_back_to_current_capture(reading):
    _, observer, _ = reading
    with pytest.raises(ValueError):
        observer.question_evidence('q_generated', source_identity=None, sequence=None)
