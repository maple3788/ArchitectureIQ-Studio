import copy

from architecture_iq.studio.rag_retrieval import retrieve_knowledge
from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
from rag_fixtures import public_question


def evolution_library(tmp_path):
    snapshot = RuleArtifactStore(tmp_path / 'evolution-rules').import_rules({'claims': [
        {'id': 'C0001', 'text': 'Wider candidates win within this research scope.',
         'rule': {'scope': ['family', 'eq', 'univariate_regression'],
                  'predict': {'higher_better': 'width'}}},
        {'id': 'C0002', 'text': 'Language model hypothesis.',
         'rule': {'scope': ['family', 'eq', 'bigram_lm'],
                  'predict': {'lower_better': 'width'}}},
    ]}, source_ref={'id': 'evolution-source', 'kind': 'knowledge_evolution',
                    'source_status': 'candidate', 'source_revision': 1})
    return {'id': 'evolution_source', 'name': '知识演化 · 第 2 轮',
            'version': snapshot['version'], 'kind': 'research_rules',
            'source_kind': 'knowledge_evolution', 'snapshot': snapshot,
            'sources': [{'id': 'evolution_source', 'kind': 'knowledge_evolution', 'round_index': 2}]}


def test_task_opt_in_matches_evolution_rules_and_keeps_research_provenance(tmp_path):
    item = evolution_library(tmp_path)
    result = retrieve_knowledge(public_question(), {'items': [item]}, allow_evolution=True)
    assert len(result['knowledge']) == 1
    assert result['selected_kb']['id'] == item['id']
    note, source = result['knowledge'][0], result['provenance'][0]
    assert note['status'] == 'unverified' and note['scientific_status'] == 'research_hypothesis'
    assert note['rule']['predict'] == {'higher_better': 'width'}
    assert source['verified'] is False
    assert source['source_claim_ids'] == ['C0001']
    assert source['source_status'] == 'candidate'
    assert source['matched_pairs'] == ['A/B', 'A/C', 'B/C']


def test_regular_rag_does_not_implicitly_adopt_evolution_or_other_research_rules(tmp_path):
    item = evolution_library(tmp_path)
    assert not retrieve_knowledge(public_question(), {'items': [item]})['knowledge']
    old = copy.deepcopy(item)
    old.pop('source_kind')
    assert not retrieve_knowledge(public_question(), {'items': [old]}, allow_evolution=True)['knowledge']


def test_evolution_tampered_or_retired_rules_cannot_be_injected(tmp_path):
    item = evolution_library(tmp_path)
    item['snapshot']['rules'][0]['state'] = 'retired'
    result = retrieve_knowledge(public_question(), {'items': [item]}, allow_evolution=True)
    assert not result['knowledge']
    assert result['excluded']['unusable_source'] == 1
