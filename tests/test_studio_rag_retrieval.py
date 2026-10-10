import copy
import json
import math

import pytest

from rag_fixtures import public_question, experience_library, formal_library


def collect(question, *items):
    from architecture_iq.studio.rag_retrieval import collect_candidates
    return collect_candidates(question, {'items': list(items)})


def test_only_verified_enabled_applicable_rules_are_admitted(tmp_path, monkeypatch):
    question, item = formal_library(tmp_path / 'formal', monkeypatch)
    result = collect(question, item)
    assert len(result['entries']) == 1
    assert result['entries'][0]['payload']['status'] == 'replicated_in_scope'
    assert result['entries'][0]['reasons']
    other = copy.deepcopy(question)
    other['profile_hash'] = 'different'
    assert collect(other, item)['entries'] == []
    from architecture_iq.kb.store import canonical_hash
    for status, enabled in [('legacy_unverified', False), ('replicated_in_scope', False)]:
        changed = copy.deepcopy(item)
        changed['snapshot']['claims'][0].update(status=status, enabled=enabled)
        changed['snapshot']['version'] = changed['version'] = canonical_hash(
            {k: v for k, v in changed['snapshot'].items() if k != 'version'})
        assert collect(question, changed)['entries'] == []


@pytest.mark.parametrize('field', ['id', 'dataset_id', 'lineage_id', 'pair_id'])
def test_related_episode_excludes_dependent_lessons(tmp_path, field):
    item = experience_library(tmp_path / 'source')
    q = public_question()
    assert len(collect(q, item)['entries']) == 1
    q[field] = item['snapshot']['episodes'][0]['question'][field]
    assert collect(q, item)['entries'] == []
    q[field] = None
    assert len(collect(q, item)['entries']) == 1


def test_retired_unsealed_other_family_lessons_are_excluded(tmp_path):
    item = experience_library(tmp_path / 'source')
    q = public_question()
    q['family'] = 'unrelated'
    assert collect(q, item)['entries'] == []
    q = public_question()
    for mutation in ('retired', 'unsealed'):
        changed = copy.deepcopy(item)
        if mutation == 'retired': changed['snapshot']['lessons'][0]['status'] = 'retired'
        else: changed['snapshot']['episodes'][0].pop('seal_hash')
        assert collect(q, changed)['entries'] == []


def test_corrupt_source_does_not_hide_valid_library(tmp_path):
    first = experience_library(tmp_path / 'a')
    second = experience_library(tmp_path / 'b')
    second['snapshot']['lessons'][0]['text'] = 'tampered'
    result = collect(public_question(), first, second)
    assert len(result['entries']) == 1
    assert result['warnings']
    assert 'correct_letter' not in json.dumps(result['entries'])


def test_duplicate_records_preserve_all_provenance_without_extra_weight(tmp_path):
    first = experience_library(tmp_path / 'a')
    second = copy.deepcopy(first)
    second['id'] = 'other-source'
    second['sources'] = [{'id': 'other-source', 'path': first['source']}]
    result = collect(public_question(), first, second)
    assert len(result['entries']) == 1
    assert len(result['entries'][0]['source_refs']) == 2
    third = experience_library(tmp_path / 'c', text='另一条关于 ReLU 的经验。')
    assert len(collect(public_question(), first, third)['entries']) == 2


def retrieve(q, items, limit=8):
    from architecture_iq.studio.rag_retrieval import retrieve_knowledge
    return retrieve_knowledge(q, {'items': items}, knowledge_limit=limit)


def test_chinese_and_identifier_terms_rank_relevant_kb_first(tmp_path):
    relevant = experience_library(tmp_path / 'relevant')
    other = experience_library(tmp_path / 'other', text='如果网络宽度 width 较大，可检查充分训练条件。')
    result = retrieve(public_question(), [other, relevant])
    assert result['selected_kb']['id'] == 'relevant'
    assert result['knowledge'][0]['text'] == relevant['snapshot']['lessons'][0]['text']
    assert result['provenance'][0]['source_refs']
    assert result == retrieve(public_question(), [relevant, other])


def test_verified_applicable_rule_precedes_unverified_lesson(tmp_path, monkeypatch):
    q, formal = formal_library(tmp_path / 'formal', monkeypatch)
    exp = experience_library(tmp_path / 'exp', text='Compare network width width width.')
    # Experience is another family, so it cannot displace this valid rule.
    result = retrieve(q, [exp, formal])
    assert result['selected_kb']['kind'] == 'formal'


def test_same_family_alone_is_not_a_lesson_match(tmp_path):
    item = experience_library(tmp_path / 'irrelevant', text='Completely unrelated zebras dance.')
    assert retrieve(public_question(), [item])['knowledge'] == []


def test_duplicate_terms_and_empty_documents_have_finite_scores(tmp_path):
    item = experience_library(tmp_path / 'source', text='tanh tanh tanh tanh')
    result = retrieve(public_question(), [item])
    assert math.isfinite(result['candidates'][0]['hits'][0]['score'])
    assert retrieve(public_question(), [])['knowledge'] == []


def test_candidates_max_three_and_knowledge_limit_one_to_twelve(tmp_path):
    items = [experience_library(tmp_path / str(i)) for i in range(4)]
    result = retrieve(public_question(), items, 1)
    assert len(result['candidates']) == 3
    assert len(result['knowledge']) == 1
    for limit in (0, 13, True):
        with pytest.raises(ValueError): retrieve(public_question(), items, limit)


def test_best_hit_after_twelfth_record_is_not_preclipped(tmp_path):
    from architecture_iq.kb.experience import ExperienceStore
    from pathlib import Path
    item = experience_library(tmp_path / 'source', text='Irrelevant zebras.')
    store = ExperienceStore(Path(item['source']).parents[1])
    ref = item['snapshot']['episodes'][0]['id']
    operations = [
        {'op': 'add', 'text': ('Different zebras ' + str(i)) if i < 12 else 'ReLU tanh 激活函数 回归 选择',
         'conditions': [], 'exceptions': [], 'source_episode_ids': [ref], 'reason': 'test'} for i in range(13)]
    snapshot = store.publish(item['version'], [], operations[:12])
    snapshot = store.publish(snapshot['version'], [], operations[12:])
    item.update(version=snapshot['version'], snapshot=snapshot,
                source=str(store.root / 'snapshots' / (snapshot['version'] + '.json')))
    assert retrieve(public_question(), [item])['knowledge'][0]['text'] == 'ReLU tanh 激活函数 回归 选择'
