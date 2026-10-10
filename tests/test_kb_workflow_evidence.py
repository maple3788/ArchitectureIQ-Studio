"""Scientific gates count independent facts, never role assertions."""
from copy import deepcopy
import math

import pytest

from architecture_iq.kb.evidence import evidence_id, summarize_confirmation


def record(index=0, **overrides):
    result = {
        "claim_id": "claim", "revision": 1, "phase": "confirmation",
        "lineage_id": f"lineage-{index}", "dataset_id": f"dataset-{index}",
        "candidate_ids": [f"a-{index}", f"b-{index}"],
        "seed_ids": list(range(10)), "outcome": "support",
        "source_hashes": {f"/artifact-{index}": f"{index:064x}"},
    }
    result.update(overrides)
    result["id"] = evidence_id(result)
    return result


def test_identity_ignores_attribution_outcome_and_aliases():
    a = record()
    b = deepcopy(a)
    b.update(claim_id="other", revision=9, phase="exploration", outcome="refute")
    b["candidate_ids"] = ["renamed-b", "renamed-a"]
    assert evidence_id(a) == evidence_id(b)


def test_all_success_has_finite_conservative_bound():
    summary = summarize_confirmation([record(i) for i in range(48)])
    assert summary["complete"] and summary["passed"]
    assert summary["n"] == summary["support"] == 48
    assert summary["rate"] == 1
    assert summary["lower"] == pytest.approx(0.793482859612)


def test_uncertain_trials_stay_in_denominator():
    records = [record(i, outcome="support" if i < 35 else "inconclusive") for i in range(48)]
    summary = summarize_confirmation(records)
    assert summary["n"] == 48 and summary["inconclusive"] == 13
    assert summary["rate"] == 35 / 48
    assert not summary["passed"]


def test_incomplete_or_exploratory_batches_never_confirm():
    assert not summarize_confirmation([record(i) for i in range(47)])["complete"]
    assert not summarize_confirmation([record(i, phase="exploration") for i in range(48)])["passed"]
    assert not summarize_confirmation([record(i) for i in range(6)], expected_count=6)["passed"]


def test_duplicate_sources_and_lineages_cannot_inflate_n():
    records = [record(i) for i in range(48)]
    with pytest.raises(ValueError, match="duplicate"):
        summarize_confirmation(records + [deepcopy(records[0])])
    records[-1]["lineage_id"] = records[0]["lineage_id"]
    records[-1]["id"] = evidence_id(records[-1])
    with pytest.raises(ValueError, match="lineage"):
        summarize_confirmation(records)


@pytest.mark.parametrize("change", [
    {"outcome": "passed"}, {"revision": True}, {"seed_ids": [1, 1]},
    {"candidate_ids": ["a"]}, {"source_hashes": {}}, {"lineage_id": ""},
])
def test_malformed_evidence_rejected(change):
    candidate = record()
    candidate.update(change)
    with pytest.raises(ValueError):
        summarize_confirmation([candidate])


def test_mixed_revisions_or_attempts_cannot_be_pooled():
    records = [record(i, plan_hash=f"{i // 24:064x}") for i in range(48)]
    with pytest.raises(ValueError, match="batch"):
        summarize_confirmation(records)
    records = [record(i, revision=1 if i < 24 else 2) for i in range(48)]
    with pytest.raises(ValueError, match="revision"):
        summarize_confirmation(records)


def test_invalid_statistical_parameters_rejected():
    for options in ({"max_attempts": 4}, {"alpha": math.nan}, {"expected_count": 0}):
        with pytest.raises(ValueError):
            summarize_confirmation([], **options)


