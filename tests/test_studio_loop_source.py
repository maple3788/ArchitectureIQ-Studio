import hashlib
import json
from pathlib import Path

import pytest

from architecture_iq.studio.loop_source import Reader, SourceUnavailable, collect


def dump(root, path, value):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(value))
    return dest


def rows(root, path, values):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(''.join(json.dumps(value) + '\n' for value in values))
    return dest


@pytest.fixture
def source(tmp_path):
    claim = {'id': 'C1', 'version': 2, 'status': 'candidate', 'text': '宽度更大', 'rules': [],
             'registered_round': 1, 'revisions': 1, 'needs_revision': False, 'stats': None,
             'parent': {'id': 'C1', 'version': 1}, 'origin': 'private/source/path'}
    dump(tmp_path, 'claims.json', {'claims': {'C1': claim}})
    rows(tmp_path, 'claim_versions.jsonl', [{**claim, 'version': 1}, claim])
    rows(tmp_path, 'records.jsonl', [{'question_id': 'q2', 'round': 2, 'family': 'regression', 'type': 'architecture',
                                    'candidates': {}, 'question_path': '/private/source'}])
    rows(tmp_path, 'ledger.jsonl', [
        {'claim_id': 'C1', 'version': 1, 'question_id': 'old', 'round': 1, 'outcome': 'support'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'dev', 'round': 1, 'outcome': 'support'},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute', 'conflicts': 1},
        {'claim_id': 'C1', 'version': 2, 'question_id': 'q2', 'round': 2, 'outcome': 'refute', 'conflicts': 1},
    ])
    dump(tmp_path, 'rounds/round_0002/plan.json', [{'item_id': 'a', 'purpose': 'target'}, {'item_id': 'b', 'purpose': 'explore'}])
    (tmp_path / 'rounds/round_0002/DONE_plan').touch()
    rows(tmp_path, 'rounds/round_0002/build.jsonl', [{'item_id': 'a', 'status': 'failed'}, {'item_id': 'a', 'status': 'ok'},
                                                 {'item_id': 'a', 'status': 'failed'}, {'item_id': 'b', 'status': 'crashed'}])
    (tmp_path / 'config.yaml').write_text('judge:\n  min_applicable: 40\n  promote_rate: 0.85\n  promote_lower_bound: 0.7\nqwen:\n  url: PRIVATE_ENDPOINT\n')
    return tmp_path


def test_stable_capture_is_read_only_and_preserves_actual_source_semantics(source):
    before = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    snapshot = collect(source)
    assert snapshot['execution']['status'] == 'unknown'
    assert snapshot['round']['completed_stages'] == ['plan']
    assert snapshot['round']['next_stage'] == 'build'
    assert snapshot['round']['build'] == {'completed': 2, 'ok': 1, 'failed': 1}
    assert snapshot['kb'] == {'claims': 1, 'candidate': 1, 'verified': 0, 'flagged': 0, 'retired': 0}
    assert snapshot['claims'][0]['stats'] is None
    assert snapshot['claims'][0]['evidence'] == {'applicable': 1, 'support': 0, 'refute': 1, 'conflicts': 1}
    assert snapshot['claim_details']['C1']['evidence'][0]['question']['question_id'] == 'q2'
    assert len(snapshot['claim_details']['C1']['history']) == 2
    assert snapshot['thresholds']['min_applicable'] == 40
    assert 'PRIVATE_ENDPOINT' not in json.dumps(snapshot)
    assert '/private/source' not in json.dumps(snapshot)
    assert 'private/source/path' not in json.dumps(snapshot)
    after = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    assert before == after


def test_incomplete_jsonl_tail_waits_for_the_writer(source):
    path = source / 'ledger.jsonl'
    with path.open('a') as file:
        file.write('{"claim_id":')
    assert collect(source)['claims'][0]['evidence']['applicable'] == 1


def test_corrupt_complete_jsonl_record_is_not_silently_ignored(source):
    with (source / 'ledger.jsonl').open('a') as file:
        file.write('not json\n')
    with pytest.raises(ValueError):
        collect(source)


def test_next_round_is_observed_without_creating_it(source):
    for stage in ('build', 'score', 'judge', 'propose', 'register', 'report'):
        (source / 'rounds/round_0002' / ('DONE_' + stage)).touch()
    result = collect(source, 'stopped')
    assert result['round']['index'] == 3
    assert result['round']['completed_stages'] == []
    assert not (source / 'rounds/round_0003').exists()
    assert result['execution']['status'] == 'stopped'


