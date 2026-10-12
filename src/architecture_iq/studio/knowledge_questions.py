"""Read-only, claim-specific applicability over the local public question bank.

Only the canonical predictor produces comparisons. Diagnostics explain why a
comparison could not be made; they never manufacture an answer or validation.
"""
from __future__ import annotations

from itertools import combinations

from architecture_iq.kb.rules import _all, _equal, _holds, _number, public_views
from architecture_iq.kb.store import canonical_hash
from .knowledge import resolve_initial_knowledge
from .rule_refinement.inputs import resolve_rule_knowledge
from .rule_refinement.pool import _case
from .rule_refinement.prediction import predict_question
from .task_answers import formal_rule_admission
from .task_explanations import _expression, _leaves


class KnowledgeReferenceConflict(ValueError):
    pass


def _reason(code, message):
    return {'code': code, 'message': message}


def _selection(catalog, inventory, reference, claim_id):
    items = [item for item in inventory.get('items', [])
             if item.get('id') == reference['id'] and item.get('version') == reference['version']]
    if not items:
        raise KeyError('KB or version not found')
    if len(items) != 1:
        raise KnowledgeReferenceConflict('KB identity is ambiguous')
    item = items[0]
    snapshot = item.get('snapshot')
    if (not isinstance(snapshot, dict) or snapshot.get('version') != reference['version']
            or canonical_hash({k: v for k, v in snapshot.items() if k != 'version'}) != reference['version']):
        raise KnowledgeReferenceConflict('KB snapshot integrity failure')
    kind = item.get('kind')
    if kind == 'experience':
        if not any(lesson.get('id') == claim_id for lesson in snapshot.get('lessons', [])):
            raise KeyError('Knowledge entry not found')
        return item, None, [], _reason('no_executable_rules', '该条目是文本经验，尚无可执行规则，无法判断题目是否适用。')
    if kind not in {'research_rules', 'formal'}:
        raise ValueError('Unsupported knowledge kind')
    try:
        kb, _, _ = resolve_rule_knowledge(catalog, {'items': [item]}, reference)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise KnowledgeReferenceConflict('KB rule snapshot unavailable') from exc
    if kind == 'research_rules':
        selected = [rule for rule in kb['rules']
                    if rule.get('metadata', {}).get('claim_id', rule['rule_id']) == claim_id]
        exists = selected or any(issue.get('source_id') == claim_id for issue in kb.get('import_issues', []))
    else:
        exists = [claim for claim in snapshot.get('claims', [])
                  if claim.get('source_claim_id', claim.get('id')) == claim_id]
        selected = [rule for rule in kb['rules'] if any(
            ref.get('source_claim_id') == claim_id for ref in rule['source_refs'])]
    if not exists:
        raise KeyError('Knowledge entry not found')
    if not selected:
        return item, kb, [], _reason('no_executable_rules', '该条目尚无可执行规则，无法判断题目是否适用。')
    selected = [rule for rule in selected if rule['state'] == 'active']
    if not selected:
        return item, kb, [], _reason('inactive_rules', '该条目的规则已停用，未用于当前适用性判断。')
    if kind == 'formal':
        try:
            resolve_initial_knowledge(reference, {'items': [item]})
        except (ValueError, KeyError, TypeError, OSError):
            return item, kb, selected, _reason('validation_unavailable', '原始验证证据或启用状态不可用，不能确认该条目适用。')
    return item, kb, selected, None


def _predicate_missing(predicate, view):
    return {leaf[0] for leaf in _leaves(predicate) if _holds(leaf, view) is None}


def _conditions(rule, a, b):
    """Tri-state authored gates, using the canonical predicate semantics.

    A known false gate suffices to rule out this pair; otherwise missing public
    inputs remain unknown. Prediction direction is deliberately not computed.
    """
    missing, failures = set(), []
    scope = rule.get('scope')
    outcomes = [_holds(scope, view) for view in (a, b)]
    if False in outcomes:
        failures.append('候选不满足 ' + _expression(scope))
    elif None in outcomes:
        missing.update(_predicate_missing(scope, a) | _predicate_missing(scope, b))
    for key in ('same', 'differ'):
        for field in rule.get(key, []):
            va, vb = a.get(field), b.get(field)
            if va is None or vb is None or any(type(v) in (int, float) and not _number(v) for v in (va, vb)):
                missing.add(field)
            elif _equal(va, vb) != (key == 'same'):
                failures.append(field + (' 需要相同' if key == 'same' else ' 需要不同'))
    if 'max_param_ratio' in rule:
        va, vb = a.get('params'), b.get('params')
        if not _number(va) or not _number(vb) or min(va, vb) <= 0:
            missing.add('params')
        elif max(va, vb) / min(va, vb) > rule['max_param_ratio']:
            failures.append('参数量比值超过规则上限')
    pred = rule['predict']
    roles = ('better', 'worse') if 'better' in pred else ('winner', 'loser')
    if any(key in pred for key in roles):
        directions = [_all([_holds(pred.get(roles[0]), winner), _holds(pred.get(roles[1]), loser)])
                      for winner, loser in ((a, b), (b, a))]
        # Only reject when both assignments are provably excluded. Missing
        # inputs and two valid assignments remain abstentions, not negatives.
        if all(direction is False for direction in directions):
            failures.append('无法同时满足优劣候选条件：' + _expression(pred.get(roles[0]))
                            + ' / ' + _expression(pred.get(roles[1])))
    return (False if failures else None if missing else True), missing, failures


