"""Frozen pair planning and bounded execution through the canonical pipeline."""
from __future__ import annotations

from copy import deepcopy
import random

from architecture_iq.candidates.generator import build_candidate_spec, write_candidate
from architecture_iq.candidates.sets import (
    make_set_name, realized_parameter_band, sample_candidate_set_pool, write_set_manifest,
)
from architecture_iq.ground_truth.runner import run_ground_truth
from architecture_iq.kb.store import write_json_atomic
from architecture_iq.prompts.renderer import write_prompt
from architecture_iq.questions.pairs import generate_question_pair
from architecture_iq.registry import get_dataset_family, get_model_type
from architecture_iq.util import short_hash


def freeze_pair_plan(profile, family, config: dict) -> list[dict]:
    """Determine every dataset, candidate, split and training seed before GT."""
    pairs = []
    for index in range(config["pair_count"]):
        seed = config["seed"] + index
        original, counter = family.create_intervention_pair(
            profile, seed, **config["intervention"], **config["family_options"])
        params = original["dataset_spec"]["params"]
        fixed_model = config["fixed_shared"].get("model", {})
        dimensions = {"input_dim": params.get("input_dim", 1), "output_dim": params.get("num_classes", 1),
                      **{key: params[key] for key in ("vocab_size", "context_length") if key in params}}
        for key, expected in dimensions.items():
            if key in fixed_model and fixed_model[key] != expected:
                raise ValueError(f"fixed_shared.model.{key} does not match dataset {expected}")
        original["candidate_specs"] = sample_candidate_set_pool(
            profile, dataset_id=original["dataset_spec"]["dataset_id"], family=family.name,
            budget=config["budget"], count=config["candidate_count"],
            varying_axes=frozenset(config["vary"]), rng=random.Random(seed),
            fixed_shared=config["fixed_shared"], model_type_counts=config["model_type_counts"],
            dataset_params=params, execution_device=config["execution_device"])
        counter["candidate_specs"] = [build_candidate_spec(
            profile, dataset_id=counter["dataset_spec"]["dataset_id"], family=family.name,
            budget=spec["budget"]["total_samples_seen"], batch_size=spec["budget"]["batch_size"],
            model=deepcopy(spec["model"]), optimizer=deepcopy(spec["optimizer"]), loss=deepcopy(spec["loss"]),
            execution_device=spec["execution"]["device"]) for spec in original["candidate_specs"]]
        mapping = [{"choice_identity": "choice_" + short_hash({key: left[key] for key in (
                       "model", "optimizer", "loss", "budget", "execution")}),
                    "original_candidate_id": left["candidate_id"],
                    "counterfactual_candidate_id": right["candidate_id"]}
                   for left, right in zip(original["candidate_specs"], counter["candidate_specs"], strict=True)]
        pair = {"seed": seed, "split": config["split"], "intervention": deepcopy(config["intervention"]),
                "training_seeds": [profile.base_seed + i for i in range(profile.n_seeds)],
                "original": original, "counterfactual": counter, "candidate_mapping": mapping,
                "selection_history": "all_significant_pairs"}
        pair["pair_id"] = "pair_" + short_hash(pair)
        pairs.append(pair)
    return pairs


