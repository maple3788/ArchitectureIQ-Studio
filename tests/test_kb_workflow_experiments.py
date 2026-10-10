"""Canonical adapter tests; synthesis is real, training itself is instrumented."""
import json
from pathlib import Path

import pytest


def request(**updates):
    return {"family": "xor_classification", "factor": "layernorm", "seed_start": 910000,
            "count": 1, "phase": "exploration", "profile": "v1.5", "claim_id": "ln", "revision": 1,
            "n_seeds": 2, "planning_limit": 3,
            "rule": {"same": ["width", "depth", "opt_key", "budget"], "differ": ["ln_all"],
                     "predict": {"better": ["ln_all", "eq", True], "worse": ["ln_any", "eq", False]}},
            **updates}


@pytest.fixture
def canonical_fixture(monkeypatch):
    from architecture_iq.kb import experiments
    from architecture_iq.ground_truth import runner
    monkeypatch.setattr(experiments, "_require_execution_host", lambda: None)
    calls = []

    def instrumented_seed(candidate_path, spec, train_x, train_y, test_x, test_y, seed, fail_threshold, **kwargs):
        calls.append((str(candidate_path), seed))
        assert train_x.shape[0] > 0 and test_x.shape[0] > 0
        metric = kwargs["selection_metric"]
        value = .1 if all(spec["model"]["layer_norm"]) else 1.0
        return {"seed": seed, "failed": False, f"final_{metric}": value,
                "step_metrics": [value], "eval_samples": [spec["budget"]["total_samples_seen"]]}

    monkeypatch.setattr(runner, "run_single_seed", instrumented_seed)
    return experiments, calls


def test_planning_freezes_public_pair_without_gt_and_is_immutable(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    plan = experiments.plan_experiment(request(), tmp_path)
    assert plan["complete"] and plan["planned_count"] == 1
    assert plan["required_candidate_seed_runs"] == 4
    assert calls == []
    pair = plan["pairs"][0]
    assert len(pair["candidate_ids"]) == 2
    assert pair["predicted_winner"] in pair["candidate_ids"]
    assert not list(tmp_path.rglob("summary.json"))
    assert experiments.plan_experiment(request(), tmp_path) == plan
    with pytest.raises(ValueError, match="request|immutable"):
        experiments.plan_experiment(request(seed_start=920000), tmp_path)


def test_unmatched_scope_has_bounded_planning_and_no_gt_resampling(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    value = request(planning_limit=2)
    value["rule"]["scope"] = ["family", "eq", "univariate_regression"]
    plan = experiments.plan_experiment(value, tmp_path)
    assert not plan["complete"]
    assert plan["planning_attempts"] == 2
    assert plan["pairs"] == []
    assert experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=0) == []
    assert calls == []


def test_budget_rejected_before_any_canonical_training(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    experiments.plan_experiment(request(), tmp_path)
    with pytest.raises(ValueError, match="budget"):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=3)
    assert calls == []
    assert not list(tmp_path.rglob("summary.json"))


@pytest.mark.parametrize("artifact", ["train.py", "candidate_spec.json"])
def test_changed_frozen_artifact_is_rejected_before_training(tmp_path, canonical_fixture, artifact):
    experiments, calls = canonical_fixture
    plan = experiments.plan_experiment(request(), tmp_path)
    path = Path(plan["pairs"][0]["candidate_paths"][0]) / artifact
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="hash|changed|frozen"):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    assert calls == []


