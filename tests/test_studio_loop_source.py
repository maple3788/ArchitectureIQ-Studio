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


def test_unused_nonfinite_record_gaps_do_not_break_monitoring(source):
    path = source / 'records.jsonl'
    record = json.loads(path.read_text())
    record['gaps'] = [float('inf'), float('-inf'), float('nan')]
    rows(source, 'records.jsonl', [record])
    before = path.read_bytes()
    snapshot = collect(source, 'running')
    question = snapshot['claim_details']['C1']['evidence'][0]['question']
    assert question['question_id'] == 'q2'
    assert 'gaps' not in question
    json.dumps(snapshot, allow_nan=False)
    assert path.read_bytes() == before


@pytest.mark.parametrize('field', ['candidates', 'comparisons'])
def test_nonfinite_public_question_fields_remain_rejected(source, field):
    record = json.loads((source / 'records.jsonl').read_text())
    record[field] = {'bad': float('inf')}
    rows(source, 'records.jsonl', [record])
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


def test_current_policy_is_sanitized_without_relabeling_old_rounds(source):
    import yaml
    (source / 'config.yaml').write_text(yaml.safe_dump({
        'evidence': {'min_relative_gap': 0.1, 'private_path': '/private/evidence'},
        'checks': {'min_history_applicable': 1, 'new_min_rate': 0.95, 'revision_min_rate': 0.95,
                   'max_conditions': 10, 'max_rules': True, 'min_coverage_kept': float('nan')},
        'judge': {'min_applicable': 40, 'promote_rate': 0.85, 'promote_lower_bound': 0.7},
        'questions': {'per_round': 300, 'target_fraction': 0.6, 'target_probe_tries': 40,
                      'target_set_probe_tries': 30, 'target_draws': 6, 'seed_workers': {'bigram_lm': 10}},
        'qwen': {'model': 'standby-model', 'base_urls': ['PRIVATE_ENDPOINT']},
        'proposer': {'model': 'gpt-6.1-sol', 'extra_params': {'reasoning_effort': 'high', 'api_key': 'PRIVATE_KEY'},
                     'base_urls': ['PRIVATE_ENDPOINT'], 'api_key_file': '/private/key',
                     'concurrency': 20, 'split_new_errors': 3, 'split_max_claims': 30,
                     'splits_per_claim': 3, 'max_new_per_round': 200, 'stream': True},
    }))
    value = collect(source)
    policy = value['configuration']
    assert policy['scope'] == 'current_source'
    assert policy['evidence'] == {'min_relative_gap': 0.1}
    assert policy['checks'] == {'min_history_applicable': 1, 'new_min_rate': 0.95,
                                'revision_min_rate': 0.95, 'max_conditions': 10}
    assert policy['questions']['seed_workers'] == {'bigram_lm': 10}
    assert policy['proposer'] == {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
                                   'concurrency': 20, 'split_new_errors': 3, 'split_max_claims': 30,
                                   'splits_per_claim': 3, 'max_new_per_round': 200, 'stream': True}
    assert policy['judge']['min_applicable'] == 40
    assert 'PRIVATE_' not in json.dumps(value) and '/private/' not in json.dumps(value)
    assert 'configuration' not in value['round_details']['2']


def test_old_policy_keeps_missing_thresholds_unknown_and_uses_saved_qwen(source):
    (source / 'config.yaml').write_text('qwen:\n  model: qwen3.5-27b\n  concurrency: 96\n')
    policy = collect(source)['configuration']
    assert policy['proposer'] == {'model': 'qwen3.5-27b', 'concurrency': 96}
    assert policy['evidence'] == {} and policy['checks'] == {}


def test_saved_round_reports_and_split_proposals_retain_actual_metrics(source):
    dump(source, 'rounds/round_0002/proposals.json', {
        'new': [{}], 'revisions': {}, 'splits': {'C1': [{}, {}]},
        'needs_revision': ['C1'], 'split_attempts': {'C1': 7, 'C2': 3},
        'model': 'saved-proposer', 'private_path': '/private/path',
    })
    dump(source, 'rounds/round_0002/report.json', {
        'round': 2, 'model': 'saved-proposer',
        'build': {'items': 3, 'ok': 2, 'failed': 1, 'steered': 1, 'target_hit': 0},
        'splits': {'parents': 2, 'registered': 2, 'private_file': '/private/file'},
        'ensemble': {'questions': 2, 'claims': 4, 'answered': 1, 'correct': 1,
                     'coverage': 0.5, 'accuracy': 1, 'overall': 0.5, 'api_key': 'PRIVATE_KEY'},
        'ensemble_explore': {'questions': 0, 'claims': 4, 'answered': 0, 'correct': 0,
                             'coverage': None, 'accuracy': None, 'overall': None},
    })
    value = collect(source)
    detail = value['round_details']['2']
    assert detail['report']['model'] == 'saved-proposer'
    assert detail['report']['build']['target_hit'] == 0
    assert detail['report']['splits'] == {'parents': 2, 'registered': 2}
    assert detail['report']['ensemble'] == {'questions': 2, 'claims': 4, 'answered': 1,
                                           'correct': 1, 'coverage': 0.5, 'accuracy': 1, 'overall': 0.5}
    assert detail['report']['ensemble_explore']['accuracy'] is None
    assert detail['proposals']['split_attempt_count'] == 2
    assert detail['proposals']['split_count'] == 2
    assert detail['proposals']['split_parent_count'] == 1
    assert detail['proposals']['model'] == 'saved-proposer'
    assert value['rounds'][0]['report'] == detail['report']
    assert 'PRIVATE_' not in json.dumps(value) and '/private/' not in json.dumps(value)


