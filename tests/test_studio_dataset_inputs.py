import json

import pytest

from test_studio_catalog import baked, bakefile
from test_studio_datasets import setup
from test_studio_pairs import import_pair


def inputs_for(c, s):
    from architecture_iq.studio.dataset_inputs import DatasetInputs
    return DatasetInputs(c, s)


def ref(record):
    return {k: record[k] for k in ('collection_id', 'revision')}


def test_public_only_question_previews_without_gt(tmp_path):
    c, s, _ = setup(tmp_path)
    q = baked('public'); q.pop('reveal')
    key = c.import_source(bakefile(tmp_path / 'public.json', [q]))['entries'][0]['key']
    a = s.create(name='Public', keys=[key], operation_id='a')
    inputs = inputs_for(c, s)
    preview = inputs.preview(ref(a), {}, purpose='public')
    assert preview['can_apply'] and preview['count'] == 1
    assert 'feedback' not in json.dumps(preview)
    assert not inputs.preview(ref(a), {}, purpose='research')['can_apply']
    with pytest.raises(ValueError): inputs.materialize(ref(a), {}, purpose='public', preview_hash=preview['preview_hash'])
    assert c.list_question_sets() == []


def test_basic_dataset_does_not_silently_select_first_question(tmp_path):
    c, s, keys = setup(tmp_path)
    a = s.create(name='A', keys=keys[:2], operation_id='a')
    inputs = inputs_for(c, s)
    preview = inputs.preview(ref(a), {}, purpose='research', method_id='basic_learning')
    assert not preview['can_apply'] and preview['count'] == 2
    assert any(b['code'] == 'basic_requires_one_question' for b in preview['blockers'])
    assert c.list_question_sets() == []
    chosen = {'keys': [keys[1]]}
    preview = inputs.preview(ref(a), chosen, purpose='research', method_id='basic_learning')
    frozen = inputs.materialize(ref(a), chosen, purpose='research', method_id='basic_learning', preview_hash=preview['preview_hash'])
    assert frozen['keys'] == [keys[1]]
    assert frozen['dataset_binding']['revision'] == a['revision']
    assert 'feedback' not in json.dumps(frozen)
    s.revise(a['collection_id'], expected_revision=a['revision'], changes={'keys': [keys[0]]}, operation_id='edit')
    assert c.get_question_set(frozen['id']) == frozen
    assert inputs.preview(ref(a), {}, purpose='public')['count'] == 2


def test_selection_order_sampling_empty_and_invalid_references(tmp_path):
    c, s, keys = setup(tmp_path)
    a = s.create(name='A', keys=keys[:2], operation_id='a')
    inputs = inputs_for(c, s)
    selected = inputs.preview(ref(a), {'keys': keys[1::-1]}, purpose='public')
    assert selected['binding']['keys'] == keys[1::-1]
    sample = inputs.preview(ref(a), {'limit': 1, 'seed': 7}, purpose='public')
    assert sample == inputs.preview(ref(a), {'limit': 1, 'seed': 7}, purpose='public')
    assert sample['count'] == 1
    assert inputs.preview(ref(a), {'keys': []}, purpose='public')['can_apply'] is False
    for selection in ({'keys': ['absent']}, {'keys': [], 'filters': {}}, {'limit': 0}, {'seed': True}, {'secret': 'x'}):
        with pytest.raises(ValueError): inputs.preview(ref(a), selection, purpose='public')


def test_phase_and_changed_source_health_invalidate_preview(tmp_path):
    c, s, keys = setup(tmp_path)
    a = s.create(name='A', keys=[keys[0]], operation_id='a')
    inputs = inputs_for(c, s)
    assert not inputs.preview(ref(a), {}, purpose='evaluation', phase='final')['can_apply']
    preview = inputs.preview(ref(a), {}, purpose='research')
    with c._connect() as conn:
        conn.execute('UPDATE aliases SET blocked=1,issues=? WHERE key=?', ('["blocked"]', keys[0]))
    with pytest.raises(RuntimeError, match='preview'):
        inputs.materialize(ref(a), {}, purpose='research', preview_hash=preview['preview_hash'])
    assert c.list_question_sets() == []


def test_complete_frozen_pair_survives_new_conflicting_revision(tmp_path):
    from architecture_iq.studio.datasets import DatasetStore
    c, original, _, _ = import_pair(tmp_path)
    s = DatasetStore(c)
    pair = c.list_question_pairs()['items'][0]
    a = s.create(name='Pairs', pair_keys=[pair['pair_key']], operation_id='a')
    original['detail']['prompt'] += ' changed'
    c.import_source(bakefile(tmp_path / 'changed.json', [original]), pairmap_path=tmp_path / 'pairmap.json')
    inputs = inputs_for(c, s)
    preview = inputs.preview(ref(a), {'filters': {'search': 'q_orig'}}, purpose='research', method_id='paired_progressive')
    assert preview['can_apply'] and preview['count'] == 2 and preview['pair_count'] == 1
    frozen = inputs.materialize(ref(a), {'filters': {'search': 'q_orig'}}, purpose='research', method_id='paired_progressive', preview_hash=preview['preview_hash'])
    assert frozen['pairs'][0]['pair_key'] == pair['pair_key']
    with pytest.raises(ValueError): inputs.preview(ref(a), {'keys': [a['keys'][0]]}, purpose='research')
    assert not inputs.preview(ref(a), {}, purpose='research', method_id='basic_learning')['can_apply']
