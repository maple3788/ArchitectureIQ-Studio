"""Public, revision-specific pair manifests derived only from stored artifacts.

Pair identity is never inferred from choice letters or winner labels. Explicit
pairmap roles take precedence; older catalog records require every CF candidate
binding to attest the same original and effective datasets.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_ROLES = ('original', 'counterfactual')
_CONTROLS = ('model', 'optimizer', 'loss', 'budget')
_SELECTION_HISTORY = {'all_significant_pairs', 'outcome_selected_release', 'unknown'}
_HEX = re.compile(r'^[0-9a-f]{64}$')


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ''


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def pair_provenance(value: Any) -> dict:
    """Allowlist the persisted pairmap projection, excluding all outcome data."""
    value = _object(value)
    result = {key: value[key] for key in (
        'pair_id', 'lineage_id', 'role', 'dataset_id', 'original_dataset_id',
        'counterfactual_dataset_id', 'original_question_id', 'counterfactual_question_id', 'pairmap_hash')
        if isinstance(value.get(key), str)}
    if value.get('verification') == 'pairmap':
        result['verification'] = 'pairmap'
    if value.get('selection_history') in _SELECTION_HISTORY:
        result['selection_history'] = value['selection_history']
    if 'candidate_mapping' in value:
        rows = value['candidate_mapping']
        if not isinstance(rows, list) or len(rows) > 4096:
            raise ValueError('Pair candidate_mapping must be a bounded list')
        result['candidate_mapping'] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Pair candidate mapping entry must be an object')
            result['candidate_mapping'].append({key: row[key] for key in (
                'choice_identity', 'original_candidate_id', 'counterfactual_candidate_id')
                if isinstance(row.get(key), str)})
    return result


def _specs(record: dict) -> tuple[dict, dict[str, dict]]:
    # Reapply the catalog's structural projection even when called directly or
    # on records frozen by an earlier catalog version.
    from .catalog import _spec, _CANDIDATE_KEYS, _DATASET_KEYS
    detail = _object(record.get('detail'))
    dataset = _spec(_object(_object(detail.get('dataset')).get('files')).get('dataset_spec.json'), _DATASET_KEYS)
    choices = {}
    for choice in detail.get('choices', []):
        cid = _text(choice.get('candidateId'))
        if not cid or cid in choices:
            raise ValueError('Missing or duplicate candidate identity')
        spec = _spec(_object(choice.get('files')).get('candidate_spec.json'), _CANDIDATE_KEYS)
        choices[cid] = {'letter': choice.get('letter'), 'spec': spec}
    return dataset, choices


def _legacy_binding(record: dict) -> tuple[str, str, str] | None:
    metadata = _object(record.get('metadata'))
    choices = _object(record.get('detail')).get('choices', [])
    if not choices:
        return None
    attestations = []
    for choice in choices:
        provenance = _object(choice.get('provenance'))
        binding = _object(provenance.get('dataset_binding'))
        source = _object(provenance.get('source_candidate_spec'))
        effective = _object(_object(choice.get('files')).get('candidate_spec.json'))
        original_id = _text(binding.get('original_dataset_id'))
        effective_id = _text(binding.get('effective_dataset_id'))
        pairmap_hash = _text(binding.get('pairmap_hash'))
        if (binding.get('verification') != 'pairmap' or binding.get('pair_id') != metadata.get('pair_id')
                or not _HEX.fullmatch(pairmap_hash) or not original_id or original_id == effective_id
                or effective_id != metadata.get('dataset_id') or source.get('dataset_id') != original_id
                or effective.get('dataset_id') != effective_id
                or source.get('candidate_id') != choice.get('candidateId')
                or any(source.get(field) != effective.get(field) for field in _CONTROLS)):
            return None
        attestations.append((original_id, effective_id, pairmap_hash))
    return attestations[0] if len(set(attestations)) == 1 else None


def _roles(records: list[dict], issues: list[str]) -> tuple[list[str], list[dict], bool]:
    provenances = [pair_provenance(_object(record.get('detail')).get('pair_provenance')) for record in records]
    if any(provenances):
        roles = []
        attestations = set()
        for record, provenance in zip(records, provenances):
            meta = _object(record.get('metadata'))
            role = provenance.get('role')
            valid = (provenance.get('verification') == 'pairmap' and role in _ROLES
                and provenance.get('pair_id') == meta.get('pair_id')
                and _HEX.fullmatch(_text(provenance.get('pairmap_hash')))
                and provenance.get(role + '_dataset_id') == meta.get('dataset_id')
                and provenance.get(role + '_question_id') == meta.get('id'))
            roles.append(role if valid else 'unknown')
            if not valid:
                issues.append('Missing or inconsistent persisted pair role provenance')
            attestations.add(tuple(provenance.get(field, '') for field in (
                'original_dataset_id', 'counterfactual_dataset_id', 'original_question_id',
                'counterfactual_question_id', 'pairmap_hash')))
        if len(attestations) != 1:
            issues.append('Conflicting pairmap provenance across members')
        return roles, provenances, False
    bindings = [_legacy_binding(record) for record in records]
    verified = [(index, binding) for index, binding in enumerate(bindings) if binding]
    roles = ['unknown'] * len(records)
    if len(verified) == 1:
        cf_index, binding = verified[0]
        roles[cf_index] = 'counterfactual'
        for index, record in enumerate(records):
            if index != cf_index and _object(record.get('metadata')).get('dataset_id') == binding[0]:
                # Partial or contradictory provenance on an alleged original
                # must not be silently converted to an original role.
                if not any(choice.get('provenance') for choice in _object(record.get('detail')).get('choices', [])):
                    roles[index] = 'original'
    if 'unknown' in roles or len(verified) != 1:
        issues.append('Legacy pair requires every counterfactual candidate to attest one dataset binding')
    return roles, provenances, True


def _changes(original: dict, counterfactual: dict, path: str = '') -> list[dict]:
    changes = []
    for key in sorted(set(original) | set(counterfactual)):
        current = f'{path}.{key}' if path else key
        before, after = original.get(key), counterfactual.get(key)
        if isinstance(before, dict) and isinstance(after, dict):
            changes.extend(_changes(before, after, current))
        elif before != after:
            sampling = (current.startswith(('seeds', 'seed', 'params.point_sampling', 'params.sampler', 'params.calibration'))
                        or 'seed' in key or key in {'train_size', 'test_size'})
            changes.append({'path': current, 'before': before, 'after': after,
                            'kind': 'sampling' if sampling else 'dataset'})
    return changes


def _sampling_known(dataset: dict) -> bool:
    params = _object(dataset.get('params'))
    return (type(_object(params.get('point_sampling')).get('seed')) is int
            or all(type(params.get(key)) is int for key in ('table_seed', 'sequence_seed'))
            or bool(dataset.get('seeds')))


def pair_manifest(records: list[dict]) -> dict:
    """Validate an entire pair group, returning a public manifest even if invalid."""
    issues = []
    records = sorted(records, key=lambda record: _text(_object(record.get('metadata')).get('key')))
    metadata = [_object(record.get('metadata')) for record in records]
    pair_ids = {_text(meta.get('pair_id')) for meta in metadata}
    pair_id = next(iter(pair_ids)) if len(pair_ids) == 1 else ''
    if not pair_id or len(pair_ids) != 1:
        issues.append('Missing or conflicting pair identity')
    if len(records) != 2:
        issues.append('Pair requires exactly two members; missing members or ambiguous revisions')
    roles, provenances, legacy = _roles(records, issues)
    if any(roles.count(role) != 1 for role in _ROLES):
        issues.append('Pair requires one original and one counterfactual revision')
    for field in ('family', 'split', 'lineage_id'):
        values = {meta.get(field) for meta in metadata}
        if len(values) != 1 or not all(values):
            issues.append(f'Pair members have missing or conflicting {field}')
    for meta in metadata:
        if not meta.get('ready'):
            issues.append('Pair member is not ready')
    members = [{**{field: meta.get(field) for field in (
        'key', 'hash', 'id', 'family', 'type', 'dataset_id', 'lineage_id', 'split')}, 'role': role}
        for meta, role in zip(metadata, roles)]
    members.sort(key=lambda member: (_ROLES.index(member['role']) if member['role'] in _ROLES else 2,
                                    _text(member['key'])))
    mapping, changes, controls = [], [], []
    status = 'unverified'
    history_values = {provenance.get('selection_history', 'unknown') for provenance in provenances}
    history = next(iter(history_values)) if len(history_values) == 1 else 'unknown'
    limitations = []
    if history == 'unknown':
        limitations.append('Selection history is unknown; this pair does not establish an unbiased sample of interventions.')
    elif history == 'outcome_selected_release':
        limitations.append('This release was selected using outcomes; pair-level results do not estimate unselected intervention behavior.')
    if legacy:
        limitations.append('Legacy pair roles were recovered from candidate dataset bindings; prospective intervention selection is not verified.')
    if len(records) == 2 and all(roles.count(role) == 1 for role in _ROLES):
        original, counter = (records[roles.index(role)] for role in _ROLES)
        try:
            left_ds, left = _specs(original)
            right_ds, right = _specs(counter)
            for ds, record, choices in ((left_ds, original, left), (right_ds, counter, right)):
                meta = record['metadata']
                if ds.get('dataset_id') != meta.get('dataset_id') or ds.get('family') != meta.get('family'):
                    issues.append('Dataset spec identity differs from pair member')
                if not ds.get('params'):
                    issues.append('Dataset parameters are unavailable for pair comparison')
                for cid, choice in choices.items():
                    spec = choice['spec']
                    if (spec.get('candidate_id') != cid or spec.get('dataset_id') != meta.get('dataset_id')
                            or spec.get('family') != meta.get('family')):
                        issues.append('Candidate spec identity or dataset binding differs from pair member')
                    budget = _object(spec.get('budget'))
                    values = [budget.get(key) for key in ('training_steps', 'batch_size', 'total_samples_seen')]
                    if any(type(v) is not int or v <= 0 for v in values) or values[0] * values[1] != values[2]:
                        issues.append('Candidate budget is missing or inconsistent')
            declared = [provenance.get('candidate_mapping') for provenance in provenances if 'candidate_mapping' in provenance]
            if declared:
                if any(rows != declared[0] for rows in declared[1:]):
                    issues.append('Conflicting candidate identity mapping')
                rows = declared[0]
            elif set(left) == set(right):
                rows = [{'choice_identity': cid, 'original_candidate_id': cid, 'counterfactual_candidate_id': cid}
                        for cid in left]
            else:
                rows = []
                issues.append('Candidate IDs differ without an explicit identity mapping')
            left_ids = [row.get('original_candidate_id') for row in rows]
            right_ids = [row.get('counterfactual_candidate_id') for row in rows]
            identities = [row.get('choice_identity') for row in rows]
            valid_mapping = (len(rows) >= 2 and set(left_ids) == set(left) and set(right_ids) == set(right)
                             and len(set(left_ids)) == len(rows) == len(set(right_ids)) == len(set(identities))
                             and all(identities))
            if not valid_mapping:
                issues.append('Candidate identity mapping must cover each choice exactly once')
            else:
                valid_controls = set(_CONTROLS)
                for row in rows:
                    a, b = left[row['original_candidate_id']], right[row['counterfactual_candidate_id']]
                    mapping.append({**row, 'original_letter': a['letter'], 'counterfactual_letter': b['letter']})
                    for field in _CONTROLS:
                        if not a['spec'].get(field) or a['spec'].get(field) != b['spec'].get(field):
                            issues.append(f'Candidate {field} is missing or differs across pair members')
                            valid_controls.discard(field)
                    if a['spec'].get('execution') != b['spec'].get('execution'):
                        issues.append('Candidate execution settings differ across pair members')
                controls = [field for field in _CONTROLS if field in valid_controls]
            public_ds_fields = ('family', 'selection_metric', 'params', 'seeds', 'seed', 'synthesis', 'task')
            changes = _changes({k: left_ds[k] for k in public_ds_fields if k in left_ds},
                               {k: right_ds[k] for k in public_ds_fields if k in right_ds})
            if left_ds.get('dataset_id') == right_ds.get('dataset_id'):
                issues.append('Pair dataset instances must be distinct')
            if not changes:
                issues.append('No changed public dataset parameters were verified.')
            if len(controls) == len(_CONTROLS):
                if len(changes) > 1 or any(change['kind'] == 'sampling' for change in changes):
                    status = 'matched_candidates_multiple_changes'
                    limitations.append('Several data or sampling conditions changed; the pair does not isolate one causal factor.')
                elif not _sampling_known(left_ds) or not _sampling_known(right_ds):
                    status = 'matched_candidates_sampling_unverified'
                    limitations.append('The stored specs do not verify fixed sampling streams.')
                elif len(changes) == 1:
                    status = 'single_factor_fixed_sampling'
                else:
                    status = 'matched_candidates_no_verified_change'
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            issues.append('Pair specs or candidate correspondence are malformed')
    issues = list(dict.fromkeys(issues))
    intervention = {'controls': controls, 'changes': changes, 'causal_status': status,
                    'selection_history': history, 'limitations': limitations}
    pair_key = _digest({'pair_id': pair_id, 'members': members, 'candidate_mapping': mapping, 'intervention': intervention})
    return {'schema_version': 1, 'pair_key': pair_key, 'pair_id': pair_id,
            'family': metadata[0].get('family', '') if metadata else '',
            'type': metadata[0].get('type', '') if metadata else '',
            'split': metadata[0].get('split', '') if metadata else '',
            'lineage_id': metadata[0].get('lineage_id', '') if metadata else '',
            'members': members, 'candidate_mapping': mapping, 'intervention': intervention,
            'ready': not issues, 'evaluation_ready': not issues, 'kb_ready': not issues and all(meta.get('kb_ready') for meta in metadata),
            'issues': issues}
