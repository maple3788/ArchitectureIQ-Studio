"""Round claim reading uses saved revisions and round-bounded research evidence."""
import json

import pytest

from architecture_iq.studio.loop_observer import LoopObserver
from architecture_iq.studio.loop_source import collect
from test_studio_loop_observer import configuration
from test_studio_loop_observer_api import client_for
from test_studio_loop_source import source, dump, rows


@pytest.fixture
def revised_source(source):
    original = json.loads((source / 'claims.json').read_text())['claims']['C1']
    revised = {**original, 'version': 3, 'registered_round': 3, 'text': 'Later revision',
               'status': 'verified', 'stats': {'support': 99}, 'parent': {'id': 'C1', 'version': 2}}
    dump(source, 'claims.json', {'claims': {'C1': revised}})
    rows(source, 'claim_versions.jsonl', [original, revised])
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 2, 'from': 'candidate', 'to': 'flagged',
         'support': 0, 'applicable': 1, 'needs_revision': True}]})
    rows(source, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q_registration', 'round': 1, 'outcome': 'support'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q_future', 'round': 3, 'outcome': 'support'},
        {'claim_id': 'C1', 'version': 3, 'question_id': 'q_revision', 'round': 4, 'outcome': 'support'}])
    return source


def observe(tmp_path, value):
    observer = LoopObserver(tmp_path / 'observer', config=configuration(), reader=lambda _: value,
                            question_reader=lambda *_: pytest.fail('Round reading must not fetch questions'))
    assert observer.poll_once()
    return observer, client_for(tmp_path, observer)


def get(client, token, *, number=2, identifier='C1', version=2):
    return client.get(f'/api/studio/kb-loop/rounds/{number}/claims/{identifier}',
                      params={**token, 'version': version})


def test_round_claim_retains_old_text_status_and_evidence_after_revision(tmp_path, revised_source):
    observer, client = observe(tmp_path, collect(revised_source))
    response = get(client, observer.round(2)['observation'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['claim']['version'] == 2 and result['claim']['text'] == '宽度更大'
    assert result['claim']['status'] == 'flagged' and result['claim']['stats']['support'] == 0
    assert result['claim']['needs_revision'] is True
    assert result['reading_round'] == 2 and result['evidence_unavailable'] is False
    assert result['evidence_total'] == 1 and result['evidence_truncated'] is False
    assert [row['question_id'] for row in result['evidence']] == ['q2']
    assert result['evidence'][0]['question']['question_id'] == 'q2'
    assert result['counterexamples']['total'] == 1
    assert result['claim']['evidence'] == {'applicable': 1, 'support': 0, 'refute': 1, 'conflicts': 0}
    assert all(row['version'] <= 2 for row in result['history'])
    assert 'claim_details' not in observer.round(2)
    assert 'evidence_questions' not in observer.round(2)
    assert client.get('/api/studio/tasks').json()['items'] == []
    assert client.get('/api/studio/runs').json()['items'] == []


def test_round_claim_keeps_seen_capture_when_new_observation_arrives(tmp_path, revised_source):
    value = collect(revised_source)
    observer, client = observe(tmp_path, value)
    token = observer.round(2)['observation']
    value['round_details']['2']['claim_details']['C1']['2']['claim']['text'] = 'New capture text'
    assert observer.poll_once()
    assert get(client, token).json()['claim']['text'] == '宽度更大'
    assert get(client, observer.round(2)['observation']).json()['claim']['text'] == 'New capture text'


@pytest.mark.parametrize('change,expected', [
    ('source', 409), ('sequence', 409), ('round', 404), ('claim', 404), ('version', 404)])
def test_round_claim_rejects_unresolvable_reading_context(tmp_path, revised_source, change, expected):
    observer, client = observe(tmp_path, collect(revised_source))
    token, extra = observer.round(2)['observation'], {}
    if change == 'source': token['source_identity'] = '0' * 64
    elif change == 'sequence': token['sequence'] = 999
    elif change == 'round': extra['number'] = 999
    elif change == 'claim': extra['identifier'] = 'C_missing'
    else: extra['version'] = 3
    assert get(client, token, **extra).status_code == expected


def test_legacy_history_returns_exact_version_with_unknown_missing_evidence(tmp_path, revised_source):
    value = collect(revised_source)
    value['round_details']['2'].pop('claim_details', None)
    observer, client = observe(tmp_path, value)
    response = get(client, observer.round(2)['observation'])
    assert response.status_code == 200
    result = response.json()
    assert result['claim']['version'] == 2 and result['claim']['text'] == '宽度更大'
    assert result['evidence'] == [] and result['evidence_total'] is None
    assert result['evidence_unavailable'] is True and result['notice']
    assert result['counterexamples']['total'] is None


def test_legacy_exact_current_revision_uses_only_saved_round_evidence(tmp_path, source):
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 2, 'to': 'candidate', 'applicable': 1, 'support': 0}]})
    rows(source, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q_future', 'round': 3, 'outcome': 'support'}])
    value = collect(source)
    value['round_details']['2'].pop('claim_details', None)
    observer, client = observe(tmp_path, value)
    result = get(client, observer.round(2)['observation']).json()
    assert result['evidence_unavailable'] is False and result['evidence_total'] == 1
    assert [row['question_id'] for row in result['evidence']] == ['q2']
    assert result['claim']['evidence']['support'] == 0


def test_legacy_window_never_claims_excluded_missing_evidence_is_complete(tmp_path, source):
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 2, 'to': 'candidate'}]})
    value = collect(source)
    value['round_details']['2'].pop('claim_details', None)
    value['claim_details']['C1']['evidence_truncated'] = True
    value['claim_details']['C1']['evidence_total'] = 200
    observer, client = observe(tmp_path, value)
    result = get(client, observer.round(2)['observation']).json()
    assert result['evidence_unavailable'] is True and result['evidence_total'] is None
    assert [row['question_id'] for row in result['evidence']] == ['q2']