def test_actual_canonical_runner_produces_source_bound_evidence_and_resume_uses_receipts(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    experiments.plan_experiment(request(), tmp_path)
    result = experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    assert len(calls) == 4
    assert len(result) == 1 and result[0]["outcome"] == "support"
    evidence = result[0]
    assert evidence["provenance"] == "canonical_gt"
    assert evidence["seed_ids"] == [0, 1]
    assert evidence["claim_id"] == "ln" and evidence["revision"] == 1
    assert str(tmp_path / "plan.json") in evidence["source_hashes"]
    for summary_path in evidence["summary_paths"]:
        summary = json.loads(Path(summary_path).read_text())
        assert summary["execution"] == "candidate_py_files"
        assert summary["candidate_id"] in evidence["candidate_ids"]
        assert summary_path in evidence["source_hashes"]
    assert experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4) == result
    assert len(calls) == 4
    summary_path = Path(evidence["summary_paths"][0])
    summary_path.write_text(summary_path.read_text() + "\n")
    with pytest.raises(ValueError, match="hash|changed|receipt"):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    assert len(calls) == 4


def test_interrupted_training_leaves_reservation_and_cannot_retry(tmp_path, canonical_fixture, monkeypatch):
    experiments, calls = canonical_fixture
    from architecture_iq.ground_truth import runner
    experiments.plan_experiment(request(), tmp_path)

    def interrupted(*args, **kwargs):
        calls.append("interrupted")
        raise RuntimeError("transport lost")

    monkeypatch.setattr(runner, "run_single_seed", interrupted)
    with pytest.raises(RuntimeError, match="transport lost"):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    with pytest.raises(RuntimeError, match="pending|uncertain|interrupted"):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    assert calls == ["interrupted"]


def test_unreceipted_gt_is_never_adopted(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    plan = experiments.plan_experiment(request(), tmp_path)
    results = Path(plan["pairs"][0]["candidate_paths"][0]) / "results"
    results.mkdir()
    (results / "summary.json").write_text('{"execution":"candidate_py_files"}')
    with pytest.raises(ValueError, match="receipt|untracked|unreceipted"):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    assert calls == []


def test_request_rejects_hidden_result_selection_and_invalid_limits(tmp_path):
    from architecture_iq.kb.experiments import plan_experiment
    for patch in ({"count": 0}, {"planning_limit": 0}, {"n_seeds": 0}, {"max_loss": 1},
                  {"phase": "final"}, {"factor": "custom"}, {"seed_start": True}):
        with pytest.raises(ValueError):
            plan_experiment(request(**patch), tmp_path)


def test_machine_evidence_passes_independent_source_verifier(tmp_path, canonical_fixture):
    from architecture_iq.kb.evidence import verify_evidence_sources
    experiments, _ = canonical_fixture
    experiments.plan_experiment(request(), tmp_path)
    records = experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4)
    claim = {"id": "ln", "revision": 1, "rule": request()["rule"]}
    assert verify_evidence_sources(records[0], claim=claim)["complete"] is True


def test_failed_training_is_logged_without_scientific_evidence_or_retry(tmp_path, canonical_fixture, monkeypatch):
    from architecture_iq.ground_truth import runner
    experiments, calls = canonical_fixture
    original = runner.run_single_seed

    def failed(*args, **kwargs):
        result = original(*args, **kwargs)
        return {**result, "failed": True, f"final_{kwargs['selection_metric']}": float("inf")}

    monkeypatch.setattr(runner, "run_single_seed", failed)
    experiments.plan_experiment(request(), tmp_path)
    assert experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4) == []
    assert len(json.loads((tmp_path / "execution_failures.json").read_text())) == 1
    assert len(calls) == 4
    assert experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4) == []
    assert len(calls) == 4


@pytest.mark.parametrize("exclusion_key", ["excluded_dataset_ids", "excluded_lineage_ids"])
def test_confirmation_excludes_prior_content_identity_across_output_aliases(tmp_path, canonical_fixture, exclusion_key):
    experiments, calls = canonical_fixture
    prior = experiments.plan_experiment(request(), tmp_path / "discovery_alias")
    pair = prior["pairs"][0]
    identity = pair["dataset_id"] if exclusion_key == "excluded_dataset_ids" else pair["lineage_id"]
    confirmation = experiments.plan_experiment(
        request(phase="confirmation", claim_id="different_claim_alias", planning_limit=1,
                **{exclusion_key: [identity]}), tmp_path / "confirmation_alias")
    assert not confirmation["complete"]
    assert confirmation["planning_attempts"] == 1
    assert confirmation["required_candidate_seed_runs"] == 0
    assert confirmation["pairs"] == []
    assert not list((tmp_path / "confirmation_alias").rglob("candidate_spec.json"))
    assert calls == []


