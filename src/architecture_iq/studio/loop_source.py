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
# The transport is standalone, so it cannot import Studio's Catalog on the
# execution host. Limit its spec payload to public structural names; the local
# Catalog applies its shared, stricter typed schemas before persistence.
SPEC_KEYS = 'schema_version candidate_id dataset_id family profile profile_hash budget model optimizer loss execution trainable_parameter_count selection_metric params seeds seed synthesis task'.split()
SPEC_PARTS = {
    'model': 'depth width input_dim output_dim vocab_size context_length d_model embed_dim num_layers num_heads d_ff ff_dim type activation activations layer_norm residual layer_residual leaky_relu_slope',
    'optimizer': 'type lr weight_decay momentum betas', 'loss': 'loss_id type lambda',
    'params': 'instance_seed input_dim output_dim num_classes train_size test_size vocab_size context_length sequence_seed table_seed n_active_features alpha spiral_turns noise_std margin label_noise scale expression rule_family layout domain active_features sampler point_sampling',
    'budget': 'training_steps batch_size total_samples_seen mixed', 'execution': 'device',
    'seeds': 'expression point sequence table', 'sampler': 'id seed max_depth retry',
    'point_sampling': 'distribution seed',
}


class SourceUnavailable(ValueError):
    """The source could not be read as one stable observation."""


def _pick(value, keys):
    return {key: value[key] for key in keys if key in value} if isinstance(value, dict) else {}


def _transport_spec(value, keys=SPEC_KEYS):
    result = _pick(value, keys)
    for key, item in list(result.items()):
        if isinstance(item, dict):
            result[key] = _transport_spec(item, SPEC_PARTS.get(key, '').split())
    return result


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


def _claim_detail(raw, history, evidence, questions):
    """Project a bounded evidence window after the caller fixes its scope."""
    claim = _claim(raw)
    claim['evidence'] = {'applicable': len(evidence),
                         'support': sum(row['outcome'] == 'support' for row in evidence),
                         'refute': sum(row['outcome'] == 'refute' for row in evidence),
                         'conflicts': sum(row.get('conflicts', 0) for row in evidence)}
    def evidence_row(row):
        public = _pick(row, ('claim_id', 'version', 'question_id', 'round', 'outcome', 'pairs', 'conflicts'))
        public['question'] = questions.get((row['question_id'], row['round']), questions.get(row['question_id']))
        return public
    rows = [evidence_row(row) for row in reversed(evidence[-MAX_EVIDENCE:])]
    refutes = [row for row in evidence if row['outcome'] == 'refute']
    return {'claim': claim, 'history': [_claim(v) for v in history],
            'evidence': rows, 'evidence_total': len(evidence), 'evidence_truncated': len(evidence) > len(rows),
            'counterexamples': {'items': [evidence_row(row) for row in reversed(refutes[-MAX_EVIDENCE:])],
                                'total': len(refutes), 'truncated': len(refutes) > MAX_EVIDENCE}}


def _claim_at_judgment(raw, event):
    """Mutable current status/stats must not leak into a historical judgment."""
    claim = _claim(raw)
    claim['status'] = event.get('to') or 'unknown'
    claim['stats'] = _pick(event, STATS) or None
    claim['needs_revision'] = event.get('needs_revision')
    return claim


