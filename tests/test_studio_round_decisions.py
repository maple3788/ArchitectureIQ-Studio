"""Durable round controls use sealed local fixtures, never a model service."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from architecture_iq.kb.roles import _seal, read_receipt
from architecture_iq.kb.store import write_json_atomic
from architecture_iq.studio.jobs import JobStore


def waiting_job(tmp_path, *, next_ids=None, evaluate=True):
    store = JobStore(tmp_path)
    job = store.create('workflow', {'workflow': {'settings': {'max_rounds': 2}}})
    store.update(job['id'], status='running')
    store.offer_round_decision(job['id'], round_index=1, kb_version='kb-one',
                              next_round_index=2, next_question_ids=['q2'] if next_ids is None else next_ids,
                              next_round_reason=None if next_ids is None else 'no_next_batch',
                              evaluate_available=evaluate)
    return store, job['id']


def test_continue_is_durable_and_consumed_once(tmp_path):
    store, identifier = waiting_job(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: store.decide_round(identifier, round_index=1, action='continue'), range(2)))
    assert values[0] == values[1]
    reloaded = JobStore(tmp_path)
    assert reloaded.get(identifier)['round_decision']['action'] == 'continue'
    first = reloaded.consume_round_decision(identifier, round_index=1)
    assert first['action'] == 'continue' and first['status'] == 'consumed'
    assert reloaded.consume_round_decision(identifier, round_index=1) is None
    assert reloaded.get(identifier)['status'] == 'running'
    assert len([event for event in reloaded.events(identifier) if event['type'] == 'round_decided']) == 1


def test_conflicting_stale_or_unavailable_decisions_rejected(tmp_path):
    store, identifier = waiting_job(tmp_path, next_ids=[], evaluate=False)
    with pytest.raises(RuntimeError, match='available'):
        store.decide_round(identifier, round_index=1, action='continue')
    with pytest.raises(RuntimeError, match='available'):
        store.decide_round(identifier, round_index=1, action='evaluate')
    with pytest.raises(RuntimeError, match='stale'):
        store.decide_round(identifier, round_index=2, action='finish')
    store.decide_round(identifier, round_index=1, action='finish')
    with pytest.raises(RuntimeError, match='conflict'):
        store.decide_round(identifier, round_index=1, action='continue')
    with pytest.raises(ValueError):
        store.decide_round(identifier, round_index=True, action='finish')


def test_pause_resume_does_not_consume_round_decision(tmp_path):
    store, identifier = waiting_job(tmp_path)
    store.control(identifier, 'pause')
    store.control(identifier, 'resume')
    assert store.get(identifier)['status'] == 'waiting_round'
    assert store.consume_round_decision(identifier, round_index=1) is None
    assert store.get(identifier)['round_decision']['status'] == 'waiting'


def test_round_wait_has_finite_polling_timeout_without_spending_a_request(tmp_path):
    store, identifier = waiting_job(tmp_path)
    assert store.wait_round_decision(identifier, round_index=1, timeout=0.01) is None
    assert store.get(identifier)['records'] == []
    assert store.get(identifier)['status'] == 'waiting_round'


def test_stage_sequence_is_durable_and_separate_from_text_cursor(tmp_path):
    store = JobStore(tmp_path)
    job = store.create('workflow', {'transport': {'stream': True}})
    store.event(job['id'], {'type': 'stage', 'node_id': 'solver', 'state': 'running',
                            'round_index': 1, 'key': 'solve-q1', 'question_id': 'q1'})
    store.reserve(job['id'], 'wire-one', {})
    frame = store.append_stream(job['id'], 'wire-one', {'node_id': 'solver', 'round_index': 1,
                                'question_key': 'q1', 'operation_key': 'solve-q1'}, {'kind': 'chunk', 'data': 'partial'})
    store.event(job['id'], {'type': 'stage', 'node_id': 'solver', 'state': 'complete',
                            'round_index': 1, 'key': 'solve-q1', 'question_id': 'q1'})
    events = JobStore(tmp_path).events(job['id'])
    assert [value['sequence'] for value in events] == [1, 2, 3]
    assert len({value['event_id'] for value in events}) == 3
    assert events[1]['event_type'] == 'step_started'
    assert events[1]['stage_id'] == 'harness' and events[1]['step_id'] == 'solve'
    assert events[1]['item_id'] == 'q1' and events[1]['attempt_id'] == 'solve-q1'
    assert frame['seq'] == frame['stream_sequence'] == 1
    assert frame['run_id'] == job['id'] and frame['stage_id'] == 'harness'
    assert frame['attempt_id'] == 'wire-one'


def completion_fixture(tmp_path):
    manifest = {'config': {'max_rounds': 3}, 'round_questions': {'1': ['q1'], '2': ['q2'], '3': ['q3']}}
    write_json_atomic(tmp_path / 'manifest.json', manifest)
    write_json_atomic(tmp_path / 'rounds/1/result.json', _seal({'result': {'round': 1, 'status': 'complete', 'kb_after': 'kb1'}}))
    return manifest


def test_early_completion_is_sealed_and_manifest_stays_frozen(tmp_path):
    from architecture_iq.kb.completion import seal_learning_complete, require_learning_complete
    manifest = completion_fixture(tmp_path)
    with pytest.raises(RuntimeError, match='complete'):
        require_learning_complete(tmp_path, manifest, 1)
    receipt = seal_learning_complete(tmp_path, manifest, 1, reason='finish')
    require_learning_complete(tmp_path, manifest, 1)
    assert receipt['completed_rounds'] == 1 and receipt['reason'] == 'finish'
    assert json.loads((tmp_path / 'manifest.json').read_text())['config']['max_rounds'] == 3
    assert seal_learning_complete(tmp_path, manifest, 1, reason='finish') == receipt
    with pytest.raises(RuntimeError, match='immutable'):
        seal_learning_complete(tmp_path, manifest, 1, reason='evaluate')
    original = read_receipt(tmp_path / 'rounds/1/result.json')['result']
    write_json_atomic(tmp_path / 'rounds/1/result.json', _seal({'result': {**original, 'kb_after': 'other'}}))
    with pytest.raises(ValueError, match='round'):
        require_learning_complete(tmp_path, manifest, 1)


def test_completion_rejects_changed_manifest_or_extra_round(tmp_path):
    from architecture_iq.kb.completion import seal_learning_complete, require_learning_complete
    manifest = completion_fixture(tmp_path)
    seal_learning_complete(tmp_path, manifest, 1, reason='finish')
    with pytest.raises(ValueError, match='manifest'):
        require_learning_complete(tmp_path, {**manifest, 'changed': True}, 1)
    write_json_atomic(tmp_path / 'rounds/2/result.json', _seal({'result': {'round': 2, 'status': 'complete'}}))
    with pytest.raises(ValueError, match='round'):
        require_learning_complete(tmp_path, manifest, 1)


def workflow_fixture(tmp_path, monkeypatch, *, mode='manual', rounds=2, count=2, evaluate=False, threshold=None):
    import copy
    from architecture_iq.kb import cli
    from architecture_iq.kb.store import canonical_hash
    from architecture_iq.studio import execution
    from test_studio_execution import fixture_config
    from test_studio_workflow import default_workflow, enable_optional, inputs, Client
    spec = default_workflow("scientific")
    spec['settings'].update(loop_mode=mode, max_rounds=rounds)
    if threshold is not None:
        spec['settings']['stop_after_no_change_rounds'] = threshold
    if evaluate:
        enable_optional(spec, 'evaluate', 'loop', 'end', 'done')
    _, questions, private, _ = inputs()
    for index in range(2, count + 1):
        q = copy.deepcopy(questions[0]); q.update(id=f'q{index}', dataset_id=f'd{index}', lineage_id=f'l{index}')
        questions.append(q); private[q['id']] = copy.deepcopy(private['q1'])
    if evaluate:
        q = copy.deepcopy(questions[0]); q.update(id='heldout', dataset_id='heldout-d', lineage_id='heldout-l', split='final')
        questions.append(q); private[q['id']] = copy.deepcopy(private['q1'])
    config = fixture_config(); config['workflow'] = spec
    lock = tmp_path / 'runtime.json'; lock.write_text('{}')
    config['models'][0].update(runtime_lock_path=str(lock), runtime_fingerprint=canonical_hash({}))
    config['question_set'].update(questions=questions, feedback=private)
    monkeypatch.setattr(cli, 'read_runtime_lock', lambda *a, **k: None)
    monkeypatch.setattr(cli, 'verify_live_runtime', lambda *a, **k: None)
    client = Client()
    monkeypatch.setattr(execution, 'create_client', lambda *a, **k: client)
    store = JobStore(tmp_path / 'studio'); job = store.create('workflow', config)
    return execution, store, job['id'], config, client


def await_waiting(store, identifier, future):
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if future.done():
            future.result()  # Surface worker errors instead of a timeout.
            pytest.fail('worker completed without a round decision')
        job = store.get(identifier)
        if job['status'] == 'waiting_round':
            return job
        time.sleep(0.01)
    pytest.fail('worker did not reach sealed round boundary')


def test_manual_wait_is_outside_round_and_continue_schedules_only_frozen_next_batch(tmp_path, monkeypatch):
    import fcntl
    execution, store, identifier, config, client = workflow_fixture(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execution.execute_workflow, store, identifier, config)
        try:
            first = await_waiting(store, identifier, future)
            output = store.directory(identifier) / 'workflow'
            assert read_receipt(output / 'rounds/1/result.json')['result']['status'] == 'complete'
            with (output / 'workflow.lock').open('a+') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
            assert not (output / 'rounds/2/start.json').exists()
            assert first['round_decision']['next_question_ids'] == ['q2']
            calls = len(client.prompts)
            store.decide_round(identifier, round_index=1, action='continue')
            store.decide_round(identifier, round_index=1, action='continue')
            # Wait for round 2, not the first still-visible consumed boundary.
            import time
            deadline = time.monotonic() + 5
            while store.get(identifier).get('round_decision_index') != 2 and time.monotonic() < deadline:
                if future.done(): future.result()
                time.sleep(0.01)
            second = store.get(identifier)
            assert second['round_decision']['round_index'] == 2
            assert second['round_decision']['available_actions'] == ['finish']
            assert len(client.prompts) == calls * 2
            with pytest.raises(RuntimeError, match='stale'):
                store.decide_round(identifier, round_index=1, action='continue')
            store.decide_round(identifier, round_index=2, action='finish')
            result = future.result(timeout=5)
            assert len(result['rounds']) == 2 and result['evaluation'] is None
            assert result['learning_completion']['reason'] == 'finish'
        finally:
            # Keep failing tests from leaving a blocked executor behind.
            current = store.get(identifier)
            if not future.done() and current.get('round_decision', {}).get('status') == 'waiting':
                store.decide_round(identifier, round_index=current['round_decision_index'], action='finish')


def test_manual_early_evaluate_uses_completion_and_preserves_cap(tmp_path, monkeypatch):
    execution, store, identifier, config, _ = workflow_fixture(tmp_path, monkeypatch, rounds=3, count=3, evaluate=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execution.execute_workflow, store, identifier, config)
        job = await_waiting(store, identifier, future)
        assert 'evaluate' in job['round_decision']['available_actions']
        store.decide_round(identifier, round_index=1, action='evaluate')
        result = future.result(timeout=5)
    assert len(result['rounds']) == 1 and result['evaluation']['scores']['current']['correct'] == 1
    output = store.directory(identifier) / 'workflow'
    assert json.loads((output / 'manifest.json').read_text())['config']['max_rounds'] == 3
    assert result['learning_completion']['reason'] == 'evaluate'
    assert not (output / 'rounds/2/start.json').exists()


@pytest.mark.parametrize('count,threshold,reason', [(1, None, 'no_next_batch'), (3, 1, 'no_change')])
def test_automatic_stops_at_frozen_input_or_no_change(tmp_path, monkeypatch, count, threshold, reason):
    execution, store, identifier, config, _ = workflow_fixture(tmp_path, monkeypatch, mode='automatic', rounds=3,
                                                               count=3, threshold=threshold)
    if count == 1:
        from architecture_iq.kb import orchestrator
        original_prepare = orchestrator.prepare_run
        def frozen_exhausted(*args, **kwargs):
            manifest = original_prepare(*args, **kwargs)
            manifest['round_questions']['2'] = []
            manifest['round_questions']['3'] = []
            write_json_atomic(args[0] / 'manifest.json', manifest)
            return manifest
        monkeypatch.setattr(orchestrator, 'prepare_run', frozen_exhausted)
    result = execution.execute_workflow(store, identifier, config)
    assert len(result['rounds']) == 1 and result['learning_completion']['reason'] == reason
    assert not any(event['type'] == 'round_waiting' for event in store.events(identifier))
    assert not (store.directory(identifier) / 'workflow/rounds/2/start.json').exists()


def test_pause_at_waiting_boundary_restores_waiting_without_continuing(tmp_path):
    import time
    store, identifier = waiting_job(tmp_path)
    store.control(identifier, 'pause')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(store.boundary, identifier)
        deadline = time.monotonic() + 3
        while store.get(identifier)['status'] != 'paused' and time.monotonic() < deadline:
            time.sleep(0.01)
        assert store.get(identifier)['status'] == 'paused'
        store.control(identifier, 'resume')
        future.result(timeout=3)
    assert store.get(identifier)['status'] == 'waiting_round'
    assert store.get(identifier)['round_decision']['status'] == 'waiting'


def test_null_stream_metadata_still_uses_canonical_step_and_explicit_recipe_override(tmp_path):
    store = JobStore(tmp_path); job = store.create('workflow', {})
    store.reserve(job['id'], 'wire', {})
    frame = store.append_stream(job['id'], 'wire', {'node_id': 'discoverer', 'step_id': 'experience_consolidate',
                                                 'stage_id': None, 'round_index': 1}, {'kind': 'done'})
    assert frame['stage_id'] == 'harness' and frame['step_id'] == 'experience_consolidate'


def test_legacy_events_remain_readable_and_new_stage_ids_never_reuse_sequence(tmp_path):
    store = JobStore(tmp_path); job = store.create('workflow', {})
    path = store.directory(job['id']) / 'events.jsonl'
    path.write_text('{"type":"stage","node_id":"solver","state":"complete"}\n')
    store.event(job['id'], {'type': 'round_waiting', 'node_id': 'loop', 'round_index': 1})
    events = store.events(job['id'])
    assert 'sequence' not in events[0]
    assert events[1]['sequence'] == 2 and events[1]['event_id'].endswith(':stage:2')


def test_malformed_action_is_rejected_and_dead_waiter_cannot_be_resumed(tmp_path):
    store, identifier = waiting_job(tmp_path)
    with pytest.raises(ValueError):
        store.decide_round(identifier, round_index=1, action=[])
    store.update(identifier, pid=2147483647)
    assert store.get(identifier)['status'] == 'interrupted'
    with pytest.raises(RuntimeError, match='waiting'):
        store.decide_round(identifier, round_index=1, action='finish')
    with pytest.raises(ValueError):
        store.control(identifier, 'resume')


def test_frozen_recipe_mismatch_blocks_before_model_or_round(tmp_path, monkeypatch):
    execution, store, identifier, config, client = workflow_fixture(tmp_path, monkeypatch)
    from architecture_iq.studio.workflow import compile_workflow
    config['method'] = {**compile_workflow(config['workflow'])['method'], 'description': 'changed'}
    with pytest.raises(ValueError, match='recipe'):
        execution.execute_workflow(store, identifier, config)
    assert client.prompts == []
    assert not (store.directory(identifier) / 'workflow/manifest.json').exists()


def test_completion_rejects_kb_changed_after_terminal_seal(tmp_path):
    from architecture_iq.kb.completion import seal_learning_complete, require_learning_complete
    from architecture_iq.kb.store import KBStore
    manifest = completion_fixture(tmp_path)
    store = KBStore(tmp_path / 'kb'); initial = store.initialize([{'id': 'legacy', 'text': 'old hypothesis'}])
    write_json_atomic(tmp_path / 'rounds/1/result.json', _seal({'result': {'round': 1, 'status': 'complete', 'kb_after': initial['version']}}))
    seal_learning_complete(tmp_path, manifest, 1, reason='finish')
    store.apply_patch({'parent_version': initial['version'], 'operations': [{'op': 'retire', 'id': 'legacy', 'reason': 'obsolete'}]}, [])
    with pytest.raises(ValueError, match='KB'):
        require_learning_complete(tmp_path, manifest, 1)


def test_completion_binds_empirical_memory_version(tmp_path):
    from architecture_iq.kb.completion import seal_learning_complete, require_learning_complete
    from architecture_iq.kb.experience import ExperienceStore
    manifest = completion_fixture(tmp_path)
    memory = ExperienceStore(tmp_path / 'experience'); initial = memory.initialize()
    result = {'round': 1, 'status': 'complete', 'kb_after': 'kb1', 'experience': {'after': initial['version']}}
    write_json_atomic(tmp_path / 'rounds/1/result.json', _seal({'result': result}))
    seal_learning_complete(tmp_path, manifest, 1, reason='finish')
    memory.publish(initial['version'], [], [])
    with pytest.raises(ValueError, match='experience'):
        require_learning_complete(tmp_path, manifest, 1)
