"""Public-only RAG preview and durable single-call inference."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from architecture_iq.kb.roles import role_prompt
from architecture_iq.kb.store import canonical_hash
from .models import api_identity, model_config, resolve_path
from .rag_inputs import validate_rag_question
from .rag_retrieval import retrieve_knowledge


def freeze_rag_model(models, model_id: str, *, allowed_roots: list[Path]) -> dict:
    profile = copy.deepcopy(models.get(model_id))
    if not profile.get('enabled', True):
        raise ValueError('模型已停用')
    if profile.get('connection_type') == 'api':
        models.credential(profile)
        identity = api_identity(profile)
    elif profile.get('runtime_lock_path'):
        from architecture_iq.kb.cli import read_runtime_lock
        path = resolve_path(profile['runtime_lock_path'], allowed_roots)
        identity = json.loads(path.read_text())
        fingerprint = canonical_hash(identity)
        read_runtime_lock(path, {'model': model_config(profile), 'runtime_fingerprint': fingerprint}, verify_files=True)
        profile['runtime_lock_path'] = str(path)
    else:
        identity = {**api_identity(profile), 'kind': 'self_hosted_configuration'}
    profile.update(service_identity=identity, runtime_fingerprint=canonical_hash(identity))
    return profile


def build_rag_request(question: dict, knowledge: list[dict], model: dict) -> dict:
    from .execution import _tools
    _, ModelConfig, builder = _tools()
    prompt = role_prompt('solver', {'question': question, 'knowledge': knowledge})
    return {'url': model['base_url'] + '/chat/completions',
            'payload': builder([{'role': 'user', 'content': prompt}], ModelConfig(**model_config(model)), stream=True),
            'reserved_tokens': len(prompt.encode()) + model['parameters']['max_tokens'] + 256,
            'knowledge': copy.deepcopy(knowledge)}


def prepare_rag(catalog, models, inventory: dict, *, question_key: str, model_id: str,
                knowledge_limit: int = 8, allowed_roots: list[Path]) -> tuple[dict, dict]:
    from .jobs import source_fingerprint
    detail = catalog.get_question(question_key, include_private=False)
    if not detail['metadata'].get('rag_ready'):
        raise ValueError('题目公开输入不可用或来源已停用')
    question = validate_rag_question(detail['public'])
    model = freeze_rag_model(models, model_id, allowed_roots=allowed_roots)
    retrieval = retrieve_knowledge(question, inventory, knowledge_limit=knowledge_limit)
    request = None
    if retrieval['knowledge']:
        retained, provenance = [], []
        if build_rag_request(question, [], model)['reserved_tokens'] > model['context_size']:
            raise ValueError('题面超出模型保守上下文预算')
        for note, hit in zip(retrieval['knowledge'], retrieval['provenance']):
            candidate = build_rag_request(question, [*retained, note], model)
            if candidate['reserved_tokens'] <= model['context_size']:
                retained.append(note)
                provenance.append(hit)
            else:
                retrieval['omitted']['budget'] += 1
        if not retained:
            raise ValueError('上下文预算不足，无法容纳任何匹配知识')
        retrieval.update(knowledge=retained, provenance=provenance)
        request = build_rag_request(question, retained, model)
    blocked = None if request else ('empty_library' if not inventory.get('items') else 'no_match')
    config = {'schema_version': 1, 'name': 'RAG 作答', 'question_key': question_key,
              'question': question, 'models': [model], 'knowledge_limit': knowledge_limit,
              'strategy': retrieval['strategy'], 'inventory_hash': retrieval['inventory_hash'],
              'retrieval': retrieval, 'request': request, 'transport': {'stream': True},
              'max_calls': 1, 'max_tokens': request['reserved_tokens'] if request else 0}
    preview = {**copy.deepcopy(config), 'kind': 'rag', 'sent': False, 'can_answer': bool(request),
               'blocked_reason': blocked, 'reserved_tokens': config['max_tokens'],
               'preview_hash': canonical_hash({'config': config, 'source_fingerprint': source_fingerprint()})}
    return config, preview
