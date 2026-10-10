"""Conservative, private content identity; never rewrites source records."""
from copy import deepcopy

from .catalog import _hash

STRATEGY = 'exact_question_v1'
_DERIVED = {'ready', 'evaluation_ready', 'kb_ready', 'rag_ready', 'source_count',
            'issues', 'source_issues', 'missing_metadata'}


def equivalence_id(record: dict, *, question_key: str) -> str:
    metadata = record.get('metadata', {})
    # Missing evidence and unknown raw audit schemas must not be guessed equal.
    if (not metadata.get('ready') or 'raw_question' in record
            or not record.get('feedback', {}).get('correct_letter')):
        return STRATEGY + ':' + _hash({'revision': question_key})
    projection = deepcopy(record)
    projection['public'].pop('id', None)
    for name in {'id', 'key', 'hash'} | _DERIVED:
        projection['metadata'].pop(name, None)
    return STRATEGY + ':' + _hash(projection)
