import copy
import json

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
