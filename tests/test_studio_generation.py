"""Generation orchestration tests; training is replaced at the canonical GT boundary."""
import json

import pytest

from architecture_iq.profile import load_profile
from architecture_iq.studio.jobs import JobStore


def config(**overrides):
    return {"profile": "v1.4", "family": "univariate_regression", "seed": 7,
            "candidate_count": 3, "vary": ["model"], "budget": 4096,
            "n_seeds": 1, "num_questions": 1, "num_choices": 3, **overrides}


def test_batch_preflight_accounts_for_every_instance():
    from architecture_iq.studio.generation import validate_generation
    value = validate_generation(config(num_questions=4, n_seeds=2))
    assert value["dataset_plan"] == [{"seed": 7, "num_questions": 1},
                                     {"seed": 8, "num_questions": 1},
                                     {"seed": 9, "num_questions": 1},
                                     {"seed": 10, "num_questions": 1}]
    assert value["dataset_count"] == 4
    assert value["candidate_seed_runs"] == 24
    assert value["total_samples_seen"] == 98304
    assert value["execution_device"] == "cpu"
    assert load_profile("v1.4").n_seeds == 10


@pytest.mark.parametrize("overrides", [
    {"profile": "../../outside"}, {"family": "unknown"}, {"seed": True},
    {"candidate_count": 21}, {"candidate_count": 2}, {"budget": 100},
    {"n_seeds": 11}, {"num_questions": 101}, {"num_choices": 1},
    {"vary": ["batch_size"]}, {"question_type": "loss_only"},
    {"family_options": {"input_dim": 4}}, {"model_type_counts": {"gru_lm": 3}},
    {"model_type_counts": {"mlp": 2}}, {"unexpected": 1},
    {"num_questions": 10, "n_seeds": 10},
    {"fixed_shared": {"model": {"type": "mlp"}}},
    {"fixed_shared": {"batch_size": 64}},
])
def test_invalid_generation_cannot_start_training(overrides):
    from architecture_iq.studio.generation import validate_generation
    with pytest.raises(ValueError):
        validate_generation(config(**overrides))


def test_family_options_obey_plugin_and_profile_constraints():
    from architecture_iq.studio.generation import validate_generation
    assert validate_generation(config(family="multivariate_regression", family_options={"input_dim": 4}))["family_options"] == {"input_dim": 4}
    with pytest.raises(ValueError):
        validate_generation(config(family="multivariate_regression", family_options={"input_dim": "4"}))
    with pytest.raises(ValueError):
        validate_generation(config(family="multivariate_regression", family_options={"input_dim": 999}))


def test_capabilities_describe_registered_sampling_and_batch_limits():
    from architecture_iq.studio.generation import capabilities
    value = capabilities()
    profile = next(p for p in value["profiles"] if p["name"] == "v1.4")
    family = next(f for f in profile["families"] if f["name"] == "multivariate_regression")
    assert family["model_types"] == ["mlp"]
    assert family["losses"] == ["mse"]
    assert family["options"] == ["input_dim"]
    assert family["config"]["input_dims"] == [2, 3, 4, 5, 8]
    assert profile["max_questions_per_dataset"] == 1


def test_canonical_generated_artifacts_are_imported_with_actual_profile(tmp_path, monkeypatch):
    from architecture_iq.candidates import sets
    from architecture_iq.studio.catalog import Catalog
    from architecture_iq.studio.generation import execute_generation
    seen = []

    def instrument_gt(candidate, profile, dataset):
        # No training: preserve the canonical set writer and question assembly.
        spec = json.loads((candidate / "candidate_spec.json").read_text())
        assert spec["execution"]["device"] == "cpu"
        assert spec["profile_hash"] == profile.profile_hash
        assert profile.raw["ground_truth"]["n_seeds"] == profile.n_seeds == 1
        assert all((candidate / name).exists() for name in ("model.py", "optimizer.py", "loss.py", "train.py"))
        seen.append((candidate, dataset, profile.profile_hash))
        mean = 0.1 * len(seen)
        (candidate / "results").mkdir()
        (candidate / "results" / "summary.json").write_text(json.dumps({
            "candidate_id": spec["candidate_id"], "mean_test_mse": mean, "std_test_mse": 0,
            "seed_results": [{"seed": 0, "final_test_mse": mean, "failed": False}],
            "excluded": False, "failed_seeds": 0}))

    monkeypatch.setattr(sets, "run_ground_truth", instrument_gt)
    store = JobStore(tmp_path / "state")
    request = config(num_questions=2)
    job = store.create("generation", request)
    catalog = Catalog(tmp_path / "catalog")
    result = execute_generation(store, job["id"], request, catalog)
    generated = store.directory(job["id"]) / "generated"
    assert result["outcome"] == "complete"
    assert result["generated_questions"] == 2
    assert len(seen) == 6
    assert all(c.is_relative_to(generated) and d.is_relative_to(generated) for c, d, _ in seen)
    assert catalog.list_questions()["total"] == 2
    assert all(q["ready"] for q in catalog.list_questions()["items"])
    metadata = json.loads((generated / "generation_manifest.json").read_text())
    assert metadata["profile_hash"] == seen[0][2]
    assert metadata["profile_hash"] != load_profile("v1.4").profile_hash
    assert metadata["configured_profile"]["ground_truth"]["n_seeds"] == 1
    assert metadata["dataset_plan"] == [{"seed": 7, "num_questions": 1}, {"seed": 8, "num_questions": 1}]
    events = store.events(job["id"])
    assert sum(e.get("stage") == "candidate_complete" for e in events) == 6
    # An already executed job must not silently regenerate training outputs.
    with pytest.raises(RuntimeError, match="already|pending|repeat"):
        execute_generation(store, job["id"], request, catalog)