def _generation_question(question):
    """Only public structural scalars belong in the generated-question list."""
    candidates = question.get('candidates') if isinstance(question, dict) else None
    if not isinstance(candidates, dict) or not 1 <= len(candidates) <= 26:
        return None
    projected = {}
    for cid, raw in candidates.items():
        if not isinstance(cid, str) or not 1 <= len(cid) <= 256 or not isinstance(raw, dict):
            continue
        view = {}
        for key in ('depth', 'width', 'lr', 'weight_decay', 'momentum', 'budget', 'steps', 'batch_size',
                    'num_layers', 'd_model', 'd_ff', 'num_heads'):
            value = raw.get(key)
            if type(value) in (int, float) and math.isfinite(value):
                view[key] = value
        for key in ('model_type', 'activation', 'opt'):
            value = raw.get(key)
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', value):
                view[key] = value
        for key in ('residual', 'layer_residual'):
            if type(raw.get(key)) is bool:
                view[key] = raw[key]
        if view:
            projected[cid] = view
    return {'candidates': projected} if projected else None


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
    items = []
    for row in planned:
        item = _pick(row, ('item_id', 'family', 'question_type', 'budget', 'purpose', 'targets'))
        saved = built.get(row['item_id'])
        item['status'] = saved['status'] if saved else 'pending'
        if saved:
            item.update(_pick(saved, ('seconds',)))
            if saved['status'] == 'ok':
                item.update(_pick(saved, ('question_id',)))
        items.append(item)
    generation = {'total': len(items), 'completed': sum(item['status'] != 'pending' for item in items),
                  'ok': sum(item['status'] == 'ok' for item in items),
                  'failed': sum(item['status'] in ('failed', 'crashed') for item in items),
                  'pending': sum(item['status'] == 'pending' for item in items), 'items': items}
    result = {'index': index, 'completed': 'report' in completed, 'completed_stages': completed,
              'plan': plan, 'build': build, 'report': _report(reader.json(prefix + 'report.json'))}
    judge = reader.json(prefix + 'judge.json', {})
    props = reader.json(prefix + 'proposals.json')
    raw_registration = reader.read(prefix + 'preregistered.json')
    registration = _json(raw_registration) if raw_registration else None
    digest = reader.read(prefix + 'preregistered.sha256')
    digest = digest.decode().strip() if digest else None
    detail = {**result, 'generation': generation,
              'score': _pick(reader.json(prefix + 'score.json'), ('questions', 'verdicts', 'added')),
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
    question_history, historical_questions = {}, {}
    for row in records:
        if type(row.get('round')) is int:
            question_history.setdefault(row['question_id'], []).append(_pick(row, question_fields))
    by_claim, ledger_history = {}, {}
    for row in ledger:
        key = (row['claim_id'], row['version'], row['question_id'])
        by_claim[key] = row  # protect one question / one claim against duplicate append records
        ledger_history.setdefault(key[:2], []).append(row)
    ledger_by_version, history_by_claim = {}, {}
    for (cid, version, _), row in by_claim.items():
        ledger_by_version.setdefault((cid, version), []).append(row)
    for version in versions:
        history_by_claim.setdefault(version['id'], []).append(version)
    claims, details = [], {}
    for cid, raw in raw_claims.items():
        evidence = [row for row in ledger_by_version.get((cid, raw['version']), [])
                    if row['round'] > raw['registered_round']]
        details[cid] = _claim_detail(raw, history_by_claim.get(cid, []), evidence, questions)
        claims.append(details[cid]['claim'])
    counts = Counter(claim['status'] for claim in claims)
    names = [name for name in reader.names('rounds') if re.fullmatch(r'round_\d{4,}', name)]
    indices = sorted(int(name.split('_')[1]) for name in names)
    # Source resumes the earliest incomplete round, not necessarily the newest.
    done = {index: reader.read(f'rounds/round_{index:04d}/DONE_report') is not None for index in indices}
    current = next((index for index in indices if not done[index]), (indices[-1] + 1) if indices else 1)
    selected = sorted(set(indices[-MAX_ROUNDS:] + [current]))
    rounds, round_details = [], {}
    version_claims = {(raw['id'], raw['version']): raw for raw in [*raw_claims.values(), *versions]}
    for index in selected:
        summary, detail = _round(reader, index)
        for item in detail['generation']['items']:
            public = _generation_question(questions.get(item.get('question_id')))
            if item.get('status') == 'ok' and public:
                item['question'] = public
        # Capture only revisions referenced by this bounded round window.
        # Reading later must not depend on the current revision's ledger.
        registered = {(raw['id'], raw['version']): raw for raw in detail['registered']}
        events = {(event.get('claim_id'), event.get('version')): event for event in detail['judge_events']}
        round_claims = {}
        for cid, version in registered.keys() | events.keys():
            raw = registered.get((cid, version)) or version_claims.get((cid, version))
            if not raw or type(raw.get('registered_round')) is not int or raw['registered_round'] > index:
                continue
            if (cid, version) in events:
                raw = _claim_at_judgment(raw, events[cid, version])
            # Apply the cutoff before deduplication: a later repeated question
            # must not replace its earlier persisted result in an older round.
            evidence = list({row['question_id']: row for row in ledger_history.get((cid, version), [])
                             if raw['registered_round'] < row['round'] <= index}.values())
            history = [item for item in history_by_claim.get(cid, [])
                       if item['version'] <= version and item.get('registered_round', index + 1) <= index]
            for row in evidence:
                key = (row['question_id'], row['round'])
                if key not in historical_questions:
                    # Resume/repeated-question records can arrive later than
                    # this claim's verdict. Bind the summary to the verdict's
                    # own round, including when another claim saw a newer one.
                    historical_questions[key] = max(
                        (question for question in reversed(question_history.get(row['question_id'], []))
                         if question['round'] <= row['round']),
                        key=lambda question: question['round'], default=None)
            saved = _claim_detail(raw, history[-MAX_EVIDENCE:], evidence, historical_questions)
            saved.update(reading_round=index, evidence_unavailable=False,
                         history_truncated=len(history) > MAX_EVIDENCE)
            round_claims.setdefault(cid, {})[str(version)] = saved
        detail['claim_details'] = round_claims
        # A question often tests several claims and appears in both evidence
        # windows. Persist its large public summary once within this round.
        evidence_questions = {}
        for revisions in round_claims.values():
            for saved in revisions.values():
                for row in [*saved['evidence'], *saved['counterexamples']['items']]:
                    question = row.pop('question', None)
                    if question is not None:
                        evidence_questions[f"{row['round']}:{row['question_id']}"] = question
        detail['evidence_questions'] = evidence_questions
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


def _stored_curve(data, *, candidate_id, letter, metric):
    """Summarize saved seed curves at their saved axis; never run the engine."""
    if data is None:
        return None
    import io
    import zipfile
    try:
        import numpy as np
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_FILE_BYTES:
                return None
        with np.load(io.BytesIO(data), allow_pickle=False) as archive:
            if 'curves' not in archive or 'samples' not in archive:
                return None
            curves, samples = archive['curves'], archive['samples']
            if (curves.dtype.kind not in 'fiu' or samples.dtype.kind not in 'fiu'
                    or curves.ndim != 2 or samples.ndim != 1 or not 1 <= len(samples) <= 100000
                    or curves.shape[1] != len(samples) or not 1 <= curves.shape[0] <= 1000
                    or curves.size > 1000000 or not np.all(np.isfinite(samples))
                    or not np.all(np.diff(samples) > 0)):
                return None
            # Failed seeds are saved as NaNs. Retain real sample positions and
            # omit a curve when any position has no saved finite observation.
            valid = np.isfinite(curves)
            if not np.all(valid.sum(axis=0) > 0):
                return None
            saved = np.where(valid, curves, np.nan)
            means, deviations = np.nanmean(saved, axis=0), np.nanstd(saved, axis=0)
            if not np.all(np.isfinite(means)) or not np.all(np.isfinite(deviations)):
                return None
            return {'candidateId': candidate_id, 'letter': letter, 'metric': metric,
                    'samples': samples.tolist(), 'mean': means.tolist(), 'std': deviations.tolist()}
    except (ImportError, ValueError, TypeError, KeyError, OSError, zipfile.BadZipFile):
        return None


def collect_question(root: Path, artifact_root: Path, identifier: str, *, include_results=False) -> dict:
    """Read one completed question, without importing or running the engine.

    Source build receipts authorize the lookup. The browser's identifier never
    becomes a filesystem path. Public spec projection is applied again locally
    before the result is persisted or delivered.
    """
    if not isinstance(identifier, str) or not re.fullmatch(r'q_[A-Za-z0-9_-]{1,80}', identifier):
        raise KeyError('Question unavailable')
    source, artifacts = Reader(root), Reader(artifact_root)
    references = set()
    for name in source.names('rounds'):
        if not re.fullmatch(r'round_\d{4,}', name):
            continue
        built = {}
        for row in source.rows(f'rounds/{name}/build.jsonl'):
            if row['status'] == 'ok' or row['item_id'] not in built:
                built[row['item_id']] = row
        for row in built.values():
            if row.get('status') == 'ok' and row.get('question_id') == identifier:
                reference = row.get('question_path')
                if not isinstance(reference, str):
                    raise SourceUnavailable('Question receipt unavailable')
                references.add(reference)
    if not references:
        raise KeyError('Question unavailable')
    if len(references) != 1:
        raise SourceUnavailable('Ambiguous question receipts')
    path = Path(references.pop())
    if '..' in path.parts or path.name != 'question.json' or path.parent.name != identifier:
        raise SourceUnavailable('Invalid question artifact')
    if path.is_absolute():
        try:
            path = path.relative_to(artifacts.root)
        except ValueError as exc:
            raise SourceUnavailable('Question outside artifact root') from exc
    question = artifacts.json(str(path), required=True)
    if not isinstance(question, dict) or question.get('question_id') != identifier:
        raise SourceUnavailable('Question identity mismatch')
    family, dataset_id = question.get('family'), question.get('dataset_id')
    if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value)
           for value in (family, dataset_id)):
        raise SourceUnavailable('Invalid dataset identity')
    dataset_path = Path('datasets') / family / dataset_id
    dataset = artifacts.json(str(dataset_path / 'dataset_spec.json'), required=True)
    if dataset.get('dataset_id') != dataset_id or dataset.get('family') != family:
        raise SourceUnavailable('Dataset identity mismatch')
    prompt = artifacts.read(str(path.parent / 'prompt.txt'), required=True).decode('utf-8')
    if not prompt.strip():
        raise SourceUnavailable('Question prompt unavailable')
    ds_files = {'dataset_spec.json': _transport_spec(dataset)}
    synthesis = artifacts.read(str(dataset_path / 'synthesize.py'))
    if synthesis is not None:
        ds_files['synthesize.py'] = synthesis.decode('utf-8')
    raw_choices = question.get('choices')
    if not isinstance(raw_choices, list) or not 1 <= len(raw_choices) <= 26:
        raise SourceUnavailable('Question choices unavailable')
    choices, details, ids, letters = [], [], set(), set()
    metric = question.get('evaluation', {}).get('selection_metric') or dataset.get('selection_metric')
    feedback = {'candidate_metrics': {}, 'reveal': {'curves': []}}
    for item in raw_choices:
        cid, letter, reference = item.get('candidate_id'), item.get('letter'), item.get('candidate_path')
        if (not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', cid)
                or not isinstance(letter, str) or not re.fullmatch(r'[A-Z]', letter)
                or cid in ids or letter in letters or not isinstance(reference, str)):
            raise SourceUnavailable('Invalid question choice')
        candidate = Path(reference)
        if (candidate.is_absolute() or '..' in candidate.parts
                or not candidate.is_relative_to(dataset_path / 'candidates') or candidate.name != cid):
            raise SourceUnavailable('Invalid candidate path')
        spec = artifacts.json(str(candidate / 'candidate_spec.json'), required=True)
        if spec.get('candidate_id') != cid or spec.get('dataset_id') != dataset_id or spec.get('family') != family:
            raise SourceUnavailable('Candidate identity mismatch')
        files = {'candidate_spec.json': _transport_spec(spec)}
        for filename in ('model.py', 'optimizer.py', 'loss.py', 'train.py'):
            code = artifacts.read(str(candidate / filename))
            if code is not None:
                files[filename] = code.decode('utf-8')
        choices.append({'id': cid, 'letter': letter, 'view': {}})
        details.append({'candidateId': cid, 'letter': letter, 'files': files})
        if include_results:
            # Read only the canonical saved result files, never their generated
            # train.py, callable modules, configurations, or private environment.
            raw = artifacts.read(str(candidate / 'results' / 'summary.json'))
            summary = json.loads(raw, parse_constant=lambda _: None) if raw is not None else None
            if summary is not None:
                if not isinstance(summary, dict) or summary.get('candidate_id') != cid:
                    raise SourceUnavailable('Result candidate identity mismatch')
                if summary.get('selection_metric', summary.get('metric', metric)) != metric:
                    raise SourceUnavailable('Result metric differs from question')
                shown = _pick(summary, ('selection_metric', 'metric', 'n_seeds', 'failed_seeds', 'excluded'))
                shown.update({key: value for key, value in summary.items()
                              if re.fullmatch(r'(mean|std)_(test|train)_[a-z0-9_]{1,48}', key)
                              and type(value) in (int, float) and math.isfinite(value)})
                feedback['candidate_metrics'][cid] = shown
            curve = _stored_curve(artifacts.read(str(candidate / 'results' / 'curves.npz')),
                                  candidate_id=cid, letter=letter, metric=metric)
            if curve:
                feedback['reveal']['curves'].append(curve)
        ids.add(cid)
        letters.add(letter)
    source.finish()
    artifacts.finish()
    result = {'metadata': {'id': identifier, **_pick(question, ('family', 'dataset_id', 'type', 'profile')),
                         'metric': question.get('evaluation', {}).get('selection_metric') or dataset.get('selection_metric')},
            'public': {'id': identifier, 'family': family, 'dataset_id': dataset_id, 'prompt': prompt, 'choices': choices},
            'detail': {'prompt': prompt, 'dataset': {'files': ds_files}, 'choices': details}}
    if include_results:
        if question.get('correct_letter') in letters:
            feedback['correct_letter'] = question['correct_letter']
        result['feedback'] = feedback
    return result


if __name__ == '__main__':
    try:
        source_root = Path(sys.argv[1])
        result = (collect_question(source_root, Path(sys.argv[3]), sys.argv[4], include_results=sys.argv[2] == '--practice')
                  if len(sys.argv) == 5 and sys.argv[2] in {'--question', '--practice'}
                  else collect(source_root, process_state(source_root)))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except KeyError:
        print(json.dumps({'error': 'question_missing'}))
        sys.exit(2)
    except Exception:
        # Never send raw paths, source config or tracebacks over the public API.
        print(json.dumps({'error': 'source_unavailable'}))
        sys.exit(1)
