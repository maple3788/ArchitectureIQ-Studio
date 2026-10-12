"""Public facts explaining an already computed canonical rule prediction.

This module does not select answers or evaluate experiments. Decisions, edges,
and paths come from ``predict_question``; feature values and predicate truth
use the same public-spec projection and predicate implementation as that solver.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import json

from architecture_iq.kb.rules import CONTROL_FIELDS, PUBLIC_FIELDS, _holds, public_views
from .rule_refinement.prediction import _cycle, _paths


_OPERATORS = {'eq': '=', 'ne': '≠', 'lt': '<', 'le': '≤', 'gt': '>', 'ge': '≥',
              'in': '属于', 'nin': '不属于'}
_SOURCE_FIELDS = ('id', 'kind', 'version', 'source_index', 'source_claim_id',
                  'source_clause_index', 'source_status', 'source_revision', 'round_index')


def _literal(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _expression(predicate):
    if predicate is None:
        return '无额外条件'
    if isinstance(predicate, dict):
        operator, children = next(iter(predicate.items()))
        if operator == 'not':
            return f'非（{_expression(children)}）'
        return (' 且 ' if operator == 'all' else ' 或 ').join(
            f'（{_expression(child)}）' for child in children)
    if isinstance(predicate[0], str):
        field, operator, expected = predicate
        return f'{field} {_OPERATORS[operator]} {_literal(expected)}'
    return ' 且 '.join(f'（{_expression(child)}）' for child in predicate)


def _leaves(predicate):
    if predicate is None:
        return []
    if isinstance(predicate, dict):
        operator, children = next(iter(predicate.items()))
        return _leaves(children) if operator == 'not' else [leaf for child in children for leaf in _leaves(child)]
    if isinstance(predicate[0], str):
        return [predicate]
    return [leaf for child in predicate for leaf in _leaves(child)]


def _predicate_facts(predicate, view):
    return {'expression': _expression(predicate), 'passed': _holds(predicate, view),
            'facts': [{'field': leaf[0], 'operator': leaf[1], 'expected': deepcopy(leaf[2]),
                       'value': deepcopy(view.get(leaf[0])), 'passed': _holds(leaf, view)}
                      for leaf in _leaves(predicate)]}


def _ratio(a, b):
    return max(a, b) / min(a, b) if min(a, b) > 0 else None


def _conditions(rule, winner, loser):
    conditions = []
    if rule.get('scope') is not None:
        predicate = rule['scope']
        conditions.append({'kind': 'scope', 'label': '两项均在规则适用条件内',
            'expression': _expression(predicate),
            'passed': _holds(predicate, winner) is True and _holds(predicate, loser) is True,
            'facts': [{'field': leaf[0], 'operator': leaf[1], 'expected': deepcopy(leaf[2]),
                       'winner_value': deepcopy(winner.get(leaf[0])),
                       'loser_value': deepcopy(loser.get(leaf[0])),
                       'winner_passed': _holds(leaf, winner), 'loser_passed': _holds(leaf, loser)}
                      for leaf in _leaves(predicate)]})
    for kind, label, operator in [('same', '控制条件相同', 'eq'), ('differ', '比较因素不同', 'ne')]:
        for field in rule.get(kind, []):
            conditions.append({'kind': kind, 'label': label, 'field': field, 'operator': operator,
                               'winner_value': deepcopy(winner.get(field)),
                               'loser_value': deepcopy(loser.get(field)), 'passed': True})
    if 'max_param_ratio' in rule:
        conditions.append({'kind': 'param_ratio', 'label': '参数量比值在上限内', 'field': 'params',
            'operator': 'le', 'expected': rule['max_param_ratio'],
            'winner_value': winner['params'], 'loser_value': loser['params'],
            'ratio': _ratio(winner['params'], loser['params']), 'passed': True})
    return conditions


def _prediction_facts(rule, winner, loser):
    prediction = rule['predict']
    if 'better' in prediction:
        return {'kind': 'better_worse', 'label': '分别满足优选与劣选条件', 'fields': [],
                'winner_condition': _predicate_facts(prediction['better'], winner),
                'loser_condition': _predicate_facts(prediction['worse'], loser)}
    if 'dominates' in prediction:
        value = {'kind': 'dominates', 'label': '所有比较因素不差，至少一项更优', 'fields': []}
        for axis in prediction['dominates']:
            field, direction = axis[:2]
            values = {'field': field, 'direction': direction,
                      'winner_value': winner[field], 'loser_value': loser[field]}
            if len(axis) == 3:
                values.update(min_ratio=axis[2], ratio=_ratio(winner[field], loser[field]))
            value['fields'].append(values)
        for side, view in [('winner', winner), ('loser', loser)]:
            if prediction.get(side) is not None:
                value[side + '_condition'] = _predicate_facts(prediction[side], view)
        return value
    kind = 'higher_better' if 'higher_better' in prediction else 'lower_better'
    field = prediction[kind]
    return {'kind': kind, 'label': '该因素越大越优' if kind == 'higher_better' else '该因素越小越优',
            'fields': [{'field': field, 'direction': 'higher' if kind == 'higher_better' else 'lower',
                        'winner_value': winner[field], 'loser_value': loser[field],
                        'min_ratio': prediction.get('min_ratio', 1),
                        'ratio': _ratio(winner[field], loser[field])}]}


def public_validated_scope(value):
    """Expose only the canonical validation envelope, never arbitrary metadata."""
    if not isinstance(value, dict):
        return None
    scope = {key: deepcopy(value[key]) for key in (
        'family', 'model_type', 'profile_hash', 'intervention', 'pair_sampling',
        'budget_values', 'optimizer_types', 'loss_types') if key in value}
    if isinstance(value.get('family_options'), dict):
        scope['family_options'] = {key: deepcopy(item) for key, item in value['family_options'].items()
                                   if key in PUBLIC_FIELDS}
    if isinstance(value.get('controls'), dict):
        controls = value['controls']
        scope['controls'] = {'equal': [field for field in controls.get('equal', []) if field in CONTROL_FIELDS]}
        if 'architecture_intervention' in controls:
            scope['controls']['architecture_intervention'] = controls['architecture_intervention']
    return scope


def _rule_facts(record, winner, loser):
    metadata = record.get('metadata', {})
    sources = [{key: deepcopy(source[key]) for key in _SOURCE_FIELDS if key in source}
               for source in record.get('source_refs', [])]
    claim_ids = {source['source_claim_id'] for source in sources if source.get('source_claim_id')}
    if claim_id := record.get('claim_id', metadata.get('claim_id')):
        claim_ids.add(claim_id)
    result = {'rule_id': record['rule_id'], 'revision': record['revision'],
              'claim_ids': sorted(claim_ids), 'text': record['text'],
              'validity_status': record.get('validity_status', metadata.get('validity_status', 'proposed')),
              'validation_origin': record.get('validation_origin', metadata.get('validation_origin', 'research')),
              'source_refs': sources, 'conditions': _conditions(record['rule'], winner, loser),
              'prediction': _prediction_facts(record['rule'], winner, loser)}
    for key in ('clause_index', 'source_status', 'source_state', 'source_revision'):
        if key in record or key in metadata:
            result[key] = deepcopy(record.get(key, metadata.get(key)))
        elif key in ('source_status', 'source_revision'):
            distinct = {source[key] for source in sources if key in source}
            if len(distinct) == 1:
                result[key] = distinct.pop()
    scope = public_validated_scope(record.get('validated_scope', metadata.get('validated_scope')))
    if scope is not None:
        result['validated_scope'] = scope
    return result


def explain_task_prediction(case: dict, prediction: dict) -> dict:
    """Describe stored solver edges without changing the aggregate decision."""
    choices = {choice['id']: {'id': choice['id'], 'letter': choice['letter']}
               for choice in case['question']['choices']}
    views = dict(zip(choices, public_views(case['dataset_spec'], case['candidate_specs'])))
    graph = {choice: set() for choice in choices}
    edges, paths = [], []
    for match in prediction['matches']:
        kb = {key: match['kb'][key] for key in ('id', 'version', 'name')}
        rules = {(rule['rule_id'], rule['revision']): rule for rule in match['rules']}
        canonical = match['prediction']
        for edge in canonical['edges']:
            winner, loser = edge['winner'], edge['loser']
            graph[winner].add(loser)
            facts = [_rule_facts(rules[(ref['rule_id'], ref['revision'])], views[winner], views[loser])
                     for ref in edge['rules']]
            edges.append({'kb': kb, 'winner': choices[winner], 'loser': choices[loser], 'rules': facts})
        if prediction['status'] == 'answered' and canonical['answer_id'] == prediction['answer_id']:
            for _, path in sorted(canonical.get('paths', {}).items()):
                steps = list(zip(path, path[1:]))
                refs = [deepcopy(ref) for winner, loser in steps for edge in canonical['edges']
                        if edge['winner'] == winner and edge['loser'] == loser for ref in edge['rules']]
                paths.append({'kb_id': kb['id'], 'candidates': [choices[candidate] for candidate in path],
                              'rule_refs': refs})
    conflicts = [{'code': 'opposite_edges', 'candidates': [choices[a], choices[b]]}
                 for a, b in combinations(sorted(choices), 2) if b in graph[a] and a in graph[b]]
    if cycle := _cycle(graph):
        conflicts.append({'code': 'cycle', 'candidates': [choices[candidate] for candidate in cycle]})
    for issue in prediction.get('issues', []):
        if issue['code'] in ('kb_disagreement', 'partial_kb_disagreement'):
            answers = sorted({match['prediction']['answer_id'] for match in prediction['matches']
                              if match['prediction']['answer_id'] is not None})
            conflicts.append({'code': issue['code'], 'candidates': [choices[candidate] for candidate in answers]})
    reachability = {candidate: _paths(graph, candidate) for candidate in graph}
    uncovered = [[choices[a], choices[b]] for a, b in combinations(sorted(choices), 2)
                 if b not in reachability[a] and a not in reachability[b]] if prediction['status'] == 'uncovered' else []
    answer = choices.get(prediction['answer_id']) if prediction['status'] == 'answered' else None
    summary = (f'规则关系支持 {answer["letter"]} 优于其余所有候选。' if answer else
               '适用规则存在相反结论或循环关系，无法确定唯一答案。' if prediction['status'] == 'conflict' else
               '没有规则适用于当前候选，暂不作答。' if not edges else
               '现有规则尚不足以支持任一 KB 确定唯一答案。')
    return {'status': prediction['status'], 'answer': answer, 'summary': summary, 'edges': edges,
            'paths': paths, 'conflicts': conflicts, 'uncovered_pairs': uncovered}