def test_insufficient_selection_is_reported_without_replacement(tmp_path, monkeypatch):
    from architecture_iq.studio import generation
    from architecture_iq.studio.catalog import Catalog
    created = []

    def candidates(profile, *, dataset_path, on_progress, **kwargs):
        created.append(json.loads((dataset_path / "dataset_spec.json").read_text())["params"]["instance_seed"])
        path = dataset_path / "candidates" / "set_test"
        path.mkdir(parents=True)
        on_progress(3, 3, "c_last")
        return path

    def questions(*args, **kwargs):
        raise RuntimeError("Failed to find significant 3-candidate subsets")

    monkeypatch.setattr(generation, "generate_candidate_set", candidates)
    monkeypatch.setattr(generation, "generate_questions", questions)
    store = JobStore(tmp_path / "state")
    request = config(num_questions=2)
    job = store.create("generation", request)
    result = generation.execute_generation(store, job["id"], request, Catalog(tmp_path / "catalog"))
    assert result["outcome"] == "insufficient"
    assert result["requested_questions"] == 2
    assert result["generated_questions"] == 0
    assert len(result["insufficient"]) == 2
    assert "significant" in result["insufficient"][0]["reason"]
    assert created == [7, 8]
    assert result["import_report"] is None


def test_pending_generation_directory_is_never_retried(tmp_path):
    from architecture_iq.studio.generation import execute_generation
    store = JobStore(tmp_path / "state")
    job = store.create("generation", config())
    (store.directory(job["id"]) / "generated").mkdir()
    with pytest.raises(RuntimeError, match="already|pending|repeat"):
        execute_generation(store, job["id"], config(), None)


def test_fixed_lm_model_is_validated_without_materializing_dataset():
    from architecture_iq.studio.generation import validate_generation
    model = {"type": "gru_lm", "vocab_size": 24, "context_length": 12,
             "d_model": 32, "num_layers": 1, "layer_residual": False}
    value = validate_generation(config(family="bigram_lm", vary=["optimizer"],
                                       question_type="optimizer_only", fixed_shared={"model": model}))
    assert value["fixed_shared"]["model"] == model


def test_frozen_preflight_cannot_be_mutated_or_change_profile():
    from architecture_iq.studio.generation import validate_generation
    value = validate_generation(config())
    assert validate_generation(value) == value
    value["dataset_plan"][0]["seed"] = 999
    with pytest.raises(ValueError, match="preflight"):
        validate_generation(value)


@pytest.mark.parametrize("question_type", [False, 0, {}, ["architecture_only"]])
def test_malformed_question_type_is_rejected(question_type):
    from architecture_iq.studio.generation import validate_generation
    with pytest.raises(ValueError):
        validate_generation(config(question_type=question_type))


def test_worker_crash_is_not_misreported_as_insufficient(tmp_path, monkeypatch):
    from architecture_iq.studio import generation

    def crashed(*args, **kwargs):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(generation, "generate_candidate_set", crashed)
    store = JobStore(tmp_path / "state")
    job = store.create("generation", config())
    with pytest.raises(RuntimeError, match="out of memory"):
        generation.execute_generation(store, job["id"], config(), None)
    with pytest.raises(RuntimeError, match="already|pending|repeat"):
        generation.execute_generation(store, job["id"], config(), None)


def test_fixed_model_dataset_shape_is_checked_before_any_gt(tmp_path, monkeypatch):
    from architecture_iq.studio import generation
    model = {"type": "mlp", "depth": 1, "width": 16, "activation": "relu",
             "layer_norm": [False], "residual": False, "input_dim": 2, "output_dim": 1}
    request = config(vary=["optimizer"], fixed_shared={"model": model})
    store = JobStore(tmp_path / "state")
    job = store.create("generation", request)

    def forbidden_gt(*args, **kwargs):
        pytest.fail("GT must not start with a known incompatible fixed model")

    monkeypatch.setattr(generation, "generate_candidate_set", forbidden_gt)
    with pytest.raises(ValueError, match="input_dim"):
        generation.execute_generation(store, job["id"], request, None)
