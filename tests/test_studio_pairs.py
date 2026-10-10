import copy
import json

import pytest

from test_studio_catalog import bakefile, baked, catalog, write


def import_pair(tmp_path, *, renamed=False, letter_shuffle=False):
    original = baked('q_orig', 'd_orig')
    counter = baked('q_cf', 'd_cf')
    for item in (original, counter):
        item['detail']['dataset']['files']['dataset_spec.json']['params']['point_sampling'] = {
            'distribution': 'uniform', 'seed': 7}
    mapping = []
    for index, (left, right) in enumerate(zip(original['detail']['choices'], counter['detail']['choices'])):
        left['files']['candidate_spec.json']['dataset_id'] = 'd_orig'
        right['files']['candidate_spec.json']['dataset_id'] = 'd_cf'
        old_id = left['candidateId']
        new_id = 'cf_' + old_id if renamed else old_id
        right['candidateId'] = new_id
        right['files']['candidate_spec.json']['candidate_id'] = new_id
        if letter_shuffle:
            right['letter'] = 'CAB'[index]
        mapping.append({'choice_identity': 'choice_' + str(index), 'original_candidate_id': old_id,
                        'counterfactual_candidate_id': new_id})
    counter['detail']['dataset']['files']['dataset_spec.json']['params']['expression'] = 'x**2'
    pairmap = {'family': original['family'], 'original_question': 'q_orig', 'counterfactual_question': 'q_cf',
               'original_dataset': 'd_orig', 'counterfactual_dataset': 'd_cf', 'candidate_mapping': mapping,
               'original_correct': 'PRIVATE_WINNER', 'counterfactual_correct': 'PRIVATE_WINNER'}
    c = catalog(tmp_path)
    c.import_source(bakefile(tmp_path / 'pair.json', [original, counter]),
                    pairmap_path=write(tmp_path / 'pairmap.json', [pairmap]))
    return c, original, counter, pairmap


def test_pairs_match_candidate_identity_not_letters_and_exclude_gt(tmp_path):
    c, *_ = import_pair(tmp_path, renamed=True, letter_shuffle=True)
    rows = c.list_question_pairs()
    assert rows['total'] == 1
    pair = rows['items'][0]
    assert pair['ready'] and pair['kb_ready'] and pair['evaluation_ready']
    assert len(pair['pair_key']) == 64
    assert [m['role'] for m in pair['members']] == ['original', 'counterfactual']
    assert pair['candidate_mapping'][0] == {'choice_identity': 'choice_0', 'original_candidate_id': 'c_A',
        'counterfactual_candidate_id': 'cf_c_A', 'original_letter': 'A', 'counterfactual_letter': 'C'}
    assert pair['intervention']['controls'] == ['model', 'optimizer', 'loss', 'budget']
    assert pair['intervention']['changes'][0] == {
        'path': 'params.expression', 'before': 'sin(x)', 'after': 'x**2', 'kind': 'dataset'}
    assert pair['intervention']['causal_status'] == 'single_factor_fixed_sampling'
    assert 'PRIVATE_' not in json.dumps(pair)
    assert 'correct_letter' not in json.dumps(pair)
    assert c.get_question_pair(pair['pair_key']) == pair


def test_pair_sets_atomically_freeze_both_members_and_manifest(tmp_path):
    c, *_ = import_pair(tmp_path)
    pair = c.list_question_pairs()['items'][0]
    saved = c.save_question_pair_set([pair['pair_key']], name='研究题对')
    assert saved['selection_mode'] == 'pairs'
    assert saved['count'] == 2 and saved['pair_count'] == 1
    assert saved['keys'] == [m['key'] for m in pair['members']]
    assert saved['pairs'] == [pair]
    assert 'feedback' not in saved
    assert all('pair_role' not in q and 'intervention' not in q for q in saved['questions'])
    assert c.get_question_set(saved['id']) == saved
    assert set(c.get_question_set(saved['id'], include_private=True)['feedback']) == set(saved['keys'])
    with pytest.raises(ValueError, match='Duplicate'):
        c.save_question_pair_set([pair['pair_key'], pair['pair_key']], name='重复')


