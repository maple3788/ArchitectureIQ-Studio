"""Public questions and sealed temporary sources for RAG tests only."""
from test_studio_catalog import baked, bakefile
import copy
import json

from architecture_iq.kb.store import canonical_hash, write_json_atomic


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


def experience_library(tmp_path, *, text='小样本回归可以比较平滑激活函数 tanh 与 ReLU。', conditions=None):
    from test_kb_experience import fixture_episode
    from architecture_iq.kb.experience import build_episode
    store, episode, _ = fixture_episode(tmp_path)
    public = json.loads((tmp_path / 'public_questions.json').read_text())
    public[0]['pair_id'] = 'source-pair'
    write_json_atomic(tmp_path / 'public_questions.json', public)
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['inputs']['public_questions.json'] = canonical_hash(public)
    write_json_atomic(tmp_path / 'manifest.json', manifest)
    episode = build_episode(tmp_path, round_index=1, question=public[0],
                            answer_path=tmp_path / episode['source_refs']['answer']['path'],
                            feedback_path=tmp_path / episode['source_refs']['feedback']['path'])
    snapshot = store.publish(store.initialize()['version'], [episode], [
        {'op': 'add', 'text': text, 'conditions': conditions or [], 'exceptions': [],
         'source_episode_ids': [episode['id']], 'reason': 'test source'}])
    return {'id': tmp_path.name, 'version': snapshot['version'], 'kind': 'experience',
            'name': '学习经验', 'snapshot': snapshot,
            'source': str(tmp_path / 'experience/snapshots' / (snapshot['version'] + '.json')),
            'sources': [{'id': tmp_path.name, 'path': str(tmp_path)}], 'counts': {}}


def formal_library(tmp_path, monkeypatch):
    from test_kb_workflow_rules import scoped_pair
    from test_kb_workflow_store import claim, patch
    from test_kb_workflow_evidence import record
    from architecture_iq.kb.store import KBStore
    question, scoped, a, b = scoped_pair()
    a['width'], b['width'] = 16, 32
    question.update(id='new-q', dataset_id='new-data', lineage_id='new-lineage',
                    prompt='Compare network width.', choices=[{'id': 'a', 'letter': 'A', 'view': a},
                                                             {'id': 'b', 'letter': 'B', 'view': b}])
    monkeypatch.setattr('architecture_iq.kb.store.verify_evidence_sources',
                        lambda *args, **kw: {'sampling_envelope': copy.deepcopy(scoped['validated_scope'])})
    store = KBStore(tmp_path / 'kb')
    initial = store.initialize([])
    evidence = [record(i, plan_hash='1' * 64) for i in range(48)]
    verified = claim(rule={'predict': {'lower_better': 'width'}}, status='replicated_in_scope',
                     enabled=True, evidence_ids=[item['id'] for item in evidence])
    snapshot = store.apply_patch(patch(initial, {'op': 'upsert', 'claim': verified, 'reason': 'test'}), evidence)
    return question, {'id': tmp_path.name, 'version': snapshot['version'], 'kind': 'formal',
                      'name': '正式知识', 'snapshot': snapshot, 'source': str(tmp_path),
                      'sources': [{'id': tmp_path.name, 'path': str(tmp_path)}], 'counts': {}}
