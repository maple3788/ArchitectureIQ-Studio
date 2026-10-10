"""Rebuildable exact-equivalence index with freshly checked source health."""
from contextlib import closing
import json

from .catalog import Catalog, _hash
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


def question_summary(catalog: Catalog, key: str) -> tuple[dict, list[dict]]:
    try:
        record = catalog.get_question(key)
        return {**record['metadata'], 'prompt': record['public']['prompt']}, record['sources']
    except (ValueError, KeyError, OSError, TypeError):
        with closing(catalog._connect()) as conn:
            row = conn.execute('SELECT summary FROM questions WHERE key=?', (key,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown question revision: {key}')
        summary = json.loads(row['summary'])
        summary.update(ready=False, evaluation_ready=False, kb_ready=False, rag_ready=False,
                       issues=['Stored question is missing or failed integrity verification'])
        return summary, []


class QuestionBank:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        with closing(catalog._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS question_equivalence
                (key TEXT PRIMARY KEY, hash TEXT NOT NULL, strategy TEXT NOT NULL,
                 equivalence_id TEXT NOT NULL, status TEXT NOT NULL)''')

    def refresh(self) -> dict:
        with closing(self.catalog._connect()) as conn:
            rows = conn.execute('SELECT key,hash FROM questions ORDER BY key').fetchall()
        entries = []
        for row in rows:
            try:
                identity = equivalence_id(self.catalog._load_frozen_record(row['key']), question_key=row['key'])
                status = 'verified'
            except (ValueError, KeyError, OSError, TypeError):
                identity = STRATEGY + ':unavailable:' + _hash(row['key'])
                status = 'unavailable'
            entries.append((row['key'], row['hash'], STRATEGY, identity, status))
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
