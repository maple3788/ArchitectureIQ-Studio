"""Controlled pair generation; GT is mocked, never a replacement training loop."""
from copy import deepcopy
import json

import pytest


def request(**overrides):
    return {"profile": "v1.4", "family": "univariate_regression", "seed": 7,
            "candidate_count": 3, "vary": ["model"], "budget": 4096,
            "n_seeds": 1, "num_questions": 1, "num_choices": 3,
            "mode": "paired", "split": "discovery",
            "intervention": {"factor": "domain", "original_value": [0, 1],
                             "counterfactual_value": [0, 0.5]}, **overrides}


def test_paired_preflight_freezes_both_conditions_and_doubles_gt_budget():
    from architecture_iq.studio.generation import validate_generation
    value = validate_generation(request(num_questions=2, n_seeds=2))
    assert value["pair_count"] == 2
    assert value["requested_question_count"] == 4
    assert value["dataset_count"] == 4
    assert value["candidate_seed_runs"] == 24
    assert len(value["pair_plan"]) == 2
    for pair in value["pair_plan"]:
        original, counter = pair["original"], pair["counterfactual"]
        before = deepcopy(original["dataset_spec"])
        after = deepcopy(counter["dataset_spec"])
        assert before.pop("dataset_id") != after.pop("dataset_id")
        assert before["params"].pop("domain") == [0, 1]
        assert after["params"].pop("domain") == [0, 0.5]
        assert before == after
        for left, right in zip(original["candidate_specs"], counter["candidate_specs"], strict=True):
            assert left["candidate_id"] != right["candidate_id"]
            for field in ("model", "optimizer", "loss", "budget", "execution"):
                assert left[field] == right[field]
    assert validate_generation(value) == value


@pytest.mark.parametrize("change", [
    {"family": "spiral_classification"},
    {"intervention": {"factor": "domain", "original_value": [0, 1], "counterfactual_value": [0, 1]}},
    {"intervention": {"factor": "domain", "original_value": [0, 1], "counterfactual_value": [0.5, 0]}},
    {"intervention": {"factor": "domain", "original_value": [-2, 1], "counterfactual_value": [0, 1]}},
    {"intervention": {"factor": "instance_seed", "original_value": 1, "counterfactual_value": 2}},
    {"mode": "unknown"}, {"split": "test"}, {"num_questions": 4, "n_seeds": 10},
])
def test_invalid_pair_conditions_fail_before_gt(change):
    from architecture_iq.studio.generation import validate_generation
    with pytest.raises(ValueError):
        validate_generation(request(**change))


def test_paired_capabilities_come_from_family_plugins():
    from architecture_iq.studio.generation import capabilities
    value = capabilities()
    assert value["generation_modes"] == ["single", "paired"]
    profile = next(p for p in value["profiles"] if p["name"] == "v1.4")
    families = {f["name"]: f for f in profile["families"]}
    assert families["univariate_regression"]["data_interventions"][0]["factor"] == "domain"
    assert families["bigram_lm"]["data_interventions"][0]["factor"] == "alpha"
    assert families["spiral_classification"]["data_interventions"] == []


@pytest.mark.parametrize("flipped", [False, True])
def test_paired_generation_uses_exact_candidate_controls_and_keeps_stable_pairs(tmp_path, monkeypatch, flipped):
    from architecture_iq.studio import pair_generation
    from architecture_iq.studio.generation import execute_generation
    from architecture_iq.studio.catalog import Catalog
    from architecture_iq.studio.jobs import JobStore
    calls = []

    def gt(candidate, profile, dataset):
        spec = json.loads((candidate / "candidate_spec.json").read_text())
        ds = json.loads((dataset / "dataset_spec.json").read_text())
        assert all((candidate / name).exists() for name in ("model.py", "train.py", "optimizer.py", "loss.py"))
        # Every condition/candidate identity must already be frozen before first GT.
        manifest = json.loads((dataset.parents[2] / "generation_manifest.json").read_text())
        assert len(manifest["config"]["pair_plan"][0]["counterfactual"]["candidate_specs"]) == 3
        index = len(calls) % 3
        is_counter = ds["params"]["domain"] == [0, 0.5]
        mean = (3 - index if flipped and is_counter else index + 1) * 0.1
        calls.append((spec, ds, profile.base_seed))
        (candidate / "results").mkdir()
        (candidate / "results" / "summary.json").write_text(json.dumps({
            "candidate_id": spec["candidate_id"], "dataset_id": ds["dataset_id"],
            "mean_test_mse": mean, "std_test_mse": 0,
            "seed_results": [{"seed": profile.base_seed, "final_test_mse": mean, "failed": False}],
            "excluded": False, "failed_seeds": 0}))

    monkeypatch.setattr(pair_generation, "run_ground_truth", gt)
    store = JobStore(tmp_path / "state")
    value = request(split="development")
    job = store.create("generation", value)
    catalog = Catalog(tmp_path / "catalog")
    result = execute_generation(store, job["id"], value, catalog)
    assert result["outcome"] == "complete"
    assert result["generated_pairs"] == 1
    assert result["generated_questions"] == 2
    assert result["changed_winner_pairs"] == int(flipped)
    assert result["stable_winner_pairs"] == int(not flipped)
    assert len(calls) == 6
    for left, right in zip(calls[:3], calls[3:], strict=True):
        assert left[2] == right[2]
        for field in ("model", "optimizer", "loss", "budget"):
            assert left[0][field] == right[0][field]
    rows = catalog.list_questions()["items"]
    assert len(rows) == 2 and all(row["split"] == "development" for row in rows)
    assert rows[0]["pair_id"] == rows[1]["pair_id"]
    for row in rows:
        detail = catalog.get_question(row["key"])
        assert "correct_letter" not in detail["public"]
    pairmap = json.loads((store.directory(job["id"]) / "generated" / "dataflip_pairs.json").read_text())
    assert len(pairmap["pairs"][0]["candidate_mapping"]) == 3
    with pytest.raises(RuntimeError, match="already|pending|repeat"):
        execute_generation(store, job["id"], value, catalog)


