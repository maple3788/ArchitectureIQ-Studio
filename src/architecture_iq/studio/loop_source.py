"""Read-only observer for an existing KB loop's persisted artifacts.

This file is also sent over SSH on stdin. It deliberately imports no benchmark
or loop implementation and cannot launch training, score claims, or change KBs.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import sys
import time

import yaml

STAGES = ('plan', 'build', 'score', 'judge', 'propose', 'register', 'report')
STATUSES = ('candidate', 'verified', 'flagged', 'retired')
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_ROUNDS = 30
MAX_EVIDENCE = 100
STATS = ('support', 'applicable', 'rate', 'lower_bound', 'alpha', 'recent_support', 'recent_applicable')
THRESHOLDS = ('min_applicable', 'promote_rate', 'promote_lower_bound', 'alpha', 'flag_rate',
              'recent_rounds', 'recent_min_applicable', 'max_revisions')


class SourceUnavailable(ValueError):
    """The source could not be read as one stable observation."""


def _pick(value, keys):
    return {key: value[key] for key in keys if key in value} if isinstance(value, dict) else {}


def _json(raw):
    def reject(_value):
        raise SourceUnavailable('Non-finite source value')
    return json.loads(raw, parse_constant=reject)


class Reader:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        if self.root.is_symlink() or not self.root.is_dir():
            raise SourceUnavailable('Source directory unavailable')
        self.files = {}
        self.directories = {}

    def path(self, relative):
        parts = Path(relative).parts
        if Path(relative).is_absolute() or '..' in parts:
            raise SourceUnavailable('Invalid source path')
        path = self.root
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise SourceUnavailable('Source link rejected')
        return path

    def stamp(self, relative):
        path = self.path(relative)
        if not path.exists():
            return None
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise SourceUnavailable('Unsupported source artifact')
        return (info.st_ino, info.st_size, info.st_mtime_ns)

    def read(self, relative, required=False):
        before = self.stamp(relative)
        if relative in self.files and self.files[relative] != before:
            raise SourceUnavailable('Source changed during observation')
        self.files[relative] = before
        if before is None:
            if required:
                raise SourceUnavailable('Required artifact unavailable')
            return None
        data = self.path(relative).read_bytes()
        if before != self.stamp(relative):
            raise SourceUnavailable('Source changed during observation')
        return data

    def json(self, relative, default=None, required=False):
        data = self.read(relative, required)
        return _json(data) if data is not None else default

    def rows(self, relative):
        data = self.read(relative)
        if data is None:
            return []
        # A writer appends its newline last. Do not consume a partially written row.
        lines = data.splitlines(keepends=True)
        return [_json(line) for line in lines if line.strip() and line.endswith(b'\n')]

    def names(self, relative):
        path = self.path(relative)
        names = tuple(sorted(p.name for p in path.iterdir())) if path.exists() else ()
        self.directories[relative] = names
        return names

    def finish(self):
        for relative, stamp in self.files.items():
            if self.stamp(relative) != stamp:
                raise SourceUnavailable('Source changed during observation')
        for relative, names in self.directories.items():
            path = self.path(relative)
            current = tuple(sorted(p.name for p in path.iterdir())) if path.exists() else ()
            if current != names:
                raise SourceUnavailable('Source changed during observation')
        return max((value[2] / 1e9 for value in self.files.values() if value), default=0)


def _claim(value):
    result = _pick(value, ('id', 'version', 'text', 'rules', 'status', 'registered_round',
                           'needs_revision', 'revisions', 'rationale'))
    result['parent'] = _pick(value.get('parent'), ('id', 'version')) or None
    result['stats'] = _pick(value.get('stats'), STATS) or None
    consistency = value.get('consistency')
    result['consistency'] = _pick(consistency, ('consistent', 'issue')) if consistency else None
    return result


def _report(value):
    if not value:
        return None
    return {
        'round': value.get('round'), 'kb': _pick(value.get('kb'), ('claims', *STATUSES)),
        'build': _pick(value.get('build'), ('items', 'ok', 'failed', 'target', 'explore')),
        'events': [_pick(event, ('round', 'claim_id', 'version', 'from', 'to', 'needs_revision', *STATS))
                   for event in value.get('events', [])],
        'registered': [_pick(claim, ('id', 'version', 'text', 'consistent', 'issue')) for claim in value.get('registered', [])],
        'rejections': value.get('rejections', {}),
        'qwen': _pick(value.get('qwen'), ('calls', 'cached', 'errors', 'failovers')),
        'preregistered_sha256': value.get('preregistered_sha256'),
    }


def _round(reader, index):
    prefix = f'rounds/round_{index:04d}/'
    completed = [stage for stage in STAGES if reader.read(prefix + 'DONE_' + stage) is not None]
    planned = reader.json(prefix + 'plan.json', [])
    built = {}
    for row in reader.rows(prefix + 'build.jsonl'):
        # Match the source's resume rule: once an item succeeded a later failed
        # retry cannot replace its successful result.
        if row['status'] == 'ok' or row['item_id'] not in built:
            built[row['item_id']] = row
    plan = {'total': len(planned), 'target': sum(row.get('purpose') == 'target' for row in planned),
            'explore': sum(row.get('purpose') == 'explore' for row in planned)}
    ok = sum(row.get('status') == 'ok' for row in built.values())
    build = {'completed': len(built), 'ok': ok, 'failed': len(built) - ok}
    result = {'index': index, 'completed': 'report' in completed, 'completed_stages': completed,
              'plan': plan, 'build': build, 'report': _report(reader.json(prefix + 'report.json'))}
    judge = reader.json(prefix + 'judge.json', {})
    props = reader.json(prefix + 'proposals.json')
    raw_registration = reader.read(prefix + 'preregistered.json')
    registration = _json(raw_registration) if raw_registration else None
    digest = reader.read(prefix + 'preregistered.sha256')
    digest = digest.decode().strip() if digest else None
    detail = {**result, 'score': _pick(reader.json(prefix + 'score.json'), ('questions', 'verdicts', 'added')),
              'judge_events': [_pick(event, ('round', 'claim_id', 'version', 'from', 'to', 'needs_revision', *STATS))
                               for event in judge.get('events', [])],
              'proposals': {'new_count': len(props.get('new', [])), 'revision_count': len(props.get('revisions', {})),
                            'rejections': props.get('rejections', {}),
                            'qwen': _pick(props.get('qwen'), ('calls', 'cached', 'errors', 'failovers'))} if props else None,
              'registration': {'count': len(registration.get('claims', [])), 'hash': digest,
                               'hash_matches': hashlib.sha256(raw_registration).hexdigest() == digest if digest else None} if registration else None,
              'registered': [_claim(c) for c in registration.get('claims', [])] if registration else []}
    return result, detail


def collect(root: Path, process_state='unknown') -> dict:
    reader = Reader(root)
    raw_claims = reader.json('claims.json', required=True)['claims']
    if not isinstance(raw_claims, dict):
        raise SourceUnavailable('Invalid claims artifact')
    versions = reader.rows('claim_versions.jsonl')
    ledger = reader.rows('ledger.jsonl')
    records = reader.rows('records.jsonl')
    question_fields = ('question_id', 'round', 'purpose', 'family', 'type', 'dataset_id',
                       'winner', 'winner_separates', 'candidates', 'comparisons')
    questions = {row['question_id']: _pick(row, question_fields) for row in records}
    by_claim = {}
    for row in ledger:
        key = (row['claim_id'], row['version'], row['question_id'])
        by_claim[key] = row  # protect one question / one claim against duplicate append records
    ledger_by_version, history_by_claim = {}, {}
    for (cid, version, _), row in by_claim.items():
        ledger_by_version.setdefault((cid, version), []).append(row)
    for version in versions:
        history_by_claim.setdefault(version['id'], []).append(version)
    claims, details = [], {}
    for cid, raw in raw_claims.items():
        claim = _claim(raw)
        evidence = [row for row in ledger_by_version.get((cid, raw['version']), [])
                    if row['round'] > raw['registered_round']]
        support = sum(row['outcome'] == 'support' for row in evidence)
        claim['evidence'] = {'applicable': len(evidence), 'support': support,
                             'refute': sum(row['outcome'] == 'refute' for row in evidence),
                             'conflicts': sum(row.get('conflicts', 0) for row in evidence)}
        rows = []
        for row in reversed(evidence[-MAX_EVIDENCE:]):
            public = _pick(row, ('claim_id', 'version', 'question_id', 'round', 'outcome', 'pairs', 'conflicts'))
            public['question'] = questions.get(row['question_id'])
            rows.append(public)
        details[cid] = {'claim': claim, 'history': [_claim(v) for v in history_by_claim.get(cid, [])],
                        'evidence': rows, 'evidence_total': len(evidence), 'evidence_truncated': len(evidence) > len(rows)}
        claims.append(claim)
    counts = Counter(claim['status'] for claim in claims)
    names = [name for name in reader.names('rounds') if re.fullmatch(r'round_\d{4,}', name)]
    indices = sorted(int(name.split('_')[1]) for name in names)
    # Source resumes the earliest incomplete round, not necessarily the newest.
    done = {index: reader.read(f'rounds/round_{index:04d}/DONE_report') is not None for index in indices}
    current = next((index for index in indices if not done[index]), (indices[-1] + 1) if indices else 1)
    selected = sorted(set(indices[-MAX_ROUNDS:] + [current]))
    rounds, round_details = [], {}
    for index in selected:
        summary, detail = _round(reader, index)
        round_details[str(index)] = detail
        if index in indices:
            rounds.append(summary)
    current_summary = round_details[str(current)]
    next_stage = next((stage for stage in STAGES if stage not in current_summary['completed_stages']), None)
    raw_config = reader.read('config.yaml')
    config = yaml.safe_load(raw_config) if raw_config else {}
    judge_cfg = _pick((config or {}).get('judge'), THRESHOLDS)
    thresholds = {key: val for key, val in judge_cfg.items() if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)}
    execution = {'status': process_state if process_state in ('running', 'stopped') else 'unknown',
                 'stop_requested': reader.read('STOP') is not None, 'alert': reader.read('ALERT') is not None}
    source_updated_at = reader.finish()
    return {'captured_at': time.time(), 'source_updated_at': source_updated_at, 'execution': execution,
            'round': {key: current_summary[key] for key in ('index', 'completed_stages', 'plan', 'build')} | {'next_stage': next_stage},
            'kb': {'claims': len(claims), **{status: counts[status] for status in STATUSES}},
            'evidence': {'questions': len(questions), 'verdicts': len(by_claim)},
            'claims': claims, 'rounds': rounds, 'thresholds': thresholds,
            'claim_details': details, 'round_details': round_details}


def process_state(root: Path) -> str:
    """Attest only presence of a loop process for this exact configured root."""
    proc = Path('/proc')
    if not proc.is_dir():
        return 'unknown'
    unknown = False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().decode().split('\0')
            if not any(arg.endswith('/kb_loop/loop.py') for arg in args) or not any(arg in ('run-forever', 'round') for arg in args):
                continue
            index = args.index('--root')
            configured = Path(args[index + 1])
            if not configured.is_absolute():
                configured = (entry / 'cwd').resolve() / configured
            if configured.resolve() == root.resolve():
                return 'running'
        except (ProcessLookupError, FileNotFoundError):
            continue
        except (OSError, ValueError, IndexError, UnicodeError):
            unknown = True
    return 'unknown' if unknown else 'stopped'


if __name__ == '__main__':
    try:
        source_root = Path(sys.argv[1])
        print(json.dumps(collect(source_root, process_state(source_root)), ensure_ascii=False, allow_nan=False))
    except Exception:
        # Never send raw paths, source config or tracebacks over the public API.
        print(json.dumps({'error': 'source_unavailable'}))
        sys.exit(1)
