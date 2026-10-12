"""Stored canonical GT/curve reading never imports generated training code."""
import json

import numpy as np
import pytest

from architecture_iq.studio import loop_source
from test_studio_loop_questions import question_source
from test_studio_loop_source import dump


def results(question_source):
    root, artifacts, qpath = question_source
    q = json.loads(qpath.read_text())
    candidate = q['choices'][0]['candidate_path']
    dump(artifacts, candidate + '/results/summary.json', {
        'candidate_id': 'c_a', 'selection_metric': 'test_ce', 'mean_test_ce': 1.5, 'std_test_ce': .5,
        'n_seeds': 2, 'environment': {'private': 'DO_NOT_TRANSPORT'}})
    return root, artifacts, artifacts / candidate / 'results'


def test_review_collector_returns_saved_answer_and_seed_aggregate_at_saved_sample_axis(question_source):
    root, artifacts, saved = results(question_source)
    np.savez(saved / 'curves.npz', curves=np.array([[4., 2.], [2., 1.]]), samples=np.array([4, 8]))
    before = {path: path.read_bytes() for path in root.parent.rglob('*') if path.is_file()}
    value = loop_source.collect_question(root, artifacts, 'q_example', include_results=True)
    assert value['feedback']['correct_letter'] == 'A'
    curve = value['feedback']['reveal']['curves'][0]
    assert curve == {'candidateId': 'c_a', 'letter': 'A', 'metric': 'test_ce',
                     'samples': [4, 8], 'mean': [3., 1.5], 'std': [1., .5]}
    assert 'DO_NOT_TRANSPORT' not in json.dumps(value)
    assert {path: path.read_bytes() for path in root.parent.rglob('*') if path.is_file()} == before
    # Reading a public question still never reads/returns these private files.
    public = loop_source.collect_question(root, artifacts, 'q_example')
    assert 'feedback' not in public and 'mean_test_ce' not in json.dumps(public)


@pytest.mark.parametrize('archive', ['missing', 'no_axis', 'wrong_axis', 'object'])
def test_missing_or_invalid_stored_curves_are_not_reconstructed(question_source, archive):
    root, artifacts, saved = results(question_source)
    if archive == 'no_axis': np.savez(saved / 'curves.npz', curves=np.array([[4., 2.]]))
    elif archive == 'wrong_axis': np.savez(saved / 'curves.npz', curves=np.array([[4., 2.]]), samples=np.array([4]))
    elif archive == 'object': np.savez(saved / 'curves.npz', curves=np.array([['private']], dtype=object), samples=np.array([4]))
    value = loop_source.collect_question(root, artifacts, 'q_example', include_results=True)
    assert value['feedback']['correct_letter'] == 'A'
    assert value['feedback']['reveal']['curves'] == []


def test_result_candidate_identity_mismatch_is_rejected(question_source):
    root, artifacts, saved = results(question_source)
    (saved / 'summary.json').write_text(json.dumps({'candidate_id': 'different', 'mean_test_ce': 1.0}))
    with pytest.raises(loop_source.SourceUnavailable):
        loop_source.collect_question(root, artifacts, 'q_example', include_results=True)


def test_result_symlink_is_rejected(question_source):
    root, artifacts, saved = results(question_source)
    target = saved / 'summary.json'
    target.unlink()
    target.symlink_to(question_source[2])
    with pytest.raises(loop_source.SourceUnavailable):
        loop_source.collect_question(root, artifacts, 'q_example', include_results=True)


def test_result_for_different_metric_is_not_mislabeled_as_question_curve(question_source):
    root, artifacts, saved = results(question_source)
    (saved / 'summary.json').write_text(json.dumps({'candidate_id': 'c_a', 'selection_metric': 'test_mse', 'mean_test_mse': 1.0}))
    np.savez(saved / 'curves.npz', curves=np.array([[3., 2.]]), samples=np.array([4, 8]))
    with pytest.raises(loop_source.SourceUnavailable):
        loop_source.collect_question(root, artifacts, 'q_example', include_results=True)
