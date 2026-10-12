"""Read-only remote loop observation, persisted before it reaches the browser.

This module never creates an executable Studio job. The remote reader is owned
by Studio and receives only an operator-configured root, never browser input.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import sqlite3
import subprocess
import threading
import time
import zlib
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Callable


_CONFIG_ERROR = '观察连接配置不可用，请检查私有部署配置'
_SYNC_ERROR = '暂时无法同步，正在保留最近一次记录'
_CAPTURE_FIELDS = frozenset({
    'source_updated_at', 'execution', 'round', 'kb', 'evidence', 'claims',
    'rounds', 'thresholds', 'claim_details', 'round_details',
})
_DETAIL_FIELDS = {'claim_details', 'round_details'}
_MAX_CAPTURE_BYTES = 32 * 1024 * 1024


class ObservationConflict(ValueError):
    """The requested reading context cannot be resolved to its saved source."""


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))


def _decode(payload):
    # Earlier local captures used plain TEXT; retain their replay identity.
    return json.loads(zlib.decompress(payload) if isinstance(payload, bytes) else payload)


@dataclass(frozen=True, repr=False)
class ObserverConfig:
    source_id: str
    host: str
    user: str
    port: int
    root: str
    python: str
    poll_seconds: float = 5
    timeout_seconds: float = 15
    artifact_root: str | None = None

    @classmethod
    def from_dict(cls, value: dict, *, authorized_host: str) -> 'ObserverConfig':
        try:
            required = {'source_id', 'host', 'user', 'port', 'root', 'python'}
            if not isinstance(value, dict) or not required <= set(value):
                raise ValueError()
            if set(value) - required - {'poll_seconds', 'timeout_seconds', 'artifact_root'}:
                raise ValueError()
            if not authorized_host.strip() or value['host'] != authorized_host:
                raise ValueError()
            for key, pattern in (
                ('source_id', r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'),
                ('host', r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}'),
                ('user', r'[A-Za-z_][A-Za-z0-9_.-]{0,63}'),
            ):
                if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
                    raise ValueError()
            if type(value['port']) is not int or not 1 <= value['port'] <= 65535:
                raise ValueError()
            root = value['root']
            if (not isinstance(root, str) or not PurePosixPath(root).is_absolute()
                    or '\x00' in root or '\n' in root or '..' in PurePosixPath(root).parts):
                raise ValueError()
            if value.get('artifact_root') is not None:
                artifact = value['artifact_root']
                if (not isinstance(artifact, str) or not PurePosixPath(artifact).is_absolute()
                        or '\x00' in artifact or '\n' in artifact or '..' in PurePosixPath(artifact).parts):
                    raise ValueError()
            executable = value['python']
            if (not isinstance(executable, str)
                    or not re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?', PurePosixPath(executable).name)
                    or '\x00' in executable or '\n' in executable
                    or (not PurePosixPath(executable).is_absolute() and '/' in executable)):
                raise ValueError()
            for key, low, high in [('poll_seconds', 1, 3600), ('timeout_seconds', 1, 60)]:
                number = value.get(key, 5 if key == 'poll_seconds' else 15)
                if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
                    raise ValueError()
            return cls(**value)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError(_CONFIG_ERROR) from exc

    @classmethod
    def from_environment(cls) -> 'ObserverConfig | None':
        location = os.environ.get('STUDIO_KB_LOOP_CONFIG', '').strip()
        if not location:
            return None
        try:
            path = Path(location)
            if not path.is_absolute() or path.stat().st_size > 16_384:
                raise ValueError()
            return cls.from_dict(json.loads(path.read_text()),
                                 authorized_host=os.environ.get('ARCHITECTURE_IQ_KB_AUTHORIZED_HOST', ''))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(_CONFIG_ERROR) from exc

    @property
    def identity(self) -> str:
        # A configuration change must never reinterpret an old source's journal.
        fields = {key: value for key, value in asdict(self).items()
                  if key not in {'poll_seconds', 'timeout_seconds'} and value is not None}
        return hashlib.sha256(_json(fields).encode()).hexdigest()


class SSHSourceReader:
    def __call__(self, config: ObserverConfig) -> dict:
        return self._read(config, [])

    def question(self, config: ObserverConfig, identifier: str) -> dict:
        if not config.artifact_root:
            raise RuntimeError('Question source unavailable')
        if not re.fullmatch(r'q_[A-Za-z0-9_-]{1,80}', identifier):
            raise KeyError('Question unavailable')
        return self._read(config, ['--question', config.artifact_root, identifier])

    def _read(self, config: ObserverConfig, arguments: list[str]) -> dict:
        collector = Path(__file__).with_name('loop_source.py').read_text()
        command = shlex.join([config.python, '-', config.root, *arguments])
        started = time.monotonic()
        for attempt in range(2):
            remaining = config.timeout_seconds - (time.monotonic() - started) if attempt else config.timeout_seconds
            if remaining <= 0:
                break
            response = subprocess.run(
                ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                 '-o', 'Compression=yes', '-p', str(config.port),
                 f'{config.user}@{config.host}', command],
                input=collector, text=True, capture_output=True,
                timeout=remaining, check=False,
            )
            if len(response.stdout.encode()) > _MAX_CAPTURE_BYTES:
                break
            if response.returncode == 2 and arguments:
                if json.loads(response.stdout) == {'error': 'question_missing'}:
                    raise KeyError('Question unavailable')
            if response.returncode == 1 and attempt == 0:
                # A concurrently changing source cannot be published. Retry
                # only that explicit reader failure, within the same deadline.
                try:
                    if json.loads(response.stdout) == {'error': 'source_unavailable'}:
                        continue
                except ValueError:
                    pass
            if response.returncode:
                break
            return json.loads(response.stdout,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        raise RuntimeError('Observation unavailable')


class LoopObserver:
    def __init__(self, state_root: Path, *, config: ObserverConfig | None = None,
                 reader: Callable[[ObserverConfig], dict] | None = None,
                 question_reader: Callable[[ObserverConfig, str], dict] | None = None):
        self.config = config
        self.reader = reader or SSHSourceReader()
        self.question_reader = question_reader or SSHSourceReader().question
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self.directory = Path(state_root) / 'loop_observer' / (config.identity if config else 'unconfigured')
        self.database = self.directory / 'observations.sqlite3'
        if config:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript('''
                    CREATE TABLE IF NOT EXISTS captures (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        digest TEXT NOT NULL, captured_at REAL NOT NULL, payload TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sync (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        status TEXT NOT NULL, last_attempt_at REAL, last_success_at REAL
                    );
                    INSERT OR IGNORE INTO sync VALUES (1, 'connecting', NULL, NULL);
                    CREATE TABLE IF NOT EXISTS question_artifacts (
                        question_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
                        captured_at REAL NOT NULL, payload BLOB NOT NULL
                    );
                ''')

    @property
    def configured(self) -> bool:
        return self.config is not None

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA synchronous = FULL')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def sync(self) -> dict:
        if not self.configured:
            return {'status': 'unconfigured', 'last_attempt_at': None, 'last_success_at': None}
        with self._connect() as connection:
            row = connection.execute('SELECT status, last_attempt_at, last_success_at FROM sync WHERE singleton=1').fetchone()
        value = dict(row)
        if value['status'] == 'connected' and self.config:
            expiry = max(2 * self.config.poll_seconds, self.config.timeout_seconds + self.config.poll_seconds)
            if value['last_success_at'] is None or time.time() - value['last_success_at'] > expiry:
                value['status'] = 'disconnected'
                value['message'] = '最近一次同步已过期，正在保留记录'
        if value['status'] == 'disconnected':
            value.setdefault('message', _SYNC_ERROR)
        return value

    def _public_capture(self, row, sync=None):
        value = _decode(row['payload']) if row else {}
        return {
            **{key: val for key, val in value.items() if key not in _DETAIL_FIELDS},
            'configured': self.configured, 'name': '知识演化',
            'sequence': row['sequence'] if row else 0,
            'captured_at': row['captured_at'] if row else None,
            'observation': self._observation_ref(row) if row else None,
            'sync': sync if sync is not None else self.sync(),
        }

    def _observation_ref(self, row):
        return {'source_identity': self.config.identity, 'sequence': row['sequence']}

    def _latest(self):
        if not self.configured:
            return None
        with self._connect() as connection:
            return connection.execute('SELECT * FROM captures ORDER BY sequence DESC LIMIT 1').fetchone()

    def snapshot(self) -> dict:
        return self._public_capture(self._latest())

    def capture(self, *, source_identity: str | None = None, sequence: int | None = None) -> dict | None:
        """Read one complete persisted observation for local artifact adapters.

        Unlike snapshot/SSE, this internal read includes round manifests. It
        never polls a remote source and does not mix fields from two captures.
        """
        if source_identity is None and sequence is None:
            row = self._latest()
        else:
            if (not isinstance(source_identity, str) or not re.fullmatch(r'[0-9a-f]{64}', source_identity)
                    or type(sequence) is not int or not 1 <= sequence <= 2**63-1):
                raise ValueError('Invalid observation reference')
            if not self.config or self.config.identity != source_identity:
                raise KeyError('Observation source changed')
            with self._connect() as connection:
                row = connection.execute('SELECT * FROM captures WHERE sequence=?', (sequence,)).fetchone()
            if not row:
                raise KeyError('Observation unavailable')
        if not row:
            return None
        value = _decode(row['payload'])
        if hashlib.sha256(_json(value).encode()).hexdigest() != row['digest']:
            raise ValueError('Observation capture integrity check failed')
        return {**value, 'observation': {
            'sequence': row['sequence'], 'content_hash': row['digest'],
            'captured_at': row['captured_at'], 'source_id': self.config.source_id,
            'source_identity': self.config.identity,
        }}

    def claim(self, identifier: str) -> dict:
        row = self._latest()
        if not row:
            raise KeyError('命题记录不可用')
        return {**_decode(row['payload'])['claim_details'][identifier], 'observation': self._observation_ref(row)}

    def round(self, number: int) -> dict:
        row = self._latest()
        if not row:
            raise KeyError('轮次记录不可用')
        return {**_decode(row['payload'])['round_details'][str(number)], 'observation': self._observation_ref(row)}

    def question_evidence(self, identifier: str, *, source_identity: str, sequence: int,
                          claim_id: str | None = None, claim_version: int | None = None) -> dict:
        """Read stored research outcomes for a human, never inference inputs.

        This view performs no matching or experiments and reads no remote file.
        Relations mean only that the source recorded a target or evidence link.
        """
        if not isinstance(identifier, str) or not re.fullmatch(r'q_[A-Za-z0-9_-]{1,80}', identifier):
            raise ValueError('Invalid question identity')
        if (not isinstance(source_identity, str) or not re.fullmatch(r'[0-9a-f]{64}', source_identity)
                or type(sequence) is not int or not 1 <= sequence <= 2**63-1):
            raise ValueError('Reading requires an exact observation reference')
        if ((claim_id is None) != (claim_version is None) or claim_id is not None and
                (not isinstance(claim_id, str) or not 1 <= len(claim_id) <= 1000
                 or type(claim_version) is not int or not 1 <= claim_version <= 100000)):
            raise ValueError('Knowledge reading requires its identity and revision')
        try:
            capture = self.capture(source_identity=source_identity, sequence=sequence)
        except KeyError as exc:
            raise ObservationConflict('知识演化来源或阅读记录已变化，请重新打开题目后重试') from exc
        if capture is None:
            raise ObservationConflict('阅读记录尚不可用，请重新打开题目后重试')
        details = capture['claim_details']
        if claim_id is not None and (claim_id not in details or
                details[claim_id]['claim'].get('version') != claim_version):
            raise ObservationConflict('正在阅读的知识修订与记录不符，请重新打开后重试')
        targets, known = set(), False
        for detail in capture['round_details'].values():
            for row in detail.get('generation', {}).get('items', []):
                if row.get('status') == 'ok' and row.get('question_id') == identifier:
                    known = True
                    targets.update(target for target in row.get('targets', []) if isinstance(target, str))
        result = []
        for cid, detail in details.items():
            claim = detail['claim']
            version = claim.get('version')
            evidence = [row for row in detail.get('evidence', [])
                        if row.get('claim_id') == cid and row.get('version') == version]
            stored_counterexamples = detail.get('counterexamples')
            refute_rows = (stored_counterexamples.get('items', []) if isinstance(stored_counterexamples, dict)
                           else evidence)
            refutes = [row for row in refute_rows if row.get('claim_id') == cid and row.get('version') == version
                       and row.get('outcome') == 'refute']
            # The independent counterexample window may retain a question that
            # has already left the latest mixed evidence window. Keep its row
            # without duplicating an identical persisted event.
            current, seen = [], set()
            for row in [*evidence, *refutes]:
                if row.get('question_id') == identifier and _json(row) not in seen:
                    current.append(row)
                    seen.add(_json(row))
            known = known or bool(current)
            if claim_id is not None and cid != claim_id:
                continue
            if claim_id is None and not current and cid not in targets:
                continue
            reported = (stored_counterexamples.get('total') if isinstance(stored_counterexamples, dict)
                        else (claim.get('evidence') or {}).get('refute'))
            total = reported if type(reported) is int and reported >= len(refutes) else None
            truncated = (bool(stored_counterexamples.get('truncated')) if isinstance(stored_counterexamples, dict)
                         else bool(detail.get('evidence_truncated')))
            if total is not None:
                truncated = truncated or total > len(refutes)
            result.append({'claim': claim, 'relation': 'selected' if claim_id is not None else
                           'evidence' if current else 'target', 'current_evidence': current,
                           'counterexamples': {'items': refutes, 'total': total, 'truncated': truncated},
                           'evidence_total': detail.get('evidence_total', len(evidence)),
                           'evidence_truncated': bool(detail.get('evidence_truncated'))})
        if not known:
            result = []
        response = {'observation': {'source_identity': source_identity, 'sequence': sequence},
                    'question_id': identifier, 'claims': result}
        if not result:
            response['notice'] = '这份记录尚未保存本题与知识的关联或验证证据。'
        return response

    def question(self, identifier: str) -> dict:
        """Return a frozen public question, persisted independently of SSE."""
        from .loop_question import public_question

        if not isinstance(identifier, str) or not re.fullmatch(r'q_[A-Za-z0-9_-]{1,80}', identifier):
            raise KeyError('Question unavailable')
        if not self.config or not self.config.artifact_root:
            raise RuntimeError('Question source unavailable')
        # Cross-process cache admission; never write to the remote artifact tree.
        with (self.directory / 'question.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            with self._connect() as connection:
                row = connection.execute('SELECT * FROM question_artifacts WHERE question_id=?', (identifier,)).fetchone()
            if row:
                value = _decode(row['payload'])
                if hashlib.sha256(_json(value).encode()).hexdigest() != row['content_hash']:
                    raise RuntimeError('Question capture integrity check failed')
                return {**value, 'observation': {'content_hash': row['content_hash'], 'captured_at': row['captured_at']}}
            value = public_question(self.question_reader(self.config, identifier), identifier)
            serialized = _json(value)
            if len(serialized.encode()) > _MAX_CAPTURE_BYTES:
                raise RuntimeError('Question capture too large')
            digest = hashlib.sha256(serialized.encode()).hexdigest()
            captured = time.time()
            with self._connect() as connection:
                connection.execute('INSERT INTO question_artifacts VALUES (?,?,?,?)',
                                   (identifier, digest, captured, zlib.compress(serialized.encode())))
            return {**value, 'observation': {'content_hash': digest, 'captured_at': captured}}

    def events(self, *, after: int = 0, limit: int = 200) -> list[dict]:
        if type(after) is not int or not 0 <= after <= 2**63-1 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('Invalid observation cursor')
        if not self.configured:
            return []
        with self._connect() as connection:
            rows = connection.execute('SELECT * FROM captures WHERE sequence > ? ORDER BY sequence LIMIT ?', (after, limit)).fetchall()
        sync = self.sync()
        return [self._public_capture(row, sync) for row in rows]

    @staticmethod
    def _capture(value):
        if not isinstance(value, dict) or not _CAPTURE_FIELDS <= set(value):
            raise ValueError('Incomplete source capture')
        payload = {key: value[key] for key in _CAPTURE_FIELDS}
        for key in _CAPTURE_FIELDS - {'source_updated_at', 'claims', 'rounds'}:
            if not isinstance(payload[key], dict):
                raise ValueError('Invalid source capture')
        if not isinstance(payload['claims'], list) or not isinstance(payload['rounds'], list):
            raise ValueError('Invalid source lists')
        serialized = _json(payload)
        if len(serialized.encode()) > _MAX_CAPTURE_BYTES:
            raise ValueError('Source capture too large')
        return serialized

    def poll_once(self) -> bool:
        if not self.config or not self._poll_lock.acquire(blocking=False):
            return False
        try:
            # Prevent duplicate collectors even when two server processes share
            # one state directory. This lock never touches the remote source.
            with (self.directory / 'collect.lock').open('a') as guard:
                try:
                    fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
                attempted = time.time()
                with self._connect() as connection:
                    connection.execute('UPDATE sync SET last_attempt_at=? WHERE singleton=1', (attempted,))
                try:
                    payload = self._capture(self.reader(self.config))
                    digest = hashlib.sha256(payload.encode()).hexdigest()
                    captured = time.time()
                    with self._connect() as connection:
                        connection.execute('BEGIN IMMEDIATE')
                        previous = connection.execute('SELECT digest FROM captures ORDER BY sequence DESC LIMIT 1').fetchone()
                        if not previous or previous['digest'] != digest:
                            connection.execute('INSERT INTO captures (digest,captured_at,payload) VALUES (?,?,?)',
                                               (digest, captured, zlib.compress(payload.encode())))
                        connection.execute("UPDATE sync SET status='connected', last_success_at=? WHERE singleton=1", (captured,))
                    return True
                except Exception:
                    # Source traces, SSH errors and private config never reach
                    # the event journal or any public API error message.
                    with self._connect() as connection:
                        connection.execute("UPDATE sync SET status='disconnected' WHERE singleton=1")
                    return False
        finally:
            self._poll_lock.release()

    def start(self):
        if not self.config:
            return
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            def follow():
                # Only one worker continuously polls a source. Standby server
                # workers still serve the same durable SQLite snapshots/SSE.
                with (self.directory / 'worker.lock').open('a') as lease:
                    while not self._stop.is_set():
                        try:
                            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            self._stop.wait(self.config.poll_seconds)
                            continue
                        while not self._stop.is_set():
                            self.poll_once()
                            self._stop.wait(self.config.poll_seconds)
            self._thread = threading.Thread(target=follow, name='kb-loop-observer', daemon=True)
            self._thread.start()

    def stop(self):
        with self._thread_lock:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=(self.config.timeout_seconds + 2) if self.config else 2)
                if not self._thread.is_alive():
                    self._thread = None
