"""Rebuildable exact-equivalence index with freshly checked source health."""
from contextlib import closing
import json

from .catalog import Catalog, _hash, _public_question, rag_ready
from .question_equivalence import STRATEGY, equivalence_id


def validate_page(offset: int, limit: int) -> None:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('offset must be nonnegative and limit must be between 1 and 1000')


def validate_filters(filters: dict | None) -> dict:
    filters = {} if filters is None else filters
    if not isinstance(filters, dict) or set(filters) - {'search', 'family', 'type', 'split'}:
        raise ValueError('Unknown question filters')
    if any(not isinstance(value, str) for value in filters.values()):
        raise ValueError('Question filters must be strings')
    if filters.get('split', '') not in ('', 'discovery', 'development', 'final'):
        raise ValueError('Invalid split')
    return filters


def matches(summary: dict, filters: dict) -> bool:
    if any(value and summary.get(name) != value for name, value in filters.items() if name != 'search'):
        return False
    term = filters.get('search', '').casefold()
    return not term or term in ' '.join(str(summary.get(k, '')) for k in
                                       ('id', 'key', 'family', 'type', 'prompt')).casefold()


def _indexed_question(catalog: Catalog, key: str, row=None) -> dict:
    if row is None:
        with closing(catalog._connect()) as conn:
            row = conn.execute('SELECT hash,summary FROM questions WHERE key=?', (key,)).fetchone()
    if row is None:
        raise KeyError(f'Unknown question revision: {key}')
    path = catalog.root / 'records' / (row['hash'] + '.json')
    try:
        if not path.resolve().is_relative_to(catalog.root):
            raise ValueError('Question record is outside the catalog')
        stat = path.stat()
        fingerprint = (row['hash'], stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except (OSError, ValueError):
        fingerprint = (row['hash'], None)
    cached = catalog._data_index_cache.get(key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    try:
        if fingerprint[-1] is None:
            raise ValueError('Question record is unavailable')
        record = catalog._load_frozen_record(key)
        public = _public_question(record['public'])
        summary = {**record['metadata'], 'prompt': public['prompt'], 'rag_ready': rag_ready(public)}
        entry = {'summary': summary, 'identity': equivalence_id(record, question_key=key), 'status': 'verified'}
        after = path.stat()
        if fingerprint != (row['hash'], after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Question record changed during indexing')
    except (ValueError, KeyError, OSError, TypeError):
        summary = json.loads(row['summary'])
        summary.update(ready=False, evaluation_ready=False, kb_ready=False, rag_ready=False,
                       issues=['Stored question is missing or failed integrity verification'])
        entry = {'summary': summary, 'identity': STRATEGY + ':unavailable:' + _hash(key), 'status': 'unavailable'}
    # Cache only the public summary and opaque identity, never the private record.
    # File changes invalidate this process-local cache; source health is read below.
    if len(catalog._data_index_cache) >= 4096 and key not in catalog._data_index_cache:
        catalog._data_index_cache.pop(next(iter(catalog._data_index_cache)), None)
    catalog._data_index_cache[key] = (fingerprint, entry)
    return entry


def question_summary(catalog: Catalog, key: str) -> tuple[dict, list[dict]]:
    entry = _indexed_question(catalog, key)
    summary = {**entry['summary']}
    with closing(catalog._connect()) as conn:
        aliases = conn.execute('SELECT source_id,origin,issues,blocked FROM aliases WHERE key=? ORDER BY source_id,origin',
                               (key,)).fetchall()
    summary['source_count'] = len({a['source_id'] for a in aliases})
    summary = catalog._source_state(summary, aliases)
    return summary, [{**dict(a), 'issues': json.loads(a['issues'])} for a in aliases]


class QuestionBank:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        with closing(catalog._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS question_equivalence
                (key TEXT PRIMARY KEY, hash TEXT NOT NULL, strategy TEXT NOT NULL,
                 equivalence_id TEXT NOT NULL, status TEXT NOT NULL)''')

    def refresh(self) -> dict:
        with closing(self.catalog._connect()) as conn:
            rows = conn.execute('SELECT key,hash,summary FROM questions ORDER BY key').fetchall()
        entries = []
        for row in rows:
            indexed = _indexed_question(self.catalog, row['key'], row)
            entries.append((row['key'], row['hash'], STRATEGY, indexed['identity'], indexed['status']))
        with closing(self.catalog._connect()) as conn, conn:
            conn.executemany('INSERT OR REPLACE INTO question_equivalence VALUES (?,?,?,?,?)', entries)
        return {'questions': len(entries), 'unavailable': sum(e[-1] != 'verified' for e in entries)}

    def list_questions(self, *, filters: dict | None = None, offset: int = 0, limit: int = 25) -> dict:
        validate_page(offset, limit)
        filters = validate_filters(filters)
        self.refresh()
        with closing(self.catalog._connect()) as conn:
            rows = conn.execute('SELECT e.* FROM question_equivalence e JOIN questions q ON q.key=e.key '
                                'WHERE e.strategy=? ORDER BY e.key', (STRATEGY,)).fetchall()
        groups = {}
        for row in rows:
            summary, sources = question_summary(self.catalog, row['key'])
            group = groups.setdefault(row['equivalence_id'], [])
            group.append((summary, sources))
        items = []
        for identity, records in groups.items():
            selected = [r for r in records if matches(r[0], filters)]
            if not selected:
                continue
            selected.sort(key=lambda r: (not bool(r[0].get('rag_ready')), r[0]['key']))
            representative = selected[0][0]
            items.append({'equivalence_id': identity, 'representative_key': representative['key'],
                          'keys': [r[0]['key'] for r in records], 'summary': representative,
                          'sources': [{**s, 'key': r[0]['key']} for r in records for s in r[1]], 'datasets': []})
        items.sort(key=lambda item: item['representative_key'])
        return {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit}
