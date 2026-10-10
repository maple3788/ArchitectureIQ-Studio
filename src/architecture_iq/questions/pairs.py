"""Assemble controlled pairs from stored GT on matching candidate subsets."""
from __future__ import annotations

import random
from pathlib import Path

from architecture_iq.profile import Profile
from architecture_iq.questions.generator import (
    _validate_pool_dataset, _write_question, find_significant_subsets,
    load_candidate_pool_from_sets,
)
from architecture_iq.questions.quality import QuestionQualityFilters
from architecture_iq.questions.runs import make_run_name, question_run_dir, write_run_manifest
from architecture_iq.util import read_json


def generate_question_pair(
    profile: Profile, *, pair_plan: dict, dataset_paths: dict[str, Path],
    candidate_set_paths: dict[str, Path], num_choices: int, question_type: str | None,
    split: str, artifact_root: Path, rng: random.Random,
) -> tuple[dict, list[tuple[dict, Path]], bool]:
    """Keep a matching subset only when both sides pass canonical quality gates.

    Winner identity is inspected only after selection, so stable winners are
    retained with the same rules as changed winners. No replacement GT runs.
    """
    quality = QuestionQualityFilters.from_profile(profile)
    specs = {role: read_json(path / "dataset_spec.json") for role, path in dataset_paths.items()}
    pools = {
        role: load_candidate_pool_from_sets([path], filters=quality,
                                            selection_metric=specs[role]["selection_metric"])
        for role, path in candidate_set_paths.items()
    }
    for role, pool in pools.items():
        _validate_pool_dataset(pool, dataset_paths[role])
    by_id = {role: {read_json(path / "candidate_spec.json")["candidate_id"]: path for path in pool}
             for role, pool in pools.items()}
    controls = pair_plan["candidate_mapping"]
    matching = [row for row in controls
                if row["original_candidate_id"] in by_id["original"]
                and row["counterfactual_candidate_id"] in by_id["counterfactual"]]
    original_pool = [by_id["original"][row["original_candidate_id"]] for row in matching]
    counterpart = {by_id["original"][row["original_candidate_id"]]:
                   by_id["counterfactual"][row["counterfactual_candidate_id"]] for row in matching}
    original_subsets = find_significant_subsets(
        original_pool, profile, rng, num_choices=num_choices, question_type=question_type,
        selection_metric=specs["original"]["selection_metric"], quality=quality)
    selected = None
    for original in original_subsets:
        counter = [counterpart[path] for path in original]
        if find_significant_subsets(
            counter, profile, rng, num_choices=num_choices, question_type=question_type,
            selection_metric=specs["counterfactual"]["selection_metric"], quality=quality,
        ):
            selected = {"original": original, "counterfactual": counter}
            break
    if selected is None:
        raise RuntimeError("Failed to find significant matched candidate subset on both pair members")

    results = []
    records = {}
    for role in ("original", "counterfactual"):
        run_name = make_run_name(num_questions=1, num_choices=num_choices,
                                 candidate_set_names=[candidate_set_paths[role].name],
                                 salt={"pair_id": pair_plan["pair_id"], "role": role, "split": split})
        run_path = question_run_dir(dataset_paths[role], run_name)
        run_path.mkdir(parents=True, exist_ok=False)
        record, output = _write_question(
            profile, dataset_spec=specs[role], dataset_path=dataset_paths[role],
            candidate_paths=selected[role], candidate_set_paths=[candidate_set_paths[role]],
            run_path=run_path, run_name=run_name, rng=rng, quality=quality,
            artifact_root=artifact_root, split=split)
        write_run_manifest(run_path, run_name=run_name, profile=profile,
                           dataset_id=specs[role]["dataset_id"], family=specs[role]["family"],
                           candidate_set_paths=[candidate_set_paths[role]], num_questions=1,
                           num_choices=num_choices, seed=pair_plan["seed"],
                           question_ids=[record["question_id"]], artifact_root=artifact_root)
        records[role] = record
        results.append((record, output))
    letters = {role: {choice["candidate_id"]: choice["letter"] for choice in record["choices"]}
               for role, record in records.items()}
    mapping = [{**row, "original_letter": letters["original"][row["original_candidate_id"]],
                "counterfactual_letter": letters["counterfactual"][row["counterfactual_candidate_id"]]}
               for row in matching if row["original_candidate_id"] in letters["original"]]
    winners = {role: next(row["choice_identity"] for row in mapping
                         if row[role + "_letter"] == records[role]["correct_letter"])
               for role in records}
    pair = {"pair_id": pair_plan["pair_id"], "family": specs["original"]["family"],
            "split": split, "intervention": pair_plan["intervention"],
            "selection_history": "all_significant_pairs", "candidate_mapping": mapping}
    for role in records:
        pair[role + "_question"] = records[role]["question_id"]
        pair[role + "_dataset"] = specs[role]["dataset_id"]
    return pair, results, winners["original"] != winners["counterfactual"]
