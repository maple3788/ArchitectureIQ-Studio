"""Pure public/private input checks shared by preflight and native preparation."""
from __future__ import annotations

import copy

from .rules import CONTROL_FIELDS


def is_basic_learning(config: dict) -> bool:
    method = config.get("method")
    return isinstance(method, dict) and method.get("id") == "basic_learning" and method.get("version") == "1"


def validate_public_inputs(config: dict, public_questions: list[dict], private_feedback: dict) -> list[dict]:
    """Return a normalized copy without creating a run, KB, or model request."""
    if not isinstance(public_questions, list) or not isinstance(private_feedback, dict):
        raise ValueError("Public questions must be a list and private feedback an object")
    questions, lineages, datasets, pairs, ids = [], {}, {}, {}, set()
    basic = is_basic_learning(config)
    needed = 1 if basic else config["max_rounds"] * config["discovery_per_round"]
    for raw in public_questions:
        if not isinstance(raw, dict):
            raise ValueError("Public question must be an object")
        allowed = {
            "id",
            "family",
            "dataset_id",
            "lineage_id",
            "prompt",
            "choices",
            "split",
            "pair_id",
            "profile_hash",
        }
        if set(raw) - allowed:
            raise ValueError("Public question contains non-whitelisted fields")
        question = copy.deepcopy(raw)
        for key in ("id", "family", "dataset_id", "lineage_id", "prompt"):
            if not isinstance(question.get(key), str) or not question[key]:
                raise ValueError(f"Question requires {key}")
        if question["id"] in ids:
            raise ValueError("Duplicate question ID")
        ids.add(question["id"])
        split = question.setdefault("split", "discovery")
        if split not in ("discovery", "development", "final"):
            raise ValueError("Invalid question split")
        lineage = question["lineage_id"]
        if lineage in lineages and lineages[lineage] != split:
            raise ValueError("A lineage cannot cross data splits")
        lineages[lineage] = split
        dataset = question["dataset_id"]
        if dataset in datasets and datasets[dataset] != split:
            raise ValueError("A dataset cannot cross data splits using lineage aliases")
        datasets[dataset] = split
        pair = question.get("pair_id")
        if pair is not None:
            if not isinstance(pair, str) or not pair:
                raise ValueError("Invalid DataFlip pair identity")
            if pair in pairs and pairs[pair] != split:
                raise ValueError("A DataFlip pair cannot cross data splits")
            pairs[pair] = split
        choices = question.get("choices")
        if not isinstance(choices, list) or any(not isinstance(c, dict) or not isinstance(c.get("letter"), str) or not c["letter"] for c in choices):
            raise ValueError("Invalid public choice shape")
        if len(choices) < 3 or len({c["letter"] for c in choices}) != len(choices):
            raise ValueError("Need at least three distinct choice letters")
        for choice in choices:
            if set(choice) != {"id", "letter", "view"} or not isinstance(
                choice["view"], dict
            ):
                raise ValueError("Invalid public choice shape")
            if set(choice["view"]) - CONTROL_FIELDS or any(
                v is not None and type(v) not in (str, int, float, bool)
                for v in choice["view"].values()
            ):
                raise ValueError("Non-public field or nested value in public view")
        if (
            len(question["prompt"].encode()) + config["model"]["max_tokens"] + 1024
            > config["context_size"]
        ):
            raise ValueError("Public question exceeds conservative context budget")
        if question["id"] not in private_feedback:
            raise ValueError("Missing private feedback")
        if not isinstance(private_feedback[question["id"]], dict) or private_feedback[question["id"]].get("correct_letter") not in {
            c["letter"] for c in choices
        }:
            raise ValueError("Private answer must identify an existing choice")
        questions.append(question)
    discovery = [q for q in questions if q["split"] == "discovery"]
    # pair_id records source provenance; only an explicit pair_manifest selects
    # the paired protocol. A single selected member retains its lineage.
    if basic and (len(questions) != 1 or len(discovery) != 1):
        raise ValueError("basic_learning requires exactly one discovery question")
    if len(discovery) < needed:
        raise ValueError(f"Need {needed} discovery questions for configured rounds")
    return questions
