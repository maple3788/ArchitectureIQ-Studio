"""Provenance-checked, public-feature retrieval for standalone RAG inference."""
from __future__ import annotations

import copy
import itertools
import json

from architecture_iq.kb.experience import episode_is_sealed
from architecture_iq.kb.rules import match_rule, match_validated_scope
from architecture_iq.kb.store import canonical_hash
from .knowledge import resolve_initial_knowledge

STRATEGY = 'public_features_text_v1'


def _source_refs(item):
    return _stable_sources([{key: source[key] for key in ('id', 'kind', 'name', 'path', 'round_index') if key in source}
                            for source in item.get('sources', [])])


def _stable_sources(values):
    return sorted({canonical_hash(value): value for value in values}.values(), key=canonical_hash)


def collect_candidates(question: dict, inventory: dict) -> dict:
    grouped, excluded = {}, {}
    warnings = copy.deepcopy(inventory.get('warnings', []))
    items = sorted(inventory.get('items', []), key=lambda item: (item['id'], item['version']))
    identity = [{**{key: item.get(key) for key in ('id', 'version', 'kind', 'source')},
                 'sources': _source_refs(item)} for item in items]

    def omit(reason):
        excluded[reason] = excluded.get(reason, 0) + 1

    def add(item, record, payload, reasons, conditions):
        content = canonical_hash({'kind': item['kind'], 'id': record['id'],
                                  'revision': record['revision'], 'payload': payload})
        citation = 'rag_' + content
        kb = {key: item[key] for key in ('id', 'version', 'kind', 'name')}
        source = {**kb, 'record_id': record['id'], 'revision': record['revision'],
                  'sources': _source_refs(item)}
        if citation not in grouped:
            grouped[citation] = {'citation_id': citation, 'record_id': record['id'],
                'revision': record['revision'], 'kind': item['kind'], 'text': record['text'],
                'payload': {**copy.deepcopy(payload), 'id': citation}, 'reasons': reasons,
                'conditions_text': conditions, 'source_refs': [], 'kbs': []}
        entry = grouped[citation]
        entry['source_refs'] = _stable_sources([*entry['source_refs'], source])
        entry['kbs'] = _stable_sources([*entry['kbs'], kb])

    for item in items:
        if item.get('kind') == 'research_rules':
            continue
        try:
            frozen = resolve_initial_knowledge({'id': item['id'], 'version': item['version']}, {'items': [item]})
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            omit('unusable_source')
            warnings.append({'source_id': item['id'], 'message': str(exc)})
            continue
        snapshot = frozen['snapshot']
        if item['kind'] == 'formal':
            for claim in snapshot['claims']:
                if claim.get('status') != 'replicated_in_scope' or claim.get('enabled') is not True or not claim.get('rule'):
                    omit('unverified_or_disabled')
                    continue
                pairs = []
                for a, b in itertools.combinations(question['choices'], 2):
                    try:
                        if (match_validated_scope(question, claim, a['view'], b['view'])
                                and match_rule(claim['rule'], a['view'], b['view']) is not None):
                            pairs.append(a['letter'] + '/' + b['letter'])
                    except (KeyError, ValueError, TypeError):
                        continue
                if not pairs:
                    omit('outside_validated_scope')
                    continue
                payload = {key: claim[key] for key in ('id', 'revision', 'text', 'rule', 'status', 'validated_scope') if key in claim}
                add(item, claim, payload, ['已验证规则适用于候选组合：' + '、'.join(pairs)],
                    json.dumps(claim['rule'], ensure_ascii=False, sort_keys=True))
        else:
            episodes = {episode['id']: episode for episode in snapshot['episodes'] if episode_is_sealed(episode)}
            eligible = {key for key, episode in episodes.items()
                if episode['question'].get('family') == question.get('family') and not any(
                    bool(question.get(field)) and question.get(field) == episode['question'].get(field)
                    for field in ('id', 'dataset_id', 'lineage_id', 'pair_id'))}
            for lesson in snapshot['lessons']:
                refs = lesson.get('source_episode_ids', [])
                if lesson.get('status') != 'active' or not refs or not set(refs) <= eligible:
                    omit('ineligible_lesson_sources')
                    continue
                payload = {key: lesson[key] for key in ('id', 'revision', 'text', 'conditions', 'exceptions', 'source_episode_ids') if key in lesson}
                payload.update(status='unverified', scientific_status='unverified')
                conditions = ' '.join([*lesson.get('conditions', []), *lesson.get('exceptions', [])])
                add(item, lesson, payload, ['同题型的学习经验，尚未独立验证'], conditions)
    return {'entries': [grouped[key] for key in sorted(grouped)], 'excluded': excluded,
            'warnings': sorted(warnings, key=canonical_hash), 'inventory_hash': canonical_hash(identity)}


