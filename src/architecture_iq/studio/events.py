"""Stable execution attribution; stage events and provider text use distinct cursors."""
from __future__ import annotations

NODE_STEPS = {
    'retrieval': ('harness', 'retrieve'), 'input': ('data', 'assemble'), 'solver': ('harness', 'solve'),
    'commit': ('harness', 'commit'), 'reveal': ('harness', 'feedback'),
    'discoverer': ('harness', 'hypothesize'), 'skeptic': ('harness', 'skeptic'),
    'experiment': ('harness', 'experiment'), 'confirmation': ('harness', 'confirmation'),
    'analyst': ('harness', 'analysis'), 'curator': ('kb', 'curate'),
    'publish': ('kb', 'publish'), 'loop': ('kb', 'loop'),
    'experience_curator': ('harness', 'experience_consolidate'),
    'experience_save': ('kb', 'experience_save'),
    'evaluate': ('task', 'evaluate'), 'end': ('kb', 'end'),
}


def attribution(run_id: str, value: dict, *, attempt_id: str | None = None) -> dict:
    stage, step = NODE_STEPS.get(value.get('node_id'), (None, None))
    index = value.get('round_index')
    return {
        'run_id': run_id,
        'round_id': f'{run_id}:round:{index}' if index is not None else None,
        'stage_id': value.get('stage_id') or stage,
        'step_id': value.get('step_id') or step,
        'item_id': value.get('item_id') or value.get('question_id') or value.get('question_key') or value.get('pair_id') or value.get('operation_key') or value.get('key'),
        'attempt_id': attempt_id or value.get('attempt_id') or value.get('operation_key') or value.get('key'),
    }


def stage_event(run_id: str, sequence: int, value: dict) -> dict:
    kind = value.get('type')
    if kind == 'stage':
        kind = {'ready': 'step_queued', 'running': 'step_started',
                'complete': 'step_completed', 'failed': 'step_failed',
                'skipped': 'step_skipped'}.get(value.get('state'), 'stage_observed')
    elif kind == 'complete':
        kind = 'run_completed'
    return {**value, **attribution(run_id, value), 'event_type': kind,
            'sequence': sequence, 'event_id': f'{run_id}:stage:{sequence}',
            'artifact_refs': value.get('artifact_refs', [])}