def test_mismatched_controls_and_revision_conflicts_are_not_selectable(tmp_path):
    c, original, counter, pairmap = import_pair(tmp_path)
    counter['detail']['choices'][0]['files']['candidate_spec.json']['optimizer']['lr'] = 0.2
    other = catalog(tmp_path / 'different')
    other.import_source(bakefile(tmp_path / 'changed.json', [original, counter]),
                        pairmap_path=write(tmp_path / 'map2.json', [pairmap]))
    invalid = other.list_question_pairs()['items'][0]
    assert not invalid['ready'] and any('optimizer' in x for x in invalid['issues'])
    with pytest.raises(ValueError, match='not ready'):
        other.save_question_pair_set([invalid['pair_key']], name='无效')
    original['detail']['prompt'] += ' amended'
    c.import_source(bakefile(tmp_path / 'revision.json', [original]), pairmap_path=tmp_path / 'pairmap.json')
    conflict = c.list_question_pairs()['items'][0]
    assert not conflict['ready'] and len(conflict['members']) == 3


def test_pair_filtering_keeps_complete_members_and_sampling_changes_visible(tmp_path):
    c, original, counter, pairmap = import_pair(tmp_path)
    counter['detail']['dataset']['files']['dataset_spec.json']['params']['instance_seed'] = 10
    other = catalog(tmp_path / 'sampling')
    other.import_source(bakefile(tmp_path / 'sampling.json', [original, counter]), pairmap_path=tmp_path / 'pairmap.json')
    pair = other.list_question_pairs(search='q_orig')['items'][0]
    assert len(pair['members']) == 2
    assert pair['intervention']['causal_status'] == 'matched_candidates_multiple_changes'
    assert any(x['kind'] == 'sampling' for x in pair['intervention']['changes'])
    assert other.list_question_pairs(split='final')['total'] == 0


def test_legacy_pair_can_recover_roles_from_all_attested_cf_candidates(tmp_path):
    from architecture_iq.studio.pairs import pair_manifest
    c, original, counter, pairmap = import_pair(tmp_path)
    records = [c.get_question(x['key']) for x in c.list_questions()['items']]
    for record in records:
        record['detail'].pop('pair_provenance', None)
        if record['metadata']['id'] == 'q_cf':
            for choice in record['detail']['choices']:
                spec = copy.deepcopy(choice['files']['candidate_spec.json'])
                spec['dataset_id'] = 'd_orig'
                choice['provenance'] = {'source_candidate_spec': spec, 'dataset_binding': {
                    'verification': 'pairmap', 'pair_id': record['metadata']['pair_id'], 'pairmap_hash': 'f' * 64,
                    'original_dataset_id': 'd_orig', 'effective_dataset_id': 'd_cf'}}
    pair = pair_manifest(records)
    assert pair['ready']
    assert [m['id'] for m in pair['members']] == ['q_orig', 'q_cf']
    records[0]['detail']['choices'][0].pop('provenance', None)
    assert not pair_manifest(records)['ready']


@pytest.mark.parametrize('defect', ['missing', 'split', 'mapping', 'budget', 'candidate_binding', 'dataset_binding'])
def test_pair_requires_complete_identity_bindings_and_fixed_controls(tmp_path, defect):
    _, original, counter, mapping = import_pair(tmp_path)
    if defect == 'split':
        counter['split'] = 'final'
    elif defect == 'mapping':
        mapping['candidate_mapping'][1]['counterfactual_candidate_id'] = 'c_A'
    elif defect == 'budget':
        counter['detail']['choices'][0]['files']['candidate_spec.json']['budget']['training_steps'] = 5
    elif defect == 'candidate_binding':
        counter['detail']['choices'][0]['files']['candidate_spec.json']['candidate_id'] = 'unrelated'
    elif defect == 'dataset_binding':
        mapping['original_dataset'] = 'unrelated'
    c = catalog(tmp_path / 'defect')
    c.import_source(bakefile(tmp_path / 'bad.json', [original] if defect == 'missing' else [original, counter]),
                    pairmap_path=write(tmp_path / 'badmap.json', [mapping]))
    pair = c.list_question_pairs()['items'][0]
    assert not pair['ready']
    with pytest.raises(ValueError, match='not ready'):
        c.save_question_pair_set([pair['pair_key']], name='invalid')
    assert c.list_question_sets() == []