def _tokens(text):
    import re
    result = []
    for word in re.findall(r'[a-zA-Z0-9_]+|[\u3400-\u9fff]+', text.lower()):
        if '\u3400' <= word[0] <= '\u9fff':
            result.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
        else:
            result.append(word)
    return result


# Validation still happens on every request; only the public token index is cached.
from collections import Counter, OrderedDict
import math
from threading import Lock
_INDEX_LOCK = Lock()
_INDEXES = OrderedDict()


def retrieve_knowledge(question: dict, inventory: dict, *, knowledge_limit: int = 8) -> dict:
    if type(knowledge_limit) is not int or not 1 <= knowledge_limit <= 12:
        raise ValueError('知识条数必须为 1–12 的整数')
    admitted = collect_candidates(question, inventory)
    entries = admitted.pop('entries')
    cache_key = canonical_hash([STRATEGY, admitted['inventory_hash'], [e['payload'] for e in entries]])
    with _INDEX_LOCK:
        if cache_key not in _INDEXES:
            docs = [Counter(_tokens(e['text'] + ' ' + e['conditions_text'])) for e in entries]
            _INDEXES[cache_key] = (docs, Counter(t for d in docs for t in d))
            if len(_INDEXES) > 8:
                _INDEXES.popitem(last=False)
        _INDEXES.move_to_end(cache_key)
        docs, df = _INDEXES[cache_key]
    views = [{k: v for k, v in c['view'].items() if k != 'family'} for c in question['choices']]
    query = set(_tokens(question['prompt'] + ' ' + json.dumps(views, ensure_ascii=False, sort_keys=True)))
    avg = sum(sum(d.values()) for d in docs) / len(docs) if docs else 0
    ranked = []
    for entry, doc in zip(entries, docs):
        condition = len(query & set(_tokens(entry['conditions_text'])))
        contributions = []
        if avg:
            length = sum(doc.values())
            for term in sorted(query & doc.keys()):
                frequency = doc[term]
                contributions.append(math.log(1 + (len(docs) - df[term] + .5) / (df[term] + .5)) * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / avg)))
        score = math.fsum(contributions)
        verified = entry['kind'] == 'formal'
        if not verified and not condition and not score:
            counts = admitted['excluded']
            counts['no_text_match'] = counts.get('no_text_match', 0) + 1
            continue
        hit = {k: copy.deepcopy(v) for k, v in entry.items() if k not in {'conditions_text', 'kbs', 'payload'}}
        hit.update(score=score, condition_score=condition, verified=verified)
        if condition:
            hit['reasons'].append('条件文本相关（词项重合，非数值验证）')
        if score:
            hit['reasons'].append('题面与知识文本相关')
        ranked.append((entry, hit))
    ranked.sort(key=lambda pair: (-int(pair[1]['verified']), -pair[1]['condition_score'], -pair[1]['score'], pair[1]['citation_id']))
    snapshots = {}
    for entry, hit in ranked:
        for kb in entry['kbs']:
            key = (kb['id'], kb['version'])
            snapshots.setdefault(key, {'kb': kb, 'hits': []})['hits'].append(hit)
    def snapshot_order(snapshot):
        signals = [(-int(h['verified']), -h['condition_score'], -h['score']) for h in snapshot['hits'][:3]]
        return tuple(signals + [(0, 0, 0)] * (3 - len(signals))) + (snapshot['kb']['id'], snapshot['kb']['version'])
    candidates = sorted(snapshots.values(), key=snapshot_order)[:3]
    chosen = candidates[0] if candidates else None
    hits = copy.deepcopy(chosen['hits'][:knowledge_limit]) if chosen else []
    payloads = {entry['citation_id']: entry['payload'] for entry, _ in ranked}
    return {**admitted, 'strategy': STRATEGY, 'candidates': candidates,
            'selected_kb': copy.deepcopy(chosen['kb']) if chosen else None,
            'knowledge': [copy.deepcopy(payloads[h['citation_id']]) for h in hits], 'provenance': hits,
            'omitted': {'limit': max(0, len(chosen['hits']) - knowledge_limit) if chosen else 0, 'budget': 0}}
