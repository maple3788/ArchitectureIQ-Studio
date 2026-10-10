import pytest

from test_studio_catalog import baked, bakefile
from test_studio_datasets import setup
from test_studio_pairs import import_pair


def test_migration_is_idempotent_and_preserves_user_edits_and_frozen_files(tmp_path):
    from architecture_iq.studio.dataset_migration import migrate_legacy_datasets
    c, s, keys = setup(tmp_path)
    c.create_question_set('Existing set', [keys[0]])
    before = {str(p): p.read_bytes() for folder in ('records', 'sets') for p in (c.root / folder).glob('*.json')}
    first = migrate_legacy_datasets(c, s)
    assert len(first['created']) == 2 and not first['errors']
    a = s.list()['items'][0]
    edited = s.revise(a['collection_id'], expected_revision=a['revision'], changes={'name': 'My edits'}, operation_id='edit')
    second = migrate_legacy_datasets(c, s)
    assert not second['created'] and len(second['skipped']) == 2
    assert s.get(a['collection_id']) == edited
    assert {str(p): p.read_bytes() for folder in ('records', 'sets') for p in (c.root / folder).glob('*.json')} == before


def test_migration_reports_missing_records_without_removing_old_set(tmp_path):
    from architecture_iq.studio.dataset_migration import migrate_legacy_datasets
    c, s, keys = setup(tmp_path)
    old = c.create_question_set('Old', [keys[0]])
    digest = c.get_question(keys[0])['metadata']['hash']
    (c.root / 'records' / (digest + '.json')).unlink()
    report = migrate_legacy_datasets(c, s)
    assert report['errors']
    assert c.get_question_set(old['id']) == old


def test_frozen_pair_migration_ignores_later_pair_group_ambiguity(tmp_path):
    from architecture_iq.studio.datasets import DatasetStore
    from architecture_iq.studio.dataset_migration import migrate_legacy_datasets
    c, original, _, _ = import_pair(tmp_path)
    pair = c.list_question_pairs()['items'][0]
    old = c.save_question_pair_set([pair['pair_key']], name='Frozen pairs')
    original['detail']['prompt'] += ' changed'
    c.import_source(bakefile(tmp_path / 'change.json', [original]), pairmap_path=tmp_path / 'pairmap.json')
    s = DatasetStore(c)
    migrate_legacy_datasets(c, s)
    migrated = next(item for item in s.list()['items'] if item['name'] == 'Frozen pairs')
    assert s.get(migrated['collection_id'])['pairs'] == old['pairs']


@pytest.mark.parametrize('damage', ['missing', 'invalid-json', 'invalid-shape', 'wrong-hash'])
def test_damaged_set_does_not_block_startup_or_other_migrations(tmp_path, damage):
    from architecture_iq.studio.dataset_migration import migrate_legacy_datasets
    from services.kb_workflow_api.app import create_app
    c, s, keys = setup(tmp_path)
    broken = c.create_question_set('Broken', [keys[0]])
    c.create_question_set('Healthy', [keys[1]])
    path = c.root / 'sets' / (broken['hash'] + '.json')
    original = path.read_bytes()
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text({'invalid-json': '{', 'invalid-shape': '[]', 'wrong-hash': '{}'}[damage])
    app = create_app(state_root=c.root, allowed_roots=[tmp_path], execution_enabled=False)
    report = app.state.dataset_migration
    assert len(report['errors']) == 1 and report['errors'][0]['id'] == broken['id']
    assert {d['name'] for d in s.list()['items']} >= {'Healthy'}
    assert len(report['created']) == 2
    path.write_bytes(original)
    recovered = migrate_legacy_datasets(c, s)
    assert len(recovered['created']) == 1 and not recovered['errors']
    assert path.read_bytes() == original
