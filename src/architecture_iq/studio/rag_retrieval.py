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
