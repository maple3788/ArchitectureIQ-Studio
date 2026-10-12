"""Applicability is a public-spec condition check, never a GT validation claim."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
from rule_refinement_fixtures import raw_case, rule_entry
from services.kb_workflow_api.app import create_app
from test_studio_catalog import bakefile


def api_case(tmp_path, monkeypatch, *, rules=None, records=None):
    app = create_app(state_root=tmp_path / 'state', allowed_roots=[tmp_path], execution_enabled=False)
    app.state.catalog.import_source(bakefile(tmp_path / 'questions.json', records or [
        raw_case('q_match', widths=(32, 16, 8)),
        raw_case('q_outside', widths=(4, 2, 1)),
        raw_case('q_tie', widths=(16, 16, 16))]))
    store = RuleArtifactStore(tmp_path / 'rules')
    snapshot = store.import_rules({'schema_version': 'kb_claim_rules_v1', 'claims': [
        {'id': 'C1', 'text': 'Prefer wider models in this scope', 'rules': rules if rules is not None else [
            rule_entry((8, 16, 32))['rule']]},
        {'id': 'C2', 'text': 'Sibling must not affect this entry', 'rules': [rule_entry(lower=True)['rule']]},
        {'id': 'C3', 'text': 'Uncompiled descriptive claim', 'rules': []}]}, source_ref={'id': 'source'})
    item = {'id': 'kb', 'version': snapshot['version'], 'kind': 'research_rules', 'name': 'Fixture',
            'snapshot': snapshot, 'counts': {}, 'sources': [], 'source': '/private/source'}
    inventory = {'items': [item]}
    monkeypatch.setattr('architecture_iq.studio.knowledge.knowledge_inventory', lambda *a: inventory)
    return {'app': app, 'client': TestClient(app), 'inventory': inventory, 'item': item, 'store': store}


def query(case, **changes):
    return case['client'].get('/api/studio/kb/questions', params={
        'kb_id': case['item']['id'], 'kb_version': case['item']['version'], 'claim_id': 'C1', **changes})


def test_selected_claim_conditions_distinguish_outside_from_tie_and_keep_counts_before_paging(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    before = deepcopy(case['item'])
    response = query(case)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['counts'] == {'applicable': 1, 'inapplicable': 1, 'unknown': 1}
    items = {item['id']: item for item in value['items']}
    assert items['q_match']['relation'] == 'applicable'
    assert items['q_match']['prediction_status'] == 'answered'
    assert items['q_match']['matched_rules'] == 1 and items['q_match']['matched_pairs'] == 3
    assert items['q_match']['candidate_configs'][0]['letter'] == 'A'
    assert items['q_match']['candidate_configs'][0]['model']['width'] == 32
    assert items['q_outside']['relation'] == 'inapplicable'
    assert items['q_outside']['reason']['code'] == 'conditions_not_met'
    assert items['q_tie']['relation'] == 'unknown'
    assert items['q_tie']['reason']['code'] == 'no_comparable_candidates'
    assert value['kb_ref'] == {key: case['item'][key] for key in ('id', 'version')}
    assert case['item'] == before
    assert '/private/' not in response.text and 'correct_letter' not in response.text and 'seed_results' not in response.text
    page = query(case, relation='unknown', limit=1).json()
    assert page['total'] == 1 and page['counts'] == value['counts'] and len(page['items']) == 1
    assert query(case, relation='unknown', offset=1).json()['items'] == []
    searched = query(case, search='q_outside').json()
    assert searched['counts'] == {'applicable': 0, 'inapplicable': 1, 'unknown': 0}
    assert case['client'].get('/api/studio/tasks/questions/' + items['q_match']['key']).status_code == 200
    assert not case['app'].state.jobs.list() and not case['app'].state.tasks.list()


def test_opposite_selected_branches_remain_applicable_with_conflict(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch, rules=[rule_entry()['rule'], rule_entry(lower=True)['rule']])
    response = query(case, search='q_match')
    assert response.status_code == 200, response.text
    item = response.json()['items'][0]
    assert item['relation'] == 'applicable' and item['prediction_status'] == 'conflict'
    assert item['matched_rules'] == 2 and item['matched_pairs'] == 3
    assert item['reason']['code'] == 'rule_conflict'


@pytest.mark.parametrize('rule', [
    {'scope': ['d_model', 'gt', 1], 'predict': {'higher_better': 'width'}},
    {'same': ['d_model'], 'predict': {'higher_better': 'width'}},
    {'differ': ['d_model'], 'predict': {'higher_better': 'width'}},
    {'predict': {'higher_better': 'd_model'}},
    {'predict': {'dominates': [['d_model', 'higher']]}},
    {'predict': {'better': ['d_model', 'gt', 16], 'worse': ['d_model', 'le', 16]}}
])
def test_complete_specs_with_missing_referenced_features_are_unknown(tmp_path, monkeypatch, rule):
    case = api_case(tmp_path, monkeypatch, rules=[rule])
    response = query(case, search='q_match')
    assert response.status_code == 200, response.text
    item = response.json()['items'][0]
    assert item['relation'] == 'unknown'
    assert item['reason']['code'] == 'missing_public_features'
    assert 'd_model' in item['reason']['message']


@pytest.mark.parametrize('rule', [
    {'same': ['width'], 'predict': {'higher_better': 'width'}},
    {'max_param_ratio': 1, 'predict': {'higher_better': 'width'}}
])
def test_known_pair_control_failures_are_inapplicable(tmp_path, monkeypatch, rule):
    raw = raw_case('q_match')
    for index, choice in enumerate(raw['detail']['choices'], 1):
        choice['files']['candidate_spec.json']['trainable_parameter_count'] = 100 * index
    case = api_case(tmp_path, monkeypatch, rules=[rule], records=[raw])
    response = query(case, search='q_match')
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['relation'] == 'inapplicable'


def test_uncompiled_claim_is_unknown_instead_of_empty_or_inapplicable(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    response = query(case, claim_id='C3')
    assert response.status_code == 200, response.text
    assert response.json()['counts'] == {'applicable': 0, 'inapplicable': 0, 'unknown': 3}
    assert all(item['reason']['code'] == 'no_executable_rules' for item in response.json()['items'])


@pytest.mark.parametrize('changes,status', [
    ({'kb_version': '0' * 64}, 404), ({'kb_id': 'unknown'}, 404),
    ({'claim_id': 'unknown'}, 404), ({'limit': 0}, 422),
    ({'offset': -1}, 422), ({'relation': 'verified'}, 422)
])
def test_invalid_or_stale_references_do_not_fall_back(tmp_path, monkeypatch, changes, status):
    case = api_case(tmp_path, monkeypatch)
    assert query(case, **changes).status_code == status


def test_mutated_snapshot_is_rejected_without_resigning(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    case['item']['snapshot']['rules'][0]['rule']['predict'] = {'lower_better': 'width'}
    frozen = json.dumps(case['item'])
    assert query(case).status_code == 409
    assert json.dumps(case['item']) == frozen


def test_retired_group_and_old_version_are_resolved_independently(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch)
    original = deepcopy(case['item'])
    rule = original['snapshot']['rules'][0]
    updated = case['store'].apply_patch(original['version'], {'base_version': original['version'],
        'operations': [{'op': 'retire', 'rule_id': rule['rule_id'], 'revision': rule['revision']}],
        'rationale': '', 'case_refs': []})
    case['item'].update(version=updated['version'], snapshot=updated)
    case['inventory']['items'].append(original)
    current = query(case, search='q_match').json()['items'][0]
    old = query(case, search='q_match', kb_version=original['version']).json()['items'][0]
    assert current['relation'] == 'unknown' and current['reason']['code'] == 'inactive_rules'
    assert old['relation'] == 'applicable'


def test_missing_parameter_count_is_unknown_not_failed_ratio(tmp_path, monkeypatch):
    case = api_case(tmp_path, monkeypatch, rules=[{'max_param_ratio': 1, 'predict': {'higher_better': 'width'}}])
    item = query(case, search='q_match').json()['items'][0]
    assert item['relation'] == 'unknown' and item['reason']['code'] == 'missing_public_features'
    assert 'params' in item['reason']['message']


def test_formal_rules_require_original_validation_and_public_scope(tmp_path, monkeypatch):
    from rag_fixtures import formal_library
    raw = raw_case('q_formal')
    raw.update(family='xor_classification', profile_hash='a' * 64, metric='test_ce')
    raw['detail']['dataset']['files']['dataset_spec.json'].update(
        family='xor_classification', selection_metric='test_ce', params={'input_dim': 2})
    for choice in raw['detail']['choices']:
        choice['files']['candidate_spec.json'].update(family='xor_classification',
            optimizer={'type': 'Adam', 'lr': .001}, loss={'loss_id': 'cross_entropy'},
            budget={'total_samples_seen': 8192, 'batch_size': 32, 'training_steps': 256})
    missing = deepcopy(raw)
    missing['id'] = 'q_no_profile'
    missing.pop('profile_hash')
    case = api_case(tmp_path, monkeypatch, records=[raw, missing])
    _, formal = formal_library(tmp_path / 'formal', monkeypatch)
    case['item'] = formal
    case['inventory']['items'] = [formal]
    cid = formal['snapshot']['claims'][0]['id']
    response = query(case, claim_id=cid)
    assert response.status_code == 200, response.text
    items = {item['id']: item for item in response.json()['items']}
    assert items['q_formal']['relation'] == 'applicable'
    assert items['q_no_profile']['relation'] == 'unknown'
    assert items['q_no_profile']['reason']['code'] == 'validation_scope_unavailable'
    # A lost/corrupted validation source must not turn a formal claim into an
    # unverified executable hypothesis or a negative applicability assertion.
    monkeypatch.setattr('architecture_iq.kb.store.verify_evidence_sources',
                        lambda *a, **kw: (_ for _ in ()).throw(ValueError('Unavailable private source')))
    value = query(case, claim_id=cid).json()
    assert value['counts'] == {'applicable': 0, 'inapplicable': 0, 'unknown': 2}
    assert all(item['reason']['code'] == 'validation_unavailable' for item in value['items'])


def test_experience_is_unknown_and_empty_bank_has_zero_counts(tmp_path, monkeypatch):
    from rag_fixtures import experience_library
    case = api_case(tmp_path, monkeypatch)
    item = experience_library(tmp_path / 'experience')
    case['item'] = item
    case['inventory']['items'] = [item]
    cid = item['snapshot']['lessons'][0]['id']
    value = query(case, claim_id=cid).json()
    assert value['counts'] == {'applicable': 0, 'inapplicable': 0, 'unknown': 3}
    empty = query(case, claim_id=cid, search='no-such-question').json()
    assert empty['items'] == [] and empty['total'] == 0
    assert empty['counts'] == {'applicable': 0, 'inapplicable': 0, 'unknown': 0}


@pytest.mark.parametrize('mode', ['better_worse', 'winner_loser'])
def test_predicate_rule_with_no_plain_sgd_candidates_is_inapplicable(tmp_path, monkeypatch, mode):
    # O3's exact authored predicates: adaptive optimizer at sufficient lr
    # versus plain SGD. Adam's momentum=None is irrelevant when opt!=SGD
    # has already made that conjunction definitively false.
    adaptive = [['opt', 'in', ['Adam', 'AdamW', 'RMSprop', 'Adagrad']], ['lr', 'ge', .0001]]
    plain_sgd = [['opt', 'eq', 'SGD'], ['momentum', 'eq', 0]]
    prediction = ({'better': adaptive, 'worse': plain_sgd} if mode == 'better_worse' else
                  {'dominates': [['width', 'higher']], 'winner': adaptive, 'loser': plain_sgd})
    raw = raw_case('q_adaptive')
    for choice in raw['detail']['choices']:
        choice['files']['candidate_spec.json']['optimizer'] = {'type': 'Adam', 'lr': .001}
    case = api_case(tmp_path, monkeypatch, rules=[{'predict': prediction}], records=[raw])
    response = query(case)
    assert response.status_code == 200, response.text
    item = response.json()['items'][0]
    assert item['relation'] == 'inapplicable' and item['reason']['code'] == 'conditions_not_met'
    assert '优劣' in item['reason']['message']


def test_predicate_direction_with_missing_feature_stays_unknown(tmp_path, monkeypatch):
    rule = {'predict': {'better': ['beta1', 'gt', .8], 'worse': ['opt', 'eq', 'SGD']}}
    raw = raw_case('q_missing_beta')
    raw['detail']['choices'][0]['files']['candidate_spec.json']['optimizer'] = {'type': 'Adam', 'lr': .001}
    case = api_case(tmp_path, monkeypatch, rules=[rule], records=[raw])
    item = query(case).json()['items'][0]
    assert item['relation'] == 'unknown' and item['reason']['code'] == 'missing_public_features'
    assert 'beta1' in item['reason']['message']


def test_both_valid_predicate_directions_are_ambiguous_not_inapplicable(tmp_path, monkeypatch):
    rule = {'predict': {'better': ['width', 'gt', 0], 'worse': ['width', 'gt', 0]}}
    case = api_case(tmp_path, monkeypatch, rules=[rule])
    item = query(case, search='q_match').json()['items'][0]
    assert item['relation'] == 'unknown' and item['reason']['code'] == 'no_comparable_candidates'


def test_opposing_predicate_clauses_keep_real_canonical_conflict(tmp_path, monkeypatch):
    adaptive, plain_sgd = ['adaptive', 'eq', True], ['opt', 'eq', 'SGD']
    rules = [{'predict': {'better': adaptive, 'worse': plain_sgd}},
             {'predict': {'better': plain_sgd, 'worse': adaptive}}]
    raw = raw_case('q_opposing')
    raw['detail']['choices'][0]['files']['candidate_spec.json']['optimizer'] = {'type': 'Adam', 'lr': .001}
    case = api_case(tmp_path, monkeypatch, rules=rules, records=[raw])
    item = query(case).json()['items'][0]
    assert item['relation'] == 'applicable' and item['prediction_status'] == 'conflict'
    assert item['reason']['code'] == 'rule_conflict' and item['matched_rules'] == 2
