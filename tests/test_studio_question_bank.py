import copy
import json

import pytest

from architecture_iq.studio.catalog import Catalog
from test_studio_catalog import baked, bakefile


def bank(catalog):
    from architecture_iq.studio.question_bank import QuestionBank
    return QuestionBank(catalog)


def test_different_display_ids_share_exact_content_without_rewriting_records(tmp_path):
    c = Catalog(tmp_path / 'state')
    c.import_source(bakefile(tmp_path / 'in.json', [baked('q1'), baked('q2')]))
    before = {p.name: p.read_bytes() for p in (c.root / 'records').glob('*.json')}
    result = bank(c).list_questions()
    assert result['total'] == 1
    assert len(result['items'][0]['keys']) == 2
    assert {p.name: p.read_bytes() for p in (c.root / 'records').glob('*.json')} == before
    assert 'correct_letter' not in json.dumps(result)


@pytest.mark.parametrize('change', ['order', 'candidate', 'dataset', 'lineage', 'pair', 'split',
                                   'code', 'config', 'feedback', 'prompt'])
def test_semantically_distinct_questions_are_never_merged(tmp_path, change):
    c = Catalog(tmp_path / 'state')
    a, b = baked('q1'), baked('q2')
    if change == 'order': b['detail']['choices'].reverse()
    if change == 'candidate': b['detail']['choices'][0]['candidateId'] = 'different'
    if change == 'dataset': b = baked('q2', dataset='d_two')
    if change == 'lineage': b['lineage_id'] = 'other'
    if change == 'pair': b['pair_id'] = 'pair_other'
    if change == 'split': b['split'] = 'final'
    if change == 'code': b['detail']['choices'][0]['files']['model.py'] += '\n# changed'
    if change == 'config': b['detail']['choices'][0]['files']['candidate_spec.json']['optimizer']['lr'] = .2
    if change == 'feedback': b['reveal']['correctLetter'] = 'A'
    if change == 'prompt': b['detail']['prompt'] += ' similar'
    c.import_source(bakefile(tmp_path / 'in.json', [a, b]))
    assert bank(c).list_questions()['total'] == 2


def test_changed_id_version_and_incomplete_records_remain_distinct(tmp_path):
    c = Catalog(tmp_path / 'state')
    a = baked()
    c.import_source(bakefile(tmp_path / 'a.json', [a]))
    a['detail']['prompt'] += ' amended'
    c.import_source(bakefile(tmp_path / 'b.json', [a]))
    missing = [baked('empty1'), baked('empty2')]
    for q in missing: q.pop('reveal')
    c.import_source(bakefile(tmp_path / 'missing.json', missing))
    assert bank(c).list_questions()['total'] == 4


def test_corrupt_record_does_not_break_bank_or_reuse_cached_availability(tmp_path):
    c = Catalog(tmp_path / 'state')
    c.import_source(bakefile(tmp_path / 'in.json', [baked('q1'), baked('q2')]))
    b = bank(c)
    b.refresh()
    item = c.list_questions()['items'][0]
    (c.root / 'records' / (item['hash'] + '.json')).write_text('{}')
    result = b.list_questions()
    assert result['total'] == 2
    broken = next(x for x in result['items'] if item['key'] in x['keys'])
    assert broken['summary']['ready'] is False
    assert broken['summary']['rag_ready'] is False
    assert broken['summary']['issues']


def test_equivalent_group_never_licenses_blocked_source(tmp_path):
    c = Catalog(tmp_path / 'state')
    c.import_source(bakefile(tmp_path / 'in.json', [baked('q1'), baked('q2')]))
    keys = [x['key'] for x in c.list_questions()['items']]
    with c._connect() as conn:
        conn.execute('UPDATE aliases SET blocked=1, issues=? WHERE key=?', ('["blocked source"]', keys[0]))
    item = bank(c).list_questions()['items'][0]
    assert item['representative_key'] == keys[1]
    assert c.get_question(keys[0])['metadata']['ready'] is False
    assert any(x['blocked'] for x in item['sources'])


def test_filters_and_pagination_are_stable_over_equivalence_groups(tmp_path):
    c = Catalog(tmp_path / 'state')
    c.import_source(bakefile(tmp_path / 'in.json', [baked('q1'), baked('q2'), baked('q3', 'd2')]))
    b = bank(c)
    first, second = b.list_questions(limit=1), b.list_questions(offset=1, limit=1)
    assert first['total'] == second['total'] == 2
    assert first['items'][0]['equivalence_id'] != second['items'][0]['equivalence_id']
    assert b.list_questions(filters={'search': 'q2'})['items'][0]['representative_key'].startswith('q2@')
    assert b.list_questions(filters={'family': 'absent'})['total'] == 0
    with pytest.raises(ValueError): b.list_questions(offset=-1)
    with pytest.raises(ValueError): b.list_questions(filters={'private': 'B'})