def test_collector_bounds_round_evidence_but_retains_real_totals(tmp_path, revised_source):
    ledger = [{'claim_id': 'C1', 'version': 2, 'question_id': f'q_{i}', 'round': 2,
               'outcome': 'refute'} for i in range(130)]
    rows(revised_source, 'ledger.jsonl', ledger + ledger + [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q_future', 'round': 3, 'outcome': 'refute'}])
    observer, client = observe(tmp_path, collect(revised_source))
    result = get(client, observer.round(2)['observation']).json()
    assert result['evidence_total'] == 130 and len(result['evidence']) == 100
    assert result['evidence_truncated'] is True and result['evidence_unavailable'] is False
    assert result['counterexamples']['total'] == 130 and len(result['counterexamples']['items']) == 100
    assert all(row['round'] == 2 for row in result['evidence'])


def test_newer_duplicate_ledger_row_does_not_erase_saved_earlier_round(tmp_path, revised_source):
    rows(revised_source, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 3, 'outcome': 'support'}])
    observer, client = observe(tmp_path, collect(revised_source))
    result = get(client, observer.round(2)['observation']).json()
    assert result['evidence_total'] == 1
    assert result['evidence'][0]['round'] == 2 and result['evidence'][0]['outcome'] == 'refute'


def test_missing_historical_text_never_substitutes_latest_revision(tmp_path, revised_source):
    value = collect(revised_source)
    value['round_details']['2'].pop('claim_details', None)
    value['claim_details']['C1']['history'] = []
    observer, client = observe(tmp_path, value)
    assert get(client, observer.round(2)['observation']).status_code == 404


def test_internal_round_read_requires_complete_observation_reference(tmp_path, revised_source):
    observer, _ = observe(tmp_path, collect(revised_source))
    with pytest.raises(ValueError):
        observer.round_claim(2, 'C1', version=2, source_identity=None, sequence=None)


def test_round_evidence_question_uses_projected_records_not_untrusted_ledger_payload(tmp_path, revised_source):
    rows(revised_source, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute',
         'question': {'question_id': 'q2', 'private_path': 'PRIVATE_LEDGER_PAYLOAD'}}])
    observer, client = observe(tmp_path, collect(revised_source))
    response = get(client, observer.round(2)['observation'])
    assert response.status_code == 200
    assert 'PRIVATE_LEDGER_PAYLOAD' not in response.text
    assert response.json()['evidence'][0]['question']['family'] == 'regression'


def test_legacy_later_duplicate_cannot_prove_an_earlier_round_had_zero_evidence(tmp_path, source):
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 2, 'to': 'candidate'}]})
    rows(source, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 3, 'outcome': 'support'}])
    value = collect(source)
    value['round_details']['2'].pop('claim_details', None)
    observer, client = observe(tmp_path, value)
    result = get(client, observer.round(2)['observation']).json()
    assert result['evidence'] == []
    assert result['evidence_total'] is None and result['evidence_unavailable'] is True


