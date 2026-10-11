"""Library grouping changes presentation, never frozen Dataset identities."""
import json

from test_studio_datasets import setup
from test_studio_pairs import import_pair


def test_identical_members_group_before_pagination_but_empty_and_different_sets_stay_separate(tmp_path):
    _, store, keys = setup(tmp_path)
    first = store.create(name='First purpose', keys=keys[:2], operation_id='first')
    second = store.create(name='Second purpose', keys=list(reversed(keys[:2])), operation_id='second')
    subset = store.create(name='First purpose', keys=keys[:1], operation_id='subset')
    empty = [store.create(name=f'Empty {i}', operation_id=f'empty-{i}') for i in range(2)]
    frozen = [first, second, subset, *empty]
    page = store.list(grouped=True, limit=1)
    assert page['total'] == 4 and page['dataset_total'] == 5 and len(page['items']) == 1
    all_groups = store.list(grouped=True)['items']
    grouped = next(item for item in all_groups if len(item['equivalent_datasets']) == 2)
    assert grouped['count'] == 2  # never sum repeated references
    assert {item['collection_id'] for item in grouped['equivalent_datasets']} == {first['collection_id'], second['collection_id']}
    assert grouped['origin'] == {'kind': 'created'}
    for record in frozen:
        assert store.get(record['collection_id'], record['revision']) == record
    assert store.list()['total'] == 5  # selectors retain the original flat contract
    assert all('equivalent_datasets' not in item for item in store.list()['items'])


def test_search_finds_alias_and_preserves_all_group_identities(tmp_path):
    _, store, keys = setup(tmp_path)
    a = store.create(name='Older alias', keys=keys[:1], operation_id='a')
    b = store.create(name='Current material', keys=keys[:1], operation_id='b')
    result = store.list(grouped=True, search='older ALIAS')
    assert result['total'] == 1 and result['dataset_total'] == 2
    assert {d['collection_id'] for d in result['items'][0]['equivalent_datasets']} == {a['collection_id'], b['collection_id']}
    assert store.list(grouped=True, family='missing')['total'] == 0
    store.revise(a['collection_id'], expected_revision=a['revision'], changes={'archived': True}, operation_id='archive')
    assert store.list(grouped=True)['dataset_total'] == 1
    assert store.list(grouped=True, archived=True)['items'][0]['collection_id'] == a['collection_id']


def test_origin_comes_from_migration_receipts_and_survives_renaming(tmp_path):
    from architecture_iq.studio.dataset_migration import migrate_legacy_datasets
    catalog, store, keys = setup(tmp_path)
    catalog.create_question_set('Existing subset', keys[:1])
    migrate_legacy_datasets(catalog, store)
    original = store.list(grouped=True)['items']
    assert {item['origin']['kind'] for item in original} == {'source', 'set'}
    subset = next(item for item in original if item['origin']['kind'] == 'set')
    store.revise(subset['collection_id'], expected_revision=subset['revision'],
                 changes={'name': 'Renamed subset', 'description': 'My own explanation'}, operation_id='rename')
    own = store.create(name='Own dataset', keys=keys[:1], description='Imported from existing source', operation_id='own')
    group = next(item for item in store.list(grouped=True)['items'] if item['collection_id'] == own['collection_id'])
    assert group['origin']['kind'] == 'created'  # user-authored description is not provenance
    assert {item['origin']['kind'] for item in group['equivalent_datasets']} == {'set', 'created'}


def test_single_questions_and_frozen_pairs_are_not_grouped_together(tmp_path):
    from architecture_iq.studio.datasets import DatasetStore
    catalog, _, _, _ = import_pair(tmp_path)
    store = DatasetStore(catalog)
    pair = catalog.list_question_pairs()['items'][0]
    paired = store.create(name='Paired', pair_keys=[pair['pair_key']], operation_id='pairs')
    store.create(name='Single', keys=paired['keys'], operation_id='single')
    result = store.list(grouped=True)
    assert result['total'] == 2
    assert all(len(item['equivalent_datasets']) == 1 for item in result['items'])
    assert 'correct_letter' not in json.dumps(result)


def test_grouped_library_api_is_read_only_and_keeps_flat_dataset_selection(tmp_path):
    from test_studio_dataset_api import create, PREFIX
    from test_studio_api import make_client
    from test_studio_catalog import baked, bakefile
    client, source = make_client(tmp_path)
    report = client.post(PREFIX+'/sources/import', json={'path':str(bakefile(source/'in.json', [baked()]))}).json()
    key = report['entries'][0]['key']
    a, b = create(client, name='A', keys=[key]), create(client, name='B', keys=[key])
    result = client.get(PREFIX+'/datasets?grouped=true&limit=1')
    assert result.status_code == 200, result.text
    assert result.json()['total'] == 1 and result.json()['dataset_total'] == 2
    assert client.get(PREFIX+'/datasets').json()['total'] == 2
    assert 'correct_letter' not in result.text
    for saved in (a, b):
        assert client.get(PREFIX+'/datasets/'+saved['collection_id']).json() == saved
