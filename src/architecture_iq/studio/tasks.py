"""Independent editable Task cards and immutable, idempotent answer receipts."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import re
import time
import uuid

from architecture_iq.kb.roles import exclusive_lock
from architecture_iq.kb.store import canonical_hash, write_json_atomic

FIELDS = {'name', 'question_key', 'mode', 'model_id', 'kb_selection', 'knowledge_limit'}
DEFAULTS = {'name': '新任务', 'question_key': None, 'mode': 'llm', 'model_id': None,
            'kb_selection': {'mode': 'auto'}, 'knowledge_limit': 8}
IDENTIFIER = re.compile(r'task_[a-f0-9]{16}')


class TaskConflict(RuntimeError):
    pass


def _text(value, maximum, *, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('任务字段需要长度有效的文本')


def validate_fields(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('任务字段无效')
    _text(value['name'], 160)
    _text(value['question_key'], 512, optional=True)
    _text(value['model_id'], 128, optional=True)
    if value['mode'] not in ('llm', 'rules'):
        raise ValueError('请选择模型作答或规则作答')
    if type(value['knowledge_limit']) is not int or not 1 <= value['knowledge_limit'] <= 12:
        raise ValueError('知识条数必须为 1–12 的整数')
    selection = value['kb_selection']
    if not isinstance(selection, dict):
        raise ValueError('KB 选择格式无效')
    if selection == {'mode': 'auto'}:
        return
    if set(selection) != {'mode', 'ref'} or selection['mode'] != 'manual':
        raise ValueError('KB 选择格式无效')
    ref = selection['ref']
    if not isinstance(ref, dict) or set(ref) != {'id', 'version'}:
        raise ValueError('请选择 KB 身份和版本')
    _text(ref['id'], 512); _text(ref['version'], 128)


class TaskStore:
    def __init__(self, state_root: Path):
        self.root = Path(state_root) / 'tasks'

    def lock(self):
        return exclusive_lock(self.root / '.lock')

    def directory(self, identifier):
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise KeyError('任务不存在')
        return self.root / identifier

    def _get(self, identifier):
        value = json.loads((self.directory(identifier) / 'card.json').read_text())
        validate_fields({k: value[k] for k in FIELDS})
        if value['id'] != identifier or type(value['revision']) is not int or value['revision'] < 1:
            raise ValueError('任务记录无效')
        return value

    def get(self, identifier):
        with self.lock():
            return self._get(identifier)

    def list(self):
        with self.lock():
            values = [self._get(path.parent.name) for path in self.root.glob('task_*/card.json')]
        return sorted(values, key=lambda item: (item['updated_at'], item['id']), reverse=True)

    def create(self, changes):
        if not isinstance(changes, dict) or set(changes) - FIELDS:
            raise ValueError('任务包含未知字段')
        fields = {**deepcopy(DEFAULTS), **deepcopy(changes)}
        validate_fields(fields)
        with self.lock():
            now = time.time()
            value = {**fields, 'id': 'task_' + uuid.uuid4().hex[:16], 'revision': 1,
                     'created_at': now, 'updated_at': now}
            write_json_atomic(self.directory(value['id']) / 'card.json', value)
        return value

    def save(self, identifier, *, expected_revision, changes):
        if not isinstance(changes, dict) or set(changes) - FIELDS:
            raise ValueError('任务包含未知字段')
        with self.lock():
            current = self.require(identifier, expected_revision)
            value = {**current, **deepcopy(changes)}
            validate_fields({k: value[k] for k in FIELDS})
            if value == current:
                return current
            write_json_atomic(self.directory(identifier) / 'revisions' / f"{current['revision']}.json", current)
            value.update(revision=current['revision'] + 1, updated_at=time.time())
            write_json_atomic(self.directory(identifier) / 'card.json', value)
            return value

    def require(self, identifier, revision):
        """Called while the caller holds lock across preparation/submission."""
        if type(revision) is not int or revision < 1:
            raise ValueError('需要已保存的任务修订')
        value = self._get(identifier)
        if value['revision'] != revision:
            raise TaskConflict('任务已在其他窗口更新，请重新加载并预览')
        return value

    def _idempotency(self, identifier, key):
        _text(key, 200)
        return self.directory(identifier) / 'runs' / (canonical_hash(key) + '.json')

    def prior(self, identifier, key, body):
        path = self._idempotency(identifier, key)
        if not path.exists():
            return None
        receipt = self._receipt(path)
        if receipt['request_hash'] != canonical_hash(body):
            raise TaskConflict('相同请求标识对应不同预览')
        return receipt

    def _receipt(self, path):
        value = json.loads(path.read_text())
        if value['receipt_hash'] != canonical_hash({k: v for k, v in value.items() if k != 'receipt_hash'}):
            raise ValueError('任务运行收据完整性校验失败')
        return value

    def record(self, identifier, key, body, value):
        value = {**deepcopy(value), 'id': 'answer_' + uuid.uuid4().hex[:16], 'created_at': time.time(),
                 'request_hash': canonical_hash(body)}
        value['receipt_hash'] = canonical_hash(value)
        # One atomic record is both the history entry and idempotency receipt.
        # There is no crash gap between an accepted run and its request mapping.
        write_json_atomic(self._idempotency(identifier, key), value)
        return value

    def history(self, identifier):
        with self.lock():
            self._get(identifier)
            values = [self._receipt(path) for path in (self.directory(identifier) / 'runs').glob('*.json')]
        return sorted(values, key=lambda value: (value['created_at'], value['id']), reverse=True)

    def answer(self, identifier, answer_id):
        if not isinstance(answer_id, str) or not re.fullmatch(r'answer_[a-f0-9]{16}', answer_id):
            raise KeyError('作答记录不存在')
        for receipt in self.history(identifier):
            if receipt['id'] == answer_id and receipt['task_id'] == identifier:
                return receipt
        raise KeyError('作答记录不存在')
