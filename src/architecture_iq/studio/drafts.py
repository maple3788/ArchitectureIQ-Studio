"""One server-owned editable workflow, with compare-and-swap and recovery copies.

Draft validation checks displayable structure only. Scientific validation and
freezing still belong to /workflows/validate and the existing run submission.
"""
from contextlib import contextmanager
import fcntl
import json
import math
from pathlib import Path
import time

from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.studio.workflow import default_workflow

MAX_DRAFT_BYTES = 1024 * 1024
BACKUP_SOURCES = {'legacy_browser', 'conflict', 'manual'}


class DraftConflict(RuntimeError):
    def __init__(self, revision: int):
        self.revision = revision
        super().__init__('共享草稿已在其他窗口更新，请先同步；你的修改可以保存为恢复副本。')


def parse_draft_json(raw: bytes):
    def reject_constant(value):
        raise ValueError(f'草稿不支持非有限数值：{value}')
    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('草稿必须是有效且层级有限的 JSON') from exc


def _validate_json(value):
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 32 or count > 20000:
            raise ValueError('草稿内容过于复杂（最多 32 层、20,000 个字段）')
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError('草稿字段名必须是文本')
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ValueError('草稿必须是 JSON')
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError('草稿不支持非有限数值')
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_DRAFT_BYTES:
        raise ValueError('草稿上限为 1 MiB')


def _validate_workflow(workflow):
    if not isinstance(workflow, dict):
        raise ValueError('workflow 必须是对象')
    if type(workflow.get('schema_version')) is not int or workflow['schema_version'] not in (1, 2):
        raise ValueError('草稿 schema_version 必须为 1 或 2')
    if not isinstance(workflow.get('name'), str) or not isinstance(workflow.get('settings'), dict):
        raise ValueError('草稿需要文本 name 和对象 settings')
    if workflow['schema_version'] == 2 and workflow['settings'].get('method_id') != 'rule_refinement':
        raise ValueError('v2 草稿只支持规则 KB 闭环')
    for key, maximum in (('nodes', 128), ('edges', 512)):
        values = workflow.get(key)
        if not isinstance(values, list) or len(values) > maximum:
            raise ValueError(f'{key} 必须是列表，最多 {maximum} 个')
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                raise ValueError(f'{key} 的每一项需要文本 id')
            if key == 'nodes':
                position = item.get('position')
                if (not isinstance(item.get('type'), str) or not isinstance(item.get('config'), dict)
                    or not isinstance(position, dict)
                    or any(type(position.get(axis)) not in (int, float) for axis in ('x', 'y'))):
                    raise ValueError('节点需要 type、config 和数值位置 x/y')
                if 'label' in item and not isinstance(item['label'], str):
                    raise ValueError('节点 label 必须是文本')
            elif any(not isinstance(item.get(field), str) for field in ('source', 'target')):
                raise ValueError('连线需要文本 source 和 target')


def _validate_payload(workflow, advanced_backup):
    _validate_json({'workflow': workflow, 'advanced_backup': advanced_backup})
    _validate_workflow(workflow)
    if advanced_backup is not None:
        _validate_workflow(advanced_backup)


class DraftStore:
    def __init__(self, state_root: Path):
        self.root = Path(state_root) / 'shared-workflow'
        self.path = self.root / 'draft.json'

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        # Separate open descriptors make flock protect both threads and processes.
        with (self.root / '.lock').open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _current(self):
        if not self.path.exists():
            write_json_atomic(self.path, {
                'workflow': default_workflow('basic_learning'), 'advanced_backup': None,
                'revision': 1, 'updated_at': time.time(),
            })
        current = parse_draft_json(self.path.read_bytes())
        if (not isinstance(current, dict) or type(current.get('revision')) is not int
            or current['revision'] < 1 or type(current.get('updated_at')) not in (int, float)
            or 'advanced_backup' not in current):
            raise ValueError('服务器草稿格式损坏；已保留原文件，请从恢复副本恢复')
        _validate_payload(current.get('workflow'), current['advanced_backup'])
        return current

    def get(self):
        with self._lock():
            return self._current()

    def save(self, *, expected_revision: int, workflow: dict, advanced_backup: dict | None):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('expected_revision 必须是正整数')
        _validate_payload(workflow, advanced_backup)
        with self._lock():
            current = self._current()
            if current['workflow'] == workflow and current['advanced_backup'] == advanced_backup:
                return current  # A lost HTTP response may safely be retried.
            if current['revision'] != expected_revision:
                raise DraftConflict(current['revision'])
            identifier = f"revision_{current['revision']:08d}"
            previous = {**current, 'id': identifier, 'source': 'revision',
                        'created_at': current['updated_at']}
            # Preserve the previous revision before atomically replacing current.
            write_json_atomic(self.root / 'history' / f'{identifier}.json', previous)
            saved = {'workflow': workflow, 'advanced_backup': advanced_backup,
                     'revision': current['revision'] + 1, 'updated_at': time.time()}
            write_json_atomic(self.path, saved)
            return saved

    def backup(self, *, workflow: dict, source: str):
        if not isinstance(source, str) or source not in BACKUP_SOURCES:
            raise ValueError('恢复副本来源必须为 legacy_browser、conflict 或 manual')
        _validate_payload(workflow, None)
        identifier = 'backup_' + canonical_hash(workflow)
        path = self.root / 'backups' / f'{identifier}.json'
        with self._lock():
            if path.exists():
                return parse_draft_json(path.read_bytes())
            backup = {'id': identifier, 'workflow': workflow, 'advanced_backup': None,
                      'created_at': time.time(), 'source': source}
            write_json_atomic(path, backup)
            return backup

    def backups(self):
        with self._lock():
            items = [parse_draft_json(path.read_bytes())
                     for folder in ('history', 'backups')
                     for path in (self.root / folder).glob('*.json')]
            items.sort(key=lambda item: (item['created_at'], item['id']), reverse=True)
            return {'items': items, 'total': len(items)}