def test_exclusions_consume_planning_attempts_then_allow_a_fresh_dataset(tmp_path, canonical_fixture):
    experiments, _ = canonical_fixture
    prior = experiments.plan_experiment(request(), tmp_path / "old")
    excluded = prior["pairs"][0]["dataset_id"]
    plan = experiments.plan_experiment(request(excluded_dataset_ids=[excluded], planning_limit=2), tmp_path / "fresh")
    assert plan["complete"] and plan["planning_attempts"] == 2
    assert plan["pairs"][0]["dataset_id"] != excluded
    assert plan["request"]["excluded_dataset_ids"] == [excluded]


def test_exclusion_sets_are_canonical_and_immutable_on_resume(tmp_path, canonical_fixture):
    experiments, _ = canonical_fixture
    first = experiments.plan_experiment(request(excluded_dataset_ids=["z", "a", "z"]), tmp_path)
    assert first["request"]["excluded_dataset_ids"] == ["a", "z"]
    assert experiments.plan_experiment(request(excluded_dataset_ids=["a", "z"]), tmp_path) == first
    with pytest.raises(ValueError, match="immutable|Immutable|request"):
        experiments.plan_experiment(request(excluded_dataset_ids=["a"]), tmp_path)


@pytest.mark.parametrize("values", [None, "id", [1], [""], ["x" * 257], ["id"] * 10001])
def test_exclusion_inventory_is_bounded_typed_input(tmp_path, values):
    from architecture_iq.kb.experiments import plan_experiment
    with pytest.raises(ValueError):
        plan_experiment(request(excluded_dataset_ids=values), tmp_path)