def test_generation_item_has_public_candidate_features_without_any_verdict_or_gt(source):
    dump(source, 'rounds/round_0002/plan.json', [{'item_id': 'a', 'purpose': 'explore'}])
    rows(source, 'rounds/round_0002/build.jsonl', [{'item_id': 'a', 'status': 'ok', 'question_id': 'q2'}])
    rows(source, 'records.jsonl', [{'question_id': 'q2', 'round': 2, 'winner': 'SECRET_WINNER',
        'candidates': {'candidate_left': {'depth': 2, 'width': 64, 'opt': 'adamw', 'lr': .01,
                                        'feedback': 'PRIVATE_FEEDBACK', 'mean_test_loss': 123,
                                        'arch_key': '{"api_key":"PRIVATE_SERIALIZED_SECRET"}'},
                       'candidate_right': {'depth': 3, 'width': 32, 'residual': True}},
        'comparisons': [['candidate_left', 'candidate_right', True]]}])
    item = collect(source)['round_details']['2']['generation']['items'][0]
    assert item['question'] == {'candidates': {
        'candidate_left': {'depth': 2, 'width': 64, 'opt': 'adamw', 'lr': .01},
        'candidate_right': {'depth': 3, 'width': 32, 'residual': True}}}
    assert 'PRIVATE_' not in json.dumps(item) and 'SECRET_' not in json.dumps(item)
    assert 'comparisons' not in item['question']


def test_round_question_pool_deduplicates_storage_and_rehydrates_both_evidence_windows(tmp_path, revised_source):
    value = collect(revised_source)
    detail = value['round_details']['2']
    saved = detail['claim_details']['C1']['2']
    assert detail['evidence_questions']['2:q2']['family'] == 'regression'
    assert 'question' not in saved['evidence'][0]
    assert 'question' not in saved['counterexamples']['items'][0]
    observer, client = observe(tmp_path, value)
    result = get(client, observer.round(2)['observation']).json()
    assert result['evidence'][0]['question']['family'] == 'regression'
    assert result['counterexamples']['items'][0]['question']['family'] == 'regression'
    assert 'evidence_questions' not in result


def test_repeated_question_summary_is_bound_to_each_claim_evidence_round(tmp_path, source):
    first = json.loads((source / 'claims.json').read_text())['claims']['C1']
    second = {**first, 'id': 'C2'}
    dump(source, 'claims.json', {'claims': {'C1': first, 'C2': second}})
    rows(source, 'claim_versions.jsonl', [first, second])
    rows(source, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q_repeat', 'round': 2, 'outcome': 'refute'},
        {'claim_id': 'C2', 'version': 2, 'question_id': 'q_repeat', 'round': 3, 'outcome': 'support'}])
    rows(source, 'records.jsonl', [
        {'question_id': 'q_repeat', 'round': 2, 'winner': 'old_winner'},
        {'question_id': 'q_repeat', 'round': 3, 'winner': 'future_winner'}])
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 2, 'to': 'candidate'}]})
    dump(source, 'rounds/round_0003/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 3, 'to': 'candidate'},
        {'claim_id': 'C2', 'version': 2, 'round': 3, 'to': 'candidate'}]})
    observer, client = observe(tmp_path, collect(source))
    for number, identifier, expected_round, winner in [(2, 'C1', 2, 'old_winner'),
            (3, 'C1', 2, 'old_winner'), (3, 'C2', 3, 'future_winner')]:
        result = get(client, observer.round(number)['observation'], number=number, identifier=identifier).json()
        assert result['evidence'][0]['question'] == {
            'question_id': 'q_repeat', 'round': expected_round, 'winner': winner}
        if identifier == 'C1':
            assert result['counterexamples']['items'][0]['question']['winner'] == 'old_winner'


@pytest.mark.parametrize('storage', ['bare_pool', 'embedded', 'legacy_fallback'])
@pytest.mark.parametrize('question_round', [2, 3])
def test_cached_round_summaries_suppress_future_record_but_keep_valid_legacy_record(
        tmp_path, source, storage, question_round):
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'round': 2, 'to': 'candidate'}]})
    value = collect(source)
    detail = value['round_details']['2']
    question = {'question_id': 'q2', 'round': question_round, 'winner': 'record_winner'}
    if storage == 'bare_pool':
        detail['evidence_questions'] = {'q2': question}
    else:
        if storage == 'legacy_fallback':
            detail.pop('claim_details')
            saved = value['claim_details']['C1']
        else:
            saved = detail['claim_details']['C1']['2']
        for row in [*saved['evidence'], *saved['counterexamples']['items']]:
            row['question'] = question
    observer, client = observe(tmp_path, value)
    result = get(client, observer.round(2)['observation']).json()
    expected = question if question_round == 2 else None
    assert result['evidence'][0]['question'] == expected
    assert result['counterexamples']['items'][0]['question'] == expected
