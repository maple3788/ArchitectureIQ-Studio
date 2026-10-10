import json

import pytest

from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.datasets import DatasetStore
from architecture_iq.studio.jobs import JobStore
from architecture_iq.studio.generation import validate_generation
from test_studio_generation import config
from test_studio_catalog import baked, bakefile
from test_studio_dataset_inputs import ref


def staged_result(tmp_path, *, empty=False, blocked=False):
    c, store = Catalog(tmp_path / 'state'), JobStore(tmp_path / 'state')
    s = DatasetStore(c)
    target = ref(s.create(name='Target', operation_id='target'))
    normalized = validate_generation(config())
    job = store.create('generation', normalized)
    generated = store.directory(job['id']) / 'generated'
    generated.mkdir()
    report = None
    if not empty:
        source = generated / 'datasets'
        bakefile(source / 'questions.json', [baked('q1')])
        report = c.import_source(source)
        if blocked:
            with c._connect() as conn:
                conn.execute('UPDATE aliases SET blocked=1 WHERE source_id=?', (report['source_id'],))
    result = {'preflight': normalized, 'import_report': report}
    manifest = generated / 'generation_manifest.json'
    manifest.write_text(json.dumps({'config': normalized, 'status': 'insufficient' if empty else 'complete', 'result': result}))
    return c, store, s, target, job, report, manifest


def test_attachment_recovers_after_import_without_reexecuting_or_rewriting(tmp_path, monkeypatch):
    from architecture_iq.studio.dataset_generation import attach_generation_result, get_generation_attachment
    c, store, s, target, job, report, manifest = staged_result(tmp_path)
    original = manifest.read_bytes()
    from architecture_iq.studio import generation
    monkeypatch.setattr(generation, 'execute_generation', lambda *a, **k: pytest.fail('must not regenerate'))
    monkeypatch.setattr(store, 'launch', lambda *a: pytest.fail('must not launch'))
    newer = baked('q1'); newer['detail']['prompt'] += ' new'
    c.import_source(bakefile(tmp_path / 'newer.json', [newer]))
    first = attach_generation_result(store, c, s, run_id=job['id'], target=target, operation_id='attach')
    second = attach_generation_result(store, c, s, run_id=job['id'], target=target, operation_id='attach')
    assert first == second and first['status'] == 'attached'
    assert s.get(target['collection_id'])['keys'] == [report['entries'][0]['key']]
    assert manifest.read_bytes() == original
    assert get_generation_attachment(s, run_id=job['id']) == first
    with pytest.raises(RuntimeError):
        attach_generation_result(store, c, s, run_id=job['id'], target={**target, 'revision': 'other'}, operation_id='attach')


@pytest.mark.parametrize('change,expected', [({'name': 'edited'}, 'revision_conflict'), ({'archived': True}, 'archived')])
def test_changed_target_preserves_generated_results(tmp_path, change, expected):
    from architecture_iq.studio.dataset_generation import attach_generation_result
    c, store, s, target, job, report, _ = staged_result(tmp_path)
    latest = s.revise(target['collection_id'], expected_revision=target['revision'], changes=change, operation_id='edit')
    result = attach_generation_result(store, c, s, run_id=job['id'], target=target, operation_id='attach')
    assert result['status'] == expected
    assert s.get(target['collection_id']) == latest
    assert c.get_question(report['entries'][0]['key'])['metadata']['ready']
    if expected == 'revision_conflict':
        retried = attach_generation_result(store, c, s, run_id=job['id'], target=ref(latest), operation_id='retry')
        assert retried['status'] == 'attached'


@pytest.mark.parametrize('empty,blocked', [(True, False), (False, True)])
def test_no_successful_available_questions_does_not_change_dataset(tmp_path, empty, blocked):
    from architecture_iq.studio.dataset_generation import attach_generation_result
    c, store, s, target, job, _, _ = staged_result(tmp_path, empty=empty, blocked=blocked)
    result = attach_generation_result(store, c, s, run_id=job['id'], target=target, operation_id='attach')
    assert result['status'] == 'empty'
    assert s.get(target['collection_id'])['revision'] == target['revision']