def artifacts(tmp_path):
    """Handwritten disk fixture, solely for testing provenance verification."""
    import hashlib
    import json
    from architecture_iq.kb.evidence import evidence_id
    root = tmp_path.resolve()
    data = root / "dataset"
    data.mkdir(parents=True)
    paths = []
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, dict) else value)
        paths.append(path)
    write(data / "dataset_spec.json", {"dataset_id": "data", "family": "univariate_regression",
                                      "selection_metric": "test_mse", "params": {"input_dim": 2, "train_size": 64},
                                      "files": {"synthesize": "synthesize.py", "train": "train.pt", "test": "test.pt"}})
    for name in ("synthesize.py", "train.pt", "test.pt"):
        write(data / name, name)
    dirs = [root / "a", root / "b"]
    summaries = []
    for index, directory in enumerate(dirs):
        write(directory / "candidate_spec.json", {"candidate_id": directory.name, "dataset_id": "data",
              "model": {"type": "mlp", "hidden_sizes": [32, 32], "layer_norm": [bool(index), bool(index)]},
              "budget": {"total_samples_seen": 100, "training_steps": 10, "batch_size": 10},
              "optimizer": {"type": "adam", "lr": .001}, "loss": {"loss_id": "mse"}})
        for name in ("model.py", "loss.py", "optimizer.py", "train.py"):
            write(directory / name, directory.name + name)
        rows = [{"seed": seed, "failed": False, "final_test_mse": float(index + 1)} for seed in range(10)]
        summary = directory / "results" / "summary.json"
        write(summary, {"candidate_id": directory.name, "selection_metric": "test_mse", "execution": "candidate_py_files",
                        "n_seeds": 10, "failed_seeds": 0, "excluded": False, "seed_results": rows,
                        "mean_test_mse": float(index + 1)})
        write(directory / "results" / "curves.npz", "curves")
        summaries.append(str(summary))
    source = root / "runner.py"
    write(source, "canonical source fixture")
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    pair_sources = {str(path): digest(path) for path in paths if path != source and "results" not in path.parts}
    pair = {"dataset_id": "data", "lineage_id": "lineage", "dataset_path": str(data), "candidate_ids": ["a", "b"],
            "candidate_paths": list(map(str, dirs)), "metric": "test_mse", "higher_is_better": False,
            "predicted_winner": "a", "source_hashes": pair_sources,
            "eligible_pair_count": 1, "chosen_variant_indexes": [0, 1]}
    plan = {"request": {"claim_id": "claim", "revision": 1, "phase": "exploration", "count": 1, "factor": "layernorm",
                        "rule": {"predict": {"lower_better": "width"}}},
            "pairs": [pair], "complete": True, "planned_count": 1, "n_seeds": 10, "seed_ids": list(range(10)),
            "source_hashes": {str(source): digest(source)}}
    plan_path = root / "plan.json"
    write(plan_path, plan)
    plan_path.with_suffix(".sha256").write_text(digest(plan_path))
    result = {"claim_id": "claim", "revision": 1, "phase": "exploration", "dataset_id": "data", "lineage_id": "lineage",
              "candidate_ids": ["a", "b"], "seed_ids": list(range(10)), "outcome": "support", "provenance": "canonical_gt",
              "plan_path": str(plan_path), "plan_hash": digest(plan_path), "pair_index": 0,
              "metric": "test_mse", "predicted_winner": "a", "summary_paths": summaries,
              "source_hashes": {str(path): digest(path) for path in paths}}
    result["id"] = evidence_id(result)
    return result


def test_provenance_checks_actual_files_and_recomputes_seed_outcome(tmp_path):
    from pathlib import Path
    from architecture_iq.kb.evidence import verify_evidence_sources
    item = artifacts(tmp_path)
    assert verify_evidence_sources(item)["planned_count"] == 1
    item["outcome"] = "refute"
    with pytest.raises(ValueError, match="outcome"):
        verify_evidence_sources(item)
    item["outcome"] = "support"
    Path(item["summary_paths"][0]).write_text("changed GT")
    with pytest.raises(ValueError, match="hash"):
        verify_evidence_sources(item)