def _prediction_missing(rule, a, b):
    pred, missing = rule['predict'], set()
    for key in ('better', 'worse', 'winner', 'loser'):
        for view in (a, b):
            missing.update(_predicate_missing(pred.get(key), view))
    numeric = [pred[key] for key in ('higher_better', 'lower_better') if key in pred]
    numeric.extend(axis[0] for axis in pred.get('dominates', []))
    return missing | {field for field in numeric if any(not _number(view.get(field)) for view in (a, b))}


def _unmatched_reason(case, selected, views, admission):
    missing, failures, undetermined, scope_unknown = set(), set(), False, False
    for a, b in combinations(views, 2):
        for record in selected:
            if admission is not None and not admission(record, a, b):
                scope_unknown = True
                continue
            state, absent, excluded = _conditions(record['rule'], a, b)
            if state is False:
                failures.update(excluded)
                continue
            missing.update(absent | _prediction_missing(record['rule'], a, b))
            undetermined = True
    if scope_unknown:
        return 'unknown', _reason('validation_scope_unavailable', '未能确认候选符合该条目的原始验证范围；缺少验证资料不代表知识不适用。')
    if missing:
        return 'unknown', _reason('missing_public_features', '公开输入缺少或无法计算规则需要的特征：' + '、'.join(sorted(missing)) + '。')
    if undetermined:
        return 'unknown', _reason('no_comparable_candidates', '条件未明确排除本题，但候选值相同、比较阈值不足或优劣条件不唯一，尚无有效候选比较。')
    return 'inapplicable', _reason('conditions_not_met', '所有候选对均不满足该条目的适用条件：' + '；'.join(sorted(failures)[:3]) + '。')


def _classify(catalog, summary, item, kb, selected, blocked):
    result = {key: summary.get(key) for key in ('key', 'id', 'family', 'type', 'candidate_configs')}
    result.update(relation='unknown', reason=blocked, prediction_status=None, matched_rules=0, matched_pairs=0)
    if blocked:
        return result
    try:
        record = catalog.get_question(summary['key'], include_private=False)
        if not record['metadata'].get('rag_ready'):
            raise ValueError('Public inputs unavailable')
        case = _case(record)
        views = public_views(case['dataset_spec'], case['candidate_specs'])
        admitted = formal_rule_admission(case['question'], item) if item['kind'] == 'formal' else None
        rule_ids = {rule['rule_id'] for rule in selected}
        prediction = predict_question(case, kb, rule_admission=lambda rule, a, b:
            rule['rule_id'] in rule_ids and (admitted is None or admitted(rule, a, b)))
        if prediction['status'] == 'invalid':
            raise ValueError('Invalid public case')
    except (ValueError, KeyError, TypeError, OSError, IndexError, OverflowError):
        result['reason'] = _reason('public_inputs_unavailable', '题目公开资料不完整或来源不可用，尚不能判断适用性。')
        return result
    result['prediction_status'] = prediction['status']
    edges = prediction['edges']
    if edges:
        result.update(relation='applicable', matched_rules=len({ref['rule_id'] for edge in edges for ref in edge['rules']}),
                      matched_pairs=len({tuple(sorted((edge['winner'], edge['loser']))) for edge in edges}),
                      reason=_reason('rule_conflict', '规则在本题候选间产生了相反结论或循环关系；保留冲突，不能确定答案。')
                      if prediction['status'] == 'conflict' else
                      _reason('rules_matched', '公开条件匹配，规则可比较本题的候选；这不代表结论已经通过实验验证。'))
    else:
        result['relation'], result['reason'] = _unmatched_reason(case, selected, views, admitted)
    return result


def knowledge_questions(catalog, inventory, *, reference, claim_id, relation='all', search='', offset=0, limit=25):
    if relation not in {'all', 'applicable', 'inapplicable', 'unknown'} or offset < 0 or not 1 <= limit <= 100:
        raise ValueError('Invalid question filters')
    item, kb, selected, blocked = _selection(catalog, inventory, reference, claim_id)
    counts = {'applicable': 0, 'inapplicable': 0, 'unknown': 0}
    items, total, cursor = [], 0, 0
    while True:
        page = catalog.list_questions(search=search, offset=cursor, limit=1000)
        for summary in page['items']:
            result = _classify(catalog, summary, item, kb, selected, blocked)
            counts[result['relation']] += 1
            if relation == 'all' or result['relation'] == relation:
                if offset <= total < offset + limit:
                    items.append(result)
                total += 1
        cursor += len(page['items'])
        if not page['items'] or cursor >= page['total']:
            break
    return {'kb_ref': reference, 'claim_id': claim_id, 'items': items, 'counts': counts,
            'total': total, 'offset': offset, 'limit': limit, 'scope': 'public_rule_conditions',
            'notice': '按当前本地题库的公开条件匹配；适用表示规则可参与候选比较，不等于正确率或独立验证。'}
