import json

from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.datasets import DatasetStore
from architecture_iq.studio.question_bank import QuestionBank
from test_studio_catalog import baked, bakefile


def test_candidate_summaries_are_public_read_time_projections_without_rewriting_revisions(tmp_path):
    catalog = Catalog(tmp_path / 'state')
    raw = baked()
    for index, choice in enumerate(raw['detail']['choices']):
        spec = choice['files']['candidate_spec.json']
        spec['model']['depth'] = index + 2
        spec['optimizer']['lr'] = 0.01 * (index + 1)
        spec['model']['private_result'] = 'SECRET_RESULT'
        spec['budget']['actual_score'] = 'SECRET_SCORE'
    report = catalog.import_source(bakefile(tmp_path / 'source.json', [raw]))
    key = report['entries'][0]['key']
    path = next((catalog.root / 'records').glob('*.json'))
    before = path.read_bytes()
    rows = [catalog.list_questions()['items'][0], catalog.get_question(key)['metadata'],
            QuestionBank(catalog).list_questions()['items'][0]['summary']]
    dataset = DatasetStore(catalog)
    revision = dataset.create(name='Comparison', keys=[key], operation_id='test')
    rows.append(dataset.list_members(revision)['items'][0])
    for row in rows:
        candidates = row['candidate_configs']
        assert [c['letter'] for c in candidates] == ['A', 'B', 'C']
        assert [c['model']['depth'] for c in candidates] == [2, 3, 4]
        assert candidates[0]['budget'] == {'training_steps': 4, 'batch_size': 3, 'total_samples_seen': 12}
        assert set(candidates[0]) == {'letter', 'model', 'optimizer', 'loss', 'budget'}
        assert 'SECRET_' not in json.dumps(candidates)
        assert 'train.py' not in json.dumps(candidates)
        assert row['key'] == key
    assert path.read_bytes() == before
    assert 'candidate_configs' not in json.loads(before)['metadata']


def test_public_view_only_summaries_preserve_missing_values_and_strip_private_fingerprints(tmp_path):
    catalog = Catalog(tmp_path / 'state')
    raw = {'id': 'public-q', 'family': 'bigram_lm', 'dataset_id': 'd', 'prompt': 'Canonical',
           'correct_letter': 'A', 'choices': [
               {'id': 'a', 'letter': 'A', 'view': {'model_type': 'gru_lm', 'budget': 16384,
                'arch_key': json.dumps({'type': 'gru_lm', 'num_layers': 2, 'score': 'SECRET'}),
                'opt_key': json.dumps({'type': 'Adam', 'lr': 0.001, 'answer': 'SECRET'})}},
               {'id': 'b', 'letter': 'B', 'view': {'model_type': 'transformer_lm',
                'num_layers': 3, 'd_model': 128, 'd_ff': 256, 'num_heads': 4, 'layer_residual': False}}]}
    source = tmp_path / 'public_questions.json'
    source.write_text(json.dumps([raw]))
    catalog.import_source(source)
    candidates = catalog.list_questions()['items'][0]['candidate_configs']
    assert candidates[0]['model'] == {'type': 'gru_lm', 'num_layers': 2}
    assert candidates[0]['optimizer'] == {'type': 'Adam', 'lr': 0.001}
    assert candidates[0]['budget'] == {'total_samples_seen': 16384}
    assert candidates[1]['budget'] == {}
    assert candidates[1]['model'] == {'type': 'transformer_lm', 'num_layers': 3,
        'd_model': 128, 'd_ff': 256, 'num_heads': 4, 'layer_residual': False}
    assert 'SECRET' not in json.dumps(candidates)


def test_dataset_type_distribution_counts_the_frozen_members_not_only_filtered_page(tmp_path):
    catalog = Catalog(tmp_path / 'state')
    records = [baked('q1', 'd1'), baked('q2', 'd2'), baked('q3', 'd3')]
    records[1]['type'] = 'optimizer_only'
    records[2].pop('type')
    catalog.import_source(bakefile(tmp_path / 'source.json', records))
    store = DatasetStore(catalog)
    keys = [row['key'] for row in catalog.list_questions()['items']]
    revision = store.create(name='Research', keys=keys, operation_id='create')
    expected = {'architecture_only': 1, 'optimizer_only': 1, '': 1}
    assert store.list()['items'][0]['type_counts'] == expected
    filtered = store.list_members(revision, filters={'type': 'architecture_only'}, limit=1)
    assert filtered['total'] == 1
    assert filtered['type_counts'] == expected
    store.revise(revision['collection_id'], expected_revision=revision['revision'],
                 changes={'keys': keys[:1]}, operation_id='shrink')
    assert store.list_members(revision)['type_counts'] == expected