def test_dataset_materializations_cannot_be_dropped_from_source_bindings(tmp_path):
    from pathlib import Path
    from architecture_iq.kb.evidence import verify_evidence_sources
    import hashlib
    import json
    item = artifacts(tmp_path)
    path = str(tmp_path / "dataset" / "train.pt")
    del item["source_hashes"][path]
    plan_path = Path(item["plan_path"])
    plan = json.loads(plan_path.read_text())
    del plan["pairs"][0]["source_hashes"][path]
    plan_path.write_text(json.dumps(plan))
    item["plan_hash"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    item["source_hashes"][str(plan_path)] = item["plan_hash"]
    plan_path.with_suffix(".sha256").write_text(item["plan_hash"])
    item["id"] = evidence_id(item)
    with pytest.raises(ValueError, match="materialized|dataset"):
        verify_evidence_sources(item)


def test_candidate_cannot_use_a_different_dataset_than_frozen_pair(tmp_path):
    from pathlib import Path
    from architecture_iq.kb.evidence import verify_evidence_sources
    import hashlib
    import json
    item = artifacts(tmp_path)
    path = tmp_path / "a" / "candidate_spec.json"
    path.write_text(json.dumps({"candidate_id": "a", "dataset_id": "different-data"}))
    item["source_hashes"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    plan_path = Path(item["plan_path"])
    plan = json.loads(plan_path.read_text())
    plan["pairs"][0]["source_hashes"][str(path)] = item["source_hashes"][str(path)]
    plan_path.write_text(json.dumps(plan))
    item["plan_hash"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    item["source_hashes"][str(plan_path)] = item["plan_hash"]
    plan_path.with_suffix(".sha256").write_text(item["plan_hash"])
    item["id"] = evidence_id(item)
    with pytest.raises(ValueError, match="dataset"):
        verify_evidence_sources(item)


def test_synthetic_and_incomplete_records_cannot_confirm(tmp_path):
    from architecture_iq.kb.evidence import verify_evidence_sources
    item = artifacts(tmp_path)
    item["synthetic"] = True
    with pytest.raises(ValueError, match="provenance"):
        verify_evidence_sources(item)
    del item["synthetic"]
    item["phase"] = "confirmation"
    with pytest.raises(ValueError, match="frozen request|confirmation"):
        verify_evidence_sources(item)


@pytest.mark.parametrize("field,value", [("phase", []), ("outcome", {}), ("revision", []), ("source_hashes", []), ("seed_ids", "0")])
def test_bad_json_field_types_raise_validation_errors(field, value):
    item = record()
    item[field] = value
    with pytest.raises(ValueError):
        summarize_confirmation([item])


def test_oversized_statistical_parameter_is_a_validation_error():
    with pytest.raises(ValueError):
        summarize_confirmation([], alpha=10 ** 10000)


def test_missing_plan_seal_is_not_executed_provenance(tmp_path):
    from pathlib import Path
    from architecture_iq.kb.evidence import verify_evidence_sources
    item = artifacts(tmp_path)
    seal = Path(item["plan_path"]).with_suffix(".sha256")
    seal.unlink(missing_ok=True)
    with pytest.raises(ValueError, match="seal|plan"):
        verify_evidence_sources(item)


def rewrite_plan_record(item, update):
    """Update a signed disk fixture to exercise checks beyond file-integrity."""
    import hashlib
    import json
    from pathlib import Path
    path = Path(item["plan_path"])
    value = json.loads(path.read_text())
    update(value)
    path.write_text(json.dumps(value))
    item["plan_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
    item["source_hashes"][str(path)] = item["plan_hash"]
    path.with_suffix(".sha256").write_text(item["plan_hash"])
    item["id"] = evidence_id(item)


def test_evidence_cannot_come_from_excluded_frozen_dataset(tmp_path):
    from architecture_iq.kb.evidence import verify_evidence_sources
    item = artifacts(tmp_path)
    rewrite_plan_record(item, lambda plan: plan["request"].update(excluded_dataset_ids=["data"]))
    with pytest.raises(ValueError, match="excluded"):
        verify_evidence_sources(item)


def test_evidence_sampling_envelope_cannot_assert_other_family(tmp_path):
    from architecture_iq.kb.evidence import verify_evidence_sources
    item = artifacts(tmp_path)
    envelope = {"family": "xor_classification", "model_type": "mlp", "profile_hash": "frozen-profile",
                "budget_values": [1024], "optimizer_types": ["adam"], "loss_types": ["mse"],
                "intervention": "width", "family_options": {},
                "pair_sampling": "uniform_applicable_pairs_from_factor_variants",
                "controls": {"equal": ["opt_key", "loss_key", "budget", "batch_size"], "architecture_intervention": "width"}}
    def mutate(plan):
        plan["request"].update(family="univariate_regression", factor="width", family_options={})
        plan["sampling_envelope"] = envelope
        plan["pairs"][0]["sampling_envelope"] = envelope
    rewrite_plan_record(item, mutate)
    with pytest.raises(ValueError, match="envelope"):
        verify_evidence_sources(item)


@pytest.mark.parametrize("metadata", [
    {"eligible_pair_count": 0, "chosen_variant_indexes": [0, 1]},
    {"eligible_pair_count": True, "chosen_variant_indexes": [0, 1]},
    {"eligible_pair_count": 1, "chosen_variant_indexes": [0, 0]},
    {"eligible_pair_count": 1, "chosen_variant_indexes": [-1, 1]},
    {"eligible_pair_count": 1, "chosen_variant_indexes": [True, 1]},
    {"eligible_pair_count": 1, "chosen_variant_indexes": [0]},
])
def test_evidence_requires_valid_preregistered_pair_selection_metadata(tmp_path, metadata):
    from architecture_iq.kb.evidence import verify_evidence_sources
    item = artifacts(tmp_path)
    rewrite_plan_record(item, lambda plan: plan["pairs"][0].update(metadata))
    with pytest.raises(ValueError, match="pair.*selection|variant|eligible"):
        verify_evidence_sources(item)


@pytest.mark.parametrize("strategy", [None, "first_applicable_pair", "uniform_applicable_pairs"])
def test_confirmation_rejects_missing_or_obsolete_pair_sampling_strategy(strategy):
    from test_kb_workflow_store import confirmed_envelope
    from architecture_iq.kb.evidence import validate_sampling_envelope
    envelope = confirmed_envelope()
    if strategy is None:
        envelope.pop("pair_sampling", None)
    else:
        envelope["pair_sampling"] = strategy
    with pytest.raises(ValueError, match="envelope|sampling"):
        validate_sampling_envelope(envelope)



def test_evidence_description_reports_actual_controls_and_seed_statistics(tmp_path):
    from architecture_iq.kb.evidence import describe_evidence
    item = artifacts(tmp_path)
    item["competing_explanation"] = "depth and width were confounded"
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    facts = describe_evidence(item)
    assert facts["id"] == item["id"] and facts["phase"] == "exploration"
    assert facts["dataset_id"] == "data" and facts["outcome"] == "support"
    assert facts["controlled_factor"] == "layernorm"
    assert facts["training_seed_ids"] == list(range(10))
    assert facts["n_seeds_per_candidate"] == 10
    assert facts["metric"] == "test_mse" and facts["higher_is_better"] is False
    assert facts["candidate_model_differences"] == {"layer_norm": {"a": [False, False], "b": [True, True]}}
    assert facts["fixed_sections"] == {"optimizer": True, "loss": True, "budget": True}
    assert facts["dataset_params"] == {"input_dim": 2, "train_size": 64}
    assert [(candidate["id"], candidate["mean"], candidate["seed_min"], candidate["seed_max"])
            for candidate in facts["candidates"]] == [("a", 1., 1., 1.), ("b", 2., 2., 2.)]
    assert facts["candidates"][0]["model"]["hidden_sizes"] == [32, 32]
    assert facts["candidates"][0]["optimizer"] == {"type": "adam", "lr": .001}
    assert "competing_explanation" not in facts
    assert {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_evidence_description_rejects_tampered_sources_before_describing(tmp_path):
    from pathlib import Path
    from architecture_iq.kb.evidence import describe_evidence
    item = artifacts(tmp_path)
    Path(item["summary_paths"][0]).write_text("forged source")
    with pytest.raises(ValueError, match="hash"):
        describe_evidence(item)


def test_evidence_description_compares_actual_dicts_and_preserves_missing_fields(tmp_path):
    import hashlib
    import json
    from architecture_iq.kb.evidence import describe_evidence
    item = artifacts(tmp_path)
    candidate_path = tmp_path / "b" / "candidate_spec.json"
    candidate = json.loads(candidate_path.read_text())
    candidate["model"]["residual"] = None
    candidate["optimizer"]["lr"] = .002
    candidate["budget"]["batch_size"] = 20
    candidate["budget"]["training_steps"] = 5
    candidate_path.write_text(json.dumps(candidate))
    digest = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    item["source_hashes"][str(candidate_path)] = digest
    rewrite_plan_record(item, lambda plan: plan["pairs"][0]["source_hashes"].update({str(candidate_path): digest}))
    facts = describe_evidence(item)
    assert facts["candidate_model_differences"]["residual"] == {"b": None}
    assert facts["fixed_sections"] == {"optimizer": False, "loss": True, "budget": False}


def test_evidence_description_uses_stored_mean_and_actual_seed_extrema(tmp_path):
    import hashlib
    import json
    from pathlib import Path
    from architecture_iq.kb.evidence import describe_evidence
    item = artifacts(tmp_path)
    summary_path = Path(item["summary_paths"][0])
    summary = json.loads(summary_path.read_text())
    for row, value in zip(summary["seed_results"], [.1, .2, .3, .4, .5, .6, .7, .8, .9, 1.]):
        row["final_test_mse"] = value
    summary["mean_test_mse"] = .55
    summary_path.write_text(json.dumps(summary))
    item["source_hashes"][str(summary_path)] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    item["id"] = evidence_id(item)
    facts = describe_evidence(item)
    assert facts["candidates"][0]["mean"] == .55
    assert facts["candidates"][0]["seed_min"] == .1
    assert facts["candidates"][0]["seed_max"] == 1.
