"""Read-only run inspection must respect durable commit and GT boundaries."""
import copy
import json

import pytest

from architecture_iq.kb.roles import _seal
from architecture_iq.kb.store import canonical_hash, write_json_atomic


def sample(tmp_path):
    directory = tmp_path / 'runs' / 'run_sample'
    out = directory / 'workflow'
    questions = [{'id': 'q1', 'prompt': 'public', 'split': 'discovery'}]
    feedback = {'q1': {'correct_letter': 'B'}, 'heldout': {'correct_letter': 'SECRET'}}
    payloads = {'public_questions.json': questions, 'private_feedback.json': feedback, 'config.json': {}}
    for name, value in payloads.items():
        write_json_atomic(out / name, value)
    write_json_atomic(out / 'manifest.json', {
        'config': {}, 'inputs': {k: canonical_hash(v) for k,v in payloads.items()},
        'round_questions': {'1': ['q1']},
    })
    events = [{'node_id': n, 'state': 'complete', 'round_index': 1, **({'key': 'q1'} if n == 'commit' else {})}
              for n in ['input', 'commit', 'reveal']]
    job = {'id': 'run_sample', 'kind': 'workflow', 'status': 'failed',
           'config': {'question_set': {'questions': questions, 'feedback': feedback}}, 'events': events}
    answer = {'ranking': ['B', 'A', 'C'], 'valid': True}
    write_json_atomic(out / 'rounds/1/answers' / (canonical_hash('q1') + '.json'),
                      _seal({'input_hash': canonical_hash(answer), 'result': answer}))
    return job, directory, out


def inspect(job, directory):
    from architecture_iq.studio.observations import node_observations
    return node_observations(job, directory)


def test_failed_run_retains_committed_program_output(tmp_path):
    job, directory, _ = sample(tmp_path)
    values = inspect(job, directory)
    assert next(v for v in values if v['node_id'] == 'commit')['output']['valid'] is True
    reveal = next(v for v in values if v['node_id'] == 'reveal')
    assert reveal['output'] == {'q1': {'correct_letter': 'B'}}
    assert 'SECRET' not in json.dumps(values)


@pytest.mark.parametrize('change', ['answer_missing', 'reveal_not_complete', 'tampered_answer'])
def test_feedback_requires_verified_answers_and_reveal(tmp_path, change):
    job, directory, out = sample(tmp_path)
    answer = next((out / 'rounds/1/answers').glob('*.json'))
    if change == 'answer_missing':
        answer.unlink()
    elif change == 'tampered_answer':
        data = json.loads(answer.read_text()); data['result']['valid'] = False
        answer.write_text(json.dumps(data))
    else:
        job['events'][-1]['state'] = 'ready'
    values = inspect(job, directory)
    assert 'correct_letter' not in json.dumps(values)
    if change == 'tampered_answer':
        assert 'output' not in next(v for v in values if v['node_id'] == 'commit')


def test_artifact_symlink_cannot_escape_run(tmp_path):
    job, directory, out = sample(tmp_path)
    external = tmp_path / 'external.json'
    original = out / 'public_questions.json'
    original.rename(external); original.symlink_to(external)
    assert all('output' not in v for v in inspect(job, directory))


def test_manifest_cannot_replace_frozen_inputs(tmp_path):
    job, directory, out = sample(tmp_path)
    replacement = [{'id': 'q1', 'prompt': 'CHANGED'}]
    write_json_atomic(out / 'public_questions.json', replacement)
    manifest = json.loads((out / 'manifest.json').read_text())
    manifest['inputs']['public_questions.json'] = canonical_hash(replacement)
    write_json_atomic(out / 'manifest.json', manifest)
    assert 'CHANGED' not in json.dumps(inspect(job, directory))


