"""Explanations retain canonical decisions and expose only their public basis."""
from copy import deepcopy
import json

from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
from architecture_iq.studio.rule_refinement.prediction import predict_question
from architecture_iq.studio.task_explanations import explain_task_prediction
from rule_refinement_fixtures import public_case, rule_entry


def prediction(tmp_path, case, entries, *, name='kb-one'):
    kb = RuleArtifactStore(tmp_path / name).import_rules(
        {'rules': entries}, source_ref={'id': name, 'source_claim_id': 'C0042',
                                      'source_clause_index': 2, 'path': '/private/secret'})
    result = predict_question(case, kb)
    matched = {ref['rule_id'] for edge in result['edges'] for ref in edge['rules']}
    return {'kb': {'id': name, 'version': kb['version'], 'name': 'Knowledge'},
            'prediction': result,
            'rules': [{**rule, 'validity_status': 'replicated_in_scope',
                       'validation_origin': 'source_reported'}
                      for rule in kb['rules'] if rule['rule_id'] in matched]}


def aggregate(matches, status=None, answer=None):
    result = matches[0]['prediction']
    return {'status': status or result['status'],
            'answer_id': answer if status else result['answer_id'], 'matches': matches, 'issues': []}


def test_trace_exposes_scope_controls_actual_values_and_original_claim_without_private_data(tmp_path):
    case = public_case()
    for spec, count in zip(case['candidate_specs'], (400, 200, 100)):
        spec['trainable_parameter_count'] = count
    rule = {'text': 'Wider wins under the same budget', 'rule': {
        'scope': {'all': [['model_type', 'eq', 'mlp'], ['budget', 'le', 12]]},
        'same': ['budget', 'opt_key'], 'differ': ['width'], 'max_param_ratio': 4,
        'predict': {'higher_better': 'width', 'min_ratio': 2}}}
    match = prediction(tmp_path, case, [rule])
    result = aggregate([match]); before = deepcopy(result)
    trace = explain_task_prediction(case, result)
    assert trace['answer'] == {'id': 'c_A', 'letter': 'A'}
    edge = next(e for e in trace['edges'] if e['loser']['letter'] == 'B')
    assert edge['winner'] == {'id': 'c_A', 'letter': 'A'}
    source = edge['rules'][0]
    assert source['claim_ids'] == ['C0042']
    assert source['revision'] == match['rules'][0]['revision']
    assert source['validity_status'] == 'replicated_in_scope'
    assert source['validation_origin'] == 'source_reported'
    scope = next(c for c in source['conditions'] if c['kind'] == 'scope')
    assert scope['passed'] and scope['facts'][1]['winner_value'] == 12
    assert scope['facts'][1]['loser_value'] == 12
    same = next(c for c in source['conditions'] if c.get('field') == 'budget')
    assert same['kind'] == 'same' and same['winner_value'] == same['loser_value'] == 12
    differ = next(c for c in source['conditions'] if c['kind'] == 'differ')
    assert (differ['winner_value'], differ['loser_value']) == (32, 16)
    ratio = next(c for c in source['conditions'] if c['kind'] == 'param_ratio')
    assert ratio['ratio'] == 2 and ratio['expected'] == 4
    assert source['prediction']['fields'][0] == {
        'field': 'width', 'direction': 'higher', 'winner_value': 32,
        'loser_value': 16, 'min_ratio': 2, 'ratio': 2}
    assert [[c['letter'] for c in p['candidates']] for p in trace['paths']] == [['A', 'B'], ['A', 'C']]
    assert trace['paths'][0]['rule_refs'][0]['rule_id'] == match['rules'][0]['rule_id']
    assert result == before
    serialized = json.dumps(trace)
    assert '/private/' not in serialized and 'correct_letter' not in serialized


def test_paths_explain_transitive_answer_using_exact_step_rules(tmp_path):
    case = public_case()
    match = prediction(tmp_path, case, [rule_entry((32, 16)), rule_entry((16, 8))])
    trace = explain_task_prediction(case, aggregate([match]))
    path = next(p for p in trace['paths'] if p['candidates'][-1]['letter'] == 'C')
    assert [c['letter'] for c in path['candidates']] == ['A', 'B', 'C']
    assert len(path['rule_refs']) == 2
    assert {ref['rule_id'] for ref in path['rule_refs']} == {r['rule_id'] for r in match['rules']}


def test_opposing_rules_and_cross_kb_cycles_explain_abstention(tmp_path):
    case = public_case()
    matches = [prediction(tmp_path, case, [rule_entry((32, 16))], name='one'),
               prediction(tmp_path, case, [rule_entry((16, 8))], name='two'),
               prediction(tmp_path, case, [rule_entry((8, 32), lower=True)], name='three')]
    trace = explain_task_prediction(case, aggregate(matches, status='conflict'))
    assert trace['answer'] is None and trace['paths'] == []
    assert [c['letter'] for c in next(c for c in trace['conflicts'] if c['code'] == 'cycle')['candidates']] == ['A', 'B', 'C', 'A']
    opposite = prediction(tmp_path, case, [rule_entry(), rule_entry(lower=True)], name='opposite')
    trace = explain_task_prediction(case, aggregate([opposite]))
    pairs = [c for c in trace['conflicts'] if c['code'] == 'opposite_edges']
    assert len(pairs) == 3 and trace['answer'] is None


