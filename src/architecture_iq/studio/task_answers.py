"""Freeze public-only Task inputs, preserving existing RAG and rule semantics."""
from __future__ import annotations

from copy import deepcopy
from architecture_iq.kb.store import canonical_hash
from .rag import prepare_rag
from .rule_refinement.inputs import resolve_rule_knowledge
from .rule_refinement.pool import _case
from .rule_refinement.prediction import predict_question, _cycle
from .knowledge import resolve_initial_knowledge
from architecture_iq.kb.rules import match_validated_scope
from .task_explanations import explain_task_prediction, public_validated_scope


def kb_description(item):
    return {**{key: deepcopy(item[key]) for key in ('id', 'version', 'name', 'kind')},
            **{key: deepcopy(item[key]) for key in ('source_kind', 'round_index', 'source_status_counts', 'skipped_claims') if key in item},
            'summary': item.get('summary', ''),
            'verification': 'research_hypothesis' if item['kind'] == 'research_rules' else
                            'experience_unverified' if item['kind'] == 'experience' else 'per_rule_scope'}


def eligible_kbs(inventory, mode):
    kinds = {'formal', 'research_rules'} if mode == 'rules' else {'formal', 'experience'}
    return sorted((item for item in inventory.get('items', []) if item.get('kind') in kinds or
                   (mode == 'llm' and item.get('kind') == 'research_rules' and item.get('source_kind') == 'knowledge_evolution')),
                  key=lambda item: (item['id'], item['version']))


def _selected_inventory(card, inventory):
    items = eligible_kbs(inventory, card['mode'])
    if card['kb_selection']['mode'] == 'manual':
        ref = card['kb_selection']['ref']
        items = [item for item in items if all(item[key] == ref[key] for key in ('id', 'version'))]
        if len(items) != 1:
            raise ValueError('所选 KB 不可用或已更新，请重新选择')
    return {'items': items, 'warnings': inventory.get('warnings', [])}


def _safe_retrieval(retrieval):
    value = deepcopy(retrieval)
    for hit in [*value['provenance'], *(h for c in value['candidates'] for h in c['hits'])]:
        for ref in hit.get('source_refs', []):
            ref['sources'] = [{k: source[k] for k in ('id', 'kind', 'name', 'round_index') if k in source}
                              for source in ref.get('sources', [])]
    value['warnings'] = [{'source_id': warning.get('source_id'), 'message': '部分知识来源不可用'}
                         for warning in value.get('warnings', [])]
    return value


def _formal_rule_claims(rule, claims):
    bound = []
    for ref in rule.get('source_refs', []):
        matching = [claim for claim in claims
            if claim.get('source_claim_id', claim['id']) == ref.get('source_claim_id')
            and claim.get('rule') == rule.get('rule')
            and ('source_clause_index' not in ref or
                 claim.get('source_clause_index') == ref['source_clause_index'])]
        if len(matching) != 1:
            return []
        bound.append(matching[0])
    return bound


def formal_rule_admission(question, item):
    """Imported formal rules retain their exact source validation boundary."""
    def admit(rule, a, b):
        bound = _formal_rule_claims(rule, item['snapshot']['claims'])
        return bool(bound) and all(claim.get('enabled') is True
            and claim.get('status') == 'replicated_in_scope'
            and match_validated_scope(question, claim, a, b) for claim in bound)
    return admit


