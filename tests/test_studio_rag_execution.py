import copy
import json

import pytest

from rag_fixtures import make_rag_case, experience_library


def prepare(case, inventory=None):
    from architecture_iq.studio.rag import prepare_rag
    return prepare_rag(case['catalog'], case['models'], inventory if inventory is not None else case['inventory'],
                       **case['selection'], allowed_roots=[case['state_root'].parent])


def test_preview_contains_only_public_exact_input_without_calls(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: pytest.fail('unexpected network'))
    config, preview = prepare(case)
    assert preview['sent'] is False and preview['can_answer'] is True
    assert preview['request']['payload'] == config['request']['payload']
    assert len(config['retrieval']['knowledge']) == 1
    assert not any(word in json.dumps(config) for word in ('correct_letter', 'feedback', 'episodes'))
    assert not case['jobs'].list()
    assert preview['preview_hash'] == prepare(case)[1]['preview_hash']


def test_empty_library_and_no_match_have_distinct_block_reasons(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    for inventory, reason in [({'items': []}, 'empty_library'),
        ({'items': [experience_library(tmp_path / 'other', text='Zebras dance.') ]}, 'no_match')]:
        config, preview = prepare(case, inventory)
        assert preview['blocked_reason'] == reason
        assert preview['can_answer'] is False and preview['request'] is None


def test_budget_omits_whole_records_and_rejects_zero_knowledge(tmp_path, monkeypatch):
    case = make_rag_case(tmp_path, monkeypatch)
    item = case['inventory']['items'][0]
    from architecture_iq.kb.experience import ExperienceStore
    from pathlib import Path
    store = ExperienceStore(Path(item['source']).parents[1])
    snapshot = store.publish(item['version'], [], [{'op': 'add', 'text': 'ReLU ' * 350,
        'conditions': [], 'exceptions': [], 'source_episode_ids': [item['snapshot']['episodes'][0]['id']], 'reason': 'test'}])
    item.update(version=snapshot['version'], snapshot=snapshot,
                source=str(store.root / 'snapshots' / (snapshot['version'] + '.json')))
    profile = case['models'].get('glm')
    profile.pop('revision', None)
    case['models'].save({**profile, 'context_size': 5100})
    config, preview = prepare(case)
    assert config['retrieval']['omitted']['budget'] >= 1
    assert preview['reserved_tokens'] <= 5100
    assert len(config['retrieval']['knowledge']) == 1
    assert 'ReLU ' * 350 not in preview['request']['payload']['messages'][0]['content']
    case['models'].save({**profile, 'context_size': 1024})
    with pytest.raises(ValueError, match='预算|上下文'):
        prepare(case)
