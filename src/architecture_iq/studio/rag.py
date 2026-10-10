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


def execute_rag(store, identifier: str, config: dict, *, client_factory=None) -> dict:
    import time
    from architecture_iq.kb.orchestrator import _answer
    from architecture_iq.kb.roles import parse_json_response
    from architecture_iq.kb.store import write_json_atomic
    from .execution import create_client, _tools
    if client_factory is None:
        client_factory = create_client
    model = config['models'][0]
    request = config['request']
    if (config.get('transport') != {'stream': True} or not config['retrieval']['knowledge']
            or request != build_rag_request(config['question'], config['retrieval']['knowledge'], model)
            or request['reserved_tokens'] > model['context_size']
            or config['max_calls'] != 1 or request['reserved_tokens'] > config['max_tokens']):
        raise ValueError('Frozen RAG request or budget differs from preview')
    write_json_atomic(store.directory(identifier) / 'retrieval.json', config['retrieval'])
    for node in ('input', 'retrieval'):
        store.event(identifier, {'type': 'stage', 'node_id': node, 'state': 'complete', 'round_index': 0})
    key = f"rag:{config['question_key']}:{model['id']}"
    attribution = {'node_id': 'solver', 'round_index': 0, 'operation_key': key,
                   'question_key': config['question_key'], 'model_id': model['id']}
    store.boundary(identifier, {**attribution, 'completed': 0, 'total': 1})
    existing = store.reserve(identifier, key, request)
    if existing:
        if existing['status'] == 'invalid':
            raise ValueError(existing.get('error', '无效回答'))
        return existing['result']
    started = time.time()
    try:
        client = client_factory(model, lambda wire: store.update_record(identifier, key, {'actual_request': wire, 'sent_at': time.time()}),
            **({'credential_root': store.state_root / 'credentials'} if model.get('connection_type') == 'api' else {}))
        client.stream = True
        client.chunk_observer = lambda frame: store.append_stream(identifier, key, attribution, frame)
        verifier = getattr(client, 'verify_runtime', None)
        if verifier: verifier()
        _, ModelConfig, _ = _tools()
        response = client.complete_conversation(request['payload']['messages'], ModelConfig(**model_config(model)))
        store.update_record(identifier, key, {'raw': response.raw, 'finish_reason': response.finish_reason,
            'usage': response.usage, 'response_received_at': time.time()})
        if verifier: verifier()
        if model.get('connection_type') != 'api' and response.raw.get('model') != model['model']:
            raise RuntimeError('Returned model identity differs from frozen request')
        try:
            if response.finish_reason != 'stop':
                raise ValueError('Incomplete answer finish reason')
            parsed = parse_json_response(response.raw['choices'][0]['message'].get('content') or '')
            answer = _answer(parsed, config['question'], config['retrieval']['knowledge'])
            if not answer['valid']:
                raise ValueError('回答 ranking 无效')
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            store.finish(identifier, key, {'status': 'invalid', 'error': str(exc)})
            raise ValueError(str(exc)) from exc
        usage = response.usage or {}
        components = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
        charged = sum(components) if all(type(n) is int and n >= 0 for n in components) else 0
        charged = charged or request['reserved_tokens']
        store.update_record(identifier, key, {'charged_tokens': charged})
        if charged > request['reserved_tokens']:
            raise RuntimeError('Actual usage exceeds reserved token budget')
        provided = {hit['citation_id']: hit for hit in config['retrieval']['provenance']}
        citations = list(dict.fromkeys(answer.get('citations', [])))
        result = {'kind': 'rag', 'question_key': config['question_key'], 'model_id': model['id'],
                  'response_model': response.raw.get('model'), 'answer': answer,
                  'retrieval': copy.deepcopy(config['retrieval']),
                  'used_sources': [copy.deepcopy(provided[c]) for c in citations if c in provided],
                  'unknown_citations': [c for c in citations if c not in provided],
                  'calls': 1, 'charged_tokens': charged, 'elapsed_seconds': time.time() - started}
        store.finish(identifier, key, {'status': 'complete', 'answer': answer, 'result': result})
        store.event(identifier, {'type': 'answer_committed', **attribution, 'node_id': 'commit'})
        store.update(identifier, progress={**attribution, 'node_id': 'commit', 'completed': 1, 'total': 1})
        return result
    except Exception as exc:
        record = json.loads(store.record_path(identifier, key).read_text())
        if record['status'] != 'invalid':
            store.finish(identifier, key, {'status': 'uncertain' if 'actual_request' in record and 'raw' not in record else 'failed',
                          'error': str(exc), 'elapsed_seconds': time.time() - started})
        raise
