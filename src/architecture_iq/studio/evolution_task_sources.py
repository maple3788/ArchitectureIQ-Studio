"""Task-owned public inputs frozen from persisted knowledge evolution records.

The observation source is read-only. Selecting a generated question captures its
public artifact once; Task references never follow a changed source or KB head.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3

from architecture_iq.kb.rules import public_views, validate_rule
from architecture_iq.kb.store import canonical_hash
from .loop_question import public_question
from .rag_inputs import rag_ready
from .rule_refinement.artifacts import RuleArtifactStore, _revision, validate_snapshot
from .tasks import TaskConflict

_STATUSES = ('candidate', 'verified', 'flagged', 'retired')
_QUESTION_ID = re.compile(r'q_[A-Za-z0-9_-]{1,80}')
_KEY = re.compile(r'evolution_[0-9a-f]{64}')
_CLAIM_FIELDS = ('id', 'version', 'text', 'rules', 'status', 'registered_round',
                 'parent', 'needs_revision', 'consistency')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))


def _question_key(source_identity, identifier):
    return 'evolution_' + canonical_hash({'source': source_identity, 'question_id': identifier})


class EvolutionTaskSources:
    def __init__(self, state_root: Path, observer):
        self.observer = observer
        self.root = Path(state_root) / 'evolution_tasks'
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'sources.sqlite3'
        self.artifacts = RuleArtifactStore(self.root / 'rules')
        with self._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS questions (
                    key TEXT PRIMARY KEY, source_identity TEXT NOT NULL,
                    question_id TEXT NOT NULL, summary TEXT NOT NULL,
                    content_hash TEXT, payload TEXT
                );
                CREATE INDEX IF NOT EXISTS source_questions ON questions(source_identity, question_id);
                CREATE TABLE IF NOT EXISTS kb_items (
                    id TEXT NOT NULL, version TEXT NOT NULL, content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(id, version)
                );
                CREATE TABLE IF NOT EXISTS kb_heads (
                    source_identity TEXT PRIMARY KEY, claims_hash TEXT NOT NULL,
                    id TEXT NOT NULL, version TEXT NOT NULL
                );
            ''')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.database, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA synchronous = FULL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _capture(self):
        return self.observer.capture()

    def _index_questions(self, capture):
        if not capture:
            return
        observation = capture['observation']
        source = observation['source_identity']
        rows = []
        for index, detail in sorted(capture['round_details'].items(), key=lambda item: int(item[0])):
            for item in detail.get('generation', {}).get('items', []):
                qid = item.get('question_id')
                if item.get('status') != 'ok' or not isinstance(qid, str) or not _QUESTION_ID.fullmatch(qid):
                    continue
                key = _question_key(source, qid)
                summary = {'key': key, 'id': qid, 'source_kind': 'knowledge_evolution',
                           'round_index': int(index), 'family': item.get('family', ''),
                           'type': item.get('question_type', ''), 'question_type': item.get('question_type', ''),
                           'purpose': item.get('purpose', ''),
                           'source_id': observation['source_id'], 'source_identity': source}
                rows.append((key, source, qid, _json(summary)))
        with self._connect() as conn:
            conn.executemany('INSERT OR IGNORE INTO questions (key,source_identity,question_id,summary) VALUES (?,?,?,?)', rows)

    def _index_evidence_question(self, capture, evidence):
        # Evidence can outlive the observer's recent generation window. Admit
        # only its public identity here; the existing observer reader still
        # requires the original successful build receipt to fetch the artifact.
        observation, qid = capture['observation'], evidence['question_id']
        public = evidence.get('question') or {}
        source = observation['source_identity']
        key = _question_key(source, qid)
        summary = {'key': key, 'id': qid, 'source_kind': 'knowledge_evolution',
                   'round_index': evidence['round'], 'family': public.get('family', ''),
                   'type': public.get('type', ''), 'question_type': public.get('type', ''),
                   'purpose': public.get('purpose', ''),
                   'source_id': observation['source_id'], 'source_identity': source}
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO questions (key,source_identity,question_id,summary) VALUES (?,?,?,?)',
                         (key, source, qid, _json(summary)))

    def list_questions(self, *, search='', offset=0, limit=25):
        if (not isinstance(search, str) or len(search) > 300 or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError('题目筛选参数无效')
        capture = self._capture()
        self._index_questions(capture)
        source = self.observer.config.identity if self.observer.config else None
        with self._connect() as conn:
            rows = conn.execute('SELECT summary,payload FROM questions WHERE source_identity=?', (source,)).fetchall()
        items = [{**json.loads(row['summary']), 'cached': row['payload'] is not None} for row in rows]
        if search.strip():
            needle = search.strip().casefold()
            items = [row for row in items if needle in ' '.join(str(row.get(k, '')) for k in
                     ('id', 'family', 'type', 'purpose', 'round_index')).casefold()]
        items.sort(key=lambda row: (-row['round_index'], row['id']))
        return {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit,
                'source': {'configured': self.observer.configured,
                           'connected': self.observer.sync()['status'] == 'connected',
                           'sequence': capture['observation']['sequence'] if capture else 0}}

    def freeze_question(self, identifier, *, capture=None):
        if not isinstance(identifier, str) or not _QUESTION_ID.fullmatch(identifier) or not self.observer.config:
            raise KeyError('该题目没有已保存的成功生成记录')
        self._index_questions(capture if capture is not None else self._capture())
        key = _question_key(self.observer.config.identity, identifier)
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM questions WHERE key=?', (key,)).fetchone()
        if not row:
            raise KeyError('该题目没有已保存的成功生成记录')
        if row['payload'] is not None:
            return self.get_question(key)
        summary = json.loads(row['summary'])
        observed = self.observer.question(identifier)
        # Reapply the public boundary even when reading an earlier observer cache.
        projected = public_question(observed, identifier)
        details = {choice['candidateId']: choice for choice in projected['detail']['choices']}
        projected['detail']['choices'] = [details[choice['id']] for choice in projected['public']['choices']]
        dataset = projected['detail']['dataset']['files']['dataset_spec.json']
        candidates = [choice['files']['candidate_spec.json'] for choice in projected['detail']['choices']]
        views = public_views(dataset, candidates)
        by_id = {spec['candidate_id']: view for spec, view in zip(candidates, views)}
        for choice in projected['public']['choices']:
            choice['view'] = by_id[choice['id']]
        public_hash = canonical_hash(projected)
        record = {**projected,
            'metadata': {**projected['metadata'], 'key': key, 'hash': public_hash,
                         'type': summary['type'], 'source_kind': 'knowledge_evolution',
                         'source_count': 1, 'round_index': summary['round_index'],
                         'rag_ready': rag_ready(projected['public']), 'evaluation_ready': False},
            'observation': deepcopy(observed['observation']),
            'provenance': {k: summary[k] for k in ('source_kind', 'source_id', 'source_identity', 'round_index')},
        }
        with self._connect() as conn:
            conn.execute('UPDATE questions SET payload=?,content_hash=? WHERE key=? AND payload IS NULL',
                         (_json(record), canonical_hash(record), key))
        return self.get_question(key)

    def get_question(self, key, *, include_private=False):
        # Even include_private never releases GT: this store contains none.
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise KeyError('知识演化题目不可用')
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM questions WHERE key=?', (key,)).fetchone()
        if not row or row['payload'] is None:
            raise KeyError('请先选择并保存该题目的公开资料')
        record = json.loads(row['payload'])
        if canonical_hash(record) != row['content_hash'] or record['metadata']['key'] != key:
            raise ValueError('已保存题目的完整性校验失败')
        return record

    def _freeze_kb(self, capture, *, update_head=True, claim_ref=None):
        observation = capture['observation']
        source_identity = observation['source_identity']
        claims = [{k: deepcopy(claim[k]) for k in _CLAIM_FIELDS if k in claim}
                  for claim in capture.get('claims', []) if isinstance(claim, dict)]
        if claim_ref is not None:
            claims = [claim for claim in claims if claim.get('id') == claim_ref['id']
                      and claim.get('version') == claim_ref['version']]
            if len(claims) != 1:
                raise TaskConflict('这条知识的阅读记录已变化，请重新打开后重试')
            update_head = False
        claims.sort(key=lambda claim: str(claim.get('id', '')))
        claims_hash = canonical_hash(claims)
        with self._connect() as conn:
            head = conn.execute('SELECT * FROM kb_heads WHERE source_identity=?', (source_identity,)).fetchone()
        if update_head and head and head['claims_hash'] == claims_hash:
            return self.resolve_kb({'id': head['id'], 'version': head['version']})
        if not claims:
            # Empty new source is an explicit empty current KB, never a stale head.
            if update_head:
                with self._connect() as conn:
                    conn.execute('DELETE FROM kb_heads WHERE source_identity=?', (source_identity,))
            return None
        round_index = capture.get('round', {}).get('index')
        counts = {status: sum(claim.get('status') == status for claim in claims) for status in _STATUSES}
        document = {'kind': 'knowledge_evolution', 'source_id': observation['source_id'],
                    'source_identity': source_identity, 'claims_hash': claims_hash,
                    'source_claims': [{k: deepcopy(v) for k, v in claim.items() if k not in {'rules', 'text'}} for claim in claims]}
        rules, skipped, seen = [], [], set()
        for claim in claims:
            cid, status = claim.get('id'), claim.get('status')
            def skip(reason, clause_index=None):
                skipped.append({'claim_id': cid, 'source_status': status, 'reason': reason,
                                **({'clause_index': clause_index} if clause_index is not None else {})})
            if (not isinstance(cid, str) or not cid.strip() or len(cid) > 1000 or cid in seen
                    or type(claim.get('version')) is not int or not 1 <= claim['version'] <= 100000):
                skip('invalid_identity'); continue
            seen.add(cid)
            if status not in {'candidate', 'verified'}:
                skip('source_flagged' if status == 'flagged' else 'source_retired' if status == 'retired' else 'unknown_status'); continue
            if claim.get('needs_revision') is True or (claim.get('consistency') or {}).get('consistent') is False:
                skip('needs_revision'); continue
            clauses = claim.get('rules')
            if not isinstance(clauses, list) or not clauses or len(clauses) > 128:
                skip('uncompiled'); continue
            valid = []
            for index, clause in enumerate(clauses, 1):
                try:
                    validate_rule(clause)
                    # Keep original source clause numbers even when siblings fail.
                    native = {'schema_version': 'kb_claim_rules_v1', 'claims': [{
                        'id': cid, 'text': claim.get('text'), 'rules': [clause],
                        'validity_status': 'proposed', 'inject': True,
                        'revision': claim['version'],
                        'usage_note': '来自知识演化的源报告状态，未提升为独立验证结论',
                    }]}
                    source_ref = {'kind': 'knowledge_evolution', 'source_kind': 'knowledge_evolution',
                        'source_id': observation['source_id'], 'source_identity': source_identity,
                        'source_status': status, 'source_revision': claim.get('version'),
                        'round_index': round_index, 'original_clause_index': index,
                        'claims_hash': claims_hash}
                    imported = self.artifacts.import_rules(native, source_ref=source_ref)
                    for rule in imported['rules']:
                        # The native adapter numbers the one-clause input from
                        # one. Seal the original clause position with the same
                        # canonical revision function; never renumber siblings.
                        references = [{**ref, 'source_clause_index': index} for ref in rule['source_refs']]
                        metadata = {**rule['metadata'], 'clause_index': index}
                        valid.append(_revision(rule['rule_id'],
                            {key: rule[key] for key in ('text', 'rationale', 'rule')},
                            parents=rule['parents'], source_refs=references, metadata=metadata))
                except (ValueError, TypeError, KeyError):
                    skip('invalid_rule', index)
            rules.extend(valid)
        snapshot = self.artifacts._save(rules, import_issues=skipped, source_document=document)
        item = {'id': 'evolution_kb_' + source_identity, 'version': snapshot['version'],
                'name': f'知识演化 · 第 {round_index} 轮' if type(round_index) is int and round_index > 0 else '知识演化 · 当前 KB',
                'kind': 'research_rules', 'source_kind': 'knowledge_evolution',
                'round_index': round_index, 'snapshot': snapshot,
                'summary': f"{len(rules)} 条可执行规则 · {len(skipped)} 条来源规则未参与作答",
                'counts': {'rules': len(rules), 'active_rules': len(rules), 'retired_rules': 0, 'verified_enabled': 0},
                'source_status_counts': counts, 'skipped_claims': skipped,
                'source': 'knowledge_evolution',
                'sources': [{'id': observation['source_id'], 'kind': 'knowledge_evolution', 'name': '知识演化',
                             'round_index': round_index}],
                'provenance': {**observation, 'claims_hash': claims_hash},
                'updated_at': observation['captured_at']}
        if claim_ref is not None:
            item.update(id=item['id'] + '_claim_' + canonical_hash(claim_ref['id']),
                        name='知识演化 · ' + claim_ref['id'],
                        source_claim_id=claim_ref['id'], source_claim_version=claim_ref['version'])
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO kb_items VALUES (?,?,?,?)',
                         (item['id'], item['version'], canonical_hash(item), _json(item)))
            if update_head:
                conn.execute('INSERT OR REPLACE INTO kb_heads VALUES (?,?,?,?)',
                             (source_identity, claims_hash, item['id'], item['version']))
        return self.resolve_kb({'id': item['id'], 'version': item['version']})

    def resolve_kb(self, reference):
        if not isinstance(reference, dict) or set(reference) != {'id', 'version'}:
            raise KeyError('知识演化 KB 引用无效')
        if not isinstance(reference['id'], str) or not isinstance(reference['version'], str):
            raise KeyError('知识演化 KB 引用无效')
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM kb_items WHERE id=? AND version=?', (reference['id'], reference['version'])).fetchone()
        if not row:
            raise KeyError('已保存的知识演化 KB 不可用')
        value = json.loads(row['payload'])
        if canonical_hash(value) != row['content_hash']:
            raise ValueError('已保存 KB 的完整性校验失败')
        validate_snapshot(value['snapshot'])
        return value

    def inventory(self, reference=None):
        capture = self._capture()
        current = self._freeze_kb(capture) if capture else None
        items = [current] if current else []
        if reference and str(reference.get('id', '')).startswith('evolution_kb_'):
            pinned = self.resolve_kb(reference)
            if not any(item['id'] == pinned['id'] and item['version'] == pinned['version'] for item in items):
                items.append(pinned)
        return {'items': items, 'total': len(items), 'warnings': []}

    def selection(self, body):
        """Prepare a Task seed from exactly the observation that was displayed."""
        allowed = {'observation', 'question_id', 'expected_question_hash', 'claim_ref'}
        if not isinstance(body, dict) or set(body) - allowed or 'observation' not in body:
            raise ValueError('快捷选择需要完整的阅读记录')
        token, qid, claim = body['observation'], body.get('question_id'), body.get('claim_ref')
        if not isinstance(token, dict) or set(token) != {'source_identity', 'sequence'}:
            raise ValueError('阅读记录引用无效')
        if (not isinstance(token['source_identity'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', token['source_identity'])
                or type(token['sequence']) is not int or not 1 <= token['sequence'] <= 2**63-1):
            raise ValueError('阅读记录引用无效')
        if not qid and not claim:
            raise ValueError('请选择题目或知识')
        if qid is not None and (not isinstance(qid, str) or not _QUESTION_ID.fullmatch(qid)):
            raise ValueError('题目标识无效')
        if claim is not None and (not isinstance(claim, dict) or set(claim) != {'id', 'version'}
                or not isinstance(claim['id'], str) or not 1 <= len(claim['id']) <= 1000
                or type(claim['version']) is not int or not 1 <= claim['version'] <= 100000):
            raise ValueError('知识版本引用无效')
        expected = body.get('expected_question_hash')
        if expected is not None and (qid is None or not isinstance(expected, str)
                                     or not re.fullmatch(r'[0-9a-f]{64}', expected)):
            raise ValueError('题面保存记录无效')
        try:
            capture = self.observer.capture(**token)
        except KeyError as exc:
            raise TaskConflict('知识演化来源或阅读记录已变化，请重新打开后重试') from exc
        if capture is None:
            raise TaskConflict('阅读记录暂时不可用，请重新打开后重试')
        if claim is not None and not any(c.get('id') == claim['id'] and c.get('version') == claim['version']
                                         for c in capture['claims']):
            raise TaskConflict('这条知识的阅读记录已变化，请重新打开后重试')
        question = None
        if qid is not None:
            known = any(row.get('status') == 'ok' and row.get('question_id') == qid
                for detail in capture['round_details'].values()
                for row in detail.get('generation', {}).get('items', []))
            if not known:
                evidence = next((row for detail in capture['claim_details'].values()
                                 for row in [*detail.get('evidence', []),
                                             *detail.get('counterexamples', {}).get('items', [])]
                                 if row.get('question_id') == qid
                                 and type(row.get('round')) is int and row['round'] > 0), None)
                if evidence is None:
                    raise TaskConflict('该阅读记录中没有这道题的生成结果或证据，请重新打开后重试')
                self._index_evidence_question(capture, evidence)
            question = self.freeze_question(qid, capture=capture)
            if expected is not None and question['observation']['content_hash'] != expected:
                raise TaskConflict('题面保存记录与正在阅读的内容不同，请重新打开后重试')
        kb = self._freeze_kb(capture, update_head=False, claim_ref=claim)
        if kb is None:
            raise TaskConflict('该阅读记录没有可携带的 KB，请等待知识保存后重试')
        return {'question_key': question['metadata']['key'] if question else None,
                'kb_selection': {'mode': 'manual', 'ref': {k: kb[k] for k in ('id', 'version')}},
                'kb': kb, 'name': f"{qid} · {kb['name']}" if qid else kb['name'], 'mode': 'rules'}
