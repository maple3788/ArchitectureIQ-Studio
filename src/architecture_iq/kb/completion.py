"""Seal early learning completion without changing the frozen round cap."""
from __future__ import annotations

from pathlib import Path
import json
import time

from .roles import _seal, exclusive_lock, read_receipt
from .store import KBStore, canonical_hash, write_json_atomic

REASONS = {"finish", "evaluate", "round_cap", "no_next_batch", "no_change"}


def _round_hashes(out: Path, completed_rounds: int) -> dict:
    paths = list((out / 'rounds').glob('*/result.json'))
    expected = {str(index) for index in range(1, completed_rounds + 1)}
    if {path.parent.name for path in paths} != expected:
        raise ValueError('Completed round receipts differ from learning completion')
    hashes = {}
    for index in range(1, completed_rounds + 1):
        record = read_receipt(out / 'rounds' / str(index) / 'result.json')
        result = record['result']
        if result.get('round') != index or result.get('status') != 'complete':
            raise ValueError('Learning requires sealed complete round results')
        hashes[str(index)] = record['receipt_hash']
    return hashes


def _identity(out: Path, manifest: dict, completed_rounds: int) -> dict:
    if type(completed_rounds) is not int or not 1 <= completed_rounds <= manifest['config']['max_rounds']:
        raise ValueError('Invalid completed round count')
    if json.loads((out / 'manifest.json').read_text()) != manifest:
        raise ValueError('Learning completion manifest differs from disk')
    return {'manifest_hash': canonical_hash(manifest), 'completed_rounds': completed_rounds,
            'round_result_hashes': _round_hashes(out, completed_rounds)}


def seal_learning_complete(out: Path, manifest: dict, completed_rounds: int, *, reason: str) -> dict:
    """Idempotently seal one terminal boundary; a different boundary is forbidden."""
    if reason not in REASONS:
        raise ValueError('Unsupported learning completion reason')
    out = Path(out)
    with exclusive_lock(out / 'workflow.lock'):
        identity = _identity(out, manifest, completed_rounds)
        path = out / 'learning_completion.json'
        if path.exists():
            saved = read_receipt(path)
            if any(saved.get(key) != value for key, value in identity.items()) or saved.get('reason') != reason:
                raise RuntimeError('Learning completion is immutable')
            return saved
        last = read_receipt(out / 'rounds' / str(completed_rounds) / 'result.json')['result']
        record = _seal({**identity, 'reason': reason, 'kb_version': last['kb_after'],
                        'status': 'complete', 'completed_at': time.time()})
        write_json_atomic(path, record)
        return record


def require_learning_complete(out: Path, manifest: dict, completed_rounds: int) -> None:
    """Accept historical cap-complete runs or an intact sealed early completion."""
    out = Path(out)
    identity = _identity(out, manifest, completed_rounds)
    path = out / 'learning_completion.json'
    if not path.exists():
        if completed_rounds != manifest['config']['max_rounds']:
            raise RuntimeError('Learning must complete before final evaluation')
        return
    saved = read_receipt(path)
    if saved.get("reason") not in REASONS:
        raise ValueError("Invalid learning completion reason")
    for key, value in identity.items():
        if saved.get(key) != value:
            raise ValueError(f'Learning completion {key} integrity failure')
    last = read_receipt(out / 'rounds' / str(completed_rounds) / 'result.json')['result']
    if saved.get('status') != 'complete' or saved.get('kb_version') != last['kb_after']:
        raise ValueError('Learning completion round KB integrity failure')

    if (out / 'kb' / 'CURRENT').exists() and KBStore(out / 'kb').current()['version'] != saved['kb_version']:
        raise ValueError('Learning completion KB version differs from current frozen version')

    experience_version = last.get('experience', {}).get('after')
    if experience_version is not None:
        from .experience import ExperienceStore
        if ExperienceStore(out / 'experience').current()['version'] != experience_version:
            raise ValueError('Learning completion experience version differs from frozen round')
