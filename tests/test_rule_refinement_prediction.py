from copy import deepcopy

import pytest

from rule_refinement_fixtures import public_case, raw_case, rule_entry
from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore


def kb(tmp_path, edges):
    entries = [rule_entry((a, b), lower=a < b) for a,b in edges]
    return RuleArtifactStore(tmp_path).import_rules({"rules": entries}, source_ref={"id": "fixture"})


def test_transitive_winner_keeps_direct_evidence(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    result = predict_question(public_case(), kb(tmp_path, [(32,16),(16,8)]))
    assert result["status"] == "answered" and result["answer_id"] == "c_A"
    assert len(result["edges"]) == 2
    assert result["paths"]["c_C"] == ["c_A", "c_B", "c_C"]
    assert sum(len(e["rules"]) for e in result["edges"]) == 2


@pytest.mark.parametrize("edges", [
    [(32,16),(16,32)],
    [(32,16),(16,8),(8,32)],
    [(32,16),(32,8),(32,4),(16,8),(8,4),(4,16)],
])
def test_lower_candidate_cycle_blocks_even_obvious_top1(tmp_path, edges):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    result = predict_question(public_case(raw_case(widths=(32,16,8,4), losses=(1,2,3,4))), kb(tmp_path,edges))
    assert result["status"] == "conflict"
    assert result["answer_id"] is None
    assert any(i["code"] in {"opposite_edges","cycle"} for i in result["issues"])


def test_disconnected_candidates_abstain(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    result = predict_question(public_case(raw_case(widths=(32,16,8,4), losses=(1,2,3,4))), kb(tmp_path,[(32,16),(8,4)]))
    assert result["status"] == "uncovered"
    assert result["answer_id"] is None
    assert result["issues"][0]["maxima"] == ["c_A", "c_C"]


def test_missing_public_control_never_guesses(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    case = public_case()
    case["candidate_specs"][0]["model"].pop("width")
    result = predict_question(case, kb(tmp_path, [(32,16),(16,8)]))
    assert result["status"] == "uncovered"
    assert result["answer_id"] is None


def test_duplicate_rules_and_candidate_order_do_not_vote_or_change_answer(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    snapshot = kb(tmp_path, [(32,16),(16,8),(32,16)])
    case = public_case()
    first = predict_question(case, snapshot)
    case["question"]["choices"].reverse()
    case["candidate_specs"].reverse()
    second = predict_question(case, snapshot)
    assert first["answer_id"] == second["answer_id"] == "c_A"
    assert len(first["edges"]) == len(second["edges"]) == 2
    assert first["paths"] == second["paths"]
    assert len(next(e for e in first["edges"] if e["winner"] == "c_A")["rules"]) == 2


@pytest.mark.parametrize("broken", ["duplicate", "single", "expression", "metric", "candidate_metric", "feedback", "misbound"])
def test_malformed_public_cases_return_invalid_without_prediction(tmp_path, broken):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    case = public_case()
    if broken == "duplicate":
        case["question"]["choices"][1]["id"] = "c_A"
    elif broken == "single":
        case["question"]["choices"] = case["question"]["choices"][:1]
        case["candidate_specs"] = case["candidate_specs"][:1]
    elif broken == "expression":
        case["dataset_spec"]["params"]["expression"] = "__import__('os').system('false')"
    elif broken == "metric":
        case["objective"] = "test_ce"
    elif broken == "candidate_metric":
        case["candidate_specs"][1]["selection_metric"] = "test_ce"
    elif broken == "feedback":
        case["feedback"] = {"correct_letter": "B"}
    else:
        case["candidate_specs"][0]["candidate_id"] = "different"
    result = predict_question(case, kb(tmp_path, [(32,16),(16,8)]))
    assert result["status"] == "invalid"
    assert result["answer_id"] is None and result["edges"] == []


def test_dense_twenty_candidate_graph_keeps_one_bounded_witness_per_target(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    case = public_case(raw_case(widths=tuple(range(20,0,-1)), losses=tuple(range(20))))
    snapshot = RuleArtifactStore(tmp_path).import_rules({"rules": [rule_entry()]}, source_ref={"id":"fixture"})
    result = predict_question(case, snapshot)
    assert result["status"] == "answered"
    assert len(result["edges"]) == 190
    assert len(result["paths"]) == 19
    assert all(len(path) == 2 for path in result["paths"].values())


def test_batch_preserves_order_and_is_pure(tmp_path, monkeypatch):
    from architecture_iq.studio.rule_refinement.prediction import predict_batch
    from architecture_iq.studio.catalog import Catalog
    from architecture_iq.studio import execution
    def forbidden(*args, **kwargs):
        pytest.fail("Prediction must not read GT or construct a model client")
    monkeypatch.setattr(Catalog, "get_question", forbidden)
    monkeypatch.setattr(execution, "create_client", forbidden)
    cases = [public_case(raw_case("second")), public_case(raw_case("first"))]
    before = deepcopy(cases)
    result = predict_batch(cases, kb(tmp_path, [(32,16),(16,8)]))
    assert [r["question_ref"]["key"] for r in result] == ["second", "first"]
    assert cases == before
