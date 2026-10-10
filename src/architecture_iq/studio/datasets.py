"""Named question collections, immutable revisions and atomic optimistic writes."""
from contextlib import closing
import json
from uuid import uuid4

from .catalog import Catalog, _hash, _json, _now
from .question_bank import matches, question_summary, validate_filters, validate_page
from .question_equivalence import equivalence_id


class DatasetConflict(RuntimeError):
    def __init__(self, message='Dataset revision changed', current_revision=None):
        super().__init__(message)
        self.current_revision = current_revision


class DatasetArchived(RuntimeError):
    pass


class DatasetStore:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        with closing(catalog._connect()) as conn, conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS collections (id TEXT PRIMARY KEY, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_revisions
                    (collection_id TEXT NOT NULL, revision TEXT NOT NULL, body TEXT NOT NULL,
                     PRIMARY KEY(collection_id, revision));
                CREATE TABLE IF NOT EXISTS collection_operations
                    (scope TEXT NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                     result TEXT NOT NULL, PRIMARY KEY(scope, operation_id));
            ''')

    def _operation(self, conn, scope, operation_id, request):
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 256:
            raise ValueError('A nonempty Idempotency-Key of at most 256 characters is required')
        row = conn.execute('SELECT request_hash,result FROM collection_operations WHERE scope=? AND operation_id=?',
                           (scope, operation_id)).fetchone()
        if row:
            if row['request_hash'] != _hash(request):
                raise DatasetConflict('Idempotency-Key already used with a different request')
            return json.loads(row['result'])
        return None

    @staticmethod
    def _receipt(conn, scope, operation_id, request, result):
        conn.execute('INSERT INTO collection_operations VALUES (?,?,?,?)',
                     (scope, operation_id, _hash(request), _json(result)))

    @staticmethod
    def _get(conn, collection_id, revision=None):
        if revision is None:
            row = conn.execute('SELECT revision FROM collections WHERE id=?', (collection_id,)).fetchone()
            if row is None:
                raise KeyError(f'Unknown Dataset: {collection_id}')
            revision = row['revision']
        row = conn.execute('SELECT body FROM collection_revisions WHERE collection_id=? AND revision=?',
                           (collection_id, revision)).fetchone()
        if row is None:
            raise KeyError('Unknown Dataset revision')
        body = json.loads(row['body'])
        if _hash(body) != revision or body['collection_id'] != collection_id:
            raise ValueError('Dataset revision integrity check failed')
        return {**body, 'revision': revision}

    def get(self, collection_id: str, revision: str | None = None) -> dict:
        with closing(self.catalog._connect()) as conn:
            return self._get(conn, collection_id, revision)

    @staticmethod
    def _save(conn, body):
        revision = _hash(body)
        conn.execute('INSERT INTO collection_revisions VALUES (?,?,?)',
                     (body['collection_id'], revision, _json(body)))
        conn.execute('INSERT INTO collections VALUES (?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision',
                     (body['collection_id'], revision))
        return {**body, 'revision': revision}

    def _keys(self, keys):
        if not isinstance(keys, list) or any(not isinstance(k, str) for k in keys):
            raise ValueError('keys must be an ordered list of question references')
        selected, seen = [], set()
        for key in keys:
            # Allow incomplete or temporarily broken records, but never unknown keys.
            question_summary(self.catalog, key)
            try:
                identity = equivalence_id(self.catalog._load_frozen_record(key), question_key=key)
            except (OSError, ValueError, KeyError, TypeError):
                identity = key
            if identity not in seen:
                selected.append(key)
                seen.add(identity)
        return selected

    def _members(self, keys=None, pair_keys=None):
        if keys is not None and pair_keys is not None:
            raise ValueError('keys and pair_keys are mutually exclusive')
        if pair_keys is None:
            return {'selection_mode': 'single', 'keys': self._keys([] if keys is None else keys), 'pairs': []}
        if not isinstance(pair_keys, list) or any(not isinstance(k, str) for k in pair_keys):
            raise ValueError('pair_keys must be an ordered list')
        pairs, members = [], []
        for key in dict.fromkeys(pair_keys):
            pair = self.catalog.get_question_pair(key)
            if len(pair['members']) != 2 or {m['role'] for m in pair['members']} != {'original', 'counterfactual'}:
                raise ValueError('Dataset requires complete, unambiguous question pairs')
            pairs.append(pair)
            members.extend(m['key'] for m in pair['members'])
        if len(set(members)) != len(members):
            raise ValueError('Question occurs in multiple pairs')
        return {'selection_mode': 'pairs', 'keys': members, 'pairs': pairs}

    @staticmethod
    def _labels(name, description):
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str):
            raise ValueError('Dataset requires a nonempty name and a text description')
        return {'name': name.strip(), 'description': description.strip()}

    def create(self, *, name: str, description: str = '', keys: list[str] | None = None,
               pair_keys: list[str] | None = None, operation_id: str) -> dict:
        request = {'name': name, 'description': description, 'keys': keys, 'pair_keys': pair_keys}
        with closing(self.catalog._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = self._operation(conn, 'create', operation_id, request)
            if prior is not None:
                return prior
            body = {'collection_id': 'ds_' + uuid4().hex, 'parent_revision': None,
                    **self._labels(name, description), **self._members(keys, pair_keys),
                    'archived': False, 'created_at': _now()}
            result = self._save(conn, body)
            self._receipt(conn, 'create', operation_id, request, result)
            return result

    def revise(self, collection_id: str, *, expected_revision: str, changes: dict, operation_id: str) -> dict:
        if not isinstance(changes, dict) or set(changes) - {'name', 'description', 'archived', 'keys', 'pair_keys'}:
            raise ValueError('Unknown Dataset revision fields')
        if 'archived' in changes and type(changes['archived']) is not bool:
            raise ValueError('archived must be boolean')
        request = {'expected_revision': expected_revision, 'changes': changes}
        with closing(self.catalog._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = self._operation(conn, collection_id, operation_id, request)
            if prior is not None:
                return prior
            current = self._get(conn, collection_id)
            if current['revision'] != expected_revision:
                raise DatasetConflict(current_revision=current['revision'])
            if current['archived'] and changes != {'archived': False}:
                raise DatasetArchived('Dataset is archived')
            body = {k: v for k, v in current.items() if k != 'revision'}
            body.update(self._labels(changes.get('name', current['name']), changes.get('description', current['description'])))
            if 'keys' in changes or 'pair_keys' in changes:
                if any(changes[k] is None for k in ('keys', 'pair_keys') if k in changes):
                    raise ValueError('Member lists cannot be null')
                body.update(self._members(changes.get('keys'), changes.get('pair_keys')))
            body['archived'] = changes.get('archived', current['archived'])
            if all(body[k] == current[k] for k in body):
                result = current
            else:
                body.update(parent_revision=expected_revision, created_at=_now())
                result = self._save(conn, body)
            self._receipt(conn, collection_id, operation_id, request, result)
            return result

    def _summary(self, record):
        families = sorted({question_summary(self.catalog, key)[0].get('family', '') for key in record['keys']} - {''})
        return {k: record[k] for k in ('collection_id', 'revision', 'name', 'description', 'archived', 'selection_mode')} | {
            'count': len(record['keys']), 'pair_count': len(record['pairs']), 'families': families,
            'updated_at': record['created_at']}

    def list(self, *, search: str = '', family: str = '', archived: bool = False, offset: int = 0, limit: int = 25) -> dict:
        validate_page(offset, limit)
        with closing(self.catalog._connect()) as conn:
            records = [self._get(conn, row['id']) for row in conn.execute('SELECT id FROM collections ORDER BY id').fetchall()]
        items = [self._summary(r) for r in records if r['archived'] == archived
                 and search.casefold() in (r['name'] + ' ' + r['description']).casefold()]
        items = [r for r in items if not family or family in r['families']]
        items.sort(key=lambda r: (r['name'].casefold(), r['collection_id']))
        return {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit}

    def list_members(self, ref: dict, *, filters: dict | None = None, offset: int = 0, limit: int = 25) -> dict:
        validate_page(offset, limit)
        filters = validate_filters(filters)
        revision = self.get(ref['collection_id'], ref['revision'])
        items = [question_summary(self.catalog, key)[0] for key in revision['keys']]
        items = [item for item in items if matches(item, filters)]
        return {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit}

    def memberships(self, keys: list[str]) -> dict[str, list[dict]]:
        result = {key: [] for key in keys}
        with closing(self.catalog._connect()) as conn:
            records = [self._get(conn, row['id']) for row in conn.execute('SELECT id FROM collections ORDER BY id').fetchall()]
        for record in records:
            shared = set(keys).intersection(record['keys'])
            if shared:
                summary = self._summary(record)
                for key in shared:
                    result[key].append(summary)
        return result
