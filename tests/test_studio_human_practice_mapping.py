import pytest

from architecture_iq.studio.human_practice import project_feedback


QUESTION = {'choices': [{'id': 'c_A', 'letter': 'A'}, {'id': 'c_B', 'letter': 'B'}]}


@pytest.mark.parametrize('mapping', [{'candidate_id': 'c_B'}, {'candidateId': 'c_B'}, {'letter': 'B'},
                                     {'candidateId': 'c_A', 'candidate_id': 'c_B'}])
def test_imported_metrics_cannot_be_relabelled_using_only_the_outer_dictionary_key(mapping):
    result = project_feedback(QUESTION, {'candidate_metrics': {
        'c_A': {**mapping, 'mean_test_ce': .25, 'selection_metric': 'test_ce'}}})
    assert result['candidate_metrics'] == {}


@pytest.mark.parametrize('kind', ['ranked', 'curves'])
def test_conflicting_candidate_aliases_in_stored_results_are_not_silently_accepted(kind):
    row = {'candidateId': 'c_A', 'candidate_id': 'c_B', 'letter': 'A', 'metric': 'test_ce',
           'mean': [1., .5] if kind == 'curves' else .5, 'steps': [0, 10]}
    result = project_feedback(QUESTION, {'reveal': {kind: [row]}})
    assert result['reveal'][kind] == []


def test_exact_or_unannotated_metrics_keep_the_original_candidate_mapping():
    result = project_feedback(QUESTION, {'candidate_metrics': {
        'c_A': {'candidate_id': 'c_A', 'candidateId': 'c_A', 'letter': 'A', 'mean_test_ce': .25},
        'c_B': {'mean_test_ce': .5}}})
    assert result['candidate_metrics'] == {
        'c_A': {'letter': 'A', 'mean_test_ce': .25}, 'c_B': {'letter': 'B', 'mean_test_ce': .5}}