def _rules_preview(catalog, card, inventory):
    record = catalog.get_question(card['question_key'], include_private=False)
    if not record['metadata'].get('rag_ready'):
        raise ValueError('题目公开输入不可用或来源已停用')
    case = _case(record)
    matches, frozen, warnings = [], [], []
    for item in inventory['items']:
        try:
            if item['kind'] == 'formal':
                resolve_initial_knowledge({k: item[k] for k in ('id', 'version')}, inventory)
            kb, source, _ = resolve_rule_knowledge(catalog, inventory, {k: item[k] for k in ('id', 'version')})
            predicted = predict_question(case, kb, rule_admission=
                formal_rule_admission(case['question'], item) if item['kind'] == 'formal' else None)
            if predicted['status'] == 'invalid':
                raise ValueError('Invalid public inputs or rules')
        except (KeyError, ValueError, TypeError, OSError):
            warnings.append({'code': 'kb_unavailable', 'kb_id': item['id'],
                             'message': '该 KB 的规则或公开输入未通过校验，未参与作答'})
            continue
        matched_rules = {ref['rule_id'] for edge in predicted['edges'] for ref in edge['rules']}
        provenance = [{'rule_id': rule['rule_id'], 'revision': rule['revision'], 'text': rule['text'],
                       'rule': deepcopy(rule['rule']),
                       'validity_status': rule.get('metadata', {}).get('validity_status', 'proposed'),
                       'validation_origin': rule.get('metadata', {}).get('validation_origin', 'research'),
                       'metadata': {k: deepcopy(v) for k, v in rule.get('metadata', {}).items()
                                    if k in ('claim_id', 'clause_index', 'validated_scope')},
                       'source_refs': [{k: s[k] for k in ('id', 'kind', 'version', 'source_index', 'source_claim_id', 'source_clause_index',
                                                        'source_status', 'source_revision', 'round_index', 'source_kind') if k in s}
                                       for s in rule.get('source_refs', [])]}
                      for rule in kb['rules'] if rule['rule_id'] in matched_rules]
        if item['kind'] == 'formal':
            # Every matched formal edge passed original validation and scope.
            for rule in provenance:
                rule.update(validity_status='replicated_in_scope', validation_origin='verified_source_scope')
                original = _formal_rule_claims(rule, item['snapshot']['claims'])
                # The formal adapter imports one original clause per rule. Use
                # its exact binding, not another clause sharing the claim ID.
                if len(original) == 1:
                    rule['validated_scope'] = public_validated_scope(original[0].get('validated_scope'))
        matches.append({'kb': kb_description(item), 'prediction': predicted, 'rules': provenance})
        frozen.append({'ref': {k: item[k] for k in ('id', 'version')}, 'snapshot': kb,
                       'source_snapshot': item['snapshot'], 'source': source})
    answers = {m['prediction']['answer_id'] for m in matches if m['prediction']['status'] == 'answered'}
    issues = []
    conflict = any(m['prediction']['status'] == 'conflict' for m in matches)
    graph = {choice['id']: set() for choice in case['question']['choices']}
    for match in matches:
        for edge in match['prediction']['edges']:
            graph[edge['winner']].add(edge['loser'])
    if _cycle(graph):
        conflict = True
    if conflict:
        issues.append({'code': 'rule_conflict', 'message': '适用规则包含相反结论或循环关系，保留冲突并停止选答'})
    if len(answers) > 1:
        conflict = True
        issues.append({'code': 'kb_disagreement', 'message': '不同 KB 给出了不同答案，无法确定唯一答案'})
    # A partial KB can contradict another KB's complete answer. Never ignore it
    # merely because it cannot by itself rank every candidate.
    candidate = next(iter(answers)) if len(answers) == 1 else None
    if candidate and any(edge['loser'] == candidate for match in matches for edge in match['prediction']['edges']):
        conflict = True
        issues.append({'code': 'partial_kb_disagreement', 'message': '其他适用规则否定了候选答案，无法确定唯一答案'})
    status = 'conflict' if conflict else 'answered' if candidate else 'uncovered'
    answer = candidate if status == 'answered' else None
    if status == 'uncovered':
        issues.append({'code': 'insufficient_rules', 'message': '没有适用规则，或规则尚不足以确定唯一答案'})
    prediction = {'status': status, 'answer_id': answer,
                  'answer_letter': next((choice['letter'] for choice in case['question']['choices'] if choice['id'] == answer), None),
                  'matches': matches, 'issues': issues}
    prediction['explanation'] = explain_task_prediction(case, prediction)
    # Include the selected catalog identity even when a source is unusable. A
    # source repair/removal must invalidate the old preview too.
    identity = canonical_hash(inventory['items'])
    config = {'question_key': card['question_key'], 'case': case, 'kbs': frozen,
              'inventory_hash': identity, 'prediction': prediction}
    return config, {'question': case['question'], 'prediction': prediction,
                    'selected_kbs': [match['kb'] for match in matches], 'warnings': warnings,
                    'can_run': True, 'can_answer': answer is not None}


def prepare_task(card, *, catalog, models, inventory, allowed_roots):
    from .jobs import source_fingerprint
    if not card['question_key']:
        raise ValueError('请先选择题目并保存任务')
    inventory = _selected_inventory(card, inventory)
    if card['mode'] == 'rules':
        config, shown = _rules_preview(catalog, card, inventory)
    else:
        if not card['model_id']:
            raise ValueError('请先选择作答模型并保存任务')
        config, result = prepare_rag(catalog, models, inventory, question_key=card['question_key'],
                                    model_id=card['model_id'], knowledge_limit=card['knowledge_limit'],
                                    allowed_roots=allowed_roots, allow_evolution=True)
        selected = result['retrieval']['selected_kb']
        model = config['models'][0]
        shown = {'question': result['question'], 'can_run': result['can_answer'], 'can_answer': result['can_answer'],
                 'selected_kbs': [selected] if selected else [], 'retrieval': _safe_retrieval(result['retrieval']),
                 'model': {k: model[k] for k in ('id', 'name', 'model', 'revision') if k in model},
                 'request': {'payload': {'messages': result['request']['payload']['messages']}} if result['request'] else None,
                 'reserved_tokens': result['reserved_tokens'], 'blocked_reason': result['blocked_reason'],
                 'warnings': [] if result['can_answer'] else [{'code': result['blocked_reason'],
                    'message': '没有可用于当前题目的知识，请调整 KB 选择'}]}
    config = {**config, 'task_id': card['id'], 'task_revision': card['revision']}
    return config, {**shown, 'task_id': card['id'], 'task_revision': card['revision'], 'mode': card['mode'],
                    'preview_hash': canonical_hash({'card': card, 'config': config, 'source_fingerprint': source_fingerprint()})}


def public_task_run(receipt, jobs):
    value = {key: deepcopy(receipt[key]) for key in
             ('id', 'task_id', 'task_revision', 'mode', 'status', 'created_at', 'receipt_hash')}
    if receipt['mode'] == 'rules':
        value['result'] = deepcopy(receipt['result'])
    else:
        value['job_id'] = receipt['job_id']
        job = jobs.get(receipt['job_id'])
        value['status'] = job['status']
        provided = _safe_retrieval(receipt['config']['retrieval'])['provenance']
        value['result'] = {'provided_sources': provided, 'used_sources': []}
        if job.get('result'):
            value['result'].update({key: deepcopy(job['result'][key]) for key in ('answer', 'unknown_citations', 'response_model')
                                   if key in job['result']})
            cited = set(job['result'].get('answer', {}).get('citations', []))
            value['result']['used_sources'] = [hit for hit in provided if hit['citation_id'] in cited]
        if job.get('error'):
            value['error'] = '模型作答未完成，请查看运行记录中的状态'
    return value
