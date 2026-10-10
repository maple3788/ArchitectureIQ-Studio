"""Bounded, job-local generation using the canonical dataset/candidate/GT pipeline."""
from __future__ import annotations

from copy import deepcopy
import math
import random
import re
from typing import TYPE_CHECKING

from .generation_forms import family_form_schema, validate_family_options

from architecture_iq.candidates.generator import SAMPLEABLE_LOSS_IDS, valid_batch_sizes
from architecture_iq.candidates.sets import generate_candidate_set, parse_varying_axes
from architecture_iq.kb.store import write_json_atomic
from architecture_iq.paths import PROFILES_DIR
from architecture_iq.profile import Profile, load_profile
from architecture_iq.prompts.renderer import write_prompt
from architecture_iq.questions.generator import generate_questions
from architecture_iq.questions.quality import QuestionQualityFilters
from architecture_iq.registry import (
    ensure_registries, get_dataset_family, get_model_type,
    list_dataset_families, list_model_types,
)

if TYPE_CHECKING:
    from .catalog import Catalog
    from .jobs import JobStore

_INPUT_FIELDS = frozenset({"profile", "family", "seed", "family_options", "candidate_count",
                          "model_type_counts", "vary", "budget", "n_seeds", "num_questions",
                          "num_choices", "question_type", "fixed_shared", "mode", "split", "intervention"})