def test_role_receipt_preserves_round_key_and_exact_request(tmp_path):
    job, directory, out = sample(tmp_path)
    role = {'role': 'solver', 'key': 'q1', 'round_index': 1, 'status': 'complete',
            'request': {'prompt': 'ACTUAL'}, 'result': {'ranking': ['B']}, 'raw': {'choices': []}}
    role['request_hash'] = canonical_hash(role['request'])
    identity = canonical_hash({'role': 'solver', 'key': 'q1', 'round': 1})
    role['id'] = identity
    write_json_atomic(out / 'calls' / (identity + '.json'), _seal(role))
    job['events'].append({'node_id': 'solver', 'state': 'complete', 'round_index': 1, 'key': 'q1'})
    value = next(v for v in inspect(job, directory) if v['node_id'] == 'solver')
    assert value['input'] == role['request']
    assert value['output']['raw'] == role['raw']
    assert value['key'] == 'q1'


def test_publish_reads_the_round_snapshot_not_current(tmp_path):
    job, directory, out = sample(tmp_path)
    snapshot = {'parent_version': None, 'claims': [{'id': 'old'}], 'evidence': []}
    version = canonical_hash(snapshot)
    snapshot['version'] = version
    write_json_atomic(out / f'kb/snapshots/{version}.json', snapshot)
    write_json_atomic(out / 'kb/CURRENT', {'version': 'newer'})
    write_json_atomic(out / 'rounds/1/result.json', _seal({'result': {'round': 1, 'kb_after': version}}))
    for name, result in [('patch', {'operations': []}), ('evidence', [])]:
        write_json_atomic(out / f'rounds/1/{name}.json', _seal({'input_hash': canonical_hash(result), 'result': result}))
    job['events'].append({'node_id': 'publish', 'state': 'complete', 'round_index': 1})
    value = next(v for v in inspect(job, directory) if v['node_id'] == 'publish')
    assert value['output'] == snapshot


def test_downstream_role_does_not_bypass_reveal_gate(tmp_path):
    job, directory, out = sample(tmp_path)
    job['events'][-1]['state'] = 'ready'
    role = {'role': 'discoverer', 'key': 'packet-0', 'round_index': 1, 'status': 'complete',
            'request': {'prompt': 'PRIVATE_GT_MARKER'}, 'result': {}, 'raw': {}}
    role['request_hash'] = canonical_hash(role['request'])
    identity = canonical_hash({'role': 'discoverer', 'key': 'packet-0', 'round': 1})
    role['id'] = identity
    write_json_atomic(out / 'calls' / (identity + '.json'), _seal(role))
    job['events'].append({'node_id': 'discoverer', 'state': 'complete', 'round_index': 1, 'key': 'packet-0'})
    assert 'PRIVATE_GT_MARKER' not in json.dumps(inspect(job, directory))


def test_run_detail_attaches_observations_without_changing_list_privacy(tmp_path):
    from fastapi.testclient import TestClient
    from architecture_iq.studio.jobs import JobStore
    from services.kb_workflow_api.app import create_app

    job, directory, _ = sample(tmp_path)
    definition = {k: copy.deepcopy(job[k]) for k in ('id', 'kind', 'config')}
    definition['created_at'] = 1
    definition['definition_hash'] = canonical_hash(definition)
    write_json_atomic(directory / 'definition.json', definition)
    write_json_atomic(directory / 'state.json', {'status': 'failed'})
    store = JobStore(tmp_path)
    for event in job['events']:
        store.event(job['id'], {'type': 'stage', **event})
    client = TestClient(create_app(state_root=tmp_path, allowed_roots=[tmp_path], execution_enabled=False))
    detail = client.get('/api/studio/runs/run_sample')
    assert detail.status_code == 200, detail.text
    assert next(v for v in detail.json()['node_observations'] if v['node_id'] == 'commit')['output']['valid']
    assert 'feedback' not in detail.json()['config']['question_set']
    listing = client.get('/api/studio/runs').json()
    assert 'node_observations' not in listing['items'][0]
    assert 'SECRET' not in json.dumps(listing)


def test_declared_output_root_cannot_redirect_to_another_run(tmp_path):
    job, directory, out = sample(tmp_path)
    declared = tmp_path / 'outputs'
    declared.mkdir()
    job['config']['output_root'] = str(declared)
    (declared / job['id']).symlink_to(directory, target_is_directory=True)
    values = inspect(job, directory)
    assert all(v['availability'] == 'unavailable' for v in values)
    assert 'correct_letter' not in json.dumps(values)


