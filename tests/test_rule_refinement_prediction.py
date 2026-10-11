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


def reported_snapshot(tmp_path, *, metadata=None, rule=None):
    """Import synthetic native claims through the same path as v9/v10."""
    metadata = dict(metadata or {})
    modified = metadata.pop("validation_origin", None) == "modified_in_studio"
    claim = {"id": metadata.pop("claim_id", "R2"), "text": "Prefer wider models",
             "rules": [rule or rule_entry()["rule"]], "validity_status": "replicated_in_scope",
             **metadata}
    store = RuleArtifactStore(tmp_path)
    snapshot = store.import_rules({"schema_version": "kb_claim_rules_v1", "claims": [claim]},
                                 source_ref={"id": "fixture"})
    if modified:
        entry = snapshot["rules"][0]
        snapshot = store.apply_patch(snapshot["version"], {
            "base_version": snapshot["version"], "rationale": "Research revision", "case_refs": [],
            "operations": [{"op": "edit", "rule_id": entry["rule_id"], "revision": entry["revision"],
                            "entry": {"text": "Revised hypothesis", "rule": entry["rule"]}}]})
    return snapshot


def test_question_context_match_returns_pair_evidence_without_answer_or_side_effects(tmp_path, monkeypatch):
    from architecture_iq.studio.rule_refinement.prediction import match_question_for_injection
    from architecture_iq.studio.catalog import Catalog
    from architecture_iq.studio import execution
    def forbidden(*args, **kwargs):
        pytest.fail("Context matching must not fetch hidden GT or create a model client")
    monkeypatch.setattr(Catalog, "get_question", forbidden)
    monkeypatch.setattr(execution, "create_client", forbidden)
    case = public_case()
    snapshot = reported_snapshot(tmp_path)
    before = deepcopy((case, snapshot))
    result = match_question_for_injection(case, snapshot)
    assert result["status"] == "matched"
    assert result["claim_ids"] == ["R2"]
    assert result["rule_ids"] == [snapshot["rules"][0]["rule_id"]]
    assert [(match["winner"], match["loser"]) for match in result["matches"]] == [
        ("c_A", "c_B"), ("c_A", "c_C"), ("c_B", "c_C")]
    assert all(match["clause_index"] == 1 and match["claim_id"] == "R2" for match in result["matches"])
    assert "answer_id" not in result
    assert (case, snapshot) == before


@pytest.mark.parametrize("metadata", [{"inject": False}, {"validity_status": "proposed"},
                                      {"validation_origin": "modified_in_studio"}])
def test_strict_predictions_remain_executable_while_context_is_withheld(tmp_path, metadata):
    from architecture_iq.studio.rule_refinement.prediction import match_question_for_injection, predict_question
    snapshot = reported_snapshot(tmp_path, metadata=metadata)
    case = public_case()
    assert predict_question(case, snapshot)["answer_id"] == "c_A"
    result = match_question_for_injection(case, snapshot)
    assert result["status"] == "unmatched"
    assert result["matches"] == [] and result["claim_ids"] == [] and result["rule_ids"] == []


def test_context_pair_evidence_never_resolves_opposing_claims_into_an_answer(tmp_path):
    from architecture_iq.kb.store import canonical_hash
    from architecture_iq.studio.rule_refinement.artifacts import executable_hash
    from architecture_iq.studio.rule_refinement.prediction import match_question_for_injection
    snapshot = reported_snapshot(tmp_path / "first")
    second = reported_snapshot(tmp_path / "second", metadata={"claim_id": "R3"},
                               rule={"predict": {"lower_better": "width"}})
    snapshot["rules"].extend(second["rules"])
    snapshot["executable_hash"] = executable_hash(snapshot["rules"])
    snapshot["version"] = canonical_hash({k: v for k, v in snapshot.items() if k != "version"})
    result = match_question_for_injection(public_case(), snapshot)
    assert result["status"] == "matched"
    assert result["claim_ids"] == ["R2", "R3"]
    assert len(result["matches"]) == 6
    assert "answer_id" not in result


def test_context_matching_rejects_hidden_feedback_and_tampered_rule_metadata(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import match_question_for_injection
    snapshot = reported_snapshot(tmp_path)
    case = public_case()
    case["feedback"] = {"correct_letter": "A"}
    result = match_question_for_injection(case, snapshot)
    assert result["status"] == "invalid" and result["matches"] == []
    snapshot["rules"][0]["metadata"]["inject"] = False
    result = match_question_for_injection(public_case(), snapshot)
    assert result["status"] == "invalid" and result["matches"] == []


def test_parameter_ratio_uses_only_published_candidate_counts_not_result_artifacts(tmp_path):
    from architecture_iq.studio.rule_refinement.prediction import predict_question
    case = public_case(raw_case(widths=(32, 16), losses=(1, 2)))
    for spec, count in zip(case["candidate_specs"], (200, 100)):
        spec["trainable_parameter_count"] = count
    snapshot = reported_snapshot(tmp_path, rule={"max_param_ratio": 2,
                                                  "predict": {"higher_better": "width"}})
    assert predict_question(case, snapshot)["answer_id"] == "c_A"
    case["candidate_specs"][0]["trainable_parameter_count"] = 201
    case["candidate_specs"][0]["results"] = {"trainable_parameter_count": 100, "mean_test_mse": .001}
    assert predict_question(case, snapshot)["status"] == "uncovered"
    case["candidate_specs"][0].pop("trainable_parameter_count")
    assert predict_question(case, snapshot)["status"] == "uncovered"