def test_generation_preserves_saved_target_misses_and_never_guesses_unrecorded_hits(source):
    rows(source, 'rounds/round_0002/build.jsonl', [
        {'item_id': 'a', 'status': 'ok', 'question_id': 'q2', 'target_hit': False, 'draws': 6},
        {'item_id': 'b', 'status': 'ok', 'question_id': 'q3'},
    ])
    items = collect(source)['round_details']['2']['generation']['items']
    assert items[0]['target_hit'] is False and items[0]['draws'] == 6
    assert 'target_hit' not in items[1] and 'draws' not in items[1]


def test_split_lineage_keeps_parent_and_omits_future_children_from_past_readings(source):
    parent = json.loads((source / 'claims.json').read_text())['claims']['C1']
    child = {**parent, 'id': 'C2', 'version': 1, 'registered_round': 2, 'text': 'Narrow condition',
             'parent': {'id': 'C1', 'version': 2}, 'origin': 'split:C1:round_2'}
    future_child = {**child, 'id': 'C3', 'registered_round': 3, 'origin': 'split:C1:round_3'}
    dump(source, 'claims.json', {'claims': {'C1': parent, 'C2': child, 'C3': future_child}})
    rows(source, 'claim_versions.jsonl', [parent, child, future_child])
    dump(source, 'rounds/round_0002/judge.json', {'events': [
        {'claim_id': 'C1', 'version': 2, 'from': 'candidate', 'to': 'candidate'},
    ]})
    value = collect(source)
    assert value['claim_details']['C2']['claim']['lineage_kind'] == 'split'
    assert value['claim_details']['C2']['claim']['parent'] == {'id': 'C1', 'version': 2}
    assert [c['id'] for c in value['claim_details']['C1']['children']] == ['C2', 'C3']
    historical = value['round_details']['2']['claim_details']['C1']['2']['children']
    assert [c['id'] for c in historical] == ['C2']
    assert historical[0]['version'] == 1 and 'status' not in historical[0]


def test_parent_rule_uses_exact_frozen_version_without_current_or_future_substitution(source):
    latest = json.loads((source / 'claims.json').read_text())['claims']['C1']
    original = {**latest, 'version': 1, 'registered_round': 0, 'text': 'Original broad rule',
                'rules': [{'id': 'original'}], 'parent': None}
    latest.update(text='Later parent revision', registered_round=3)
    child = {**latest, 'id': 'C2', 'version': 1, 'registered_round': 2,
             'parent': {'id': 'C1', 'version': 1}, 'origin': 'split:C1:round_2'}
    impossible = {**child, 'id': 'C3', 'parent': {'id': 'C1', 'version': 2}}
    missing = {**child, 'id': 'C4', 'parent': {'id': 'C_missing', 'version': 1}}
    dump(source, 'claims.json', {'claims': {'C1': latest, 'C2': child, 'C3': impossible, 'C4': missing}})
    rows(source, 'claim_versions.jsonl', [original, latest, child, impossible, missing])
    dump(source, 'rounds/round_0002/preregistered.json', {'claims': [child, impossible, missing]})
    value = collect(source)
    parent = value['claim_details']['C2']['parent_claim']
    assert parent == {'id': 'C1', 'version': 1, 'text': 'Original broad rule',
                      'rules': [{'id': 'original'}], 'registered_round': 0, 'parent': None}
    historical = value['round_details']['2']['claim_details']
    assert historical['C2']['1']['parent_claim'] == parent
    assert 'parent_claim' not in historical['C3']['1'] and 'parent_claim' not in historical['C4']['1']
    assert 'parent_claim' not in value['claim_details']['C3']
    assert 'parent_claim' not in value['claim_details']['C4']