def test_incomplete_or_unrelated_manifest_is_not_a_generation_resume(tmp_path):
    from architecture_iq.studio.dataset_generation import attach_generation_result
    c, store, s, target, job, _, manifest = staged_result(tmp_path)
    value = json.loads(manifest.read_text()); value['status'] = 'running'
    manifest.write_text(json.dumps(value))
    result = attach_generation_result(store, c, s, run_id=job['id'], target=target, operation_id='attach')
    assert result['status'] == 'unavailable'


def test_target_bound_preflight_changes_without_changing_canonical_plan(tmp_path):
    from architecture_iq.studio.dataset_generation import validate_generation_target
    c, _, s, target, _, _, _ = staged_result(tmp_path)
    base = validate_generation(config())
    targeted = validate_generation(config(dataset_target=target))
    assert {k: v for k, v in targeted.items() if k != 'dataset_target'} == base
    first = validate_generation_target(targeted, s)
    other = ref(s.create(name='Other', operation_id='other'))
    assert first != validate_generation_target(validate_generation(config(dataset_target=other)), s)
    s.revise(target['collection_id'], expected_revision=target['revision'], changes={'name': 'edit'}, operation_id='edit')
    with pytest.raises(RuntimeError): validate_generation_target(targeted, s)


@pytest.mark.parametrize('mode', ['single', 'paired'])
def test_canonical_mocked_generation_attaches_after_persisting_manifest(tmp_path, monkeypatch, mode):
    from architecture_iq.candidates import sets
    from architecture_iq.studio import pair_generation
    from architecture_iq.studio.generation import execute_generation
    from test_studio_pair_generation import request
    c, store = Catalog(tmp_path / 'state'), JobStore(tmp_path / 'state')
    s = DatasetStore(c)
    target = ref(s.create(name='Target', operation_id='target'))
    calls = []
    def gt(candidate, profile, dataset):
        spec = json.loads((candidate / 'candidate_spec.json').read_text())
        # Same rank on both sides, distinct outcomes within each candidate set.
        mean = (len(calls) % 3 + 1) * 0.1
        calls.append(str(candidate))
        (candidate / 'results').mkdir(exist_ok=True)
        (candidate / 'results' / 'summary.json').write_text(json.dumps({
            'candidate_id': spec['candidate_id'], 'mean_test_mse': mean, 'std_test_mse': 0,
            'seed_results': [{'seed': 0, 'final_test_mse': mean, 'failed': False}],
            'excluded': False, 'failed_seeds': 0}))
    monkeypatch.setattr(sets, 'run_ground_truth', gt)
    monkeypatch.setattr(pair_generation, 'run_ground_truth', gt)
    configured = validate_generation((config if mode == 'single' else request)(dataset_target=target))
    job = store.create('generation', configured)
    result = execute_generation(store, job['id'], configured, c)
    assert result['outcome'] == 'complete'
    assert result['dataset_attachment']['status'] == 'attached'
    attached = s.get(target['collection_id'])
    assert len(attached['keys']) == (1 if mode == 'single' else 2)
    assert len(attached['pairs']) == (0 if mode == 'single' else 1)
    assert len(calls) == (3 if mode == 'single' else 6)


def test_attachment_database_failure_does_not_reclassify_sealed_generation(tmp_path, monkeypatch):
    import sqlite3
    from architecture_iq.studio.dataset_generation import finish_generation_attachment
    c, store, s, target, job, _, manifest = staged_result(tmp_path)
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError('database temporarily unavailable')
    monkeypatch.setattr(DatasetStore, 'attach', broken)
    result = {'outcome': 'complete'}
    finish_generation_attachment(store, c, job['id'], {'dataset_target': target}, result)
    assert result['outcome'] == 'complete' and manifest.exists()
    assert any(e['type'] == 'dataset_attachment_error' for e in store.events(job['id']))
