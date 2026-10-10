"""Public questions and sealed temporary sources for RAG tests only."""
from test_studio_catalog import baked, bakefile


def public_question():
    return {'id': 'rag-q', 'family': 'univariate_regression', 'dataset_id': 'new-data',
            'lineage_id': 'new-lineage', 'split': 'discovery',
            'prompt': '在小样本回归任务中比较 ReLU 与平滑激活函数，选择合适模型。',
            'choices': [{'id': 'c' + letter, 'letter': letter,
                         'view': {'family': 'univariate_regression', 'width': width,
                                  'activation': activation, 'train_size': 12}}
                        for letter, width, activation in [('A', 8, 'relu'), ('B', 16, 'tanh'), ('C', 32, 'relu')]]}


def import_question(catalog, tmp_path, *, split='discovery', gt=True):
    raw = baked(split=split)
    if not gt:
        raw.pop('reveal')
    catalog.import_source(bakefile(tmp_path / 'questions.json', [raw]))
    return catalog.list_questions()['items'][0]['key']