def test_malformed_json_receipt_becomes_unavailable(tmp_path):
    job, directory, out = sample(tmp_path)
    next((out / 'rounds/1/answers').glob('*.json')).write_text('null')
    values = inspect(job, directory)
    assert next(v for v in values if v['node_id'] == 'commit')['availability'] == 'unavailable'
    assert 'correct_letter' not in json.dumps(values)


def test_non_stage_event_cannot_attest_feedback_reveal(tmp_path):
    job, directory, _ = sample(tmp_path)
    job['events'][-1]['state'] = 'ready'
    job['events'].append({'type': 'error', 'node_id': 'reveal', 'state': 'complete', 'round_index': 1})
    assert 'correct_letter' not in json.dumps(inspect(job, directory))


def test_feedback_requires_each_answer_commit_event(tmp_path):
    job, directory, _ = sample(tmp_path)
    job['events'][1]['state'] = 'ready'
    assert 'correct_letter' not in json.dumps(inspect(job, directory))


@pytest.mark.parametrize('mismatch', ['input_hash', 'raw'])
def test_answer_must_match_its_own_solver_receipt(tmp_path, mismatch):
    job, directory, out = sample(tmp_path)
    raw = {'ranking': ['B', 'A', 'C'], 'rationale': 'own response'}
    role = {'role': 'solver', 'key': 'q1', 'round_index': 1, 'status': 'complete',
            'request': {'prompt': 'ACTUAL'}, 'result': raw, 'raw': {'choices': []}}
    role['request_hash'] = canonical_hash(role['request'])
    identity = canonical_hash({'role': 'solver', 'key': 'q1', 'round': 1})
    role['id'] = identity
    write_json_atomic(out / 'calls' / (identity + '.json'), _seal(role))
    answer = {'valid': True, 'raw': raw if mismatch == 'input_hash' else {'ranking': ['A', 'B', 'C']}}
    write_json_atomic(out / 'rounds/1/answers' / (canonical_hash('q1') + '.json'),
                      _seal({'input_hash': canonical_hash({'borrowed': True} if mismatch == 'input_hash' else raw), 'result': answer}))
    values = inspect(job, directory)
    assert next(v for v in values if v['node_id'] == 'commit')['availability'] == 'unavailable'
    assert 'correct_letter' not in json.dumps(values)


@pytest.mark.parametrize('revealed', [True, False])
def test_recipe_steps_bind_their_own_role_receipts(tmp_path, revealed):
    job, directory, out = sample(tmp_path)
    if not revealed:
        job['events'][-1]['state'] = 'ready'
    for role_name, step in [('pair_researcher', 'pair_induction'),
                            ('experience_curator', 'experience_consolidate')]:
        request = {'prompt': 'PRIVATE_' + role_name}
        identity = canonical_hash({'role': role_name, 'key': 'shared', 'round': 1})
        value = {'id': identity, 'role': role_name, 'key': 'shared', 'round_index': 1,
                 'status': 'complete', 'request': request, 'request_hash': canonical_hash(request),
                 'result': {'step': step}, 'raw': {}}
        write_json_atomic(out / 'calls' / (identity + '.json'), _seal(value))
        job['events'].append({'node_id': 'discoverer', 'role': role_name, 'key': 'shared',
                              'round_index': 1, 'state': 'complete', 'stage_id': 'harness', 'step_id': step})
    values = [v for v in inspect(job, directory) if v['node_id'] == 'discoverer']
    assert len(values) == 2
    assert {v['step_id'] for v in values} == {'pair_induction', 'experience_consolidate'}
    if revealed:
        for row in values:
            assert row['stage_id'] == 'harness'
            assert row['output']['result']['step'] == row['step_id']
            assert row['availability'] == 'available'
    else:
        assert 'PRIVATE_' not in json.dumps(values)
