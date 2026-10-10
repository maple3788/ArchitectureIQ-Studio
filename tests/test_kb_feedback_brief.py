"""Scientific discovery inputs retain evidence, not presentation artifacts."""
import copy
import json

import pytest

from architecture_iq.kb.orchestrator import _feedback_brief


def feedback():
    summary = {
        'candidate_id': 'c1', 'selection_metric': 'test_ce',
        'mean_test_ce': 0.3, 'std_test_ce': 0.1, 'n_seeds': 2,
        'failed_seeds': 1, 'excluded': False,
        'seed_results': [{'seed': 0, 'failed': False, 'final_test_ce': 0.3, 'final_test_accuracy': 0.9},
                         {'seed': 1, 'failed': True, 'final_test_ce': None}],
        'environment': {'big': 'ENVIRONMENT' * 10000},
    }
    return {
        'correct_letter': 'A', 'higher_is_better': False,
        'candidate_metrics': {'c1': summary},
        'significance': {'metric': 'test_ce', 'passed': True, 'gap': 0.2, 'win_rate': 1.0},
        'reveal': {'correctLetter': 'A', 'ranked': [{'candidateId': 'c1', 'letter': 'A', 'metric': 'test_ce', 'mean': 0.3, 'std': 0.1}],
                   'curves': [{'letter': 'A', 'mean': [0.3] * 10000}],
                   'files': {'A': {'summary.json': copy.deepcopy(summary)}}},
        'curves': [[0.3] * 10000], 'unknown_blob': 'BLOB' * 10000,
    }


def test_nested_bake_feedback_projects_only_scientific_fields_without_mutation():
    original = feedback()
    before = copy.deepcopy(original)
    result = _feedback_brief(original)
    assert original == before
    assert len(json.dumps(result)) < 2500
    assert 'ENVIRONMENT' not in json.dumps(result) and 'BLOB' not in json.dumps(result)
    assert 'reveal' not in result and 'curves' not in result
    assert result['correct_letter'] == 'A' and result['higher_is_better'] is False
    assert result['selection_metric'] == 'test_ce'
    candidate = result['candidate_metrics']['c1']
    assert {k: candidate[k] for k in ['mean', 'std', 'n_seeds', 'failed_seeds']} == {'mean': 0.3, 'std': 0.1, 'n_seeds': 2, 'failed_seeds': 1}
    assert candidate['seed_results'] == [{'seed': 0, 'failed': False, 'final_test_ce': 0.3}, {'seed': 1, 'failed': True, 'final_test_ce': None}]
    assert result['significance'] == original['significance']
    assert 'private_feedback.json' in json.dumps(result['summary'])


def test_legacy_metric_and_minimal_feedback_remain_supported_without_direction_guessing():
    original = {'correct_letter': 'B', 'candidate_metrics': {'c1': {'metric': 'test_ce', 'mean': 0.5, 'seed_results': [{'seed': 4, 'failed': False, 'final_test_ce': 0.5}]}}}
    result = _feedback_brief(original)
    assert result['candidate_metrics']['c1']['selection_metric'] == 'test_ce'
    assert result['candidate_metrics']['c1']['mean'] == 0.5
    assert result['higher_is_better'] is None
    assert 'higher_is_better' in result['summary']['missing']
    minimal = _feedback_brief({'correct_letter': 'B'})
    assert minimal['correct_letter'] == 'B' and minimal['candidate_metrics'] == {}


@pytest.mark.parametrize('change', ['metric_alias', 'mean_alias', 'correct_letter', 'duplicate_summary', 'direction', 'ranked_mean'])
def test_conflicting_scientific_values_are_rejected(change):
    value = feedback()
    if change == 'metric_alias':
        value['candidate_metrics']['c1']['metric'] = 'test_mse'
    elif change == 'mean_alias':
        value['candidate_metrics']['c1']['mean'] = 9
    elif change == 'correct_letter':
        value['reveal']['correctLetter'] = 'B'
    elif change == 'duplicate_summary':
        value['reveal']['files']['A']['summary.json']['n_seeds'] = 9
    elif change == 'direction':
        value['significance']['higher_is_better'] = True
    else:
        value['reveal']['ranked'][0]['mean'] = 9
    with pytest.raises(ValueError, match='Conflicting'):
        _feedback_brief(value)


def test_reveal_only_summary_uses_public_choice_identity_and_preserves_all_seeds():
    original = feedback()
    original.pop('candidate_metrics')
    original['reveal'].pop('ranked')
    rows = [{'seed': seed, 'failed': False, 'final_test_ce': 0.3} for seed in range(101)]
    original['reveal']['files']['A']['summary.json'].update(seed_results=rows, n_seeds=101, failed_seeds=0)
    question = {'choices': [{'letter': 'A', 'id': 'c1'}], 'prompt': 'Unchanged data conditions'}
    before = copy.deepcopy(question)
    result = _feedback_brief(original, question=question)
    assert result['candidate_metrics']['c1']['seed_results'] == rows
    assert question == before


def test_missing_metric_never_labels_arbitrary_seed_fields_as_selection_results():
    value = {'correct_letter': 'A', 'candidate_metrics': {'c': {'seed_results': [{'seed': 1, 'failed': False, 'final_unrecognized': 4}]}}}
    result = _feedback_brief(value)
    assert result['candidate_metrics']['c']['seed_results'] == [{'seed': 1, 'failed': False}]
    assert 'candidate_metrics.c.selection_metric' in result['summary']['missing']


def test_seed_final_metric_must_be_scalar_not_an_embedded_curve():
    value = feedback()
    value['candidate_metrics']['c1']['seed_results'][0]['final_test_ce'] = [0.3] * 10000
    with pytest.raises(ValueError, match='final selection metric'):
        _feedback_brief(value)
