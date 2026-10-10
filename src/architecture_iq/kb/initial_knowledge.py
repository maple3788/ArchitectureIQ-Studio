"""Frozen, read-only library inputs, kept separate from this run's publications."""
from __future__ import annotations

from .experience import episode_is_sealed, _strings
from .store import KBStore, _claim_shape, canonical_hash


def validate_initial_knowledge(value: dict, *, verify_sources: bool = False) -> dict:
    if not isinstance(value, dict) or value.get('kind') not in {'formal', 'experience'}:
        raise ValueError('所选 KB 类型无效，请重新选择')
    for field in ('id', 'version', 'name', 'source'):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValueError('所选 KB 缺少版本或来源，请重新选择')
    snapshot = value.get('snapshot')
    if (not isinstance(snapshot, dict) or snapshot.get('version') != value['version']
            or canonical_hash({k: v for k, v in snapshot.items() if k != 'version'}) != value['version']):
        raise ValueError('所选 KB 的快照校验失败，请重新选择')
    if value['kind'] == 'formal':
        claims = snapshot.get('claims')
        if not isinstance(claims, list) or not isinstance(snapshot.get('evidence'), list):
            raise ValueError('所选 KB 的知识记录格式无效')
        seen = set()
        ledger = {(e['id'], e['claim_id'], e['revision']): e for e in snapshot['evidence']}
        for claim in claims:
            _claim_shape(claim)
            if claim['id'] in seen:
                raise ValueError('所选 KB 包含重复知识记录')
            seen.add(claim['id'])
            if claim['enabled'] and claim['status'] != 'replicated_in_scope':
                raise ValueError('未验证知识不能启用')
            if claim['enabled'] and verify_sources:
                # Admission remains governed by the original evidence pipeline.
                import copy
                checked = copy.deepcopy(claim)
                KBStore._check_claim_evidence(checked, ledger)
                if checked != claim:
                    raise ValueError('所选 KB 的验证范围与证据不一致')
        if not any(c['enabled'] and c['status'] == 'replicated_in_scope' for c in claims):
            raise ValueError('该 KB 没有已验证且启用的知识；历史导入记录目前仅供查看')
    else:
        episodes, lessons = snapshot.get('episodes'), snapshot.get('lessons')
        if (snapshot.get('scientific_status') != 'unverified' or not isinstance(episodes, list)
                or not isinstance(lessons, list) or not isinstance(snapshot.get('operations'), list)):
            raise ValueError('所选 KB 的经验快照格式无效')
        if any(not episode_is_sealed(e) for e in episodes):
            raise ValueError('所选 KB 包含未经封存的学习案例')
        episode_ids = {e['id'] for e in episodes}
        if len(episode_ids) != len(episodes):
            raise ValueError('所选 KB 包含重复学习案例')
        seen = set()
        for lesson in lessons:
            if (not isinstance(lesson, dict) or not isinstance(lesson.get('id'), str)
                    or lesson['id'] in seen or not isinstance(lesson.get('text'), str)
                    or not lesson['text'].strip() or len(lesson['text']) > 2400
                    or type(lesson.get('revision')) is not int or lesson['revision'] < 1
                    or lesson.get('status') not in {'active', 'retired'}
                    or lesson.get('scientific_status') != 'unverified'):
                raise ValueError('所选 KB 的经验条目格式无效')
            seen.add(lesson['id'])
            _strings(lesson.get('conditions'), 'conditions')
            _strings(lesson.get('exceptions'), 'exceptions')
            refs = lesson.get('source_episode_ids')
            if (not isinstance(refs, list) or not refs or any(not isinstance(e, str) for e in refs)
                    or not set(refs) <= episode_ids):
                raise ValueError('所选 KB 的经验缺少可核验来源')
        if not any(lesson['status'] == 'active' for lesson in lessons):
            raise ValueError('该 KB 暂无可用的学习经验，请选择其他 KB')
    return value