def test_pair_set_is_immutable_and_listed_with_pair_metadata(tmp_path):
    c, original, *_ = import_pair(tmp_path)
    pair = c.list_question_pairs()['items'][0]
    saved = c.save_question_pair_set([pair['pair_key']], name='frozen')
    original['detail']['prompt'] += ' a new revision'
    c.import_source(bakefile(tmp_path / 'revision.json', [original]), pairmap_path=tmp_path / 'pairmap.json')
    assert c.get_question_set(saved['id']) == saved
    listed = c.list_question_sets()[0]
    assert listed['selection_mode'] == 'pairs'
    assert listed['pair_count'] == 1 and listed['count'] == 2
    assert listed['pair_keys'] == [pair['pair_key']]


def test_pair_preview_unknown_sampling_and_selection_history_are_explicit(tmp_path):
    _, original, counter, mapping = import_pair(tmp_path)
    for raw in (original, counter):
        raw['detail']['dataset']['files']['dataset_spec.json']['params'].pop('point_sampling')
    mapping['selection_history'] = 'all_significant_pairs'
    mapping['intervention'] = {'private_label': 'PRIVATE_MAPPING'}
    counter['detail']['dataset']['files']['dataset_spec.json']['params']['private_answer'] = 'PRIVATE_DS'
    c = catalog(tmp_path / 'unknown')
    c.import_source(bakefile(tmp_path / 'unknown.json', [original, counter]),
                    pairmap_path=write(tmp_path / 'unknown-map.json', [mapping]))
    pair = c.list_question_pairs()['items'][0]
    assert pair['ready']
    assert pair['intervention']['causal_status'] == 'matched_candidates_sampling_unverified'
    assert pair['intervention']['selection_history'] == 'all_significant_pairs'
    assert 'PRIVATE_' not in json.dumps(pair)


def test_legacy_role_recovery_rejects_conflicting_attestation(tmp_path):
    from architecture_iq.studio.pairs import pair_manifest
    c, *_ = import_pair(tmp_path)
    records = [c.get_question(row['key']) for row in c.list_questions()['items']]
    for record in records:
        record['detail'].pop('pair_provenance')
        if record['metadata']['id'] == 'q_cf':
            for choice in record['detail']['choices']:
                spec = copy.deepcopy(choice['files']['candidate_spec.json'])
                spec['dataset_id'] = 'd_orig'
                choice['provenance'] = {'source_candidate_spec': spec, 'dataset_binding': {
                    'verification': 'pairmap', 'pair_id': record['metadata']['pair_id'], 'pairmap_hash': 'a' * 64,
                    'original_dataset_id': 'd_orig', 'effective_dataset_id': 'd_cf'}}
            record['detail']['choices'][-1]['provenance']['dataset_binding']['original_dataset_id'] = 'other'
    assert not pair_manifest(records)['ready']


def test_pair_requires_a_verified_dataset_change(tmp_path):
    _, original, counter, mapping = import_pair(tmp_path)
    counter['detail']['dataset']['files']['dataset_spec.json']['params']['expression'] = 'sin(x)'
    c = catalog(tmp_path / 'unchanged')
    c.import_source(bakefile(tmp_path / 'unchanged.json', [original, counter]),
                    pairmap_path=write(tmp_path / 'unchanged-map.json', [mapping]))
    pair = c.list_question_pairs()['items'][0]
    assert not pair['ready']
    assert any('change' in issue for issue in pair['issues'])


def test_pair_selection_pagination_never_slices_members(tmp_path):
    c, *_ = import_pair(tmp_path)
    assert c.list_question_pairs(limit=1, offset=0)['total'] == 1
    assert len(c.list_question_pairs(limit=1, offset=0)['items'][0]['members']) == 2
    assert c.list_question_pairs(limit=1, offset=1) == {'items': [], 'total': 1}
    for kwargs in ({'offset': -1}, {'limit': 0}, {'split': 'invalid'}):
        with pytest.raises(ValueError):
            c.list_question_pairs(**kwargs)


def test_unknown_pair_revision_does_not_publish_partial_selection(tmp_path):
    c, *_ = import_pair(tmp_path)
    pair = c.list_question_pairs()['items'][0]
    with pytest.raises(KeyError):
        c.save_question_pair_set([pair['pair_key'], '0' * 64], name='incomplete selection')
    assert c.list_question_sets() == []
