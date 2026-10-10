import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from architecture_iq.studio.catalog import Catalog
from test_studio_catalog import baked, bakefile
from test_studio_pairs import import_pair


def setup(tmp_path):
    from architecture_iq.studio.datasets import DatasetStore
    c = Catalog(tmp_path / 'state')
    c.import_source(bakefile(tmp_path / 'in.json', [baked('a'), baked('b', 'd_b'), baked('dup')]))
    keys = [q['key'] for q in c.list_questions()['items']]
    return c, DatasetStore(c), keys


def test_shared_membership_and_duplicate_operation_do_not_copy_questions(tmp_path):
    c, s, keys = setup(tmp_path)
    a = s.create(name='A', keys=[keys[0], keys[0], keys[2]], operation_id='a')
    b = s.create(name='B', keys=[keys[0]], operation_id='b')
    assert a['keys'] == b['keys'] == [keys[0]]
    assert s.create(name='A', keys=[keys[0], keys[0], keys[2]], operation_id='a') == a
    assert len(s.memberships([keys[0]])[keys[0]]) == 2
    assert c.stats()['questions'] == 3


def test_stale_revision_preserves_both_memberships(tmp_path):
    from architecture_iq.studio.datasets import DatasetStore, DatasetConflict
    c, s, keys = setup(tmp_path)
    a = s.create(name='A', operation_id='a')
    barrier = Barrier(2)
    def edit(index):
        other = DatasetStore(c)
        barrier.wait()
        try:
            return other.revise(a['collection_id'], expected_revision=a['revision'],
                                changes={'keys': [keys[index]]}, operation_id=str(index))
        except DatasetConflict as exc:
            return exc
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, [0, 1]))
    assert sum(isinstance(r, DatasetConflict) for r in results) == 1
    winner = next(r for r in results if isinstance(r, dict))
    assert s.get(a['collection_id']) == winner
    assert s.get(a['collection_id'], a['revision']) == a


def test_remove_and_archive_preserve_old_revision_and_question(tmp_path):
    from architecture_iq.studio.datasets import DatasetArchived
    c, s, keys = setup(tmp_path)
    a = s.create(name='A', keys=[keys[0]], operation_id='a')
    b = s.create(name='B', keys=[keys[0]], operation_id='b')
    r = s.revise(a['collection_id'], expected_revision=a['revision'],
                 changes={'keys': [], 'archived': True}, operation_id='edit')
    assert s.get(a['collection_id'], a['revision']) == a
    assert s.get(b['collection_id'])['keys'] == [keys[0]]
    assert c.get_question(keys[0])['metadata']['ready']
    assert s.list()['total'] == 1 and s.list(archived=True)['total'] == 1
    with pytest.raises(DatasetArchived):
        s.revise(a['collection_id'], expected_revision=r['revision'], changes={'name': 'X'}, operation_id='x')


def test_operation_id_reuse_with_different_body_conflicts(tmp_path):
    from architecture_iq.studio.datasets import DatasetConflict
    _, s, _ = setup(tmp_path)
    s.create(name='A', operation_id='a')
    with pytest.raises(DatasetConflict): s.create(name='B', operation_id='a')
    with pytest.raises(ValueError): s.create(name=' ', operation_id='b')
    with pytest.raises(ValueError): s.create(name='B', operation_id='')
    with pytest.raises(KeyError): s.create(name='B', keys=['unknown'], operation_id='b')


def test_unready_members_pagination_and_mode_switch(tmp_path):
    c, s, keys = setup(tmp_path)
    incomplete = baked('incomplete', 'd_empty'); incomplete.pop('reveal')
    report = c.import_source(bakefile(tmp_path / 'empty.json', [incomplete]))
    key = report['entries'][0]['key']
    a = s.create(name='Mixed', keys=[keys[1], key, keys[0]], operation_id='a')
    page = s.list_members(a, offset=1, limit=1)
    assert page['total'] == 3 and page['items'][0]['key'] == key
    assert not page['items'][0]['ready']
    assert s.list(family='univariate_regression')['total'] == 1
    assert s.list(family='missing')['total'] == 0
    with pytest.raises(ValueError): s.list_members(a, offset=-1)
    r = s.revise(a['collection_id'], expected_revision=a['revision'], changes={'pair_keys': []}, operation_id='p')
    assert r['selection_mode'] == 'pairs' and r['keys'] == r['pairs'] == []
    r = s.revise(a['collection_id'], expected_revision=r['revision'], changes={'keys': [key]}, operation_id='k')
    assert r['selection_mode'] == 'single' and r['pairs'] == []
    stored = c.get_question(key)['metadata']['hash']
    (c.root / 'records' / (stored + '.json')).write_text('{}')
    assert s.list_members(r)['items'][0]['ready'] is False


def test_pair_revision_survives_later_catalog_pair_ambiguity(tmp_path):
    from architecture_iq.studio.datasets import DatasetStore
    c, original, _, _ = import_pair(tmp_path)
    s = DatasetStore(c)
    pair = c.list_question_pairs()['items'][0]
    a = s.create(name='Pairs', pair_keys=[pair['pair_key']], operation_id='a')
    original['detail']['prompt'] += ' modified'
    c.import_source(bakefile(tmp_path / 'changed.json', [original]), pairmap_path=tmp_path / 'pairmap.json')
    assert len(c.list_question_pairs()['items'][0]['members']) == 3
    assert s.get(a['collection_id'])['pairs'] == [pair]
    assert len(a['keys']) == 2
    assert 'correct_letter' not in json.dumps(a)
    edited = s.revise(a['collection_id'], expected_revision=a['revision'],
                      changes={'name': 'Retained pair', 'pair_keys': [pair['pair_key']]}, operation_id='retain')
    assert edited['pairs'] == a['pairs'] and edited['keys'] == a['keys']
    assert s.get(a['collection_id'], a['revision']) == a
    with pytest.raises(KeyError):
        s.create(name='New ambiguous pair', pair_keys=[pair['pair_key']], operation_id='ambiguous')
