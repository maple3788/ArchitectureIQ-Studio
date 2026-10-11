"""Read-only, provenance-checked views of durable workflow artifacts.

This reader deliberately does not invoke execution verification: historical runs
remain inspectable after code upgrades. It never executes or repairs artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

from architecture_iq.kb.roles import read_receipt
from architecture_iq.kb.store import canonical_hash

_ROLES = {'solver', 'discoverer', 'skeptic', 'analyst', 'curator', 'experience_curator'}
_ARTIFACT_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError)


def node_observations(job: dict, directory: Path) -> list[dict]:
    if job.get('kind') in {'rule_refinement', 'rule_evaluation'}:
        from .rule_refinement.views import refinement_observations
        return refinement_observations(job, directory)
    if job.get('kind') != 'workflow':
        return []
    events = [event for event in job.get('events', [])
              if isinstance(event, dict) and event.get('type', 'stage') == 'stage']
    stages = {}
    for event in events:
        if not event.get('node_id') or event.get('candidate_id'):
            continue
        identity = (event['node_id'], event.get('round_index', 0), event.get('key'), event.get('step_id'))
        stages[identity] = event
    for node in job.get('config', {}).get('workflow', {}).get('nodes', []):
        if not any(key[0] == node['id'] for key in stages):
            stages[(node['id'], 0, None, None)] = {'node_id': node['id']}
    rows = []
    config = job['config']
    declared = Path(config['output_root']).resolve() if config.get('output_root') else Path(directory).resolve().parent
    root = declared / job['id'] / 'workflow' if config.get('output_root') else Path(directory).resolve() / 'workflow'

    def path(relative):
        target = root / relative
        if root.resolve() != root or target.resolve() != target or not target.is_relative_to(root):
            raise ValueError('Artifact path escapes the declared workflow directory or uses a symlink')
        return target

    def load(relative):
        return json.loads(path(relative).read_text())

    def receipt(relative):
        return read_receipt(path(relative))

    problem = None
    try:
        manifest = load('manifest.json')
        public = load('public_questions.json')
        private = load('private_feedback.json')
        actual_config = load('config.json')
        for name, value in [('public_questions.json', public), ('private_feedback.json', private), ('config.json', actual_config)]:
            if canonical_hash(value) != manifest['inputs'][name]:
                raise ValueError('Frozen workflow input integrity failure')
        from .task_inputs import workflow_inputs
        from .workflow import compile_workflow
        phase = compile_workflow(config['workflow'])['evaluate_phase'] if config.get('workflow') else None
        expected_public, expected_private = workflow_inputs(config['question_set'], config.get('task_question_set'), phase=phase)
        if canonical_hash(public) != canonical_hash(expected_public) or canonical_hash(private) != canonical_hash(expected_private):
            raise ValueError('Workflow inputs differ from frozen job inputs')
        if actual_config != manifest['config']:
            raise ValueError('Workflow config differs from manifest')
        by_id = {q['id']: q for q in public}
    except _ARTIFACT_ERRORS as exc:
        problem = str(exc)

    def round_ids(index):
        ids = manifest['round_questions'][str(index)]
        if not ids or len(ids) != len(set(ids)) or any(by_id[q].get('split', 'discovery') != 'discovery' for q in ids):
            raise ValueError('Invalid discovery round membership')
        return ids

    def answer(index, key):
        if key not in round_ids(index):
            raise ValueError('Answer is not a member of this round')
        name = f'rounds/{index}/answers/{canonical_hash(key)}.json'
        saved = receipt(name)
        result = saved['result']
        if not isinstance(result, dict):
            raise ValueError('Invalid committed answer shape')
        # Missing older call receipts leave a partial answer view. An existing
        # receipt must verify and bind this answer to this question and round.
        try:
            solver, _ = call('solver', key, index)
        except FileNotFoundError:
            solver = None
        if solver is not None:
            if solver.get('status') != 'complete' or saved.get('input_hash') != canonical_hash(solver['result']):
                raise ValueError('Committed answer differs from its Solver result')
            if 'raw' in result and result['raw'] != solver['result']:
                raise ValueError('Committed answer raw response differs from its Solver result')
        return result, name

    def revealed(index):
        if not any(e.get('node_id') == 'reveal' and e.get('round_index') == index and e.get('state') == 'complete' for e in events):
            raise ValueError('Feedback has not been revealed')
        for key in round_ids(index):
            if not any(e.get('node_id') == 'commit' and e.get('round_index') == index
                       and e.get('key') == key and e.get('state') == 'complete' for e in events):
                raise ValueError('A designated answer has no completed commit event')
            answer(index, key)

    def call(role, key, index):
        identity = canonical_hash({'role': role, 'key': key, 'round': index})
        name = f'calls/{identity}.json'
        value = receipt(name)
        if value.get('id') != identity or (value.get('role'), value.get('key'), value.get('round_index')) != (role, key, index):
            raise ValueError('Role receipt identity mismatch')
        if canonical_hash(value['request']) != value['request_hash']:
            raise ValueError('Role request integrity failure')
        return value, name

    for (node, index, key, step), event in stages.items():
        row = {'node_id': node, 'round_index': index, 'source': [], 'availability': 'unavailable'}
        if key is not None:
            row['key'] = key
        for field in ('step_id', 'stage_id'):
            if event.get(field):
                row[field] = event[field]
        try:
            if problem:
                raise ValueError(problem)
            if node == 'end' and job.get('status') == 'complete' and job.get('result'):
                row.update(output=job['result'], source=['job/result.json'])
            elif event.get('state') != 'complete':
                raise ValueError('No completed stage is attested; input/output has not been exposed')
            elif node == 'input':
                ids = round_ids(index)
                row.update(input={'question_ids': ids}, output=[by_id[q] for q in ids], source=['manifest.json', 'public_questions.json'])
            elif node == 'commit':
                value, name = answer(index, key)
                row.update(output=value, source=[name])
                try:
                    saved, name = call('solver', key, index)
                    if saved.get('status') == 'complete':
                        row['input'] = saved['result']
                        row['source'].append(name)
                except _ARTIFACT_ERRORS:
                    pass  # Older/incomplete runs can retain only the answer.
            elif node == 'reveal':
                revealed(index)
                ids = round_ids(index)
                row.update(input={'committed_question_ids': ids}, output={q: private[q] for q in ids}, source=['private_feedback.json', *[f'rounds/{index}/answers/{canonical_hash(q)}.json' for q in ids]])
            elif node in _ROLES or (node == 'evaluate' and key):
                if node in _ROLES - {'solver'}:
                    revealed(index)
                role = 'solver' if node == 'evaluate' else node
                if node == 'discoverer' and event.get('role') in {'pair_researcher', 'experience_curator'}:
                    role = event['role']
                saved, name = call(role, key, index)
                row.update(input=saved['request'], source=[name])
                if saved.get('status') == 'complete':
                    row['output'] = {k: saved[k] for k in ('result', 'raw', 'finish_reason', 'status') if k in saved}
            elif node in {'experiment', 'confirmation'} and key:
                phase = 'exploration' if node == 'experiment' else 'confirmation'
                name = f'rounds/{index}/experiments/{phase}_{canonical_hash(key)[:16]}/coordinator_receipt.json'
                saved = receipt(name)
                if saved.get('status') != 'complete' or canonical_hash(saved['request']) != saved['input_hash'] or saved['request'].get('claim_id') != key or saved['request'].get('phase') != phase:
                    raise ValueError('Experiment is incomplete or its request differs')
                row.update(input=saved['request'], output=saved['records'], source=[name])
            elif node == 'experience_save':
                revealed(index)
                name = f'rounds/{index}/result.json'
                result = receipt(name)['result']
                experience = result['experience']
                version = experience['after']
                if not isinstance(version, str) or len(version) != 64 or any(c not in '0123456789abcdef' for c in version):
                    raise ValueError('Invalid experience version')
                snapshot_name = f'experience/snapshots/{version}.json'
                snapshot = load(snapshot_name)
                if snapshot.get('version') != version or canonical_hash({k: v for k, v in snapshot.items() if k != 'version'}) != version:
                    raise ValueError('Experience snapshot integrity failure')
                if snapshot['parent_version'] != experience['before'] or snapshot['operations'] != experience['operations']:
                    raise ValueError('Experience snapshot differs from sealed round')
                row.update(input={'parent_version': experience['before'], 'operations': experience['operations']},
                           output=snapshot, source=[name, snapshot_name])
            elif node in {'publish', 'loop'}:
                name = f'rounds/{index}/result.json'
                result = receipt(name)['result']
                if node == 'loop':
                    row.update(output=result, source=[name])
                else:
                    patch_name, evidence_name = f'rounds/{index}/patch.json', f'rounds/{index}/evidence.json'
                    patch, evidence = receipt(patch_name)['result'], receipt(evidence_name)['result']
                    version = result['kb_after']
                    if not isinstance(version, str) or len(version) != 64 or any(c not in '0123456789abcdef' for c in version):
                        raise ValueError('Invalid published version')
                    snapshot_name = f'kb/snapshots/{version}.json'
                    snapshot = load(snapshot_name)
                    if snapshot.get('version') != version or canonical_hash({k: v for k, v in snapshot.items() if k != 'version'}) != version:
                        raise ValueError('Published KB snapshot integrity failure')
                    row.update(input={'patch': patch, 'evidence': evidence}, output=snapshot, source=[name, patch_name, evidence_name, snapshot_name])
            elif node == 'evaluate':
                # Full evaluation contains private scoring only after all arms
                # completed. Result paths come from the fixed phase directory.
                phase = event.get('phase')
                if phase not in {'development', 'final'}:
                    raise ValueError('No completed evaluation phase')
                candidates = list(path(f'evals/{phase}').glob('*/result.json'))
                matches = []
                for candidate in candidates:
                    name = str(candidate.relative_to(root))
                    result = receipt(name)['result']
                    if result.get('phase') == phase:
                        matches.append((name, result))
                if len(matches) != 1:
                    raise ValueError('Evaluation snapshot cannot be uniquely identified')
                name, result = matches[0]
                row.update(output=result, source=[name])
            else:
                raise ValueError('No independently persisted input/output for this stage')
            row['availability'] = 'available' if 'input' in row and 'output' in row else 'partial'
            if row['availability'] == 'partial':
                row['reason'] = 'Only the persisted side is available; missing data is not reconstructed'
        except _ARTIFACT_ERRORS as exc:
            row.pop('input', None)
            row.pop('output', None)
            row['reason'] = str(exc)
        rows.append(row)
    return rows
