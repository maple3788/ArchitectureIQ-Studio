"""One-time reference registration; legacy snapshots and sources stay untouched."""
from contextlib import closing
import json
from uuid import uuid4

from .catalog import Catalog, _hash, _now
from .datasets import DatasetStore
from .pairs import pair_manifest


def migrate_legacy_datasets(catalog: Catalog, datasets: DatasetStore) -> dict:
    report = {'created': [], 'skipped': [], 'errors': []}
    with closing(catalog._connect()) as conn, conn:
        conn.execute('CREATE TABLE IF NOT EXISTS collection_origins (origin TEXT PRIMARY KEY, collection_id TEXT NOT NULL)')
        # Enumerate metadata first so one unreadable origin cannot stop startup.
        origins = [('set', row['id'], dict(row)) for row in conn.execute(
            'SELECT id,name FROM question_sets ORDER BY created_at DESC,id').fetchall()]
        origins += [('source', row['id'], dict(row)) for row in conn.execute(
            'SELECT id,name,report FROM sources ORDER BY imported_at,id').fetchall()]
    for kind, identifier, row in origins:
        origin = _hash({'kind': kind, 'id': identifier})
        try:
            with closing(catalog._connect()) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                prior = conn.execute('SELECT collection_id FROM collection_origins WHERE origin=?', (origin,)).fetchone()
                if prior:
                    report['skipped'].append(prior['collection_id'])
                    continue
                snapshot = catalog.get_question_set(identifier) if kind == 'set' else None
                source_report = json.loads(row['report']) if kind == 'source' else {}
                if not isinstance(source_report, dict):
                    raise ValueError('Invalid source report')
                keys = snapshot['keys'] if snapshot else list(dict.fromkeys(
                    e['key'] for e in source_report.get('entries', []) if e.get('key')))
                # A migration never silently loses a member. Broken origins remain retryable.
                for key in keys:
                    catalog._load_frozen_record(key)
                if snapshot and snapshot.get('selection_mode') == 'pairs':
                    pairs = snapshot['pairs']
                    for pair in pairs:
                        checked = pair_manifest([catalog.get_question(m['key']) for m in pair['members']])
                        if checked['pair_key'] != pair['pair_key']:
                            raise ValueError('Frozen pair identity changed')
                    members = {'selection_mode': 'pairs', 'keys': keys, 'pairs': pairs}
                else:
                    members = datasets._members(keys=keys)
                body = {'collection_id': 'ds_' + uuid4().hex, 'parent_revision': None,
                        'name': row.get('name') or identifier, 'description': 'Imported from existing ' + kind,
                        'archived': False, 'created_at': _now(), **members}
                result = datasets._save(conn, body)
                conn.execute('INSERT INTO collection_origins VALUES (?,?)', (origin, result['collection_id']))
                report['created'].append(result['collection_id'])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            report['errors'].append({'kind': kind, 'id': identifier, 'message': str(exc)})
    return report
