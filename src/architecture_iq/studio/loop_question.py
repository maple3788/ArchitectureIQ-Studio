"""Project an observed canonical question through Studio's public boundary."""
from __future__ import annotations

from .catalog import _CANDIDATE_KEYS, _CODE_FILES, _DATASET_KEYS, _public_question, _spec


def public_question(value: dict, identifier: str) -> dict:
    """Keep original public text and source option letters; discard GT fields."""
    public = _public_question(value['public'])
    metadata = value['metadata']
    if public.get('id') != identifier or metadata.get('id') != identifier:
        raise ValueError('Question identity mismatch')
    prompt = public.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('Question prompt unavailable')
    choices, seen = [], set()
    for item in value['detail']['choices']:
        identity = (item['candidateId'], item['letter'])
        if identity in seen:
            raise ValueError('Duplicate source choice')
        seen.add(identity)
        raw_files = item.get('files', {})
        files = {name: raw_files[name] for name in _CODE_FILES if isinstance(raw_files.get(name), str)}
        files['candidate_spec.json'] = _spec(raw_files['candidate_spec.json'], _CANDIDATE_KEYS)
        if files['candidate_spec.json'].get('candidate_id') != identity[0]:
            raise ValueError('Candidate identity mismatch')
        choices.append({'candidateId': identity[0], 'letter': identity[1], 'files': files})
    if not choices or seen != {(item['id'], item['letter']) for item in public['choices']}:
        raise ValueError('Question choice mapping mismatch')
    raw_dataset = value['detail']['dataset']['files']
    ds_files = {'dataset_spec.json': _spec(raw_dataset['dataset_spec.json'], _DATASET_KEYS)}
    if isinstance(raw_dataset.get('synthesize.py'), str):
        ds_files['synthesize.py'] = raw_dataset['synthesize.py']
    return {
        'metadata': {key: metadata[key] for key in ('id', 'family', 'dataset_id', 'type', 'profile', 'metric')
                     if isinstance(metadata.get(key), str)},
        'public': public,
        'detail': {'prompt': prompt, 'dataset': {'files': ds_files}, 'choices': choices},
    }
