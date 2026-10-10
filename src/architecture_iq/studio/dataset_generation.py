"""Attach only already-persisted generation results; never launch or resume GT."""
from pathlib import Path
import sqlite3

from .catalog import _hash, _read
from .datasets import DatasetArchived, DatasetConflict, DatasetStore
from .pairs import pair_manifest


def validate_target_ref(target):
    if (not isinstance(target, dict) or set(target) != {'collection_id', 'revision'}
            or any(not isinstance(v, str) or not v for v in target.values())):
        raise ValueError('dataset_target requires collection_id and revision')
    return dict(target)


def validate_generation_target(config: dict, datasets: DatasetStore) -> str | None:
    if 'dataset_target' not in config:
        return None
    target = validate_target_ref(config['dataset_target'])
    current = datasets.get(target['collection_id'])
    if current['archived']:
        raise DatasetArchived('Target Dataset is archived')
    if current['revision'] != target['revision']:
        raise DatasetConflict(current_revision=current['revision'])
    if current['keys'] and (config['mode'] == 'paired') != (current['selection_mode'] == 'pairs'):
        raise ValueError('Generation mode does not match target Dataset')
    return _hash({'config': config, 'target': target})


def get_generation_attachment(datasets, *, run_id: str) -> dict | None:
    return datasets.attachment(run_id)


def _completed_keys(store, catalog, run_id):
    definition = store.definition(run_id)
    if definition['kind'] != 'generation':
        raise ValueError('Only generation runs have generated questions')
    directory = store.directory(run_id).resolve()
    generated = (directory / 'generated').resolve()
    if not directory.is_relative_to(store.root.resolve()) or not generated.is_relative_to(directory):
        raise ValueError('Generation path escapes run directory')
    manifest = _read(generated / 'generation_manifest.json', generated)
    if manifest.get('status') not in ('complete', 'partial', 'insufficient', 'import_failed'):
        raise ValueError('Generation manifest has no sealed result')
    config = manifest['config']
    if manifest['result'].get('preflight') != config or any(config.get(k) != v for k, v in definition['config'].items()):
        raise ValueError('Generation result does not match its frozen configuration')
    report = manifest['result'].get('import_report')
    if not report:
        return [], []
    source = next((s for s in catalog.list_sources() if s['id'] == report.get('source_id')), None)
    if (not source or source['hash'] != report.get('source_hash')
            or Path(source['path']).resolve() != (generated / 'datasets').resolve()):
        raise ValueError('Generation result does not match its registered source')
    records = []
    for entry in report.get('entries', []):
        if entry.get('status') not in ('added', 'duplicate', 'conflict') or entry.get('blocked') or not entry.get('key'):
            continue
        record = catalog.get_question(entry['key'])
        aliases = [s for s in record['sources'] if s['source_id'] == source['id']]
        if record['metadata']['ready'] and any(not a['blocked'] for a in aliases):
            records.append(record)
    records = list({r['metadata']['key']: r for r in records}.values())
    if config['mode'] != 'paired':
        return [r['metadata']['key'] for r in records], []
    grouped = {}
    for record in records:
        if record['metadata'].get('pair_id'):
            grouped.setdefault(record['metadata']['pair_id'], []).append(record)
    pairs = [pair_manifest(group) for group in grouped.values()]
    pairs = [p for p in pairs if p['ready'] and len(p['members']) == 2]
    return [m['key'] for p in pairs for m in p['members']], pairs


def attach_generation_result(store, catalog, datasets, *, run_id: str, target: dict, operation_id: str) -> dict:
    target = validate_target_ref(target)
    store.definition(run_id)  # Verify the run even when returning an idempotency receipt.
    prior = datasets.attachment(run_id, operation_id=operation_id, target=target)
    if prior is not None:
        return prior
    try:
        keys, pairs = _completed_keys(store, catalog, run_id)
    except (OSError, ValueError, KeyError, TypeError):
        result = datasets.record_attachment(run_id, operation_id, target, status='unavailable',
            message='持久化生成结果尚不可用或完整性校验失败；不会重新执行生成')
    else:
        result = datasets.attach(target['collection_id'], expected_revision=target['revision'], keys=keys, pairs=pairs,
                                 run_id=run_id, operation_id=operation_id)
    store.event(run_id, {'type': 'dataset_attachment', 'attachment': result})
    return result


def finish_generation_attachment(store, catalog, run_id, config, result):
    if 'dataset_target' not in config:
        return
    try:
        result['dataset_attachment'] = attach_generation_result(store, catalog, DatasetStore(catalog),
            run_id=run_id, target=config['dataset_target'], operation_id='automatic')
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        # The canonical generation result is already sealed. Its success must survive
        # a separate collection-write failure; the endpoint can retry attachment later.
        store.event(run_id, {'type': 'dataset_attachment_error', 'message': str(exc)})