def test_no_rule_and_partial_rule_trace_identify_uncovered_pairs(tmp_path):
    case = public_case()
    for name, rules, expected in [('empty', [], 3), ('partial', [rule_entry((32, 16))], 2)]:
        match = prediction(tmp_path, case, rules, name=name)
        trace = explain_task_prediction(case, aggregate([match]))
        assert trace['status'] == 'uncovered' and trace['answer'] is None
        assert len(trace['uncovered_pairs']) == expected
        assert trace['conflicts'] == [] and trace['paths'] == []


def test_compound_predicate_and_dominance_show_conditions_without_claiming_each_branch_true(tmp_path):
    case = public_case()
    rule = {'text': 'Wider at the same depth', 'rule': {
        'scope': {'any': [['width', 'eq', 999], {'not': ['activation', 'eq', 'gelu']}]},
        'predict': {'dominates': [['width', 'higher', 2], ['depth', 'lower']],
                    'winner': ['width', 'ge', 16], 'loser': ['width', 'le', 16]}}}
    match = prediction(tmp_path, case, [rule])
    trace = explain_task_prediction(case, aggregate([match]))
    source = trace['edges'][0]['rules'][0]
    scope = source['conditions'][0]
    assert scope['passed'] and scope['facts'][0]['winner_passed'] is False
    assert '或' in scope['expression'] and '非' in scope['expression']
    assert source['prediction']['kind'] == 'dominates'
    assert [field['direction'] for field in source['prediction']['fields']] == ['higher', 'lower']
    assert source['prediction']['winner_condition']['passed'] is True
    assert source['prediction']['loser_condition']['passed'] is True


def test_better_worse_rule_renders_predicate_evidence_and_lower_direction(tmp_path):
    case = public_case()
    better = {'text': 'Prefer narrow', 'rule': {'predict': {
        'better': ['width', 'eq', 8], 'worse': ['width', 'gt', 8]}}}
    match = prediction(tmp_path, case, [better])
    trace = explain_task_prediction(case, aggregate([match]))
    assert trace['answer']['letter'] == 'C'
    source = trace['edges'][0]['rules'][0]
    assert source['prediction']['kind'] == 'better_worse'
    assert source['prediction']['winner_condition']['facts'][0]['value'] == 8
    match = prediction(tmp_path, case, [rule_entry(lower=True)], name='lower')
    trace = explain_task_prediction(case, aggregate([match]))
    assert trace['answer']['letter'] == 'C'
    assert trace['edges'][0]['rules'][0]['prediction']['fields'][0]['direction'] == 'lower'


def test_source_status_and_validation_boundary_remain_separate_from_solver_outcome(tmp_path):
    case = public_case()
    match = prediction(tmp_path, case, [rule_entry()])
    source = match['rules'][0]
    source['source_refs'][0].update(source_status='candidate', source_revision='frozen-source-42')
    source.update(validity_status='proposed', validation_origin='source_reported',
                  claim_id='C0042', clause_index=2, validated_scope={
                      'family': 'univariate_regression', 'budget_values': [12],
                      'controls': {'equal': ['budget', 'opt_key'], 'architecture_intervention': 'width'},
                      'family_options': {'input_dim': 1, 'private': '/private/secret'},
                      'source_file': '/private/source.json'})
    trace = explain_task_prediction(case, aggregate([match]))
    rule = trace['edges'][0]['rules'][0]
    assert trace['status'] == 'answered'
    assert rule['source_status'] == 'candidate' and rule['source_revision'] == 'frozen-source-42'
    assert rule['validity_status'] == 'proposed' and rule['validation_origin'] == 'source_reported'
    assert rule['claim_ids'] == ['C0042'] and rule['clause_index'] == 2
    assert rule['validated_scope']['budget_values'] == [12]
    assert rule['validated_scope']['family_options'] == {'input_dim': 1}
    assert '/private/' not in json.dumps(trace)


def test_formal_task_explanation_keeps_original_validation_scope_after_rule_import(tmp_path, monkeypatch):
    from rag_fixtures import formal_library
    from rule_refinement_fixtures import raw_case
    from test_studio_catalog import bakefile
    from test_studio_tasks import rules_case, task, preview

    case = rules_case(tmp_path, monkeypatch)
    _, item = formal_library(tmp_path / 'formal', monkeypatch)
    case['inventory']['items'] = [item]
    raw = raw_case(qid='q_formal_scope')
    raw.update(family='xor_classification', profile_hash='a' * 64, metric='test_ce')
    dataset = raw['detail']['dataset']['files']['dataset_spec.json']
    dataset.update(family='xor_classification', selection_metric='test_ce', params={'input_dim': 2})
    for choice in raw['detail']['choices']:
        choice['files']['candidate_spec.json'].update(family='xor_classification',
            optimizer={'type': 'Adam', 'lr': .001}, loss={'loss_id': 'cross_entropy'},
            budget={'total_samples_seen': 8192, 'batch_size': 32, 'training_steps': 256})
    case['catalog'].import_source(bakefile(tmp_path / 'formal-question.json', [raw]))
    case['question_key'] = next(q['key'] for q in case['catalog'].list_questions()['items'] if q['id'] == raw['id'])
    shown = preview(case, task(case, mode='rules', model_id=None))
    assert shown['prediction']['answer_letter'] == 'C'
    rule = shown['prediction']['explanation']['edges'][0]['rules'][0]
    assert rule['validated_scope']['profile_hash'] == 'a' * 64
    assert rule['validated_scope']['budget_values'] == [8192]
    assert rule['validated_scope']['intervention'] == 'width'
    assert rule['validated_scope']['controls']['equal'] == ['opt_key', 'loss_key', 'budget', 'batch_size']
    assert rule['validation_origin'] == 'verified_source_scope'
    assert '/formal/' not in json.dumps(shown)