def execute_paired_generation(store, job_id: str, config: dict, profile, catalog) -> dict:
    generated = store.directory(job_id).resolve() / "generated"
    try:
        generated.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeError("Generation already started or pending; never repeat automatically") from exc
    family = get_dataset_family(config["family"])
    manifest = {"schema_version": 1, "status": "running", "config": config,
                "profile_hash": profile.profile_hash, "base_profile_hash": config["base_profile_hash"],
                "configured_profile": profile.raw, "dataset_plan": config["dataset_plan"], "pairs": []}
    manifest_path = generated / "generation_manifest.json"
    write_json_atomic(manifest_path, manifest)
    store.event(job_id, {"type": "generation_plan", "profile_hash": profile.profile_hash,
                         "pair_count": config["pair_count"], "dataset_count": config["dataset_count"],
                         "candidate_seed_runs": config["candidate_seed_runs"],
                         "total_samples_seen": config["total_samples_seen"]})
    pairs, question_ids, failures = [], [], []
    changed = 0
    for index, plan in enumerate(config["pair_plan"]):
        entry = {"pair_id": plan["pair_id"], "seed": plan["seed"], "status": "running", "members": {}}
        manifest["pairs"].append(entry)
        dataset_paths, candidate_sets = {}, {}
        # Specs for every pair are in the persisted manifest before this boundary.
        for role in ("original", "counterfactual"):
            condition = plan[role]
            spec = condition["dataset_spec"]
            output = generated / "datasets" / family.name / spec["dataset_id"]
            dataset_paths[role] = output
            store.boundary(job_id, {"stage": "dataset", "pair_index": index + 1,
                                    "pair_count": config["pair_count"], "role": role})
            family.materialize({**spec, **condition["synthesis_context"]}, output)
            set_name = make_set_name(config["budget"], frozenset(config["vary"]),
                                     salt={"pair_id": plan["pair_id"], "role": role})
            set_path = output / "candidates" / set_name
            set_path.mkdir(parents=True, exist_ok=False)
            candidate_sets[role] = set_path
            candidates = condition["candidate_specs"]
            shared = {"batch_size": candidates[0]["budget"]["batch_size"],
                      **{axis: candidates[0][axis] for axis in ("model", "optimizer", "loss")
                         if axis not in config["vary"]}}
            write_set_manifest(
                set_path, set_name=set_name, budget=config["budget"], count=len(candidates),
                varying_axes=frozenset(config["vary"]), fixed_shared=shared,
                model_type_counts=config["model_type_counts"], seed=plan["seed"], profile=profile,
                dataset_id=spec["dataset_id"], family=family.name,
                parameter_band=realized_parameter_band(candidates, ratio_max=profile.parameter_ratio_max()))
            for done, candidate in enumerate(candidates, 1):
                path = set_path / candidate["candidate_id"]
                write_candidate(candidate, path, get_model_type(candidate["model"]["type"]))
                store.boundary(job_id, {"stage": "candidate", "pair_index": index + 1, "role": role,
                                        "candidate_id": candidate["candidate_id"]})
                run_ground_truth(path, profile, output)
                store.boundary(job_id, {"stage": "candidate_complete", "pair_index": index + 1,
                                        "role": role, "candidate_id": candidate["candidate_id"],
                                        "completed": done, "total": len(candidates)})
            entry["members"][role] = {"dataset_id": spec["dataset_id"],
                                      "candidate_set": str(set_path.relative_to(generated))}
            write_json_atomic(manifest_path, manifest)
        store.boundary(job_id, {"stage": "questions", "pair_index": index + 1})
        try:
            pair, questions, winner_changed = generate_question_pair(
                profile, pair_plan=plan, dataset_paths=dataset_paths, candidate_set_paths=candidate_sets,
                num_choices=config["num_choices"], question_type=config["question_type"],
                split=config["split"], artifact_root=generated, rng=random.Random(plan["seed"]))
            for role, (record, path) in zip(("original", "counterfactual"), questions, strict=True):
                write_prompt(path, dataset_path=dataset_paths[role], artifact_root=generated)
                question_ids.append(record["question_id"])
            pairs.append(pair)
            changed += int(winner_changed)
            entry.update(status="complete", question_ids=[record["question_id"] for record, _ in questions],
                         winner_changed=winner_changed)
        except RuntimeError as exc:
            if not str(exc).startswith("Failed to find significant matched"):
                raise
            failure = {"pair_id": plan["pair_id"], "seed": plan["seed"], "stage": "questions", "reason": str(exc)}
            failures.append(failure)
            entry.update(status="insufficient", reason=str(exc))
            store.event(job_id, {"type": "generation_insufficient", **failure})
        write_json_atomic(manifest_path, manifest)
    pairmap_path = generated / "dataflip_pairs.json"
    write_json_atomic(pairmap_path, {"schema_version": 1, "pairs": pairs})
    report = None
    if pairs:
        store.boundary(job_id, {"stage": "import", "generated_questions": len(question_ids)})
        report = catalog.import_source(generated / "datasets", name=f"Generation {job_id}", pairmap_path=pairmap_path)
    outcome = "complete" if len(pairs) == config["pair_count"] else ("partial" if pairs else "insufficient")
    if report and report.get("errors"):
        outcome = "import_failed"
    result = {"outcome": outcome, "requested_pairs": config["pair_count"],
              "requested_questions": config["requested_question_count"],
              "generated_pairs": len(pairs), "generated_questions": len(question_ids),
              "changed_winner_pairs": changed, "stable_winner_pairs": len(pairs) - changed,
              "pair_ids": [pair["pair_id"] for pair in pairs], "question_ids": question_ids,
              "insufficient": failures, "import_report": report, "output_path": str(generated),
              "profile_hash": profile.profile_hash, "preflight": config}
    manifest.update(status=outcome, result=result)
    write_json_atomic(manifest_path, manifest)
    store.event(job_id, {"type": "generation_result", "outcome": outcome,
                         "generated_pairs": len(pairs), "generated_questions": len(question_ids),
                         "requested_questions": config["requested_question_count"]})
    return result