def test_registration_hash_mismatch_is_visible_without_promoting_claims(source):
    data = {'claims': []}
    path = dump(source, 'rounds/round_0002/preregistered.json', data)
    digest = path.with_suffix('.sha256')
    assert collect(source)['round_details']['2']['registration']['hash_matches'] is None
    digest.write_text('incorrect')
    result = collect(source)
    assert result['round_details']['2']['registration']['hash_matches'] is False
    digest.write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    result = collect(source)
    assert result['round_details']['2']['registration']['hash_matches'] is True
    assert result['kb']['verified'] == 0


def test_source_links_and_traversal_are_rejected(source, tmp_path):
    with pytest.raises(SourceUnavailable):
        Reader(source).read('../outside')
    (source / 'ledger.jsonl').unlink()
    (source / 'ledger.jsonl').symlink_to(source / 'claims.json')
    with pytest.raises(SourceUnavailable):
        collect(source)


def test_changed_artifact_during_capture_is_rejected(source, monkeypatch):
    original = Reader.finish
    def change(reader):
        (source / 'claims.json').write_text('{}')
        return original(reader)
    monkeypatch.setattr(Reader, 'finish', change)
    with pytest.raises(SourceUnavailable):
        collect(source)


def test_round_completion_between_two_reads_cannot_replace_the_original_stamp(source, monkeypatch):
    original = Reader.read
    def mark_report(reader, relative, required=False):
        if relative.endswith('DONE_report') and relative in reader.files:
            (source / relative).touch()
        return original(reader, relative, required)
    monkeypatch.setattr(Reader, 'read', mark_report)
    with pytest.raises(SourceUnavailable):
        collect(source)


def test_observer_never_emits_source_alert_text_or_config(source):
    (source / 'ALERT').write_text('traceback PRIVATE_HOST PRIVATE_SECRET /private/path')
    (source / 'STOP').touch()
    result = collect(source, 'running')
    assert result['execution'] == {'status': 'running', 'stop_requested': True, 'alert': True}
    assert 'PRIVATE_' not in json.dumps(result)
    assert '/private' not in json.dumps(result)


def test_source_evidence_list_is_bounded_but_exact_total_is_retained(source):
    rows(source, 'ledger.jsonl', [{'claim_id': 'C1', 'version': 2, 'question_id': f'q{i}', 'round': 2, 'outcome': 'support'} for i in range(130)])
    result = collect(source)
    detail = result['claim_details']['C1']
    assert detail['evidence_total'] == 130
    assert detail['evidence_truncated'] is True
    assert len(detail['evidence']) == 100
    assert detail['claim']['evidence']['support'] == 130


def test_generation_items_follow_saved_results_and_never_infer_active_worker(source):
    dump(source, 'rounds/round_0002/plan.json', [
        {'item_id': 'a', 'family': 'xor_classification', 'question_type': 'mixed', 'budget': 4096,
         'purpose': 'target', 'targets': ['C1'], 'seed_base': 123},
        {'item_id': 'b', 'family': 'multivariate_regression', 'question_type': 'architecture_only',
         'budget': 8192, 'purpose': 'explore', 'targets': []},
        {'item_id': 'c', 'family': 'bigram_lm', 'question_type': 'optimizer_only',
         'budget': 4096, 'purpose': 'explore', 'targets': []},
    ])
    rows(source, 'rounds/round_0002/build.jsonl', [
        {'item_id': 'a', 'status': 'failed', 'notes': ['PRIVATE_PATH']},
        {'item_id': 'a', 'status': 'ok', 'question_id': 'q_good', 'seconds': 7.5,
         'question_path': '/PRIVATE_PATH/question.json'},
        {'item_id': 'a', 'status': 'crashed', 'traceback': 'PRIVATE_TRACE'},
        {'item_id': 'b', 'status': 'crashed', 'traceback': 'PRIVATE_TRACE'},
    ])
    value = collect(source, 'running')['round_details']['2']['generation']
    assert {key: value[key] for key in ('total', 'completed', 'ok', 'failed', 'pending')} == {
        'total': 3, 'completed': 2, 'ok': 1, 'failed': 1, 'pending': 1}
    assert value['items'] == [
        {'item_id': 'a', 'family': 'xor_classification', 'question_type': 'mixed', 'budget': 4096,
         'purpose': 'target', 'targets': ['C1'], 'status': 'ok', 'seconds': 7.5, 'question_id': 'q_good'},
        {'item_id': 'b', 'family': 'multivariate_regression', 'question_type': 'architecture_only',
         'budget': 8192, 'purpose': 'explore', 'targets': [], 'status': 'crashed'},
        {'item_id': 'c', 'family': 'bigram_lm', 'question_type': 'optimizer_only',
         'budget': 4096, 'purpose': 'explore', 'targets': [], 'status': 'pending'},
    ]
    assert 'PRIVATE_' not in json.dumps(value)