def test_execution_rejects_a_pair_excluded_by_frozen_request_before_gt(tmp_path, canonical_fixture):
    import hashlib
    from architecture_iq.kb.store import write_json_atomic
    experiments, calls = canonical_fixture
    plan = experiments.plan_experiment(request(), tmp_path)
    plan["request"]["excluded_dataset_ids"] = [plan["pairs"][0]["dataset_id"]]
    path = tmp_path / "plan.json"
    write_json_atomic(path, plan)
    path.with_suffix(".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
    with pytest.raises(ValueError, match="excluded|exclusion"):
        experiments.execute_experiment(path, max_candidate_seed_runs=4)
    assert calls == []


def test_pair_envelope_binds_only_the_generated_family_model_and_profile_distribution(tmp_path, canonical_fixture):
    experiments, _ = canonical_fixture
    plan = experiments.plan_experiment(request(), tmp_path)
    envelope = plan["pairs"][0]["sampling_envelope"]
    assert envelope == plan["sampling_envelope"]
    assert envelope["family"] == "xor_classification"
    assert envelope["model_type"] == "mlp"
    assert envelope["profile_hash"] == plan["profile_hash"]
    assert envelope["budget_values"] == [4096, 8192, 16384, 32768]
    assert envelope["optimizer_types"] == ["Adagrad", "Adam", "AdamW", "RMSprop", "SGD"]
    assert envelope["loss_types"] == ["cross_entropy"]
    assert envelope["intervention"] == "layernorm"


def test_envelope_preserves_family_overrides_and_all_equal_controls(tmp_path, canonical_fixture):
    experiments, _ = canonical_fixture
    plan = experiments.plan_experiment(request(family_options={"input_dim": 4}), tmp_path)
    envelope = plan["sampling_envelope"]
    assert envelope["family_options"] == {"input_dim": 4}
    assert envelope["controls"] == {"equal": ["opt_key", "loss_key", "budget", "batch_size"],
                                    "architecture_intervention": "layernorm"}


def test_execution_rejects_overstated_sampling_envelope_before_gt(tmp_path, canonical_fixture):
    import hashlib
    from architecture_iq.kb.store import write_json_atomic
    experiments, calls = canonical_fixture
    plan = experiments.plan_experiment(request(), tmp_path)
    plan["sampling_envelope"]["family"] = "univariate_regression"
    path = tmp_path / "plan.json"
    write_json_atomic(path, plan)
    path.with_suffix(".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
    with pytest.raises(ValueError, match="envelope"):
        experiments.execute_experiment(path, max_candidate_seed_runs=4)
    assert calls == []


@pytest.mark.parametrize("factor", ["depth", "width"])
def test_preregistered_pair_sampling_reaches_nonfirst_pairs_without_gt(tmp_path, canonical_fixture, factor):
    experiments, calls = canonical_fixture
    value = request(factor=factor, count=32, planning_limit=32,
                    rule={"predict": {"higher_better": factor}})
    plan = experiments.plan_experiment(value, tmp_path)
    selected = [tuple(json.loads((Path(directory) / "candidate_spec.json").read_text())["model"][factor]
                      for directory in pair["candidate_paths"]) for pair in plan["pairs"]]
    assert plan["complete"]
    assert len(set(selected)) > 3
    if factor == "depth":
        assert any(5 in pair for pair in selected)
        assert any(pair[0] >= 3 for pair in selected)
    else:
        assert any(256 in pair for pair in selected)
    assert calls == []
    assert not list(tmp_path.rglob("summary.json"))
    assert plan["sampling_envelope"]["pair_sampling"] == "uniform_applicable_pairs_from_factor_variants"
    for pair, selected_values in zip(plan["pairs"], selected):
        assert pair["eligible_pair_count"] == (10 if factor == "depth" else 3)
        a_index, b_index = pair["chosen_variant_indexes"]
        assert 0 <= a_index < b_index < (5 if factor == "depth" else 3)
        if factor == "depth":
            assert selected_values == (a_index + 1, b_index + 1)


def test_public_pair_sampling_is_reproducible_across_output_aliases(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    value = request(factor="depth", count=8, planning_limit=8,
                    rule={"predict": {"higher_better": "depth"}})
    a = experiments.plan_experiment(value, tmp_path / "first")
    b = experiments.plan_experiment(value, tmp_path / "second")
    assert [pair["candidate_ids"] for pair in a["pairs"]] == [pair["candidate_ids"] for pair in b["pairs"]]
    assert [pair["predicted_winner"] for pair in a["pairs"]] == [pair["predicted_winner"] for pair in b["pairs"]]
    assert calls == []


def test_pair_audit_records_the_only_eligible_layernorm_pair(tmp_path, canonical_fixture):
    experiments, _ = canonical_fixture
    pair = experiments.plan_experiment(request(), tmp_path)["pairs"][0]
    assert pair["eligible_pair_count"] == 1
    assert pair["chosen_variant_indexes"] == [0, 1]


def test_candidate_safe_boundary_is_after_durable_completion_and_resume_never_retrains(tmp_path, canonical_fixture):
    experiments, calls = canonical_fixture
    experiments.plan_experiment(request(), tmp_path)
    events = []
    class Pause(Exception):
        pass
    def pause_after_completed_candidate(event):
        events.append(event)
        if event["state"] == "complete":
            assert event["safe_boundary"] is True
            receipt = json.loads(Path(event["receipt_path"]).read_text())
            assert receipt["state"] == "complete"
            assert len(calls) == 2
            raise Pause()
    with pytest.raises(Pause):
        experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4,
                                       safe_boundary=pause_after_completed_candidate)
    assert events[-1]["node_id"] == "experiment"
    result = experiments.execute_experiment(tmp_path / "plan.json", max_candidate_seed_runs=4,
                                            safe_boundary=events.append)
    assert len(calls) == 4 and result[0]["provenance"] == "canonical_gt"
    assert len([e for e in events if e["state"] == "complete"]) == 2
