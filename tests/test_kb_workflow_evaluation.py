from architecture_iq.kb.evaluation import score_evaluation

import copy
import pytest


def test_ranking_uses_only_decisive_seed_ranges_and_invalid_counts_wrong():
    q = {"id": "q1", "family": "f", "choices": [{"id": x, "letter": x} for x in "ABC"]}
    metrics = {
        x: {
            "metric": "test_mse",
            "seed_results": [
                {"seed": i, "failed": False, "final_test_mse": v}
                for i, v in enumerate(values)
            ],
        }
        for x, values in {"A": [1.0, 2.0], "B": [3.0, 4.0], "C": [2.0, 5.0]}.items()
    }
    private = {"q1": {"correct_letter": "A", "candidate_metrics": metrics}}
    outputs = {
        "clean": {
            "q1": {
                "valid": True,
                "ranking": ["B", "A", "C"],
                "knowledge_count": 0,
                "invalid_citations": False,
            }
        },
        "current": {
            "q1": {
                "valid": True,
                "ranking": ["A", "C", "B"],
                "knowledge_count": 1,
                "invalid_citations": False,
            }
        },
    }
    scores = score_evaluation([q], outputs, private)
    assert scores["clean"]["pairwise_total"] == 1
    assert scores["clean"]["pairwise_correct"] == 0
    assert scores["current"]["pairwise_correct"] == 1
    assert scores["current"]["helpful_changes"] == 1
    assert scores["current"]["harmful_changes"] == 0
    assert scores["current"]["covered_questions"] == 1
    assert scores["current"]["pairwise_unresolved"] == 2


def test_missing_pairwise_gt_is_reported_not_fabricated():
    q = {"id": "q", "family": "f", "choices": [{"id": x, "letter": x} for x in "ABC"]}
    outputs = {
        "clean": {
            "q": {
                "valid": False,
                "ranking": [],
                "knowledge_count": 0,
                "invalid_citations": True,
            }
        }
    }
    s = score_evaluation([q], outputs, {"q": {"correct_letter": "A"}})["clean"]
    assert s["pairwise_total"] == 0 and s["pairwise_accuracy"] is None
    assert s["pairwise_unresolved"] == 3 and s["invalid"] == 1
    assert s["invalid_citation_questions"] == 1


@pytest.mark.parametrize("metric_fields", [{"selection_metric": "test_mse"},
                                         {"metric": "test_mse", "selection_metric": "test_mse"}])
def test_canonical_runner_selection_metric_counts_decisive_pairs(metric_fields):
    question = {"id": "q", "family": "f", "choices": [{"id": letter, "letter": letter} for letter in "ABC"]}
    summaries = {letter: {**metric_fields, "execution": "candidate_py_files", "seed_results": [
        {"seed": seed, "failed": False, "final_test_mse": start + seed}
        for seed in range(2)]} for letter, start in zip("ABC", (1, 4, 7))}
    private = {"q": {"correct_letter": "A", "candidate_metrics": summaries}}
    before = copy.deepcopy(private)
    output = {"clean": {"q": {"valid": True, "ranking": list("ABC"), "knowledge_count": 0,
                               "invalid_citations": False}}}
    scores = score_evaluation([question], output, private)["clean"]
    assert scores["pairwise_total"] == scores["pairwise_correct"] == 3
    assert scores["pairwise_unresolved"] == 0
    assert private == before


@pytest.mark.parametrize("conflicting", [{"metric": "test_mse", "selection_metric": "test_ce"},
                                        {"metric": "test_ce", "selection_metric": "test_mse"},
                                        {"metric": 42, "selection_metric": "test_mse"}])
def test_conflicting_metric_aliases_abstain_without_changing_feedback(conflicting):
    question = {"id": "q", "family": "f", "choices": [{"id": letter, "letter": letter} for letter in "ABC"]}
    summaries = {letter: {"metric": "test_mse", "seed_results": [
        {"seed": 0, "failed": False, "final_test_mse": value}]}
        for letter, value in zip("ABC", (1, 4, 7))}
    summaries["A"].update(conflicting)
    private = {"q": {"correct_letter": "A", "candidate_metrics": summaries}}
    before = copy.deepcopy(private)
    output = {"clean": {"q": {"valid": True, "ranking": list("ABC"), "knowledge_count": 0,
                               "invalid_citations": False}}}
    scores = score_evaluation([question], output, private)["clean"]
    assert scores["pairwise_total"] == scores["pairwise_correct"] == 1
    assert scores["pairwise_unresolved"] == 2
    assert private == before