def test_mutating_frozen_pair_spec_is_rejected():
    from architecture_iq.studio.generation import validate_generation
    frozen = validate_generation(request())
    frozen["pair_plan"][0]["counterfactual"]["candidate_specs"][0]["optimizer"]["lr"] *= 2
    with pytest.raises(ValueError, match="preflight"):
        validate_generation(frozen)


def test_bigram_pair_preflight_changes_only_alpha_and_shares_rng_streams():
    from architecture_iq.studio.generation import validate_generation
    frozen = validate_generation(request(family="bigram_lm", num_choices=2, candidate_count=2,
        model_type_counts={"gru_lm": 2}, intervention={"factor": "alpha", "original_value": 0.5,
                                                   "counterfactual_value": 2.0}))
    pair = frozen["pair_plan"][0]
    left, right = [deepcopy(pair[role]["dataset_spec"]) for role in ("original", "counterfactual")]
    assert left.pop("dataset_id") != right.pop("dataset_id")
    assert left["params"].pop("alpha") == 0.5
    assert right["params"].pop("alpha") == 2.0
    assert left == right
    assert pair["training_seeds"]
    assert pair["selection_history"] == "all_significant_pairs"


@pytest.mark.parametrize("field", ["split", "training_seeds", "synthesis_context"])
def test_pair_provenance_is_frozen_before_execution(field):
    from architecture_iq.studio.generation import validate_generation
    frozen = validate_generation(request())
    pair = frozen["pair_plan"][0]
    if field == "split":
        pair[field] = "final"
    elif field == "training_seeds":
        pair[field][0] += 1
    else:
        pair["original"][field]["_torch_expression"] = "x * 0"
    with pytest.raises(ValueError, match="preflight"):
        validate_generation(frozen)


def test_pair_rejects_individually_significant_nonmatching_subsets_without_retraining(tmp_path, monkeypatch):
    from architecture_iq.studio import pair_generation
    from architecture_iq.studio.generation import execute_generation
    from architecture_iq.studio.catalog import Catalog
    from architecture_iq.studio.jobs import JobStore
    calls = []

    def gt(candidate, profile, dataset):
        spec = json.loads((candidate / "candidate_spec.json").read_text())
        ds = json.loads((dataset / "dataset_spec.json").read_text())
        index = len(calls) % 4
        is_counter = ds["params"]["domain"] == [0, 0.5]
        excluded = index == (3 if is_counter else 0)
        mean = (index + 1) * 0.1
        calls.append(spec["candidate_id"])
        (candidate / "results").mkdir()
        (candidate / "results" / "summary.json").write_text(json.dumps({
            "candidate_id": spec["candidate_id"], "dataset_id": ds["dataset_id"],
            "mean_test_mse": mean, "std_test_mse": 0,
            "seed_results": [{"seed": profile.base_seed, "final_test_mse": mean, "failed": False}],
            "excluded": excluded, "failed_seeds": 0}))

    monkeypatch.setattr(pair_generation, "run_ground_truth", gt)
    store = JobStore(tmp_path / "state")
    value = request(candidate_count=4)
    job = store.create("generation", value)
    catalog = Catalog(tmp_path / "catalog")
    result = execute_generation(store, job["id"], value, catalog)
    assert result["outcome"] == "insufficient"
    assert result["generated_pairs"] == result["generated_questions"] == 0
    assert len(calls) == 8
    assert len(result["insufficient"]) == 1
    assert catalog.list_questions()["total"] == 0
    assert not list((store.directory(job["id"]) / "generated").rglob("question.json"))
