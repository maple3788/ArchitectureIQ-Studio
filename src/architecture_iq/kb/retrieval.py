"""Deterministic, bounded retrieval from prior empirical discovery snapshots."""
from __future__ import annotations

import copy
import json

from .experience import episode_is_sealed


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())


def retrieve_experience(question: dict, snapshot: dict, *, mode: str, byte_budget: int,
                        repeated_practice: bool = False, initial_learning: bool = False) -> dict:
    if mode not in {'examples', 'lessons', 'combined'}:
        raise ValueError('Unknown experience retrieval mode')
    if initial_learning and (mode != 'lessons' or question.get('split', 'discovery') != 'discovery'):
        raise ValueError('Initial learning accepts discovery lessons only')
    if type(byte_budget) is not int or byte_budget < 0:
        raise ValueError('Experience byte budget must be nonnegative')
    if snapshot.get('scientific_status') != 'unverified':
        raise ValueError('Only unverified empirical snapshots are eligible')
    episodes = {e['id']: e for e in snapshot.get('episodes', []) if episode_is_sealed(e)}
    excluded = {'ineligible_examples': len(snapshot.get('episodes', [])) - len(episodes),
                'related_or_other_family_examples': 0, 'lessons_with_excluded_sources': 0}
    def eligible(episode):
        q = episode['question']
        if initial_learning:
            return q.get('family') == question.get('family')
        if repeated_practice:
            return (question.get('split', 'discovery') == 'discovery'
                    and all(question.get(field) == q.get(field)
                            for field in ('id', 'family', 'dataset_id', 'lineage_id', 'pair_id')))
        return (q.get('family') == question.get('family') and not any(
            question.get(field) is not None and question.get(field) == q.get(field)
            for field in ('id', 'dataset_id', 'lineage_id', 'pair_id')))
    valid = {key for key, e in episodes.items() if eligible(e)}
    excluded['related_or_other_family_examples'] = len(episodes) - len(valid)
    examples = [copy.deepcopy(episodes[key]) for key in sorted(valid)] if mode != 'lessons' else []
    lessons = []
    if mode != 'examples':
        for lesson in sorted(snapshot.get('lessons', []), key=lambda v: v['id']):
            refs = lesson.get('source_episode_ids', [])
            if (lesson.get('status') == 'active' and lesson.get('scientific_status') == 'unverified'
                    and refs and set(refs) <= valid):
                lessons.append(copy.deepcopy(lesson))
            elif refs and not set(refs) <= valid:
                excluded['lessons_with_excluded_sources'] += 1
    selected_examples, selected_lessons = [], []
    content_bytes = 0
    # Rules first in combined mode; whole records are omitted, never cut mid-JSON.
    for items, selected in ((lessons, selected_lessons), (examples, selected_examples)):
        for item in items:
            size = _bytes(item)
            if content_bytes + size <= byte_budget:
                selected.append(item)
                content_bytes += size
    related = any(any(question.get(field) is not None and question.get(field) == e['question'].get(field)
                      for field in ('id', 'dataset_id', 'lineage_id', 'pair_id'))
                  for key, e in episodes.items() if key in valid)
    return {**({'source_policy': 'selected_initial_lessons_only', 'prior_related_feedback': related,
                'independent_evaluation': False} if initial_learning else {}),
            **({'practice': 'same_question_practice'} if repeated_practice else {}),
            'version': snapshot['version'], 'scientific_status': 'unverified', 'mode': mode,
            'example_ids': [e['id'] for e in selected_examples], 'lesson_ids': [e['id'] for e in selected_lessons],
            'examples': selected_examples, 'lessons': selected_lessons,
            'omitted': {'examples': len(examples) - len(selected_examples), 'lessons': len(lessons) - len(selected_lessons)},
            'excluded': excluded, 'ordering': 'lesson_id_then_episode_id',
            'clipping': 'omit_whole_records_rules_first',
            'byte_budget': byte_budget, 'content_bytes': content_bytes}