_DERIVED_FIELDS = frozenset({"dataset_plan", "dataset_count", "questions_per_dataset",
                            "candidate_seed_runs", "total_samples_seen", "execution_device",
                            "profile_hash", "base_profile_hash", "pair_count", "requested_question_count",
                            "pair_plan"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _integer(value, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def _load(name: str) -> Profile:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("profile must be a registered profile name")
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.is_file() or not path.resolve().is_relative_to(PROFILES_DIR.resolve()):
        raise ValueError(f"Unknown profile: {name!r}")
    return load_profile(name)


def _configured_profile(profile: Profile, n_seeds: int) -> Profile:
    configured = deepcopy(profile)
    configured.ground_truth["n_seeds"] = n_seeds
    configured.ground_truth["device"] = "cpu"
    configured.raw["ground_truth"] = configured.ground_truth
    return configured


def _models(profile: Profile, family) -> list[str]:
    registered = set(list_model_types())
    return [name for name in profile.model_types_for_family(
        family.name, family.compatible_model_types()) if name in registered]


def _losses(profile: Profile, family: str) -> list[str]:
    return [name for name in profile.pools.get("losses", {}).get(family, [])
            if name in SAMPLEABLE_LOSS_IDS]


def capabilities() -> dict:
    """Return the real profile/registry pools plus server generation bounds."""
    ensure_registries()
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        profile = _load(path.stem)
        families = []
        for name in profile.pools["dataset_families"]:
            family = get_dataset_family(name)
            families.append({"name": name, "model_types": _models(profile, family),
                             "losses": _losses(profile, name),
                             "options": list(family.instance_option_names),
                             "config": profile.family_config(name),
                             "form_schema": family_form_schema(profile, family),
                             "data_interventions": family.data_interventions()})
        profiles.append({"name": path.stem, "pools": deepcopy(profile.pools),
                         "budgets": profile.budget_values, "n_seeds": profile.n_seeds,
                         "num_choices": profile.num_choices, "families": families,
                         "max_questions_per_dataset": QuestionQualityFilters.from_profile(profile).max_questions_per_dataset})
    return {"profiles": profiles, "families": list_dataset_families(),
            "generation_modes": ["single", "paired"], "splits": ["discovery", "development", "final"],
            "model_types": list_model_types(), "generation_limits": {
                "candidate_count": 20, "n_seeds": 10, "num_questions": 100,
                "candidate_seed_runs": 200, "execution_device": "cpu"}}


def _family_options(profile: Profile, family, value) -> dict:
    return validate_family_options(profile, family, value)


def _finite_number(value, name: str, *, minimum: float = 0) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be a finite number >= {minimum}")


def _fixed_shared(profile: Profile, family, axes: frozenset[str], budget: int, value) -> dict:
    if not isinstance(value, dict) or set(value) - {"batch_size", "model", "optimizer", "loss"}:
        raise ValueError("fixed_shared accepts only batch_size, model, optimizer and loss")
    fixed = deepcopy(value)
    if set(fixed) & axes:
        raise ValueError("fixed_shared cannot pin a varying axis")
    if "batch_size" in fixed:
        _integer(fixed["batch_size"], "fixed_shared.batch_size", 1, budget)
        if fixed["batch_size"] not in valid_batch_sizes(profile, budget):
            raise ValueError("fixed_shared.batch_size violates profile budget/step limits")
    if "loss" in fixed:
        loss = fixed["loss"]
        if not isinstance(loss, dict) or set(loss) != {"loss_id"} or loss["loss_id"] not in _losses(profile, family.name):
            raise ValueError("fixed_shared.loss must use the family's sampleable loss pool")
    if "optimizer" in fixed:
        optimizer = fixed["optimizer"]
        if not isinstance(optimizer, dict) or set(optimizer) - {"type", "lr", "weight_decay", "momentum", "betas"}:
            raise ValueError("Invalid fixed_shared.optimizer fields")
        if optimizer.get("type") not in profile.pools["optimizers"]:
            raise ValueError("fixed_shared.optimizer.type is outside the profile pool")
        _finite_number(optimizer.get("lr"), "optimizer.lr", minimum=1e-30)
        _finite_number(optimizer.get("weight_decay", 0), "optimizer.weight_decay")
        if "momentum" in optimizer:
            if optimizer["type"] != "SGD":
                raise ValueError("Only SGD accepts momentum")
            _finite_number(optimizer["momentum"], "optimizer.momentum")
        if "betas" in optimizer:
            betas = optimizer["betas"]
            if optimizer["type"] not in {"Adam", "AdamW"} or not isinstance(betas, list) or len(betas) != 2:
                raise ValueError("Only Adam/AdamW accept a pair of betas")
            for beta in betas:
                _finite_number(beta, "optimizer.beta")
                if beta >= 1:
                    raise ValueError("optimizer.beta must be < 1")
    if "model" in fixed:
        model = fixed["model"]
        if not isinstance(model, dict) or model.get("type") not in _models(profile, family):
            raise ValueError("fixed_shared.model.type is outside family/profile compatibility")
        # Model renderers interpolate scalar dimensions. Never accept executable
        # strings as numeric fields or silently ignore unknown advanced fields.
        model_type = get_model_type(model["type"])
        from architecture_iq.candidates.generator import sample_model
        params = {"vocab_size": model.get("vocab_size", 2),
                  "context_length": model.get("context_length", 1),
                  "input_dim": model.get("input_dim", 1),
                  "num_classes": model.get("output_dim", 1)}
        example = {}
        for probe_seed in range(16):
            example.update(sample_model(profile, random.Random(probe_seed), family=family.name,
                                        model_type=model["type"], dataset_params=params))
        if set(model) - set(example):
            raise ValueError("Unknown fixed_shared.model fields")
        for key, item in model.items():
            expected = example.get(key)
            if type(expected) is int:
                _integer(item, f"model.{key}", 1, 100000)
            elif type(expected) is bool and type(item) is not bool:
                raise ValueError(f"model.{key} must be a boolean")
            elif type(expected) is float:
                _finite_number(item, f"model.{key}")
            elif isinstance(expected, list) and (
                not isinstance(item, list) or not all(type(v) is bool for v in item)
            ):
                raise ValueError(f"model.{key} must be a boolean list")
            elif isinstance(expected, str) and not isinstance(item, str):
                raise ValueError(f"model.{key} must be a string")
        try:
            model_type.validate(model)
            model_type.render_model_py(model)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid fixed_shared.model: {exc}") from exc
    return fixed


def validate_generation(config: dict) -> dict:
    """Freeze a bounded batch before any dataset synthesis or GT execution."""
    ensure_registries()
    if not isinstance(config, dict) or set(config) - _INPUT_FIELDS - _DERIVED_FIELDS:
        raise ValueError("Unknown generation configuration fields")
    mode = config.get("mode", "single")
    if mode not in ("single", "paired"):
        raise ValueError("mode must be single or paired")
    split = config.get("split", "discovery")
    if split not in ("discovery", "development", "final"):
        raise ValueError("split must be discovery, development, or final")
    intervention = config.get("intervention")
    if mode == "single" and intervention is not None:
        raise ValueError("intervention requires paired generation")
    if mode == "paired" and (not isinstance(intervention, dict) or set(intervention) != {
            "factor", "original_value", "counterfactual_value"}):
        raise ValueError("paired generation requires factor, original_value and counterfactual_value")
    profile_name = config.get("profile", "v1.4")
    base = _load(profile_name)
    family_name = config.get("family")
    if not isinstance(family_name, str) or family_name not in base.pools["dataset_families"]:
        raise ValueError("family must belong to the selected profile pool")
    family = get_dataset_family(family_name)
    if mode == "paired":
        family.validate_data_intervention(base, intervention["factor"], intervention["original_value"])
        family.validate_data_intervention(base, intervention["factor"], intervention["counterfactual_value"])
        if intervention["original_value"] == intervention["counterfactual_value"]:
            raise ValueError("The intervention must change its declared factor")
    if not _models(base, family) or not _losses(base, family_name):
        raise ValueError("Profile has no registered compatible models or sampleable losses")
    seed = _integer(config.get("seed", 0), "seed", 0, 2**32 - 1)
    count = _integer(config.get("candidate_count", base.num_choices), "candidate_count", 2, 20)
    n_seeds = _integer(config.get("n_seeds", base.n_seeds), "n_seeds", 1, 10)
    num_questions = _integer(config.get("num_questions", 1), "num_questions", 1, 100)
    num_choices = _integer(config.get("num_choices", base.num_choices), "num_choices", 2, count)
    budget = _integer(config.get("budget", base.budget_values[0]), "budget", 1, 10**12)
    if budget not in base.budget_values or not valid_batch_sizes(base, budget):
        raise ValueError("budget must be a profile budget with a valid batch size")
    vary = config.get("vary", ["model"])
    if not isinstance(vary, list) or not all(isinstance(axis, str) for axis in vary):
        raise ValueError("vary must be a list of axis names")
    axes = parse_varying_axes(vary)
    if "loss" in axes and len(_losses(base, family_name)) < 2:
        raise ValueError("The sampleable loss pool cannot vary for this family")
    question_type = config.get("question_type")
    if question_type is not None and not isinstance(question_type, str):
        raise ValueError("question_type must be a string or null")
    if question_type == "":
        question_type = None
    if question_type is not None:
        if question_type not in base.pools.get("question_types", []):
            raise ValueError("question_type must belong to the profile pool")
        required_axis = {"architecture_only": "model", "optimizer_only": "optimizer", "loss_only": "loss"}.get(question_type)
        if required_axis and axes != frozenset({required_axis}):
            raise ValueError("question_type does not agree with varying axes")
        if question_type == "mixed" and len(axes) < 2:
            raise ValueError("mixed questions require multiple varying axes")
    quotas = config.get("model_type_counts")
    if quotas is not None:
        if not isinstance(quotas, dict) or not quotas or "model" not in axes:
            raise ValueError("model_type_counts requires model variation and a nonempty object")
        if set(quotas) - set(_models(base, family)):
            raise ValueError("model_type_counts contains incompatible/unregistered model types")
        for model, amount in quotas.items():
            _integer(amount, f"model_type_counts.{model}", 1, count)
        if sum(quotas.values()) != count:
            raise ValueError("model_type_counts must sum to candidate_count")
    profile = _configured_profile(base, n_seeds)
    limit = QuestionQualityFilters.from_profile(profile).max_questions_per_dataset
    per_dataset = min(count // num_choices, limit if limit is not None else 100)
    if per_dataset < 1:
        raise ValueError("The profile cannot supply one question per dataset")
    if mode == "paired":
        per_dataset = 1
    dataset_count = 2 * num_questions if mode == "paired" else math.ceil(num_questions / per_dataset)
    candidate_seed_runs = count * n_seeds * dataset_count
    if candidate_seed_runs > 200:
        raise ValueError(f"Batch needs {candidate_seed_runs} candidate-seed runs; maximum is 200 "
                         f"({dataset_count} datasets × {count} candidates × {n_seeds} seeds)")
    if seed + (num_questions if mode == "paired" else dataset_count) - 1 > 2**32 - 1:
        raise ValueError("Batch dataset seeds exceed the supported seed range")
    plan = [{"seed": seed + index, "num_questions": min(per_dataset, num_questions - index * per_dataset)}
            for index in range(dataset_count)]
    if mode == "paired":
        plan = [{"seed": seed + index, "num_questions": 1, "pair_index": index, "role": role}
                for index in range(num_questions) for role in ("original", "counterfactual")]
    normalized = {"mode": mode, "split": split, "intervention": deepcopy(intervention),
                  "pair_count": num_questions if mode == "paired" else 0,
                  "requested_question_count": num_questions * (2 if mode == "paired" else 1),
                  "pair_plan": [], "profile": profile_name, "family": family_name, "seed": seed,
                  "family_options": _family_options(profile, family, config.get("family_options", {})),
                  "candidate_count": count, "model_type_counts": deepcopy(quotas),
                  "vary": sorted(axes), "budget": budget, "n_seeds": n_seeds,
                  "num_questions": num_questions, "num_choices": num_choices,
                  "question_type": question_type,
                  "fixed_shared": _fixed_shared(profile, family, axes, budget, config.get("fixed_shared", {})),
                  "dataset_plan": plan, "dataset_count": dataset_count,
                  "questions_per_dataset": per_dataset, "candidate_seed_runs": candidate_seed_runs,
                  "total_samples_seen": budget * candidate_seed_runs, "execution_device": "cpu",
                  "base_profile_hash": base.profile_hash, "profile_hash": profile.profile_hash}
    if mode == "paired":
        from .pair_generation import freeze_pair_plan
        normalized["pair_plan"] = freeze_pair_plan(profile, family, normalized)
    for key in _DERIVED_FIELDS & set(config):
        if config[key] != normalized[key]:
            raise ValueError(f"Frozen generation preflight changed: {key}")
    return normalized


def _insufficient(exc: RuntimeError) -> bool:
    message = str(exc)
    return message.startswith(("Could not sample ", "No parameter band ",
                               "Not enough eligible candidates ", "Failed to find significant ")) or (
        message.startswith("Requested ") and "questions but no valid selection" in message)


def execute_generation(store: JobStore, job_id: str, config: dict, catalog: Catalog) -> dict:
    """Execute the frozen batch once. Interruptions never trigger replacement GT."""
    normalized = validate_generation(config)
    profile = _configured_profile(_load(normalized["profile"]), normalized["n_seeds"])
    if profile.profile_hash != normalized["profile_hash"]:
        raise ValueError("Frozen generation profile changed before execution")
    if normalized["mode"] == "paired":
        from .pair_generation import execute_paired_generation
        return execute_paired_generation(store, job_id, normalized, profile, catalog)
    directory = store.directory(job_id).resolve()
    generated = directory / "generated"
    try:
        generated.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeError("Generation already started or pending; never repeat automatically") from exc
    family = get_dataset_family(normalized["family"])
    manifest = {"schema_version": 1, "status": "planning", "config": normalized,
                "profile_hash": profile.profile_hash, "base_profile_hash": normalized["base_profile_hash"],
                "configured_profile": profile.raw, "dataset_plan": normalized["dataset_plan"], "datasets": []}
    manifest_path = generated / "generation_manifest.json"
    write_json_atomic(manifest_path, manifest)
    planned = []
    paths = set()
    # All identities and requested quantities are fixed before the first GT run.
    for item in normalized["dataset_plan"]:
        partial = family.create_instance(profile, item["seed"], **normalized["family_options"])
        spec = family.build_spec_with_id(partial)
        model = normalized["fixed_shared"].get("model", {})
        params = spec["params"]
        expected_dimensions = {"input_dim": params.get("input_dim", 1),
                               "output_dim": params.get("num_classes", 1),
                               **{key: params[key] for key in ("vocab_size", "context_length") if key in params}}
        for key, expected in expected_dimensions.items():
            if key in model and model[key] != expected:
                raise ValueError(f"fixed_shared.model.{key}={model[key]} does not match dataset {expected}")
        identifier = spec["dataset_id"]
        if not isinstance(identifier, str) or not _NAME.fullmatch(identifier):
            raise ValueError("Dataset plugin returned an unsafe dataset_id")
        output = generated / "datasets" / family.name / identifier
        if output in paths:
            raise ValueError("Frozen batch contains duplicate dataset identities")
        paths.add(output)
        planned.append((item, {**partial, **spec}, output))
        manifest["datasets"].append({**item, "dataset_id": identifier, "path": str(output.relative_to(generated)),
                                     "dataset_spec": spec, "status": "planned"})
    manifest["status"] = "running"
    write_json_atomic(manifest_path, manifest)
    store.event(job_id, {"type": "generation_plan", "profile_hash": profile.profile_hash,
                         "dataset_count": normalized["dataset_count"],
                         "candidate_seed_runs": normalized["candidate_seed_runs"],
                         "total_samples_seen": normalized["total_samples_seen"]})
    completed = []
    failures = []
    for index, (item, spec, output) in enumerate(planned):
        entry = manifest["datasets"][index]
        stage = "dataset"
        store.boundary(job_id, {"stage": "dataset", "dataset_index": index + 1,
                                "dataset_count": len(planned), "seed": item["seed"]})
        family.materialize(spec, output)

        def progress(done: int, total: int, candidate_id: str) -> None:
            store.boundary(job_id, {"stage": "candidate_complete", "dataset_index": index + 1,
                                    "candidate_id": candidate_id, "completed": done, "total": total})

        try:
            stage = "candidates"
            store.boundary(job_id, {"stage": stage, "dataset_index": index + 1})
            candidate_set = generate_candidate_set(
                profile, dataset_path=output, budget=normalized["budget"], count=normalized["candidate_count"],
                varying_axes=frozenset(normalized["vary"]), rng=random.Random(item["seed"]),
                fixed_shared=normalized["fixed_shared"], model_type_counts=normalized["model_type_counts"],
                seed=item["seed"], on_progress=progress, execution_device="cpu")
            entry["candidate_set"] = str(candidate_set.relative_to(generated))
            stage = "questions"
            store.boundary(job_id, {"stage": stage, "dataset_index": index + 1})
            run_path, questions = generate_questions(
                profile, dataset_path=output, candidate_set_paths=[candidate_set], rng=random.Random(item["seed"]),
                num_questions=item["num_questions"], num_choices=normalized["num_choices"], seed=item["seed"],
                question_type=normalized["question_type"], artifact_root=generated, split=normalized["split"])
            for _, question_path in questions:
                write_prompt(question_path, dataset_path=output, artifact_root=generated)
            entry.update(status="complete", question_run=str(run_path.relative_to(generated)),
                         question_ids=[record["question_id"] for record, _ in questions])
            completed.extend(record["question_id"] for record, _ in questions)
        except RuntimeError as exc:
            if not _insufficient(exc):
                raise
            failure = {"dataset_id": spec["dataset_id"], "seed": item["seed"], "stage": stage,
                       "requested_questions": item["num_questions"], "reason": str(exc)}
            failures.append(failure)
            entry.update(status="insufficient", reason=str(exc))
            store.event(job_id, {"type": "generation_insufficient", **failure})
        write_json_atomic(manifest_path, manifest)
    import_report = None
    if completed:
        store.boundary(job_id, {"stage": "import", "generated_questions": len(completed)})
        import_report = catalog.import_source(generated / "datasets", name=f"Generation {job_id}")
    outcome = "complete" if len(completed) == normalized["num_questions"] else ("partial" if completed else "insufficient")
    if import_report and import_report.get("errors"):
        outcome = "import_failed"
    result = {"outcome": outcome, "requested_questions": normalized["num_questions"],
              "generated_questions": len(completed), "question_ids": completed,
              "insufficient": failures, "import_report": import_report, "output_path": str(generated),
              "profile_hash": profile.profile_hash, "preflight": normalized}
    manifest.update(status=outcome, result=result)
    write_json_atomic(manifest_path, manifest)
    store.event(job_id, {"type": "generation_result", "outcome": outcome,
                         "generated_questions": len(completed), "requested_questions": normalized["num_questions"]})
    return result
