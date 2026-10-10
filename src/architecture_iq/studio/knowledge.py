"""Read-only knowledge inventory with content identity and explicit count units."""
from __future__ import annotations

import json
from pathlib import Path

from architecture_iq.kb.store import KBStore, canonical_hash
from .observations import node_observations


_ARTIFACT_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _description(kind: str, snapshot: dict) -> tuple[dict, str]:
    if kind == 'experience':
        lessons = snapshot.get('lessons', [])
        active = sum(value.get('status') == 'active' for value in lessons)
        counts = {'lessons': len(lessons), 'active_lessons': active,
                  'retired_lessons': sum(value.get('status') == 'retired' for value in lessons),
                  'episodes': len(snapshot.get('episodes', [])), 'verified_enabled': 0}
        return counts, (f"{active} 条可用经验 · {counts['episodes']} 次学习案例；"
                        '经验尚未经过独立验证，同题复盘不代表新题效果。')
    claims = snapshot.get('claims', [])
    originals = {value.get('source_claim_id') or value['id'] for value in claims}
    verified = sum(value.get('status') == 'replicated_in_scope' and value.get('enabled') is True
                   for value in claims)
    legacy = sum(value.get('status') == 'legacy_unverified' for value in claims)
    counts = {'records': len(claims), 'source_claims': len(originals),
              'split_records': len(claims) - len(originals),
              'compiled_rules': sum(value.get('rule') is not None for value in claims),
              'verified_enabled': verified, 'legacy_unverified': legacy}
    summary = f"{len(originals)} 条原始规律，对应 {len(claims)} 条存储记录。"
    if counts['split_records']:
        summary += f"复合规律拆成多个规则子项，额外增加 {counts['split_records']} 条记录。"
    summary += f"{verified} 条已验证且启用。"
    if legacy:
        summary += f"{legacy} 条为历史导入、待验证；历史计分不等于当前验证通过。"
    return counts, summary


def knowledge_inventory(jobs, archives: list[dict]) -> dict:
    """Collapse only byte-equivalent canonical snapshots, preserving every source.

    A waiting manual loop already has sealed round receipts. Read their validated
    experience output instead of waiting for the final job result. Merely finding
    a CURRENT pointer or unsealed model proposal is not publication evidence.
    """
    grouped: dict[tuple[str, str], dict] = {}
    warnings = []

    def add(kind, snapshot, source):
        if not isinstance(snapshot, dict):
            raise ValueError('Invalid knowledge snapshot')
        version = snapshot.get('version')
        if version != canonical_hash({k: v for k, v in snapshot.items() if k != 'version'}):
            raise ValueError('Knowledge snapshot integrity failure')
        key = (kind, canonical_hash(snapshot))
        if key not in grouped:
            counts, summary = _description(kind, snapshot)
            name = ('历史导入知识' if kind == 'formal' and counts['legacy_unverified'] == counts['records']
                    else f"{source['name']} · {'学习经验' if kind == 'experience' else '知识快照'}")
            grouped[key] = {'id': source['id'] + (':experience' if kind == 'experience' else ''),
                            'kind': kind, 'name': name, 'summary': summary,
                            'counts': counts, 'snapshot': snapshot, 'version': version,
                            'source': source['path'], 'sources': [], 'source_count': 0,
                            'updated_at': source['updated_at']}
        item = grouped[key]
        if not any(value['id'] == source['id'] and value['path'] == source['path'] for value in item['sources']):
            item['sources'].append(source)
        item['source_count'] = len(item['sources'])
        item['updated_at'] = max(item['updated_at'], source['updated_at'])

    for archive in archives:
        directory = Path(archive['config']['source_path'])
        if not (directory / 'kb/CURRENT').is_file():
            continue
        source = {'id': archive['id'], 'kind': 'archive', 'name': '历史研究归档',
                  'path': str(directory), 'created_at': archive['created_at'],
                  'updated_at': archive['updated_at']}
        try:
            snapshot = KBStore(directory / 'kb').current()
            if snapshot.get('claims'):
                add('formal', snapshot, source)
        except _ARTIFACT_ERRORS as exc:
            warnings.append({'source_id': source['id'], 'message': str(exc)})

    for job in jobs.list():
        directory = jobs.directory(job['id'])
        config = job['config']
        name = config.get('workflow', {}).get('name') or config.get('name') or '研究运行'
        source = {'id': job['id'], 'kind': 'run', 'name': name,
                  'path': str(directory / 'result.json'), 'created_at': job['created_at'],
                  'updated_at': job['updated_at']}
        result_path = directory / 'result.json'
        if result_path.is_file():
            try:
                snapshot = _read(result_path).get('kb')
                if snapshot and snapshot.get('claims'):
                    add('formal', snapshot, source)
            except _ARTIFACT_ERRORS as exc:
                warnings.append({'source_id': job['id'], 'message': str(exc)})
        if job['kind'] != 'workflow':
            continue
        output = (Path(config['output_root']) / job['id'] / 'workflow'
                  if config.get('output_root') else directory / 'workflow')
        if not (output / 'experience/CURRENT.json').is_file():
            continue
        full = jobs.get(job['id'])
        published_rounds = {event.get('round_index') for event in full.get('events', [])
                            if event.get('node_id') == 'experience_save' and event.get('state') == 'complete'}
        if not published_rounds:
            continue
        rows = [row for row in node_observations(full, directory) if row['node_id'] == 'experience_save']
        saved = [row for row in rows if row['availability'] == 'available']
        if not saved:
            warnings.append({'source_id': job['id'], 'message': '经验快照尚无可核验的封存记录。'})
            continue
        available_rounds = {row['round_index'] for row in saved}
        if published_rounds - available_rounds:
            warnings.append({'source_id': job['id'], 'message': '部分已保存的经验版本未通过来源核验，仅展示最近可核验的版本。'})
        latest = max(saved, key=lambda row: row['round_index'])
        snapshot = latest['output']
        source = {**source, 'round_index': latest['round_index'],
                  'path': str(output / 'experience/snapshots' / (snapshot['version'] + '.json'))}
        try:
            add('experience', snapshot, source)
        except _ARTIFACT_ERRORS as exc:
            warnings.append({'source_id': job['id'], 'message': str(exc)})
    items = sorted(grouped.values(), key=lambda item: item['updated_at'], reverse=True)
    return {'items': items, 'total': len(items), 'warnings': warnings,
            'notice': '相同完整快照合并展示并保留全部来源；条数相同但内容不同的快照分别保留。'}


def resolve_initial_knowledge(selection: dict, inventory: dict) -> dict:
    """Resolve only a catalog identity/version; callers cannot supply snapshots."""
    import copy
    from architecture_iq.kb.initial_knowledge import validate_initial_knowledge
    item = next((value for value in inventory['items'] if value['id'] == selection['id']), None)
    if item is None:
        raise ValueError('所选 KB 已不可用，请回到作答节点重新选择')
    if item['version'] != selection['version']:
        raise ValueError('所选 KB 已有新版本，请重新选择并预览')
    frozen = copy.deepcopy({key: item[key] for key in (
        'id', 'version', 'kind', 'name', 'counts', 'snapshot', 'source', 'sources')})
    validate_initial_knowledge(frozen, verify_sources=True)
    if frozen['kind'] == 'experience':
        from architecture_iq.kb.experience import validate_episode
        root = Path(frozen['source']).parents[2]
        for episode in frozen['snapshot']['episodes']:
            validate_episode(episode, root)
    return frozen
