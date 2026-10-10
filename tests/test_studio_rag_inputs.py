import copy
import json

import pytest

from architecture_iq.studio.catalog import Catalog
from rag_fixtures import public_question, import_question


@pytest.mark.parametrize('split', ['discovery', 'development', 'final'])
def test_public_only_question_is_rag_ready_without_gt(tmp_path, split):
    catalog = Catalog(tmp_path)
    key = import_question(catalog, tmp_path, split=split, gt=False)
    row = catalog.list_questions()['items'][0]
    assert row['rag_ready'] is True
    assert row['ready'] is False
    record = catalog.get_question(key)
    assert record['metadata']['rag_ready'] is True
    assert 'feedback' not in record


@pytest.mark.parametrize('change', ['one', 'letters', 'ids', 'prompt', 'family', 'private_view'])
def test_invalid_public_choices_are_rejected(change):
    from architecture_iq.studio.rag_inputs import validate_rag_question
    q = public_question()
    if change == 'one': q['choices'] = q['choices'][:1]
    if change == 'letters': q['choices'][1]['letter'] = 'A'
    if change == 'ids': q['choices'][1]['id'] = 'cA'
    if change in {'prompt', 'family'}: q[change] = ''
    if change == 'private_view': q['choices'][0]['view']['correct_letter'] = 'B'
    with pytest.raises(ValueError):
        validate_rag_question(q)


def test_old_record_readiness_is_derived_without_rewriting_hash(tmp_path):
    catalog = Catalog(tmp_path)
    key = import_question(catalog, tmp_path, gt=False)
    files = list((catalog.root / 'records').glob('*.json'))
    before = {p: p.read_bytes() for p in files}
    with catalog._connect() as conn:
        row = conn.execute('SELECT summary FROM questions WHERE key=?', (key,)).fetchone()
        summary = json.loads(row['summary'])
        summary.pop('rag_ready', None)
        conn.execute('UPDATE questions SET summary=? WHERE key=?', (json.dumps(summary), key))
    assert catalog.list_questions()['items'][0]['rag_ready'] is True
    assert catalog.get_question(key)['metadata']['rag_ready'] is True
    assert {p: p.read_bytes() for p in files} == before


def test_all_blocked_sources_disable_rag(tmp_path):
    catalog = Catalog(tmp_path)
    key = import_question(catalog, tmp_path)
    with catalog._connect() as conn:
        conn.execute('UPDATE aliases SET blocked=1 WHERE key=?', (key,))
    assert catalog.list_questions()['items'][0]['rag_ready'] is False
    assert catalog.get_question(key)['metadata']['rag_ready'] is False


def test_private_fields_never_enter_rag_input():
    from architecture_iq.studio.rag_inputs import validate_rag_question
    q = public_question()
    q.update(correct_letter='GT_SECRET', feedback={'secret': 'GT_SECRET'})
    result = validate_rag_question(q)
    assert 'GT_SECRET' not in json.dumps(result)
    assert result['choices'][0]['view']['width'] == 8
    result['choices'][0]['view']['width'] = 100
    assert q['choices'][0]['view']['width'] == 8
