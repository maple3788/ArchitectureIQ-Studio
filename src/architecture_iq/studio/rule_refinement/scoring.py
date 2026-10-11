"""Whole-batch prediction seals, followed by stored-GT-only research scoring."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Callable

from architecture_iq.kb.evaluation import decisive_pairs
from architecture_iq.kb.roles import exclusive_lock, _seal, read_receipt
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from .artifacts import validate_snapshot
from .contracts import PREDICTOR_VERSION, artifact_path, identifier, validate_pool
from .prediction import predict_batch


def _save_sealed(root, reference, record, *, kind):
    path = artifact_path(root, reference, kind=kind)
    value = _seal({**record, "receipt_ref": reference})
    with exclusive_lock(Path(root) / "scoring.lock"):
        if path.exists():
            if read_receipt(path) != value:
                raise ValueError("Sealed artifact cannot be overwritten")
        else:
            write_json_atomic(path, value)
    return value


def seal_predictions(root: Path, *, batch_id: str, pool: dict, kb: dict, predictions: list[dict]) -> dict:
    validate_pool(pool)
    validate_snapshot(kb)
    cases = [m["case"] for m in pool["members"]]
    # A deterministic receipt cannot certify an arbitrary client-supplied answer.
    if predictions != predict_batch(cases, kb):
        raise ValueError("Incomplete or altered deterministic predictions")
    return _save_sealed(root, f"predictions/{identifier(batch_id)}.json",
                        {"batch_id": batch_id, "pool_version": pool["version"], "kb": deepcopy(kb),
                         "predictor_version": PREDICTOR_VERSION,
                         "question_refs": [deepcopy(m["ref"]) for m in pool["members"]],
                         "predictions": deepcopy(predictions)}, kind="predictions")


def _problem(kind, member, **extra):
    value = {"type": kind, "question_ref": deepcopy(member["ref"]), **extra}
    return {**value, "case_ref": canonical_hash(value)}


def _feedback_for_objective(feedback, case):
    if not isinstance(feedback, dict):
        raise ValueError("Missing stored feedback")
    letters = {c["letter"] for c in case["question"]["choices"]}
    if feedback.get("correct_letter") not in letters:
        raise ValueError("No valid stored answer")
    metrics = feedback.get("candidate_metrics", {})
    if not isinstance(metrics, dict):
        raise ValueError("Invalid candidate metrics")
    ids = {c["id"] for c in case["question"]["choices"]}
    for cid, summary in metrics.items():
        if cid not in ids or not isinstance(summary, dict):
            raise ValueError("Metrics do not match the frozen candidates")
        declared = [summary[key] for key in ("metric", "selection_metric") if summary.get(key) is not None]
        if any(metric != case["objective"] for metric in declared):
            raise ValueError("Stored metric differs from public objective")
    return {k: deepcopy(feedback[k]) for k in ("correct_letter", "candidate_metrics", "higher_is_better")
            if k in feedback}


def score_sealed_batch(root: Path, *, prediction_receipt: str, pool: dict,
                       feedback_loader: Callable[[dict], dict]) -> dict:
    validate_pool(pool)
    sealed = read_receipt(artifact_path(root, prediction_receipt, kind="predictions"))
    if (sealed.get("receipt_ref") != prediction_receipt or sealed["pool_version"] != pool["version"]
            or sealed["predictor_version"] != PREDICTOR_VERSION
            or sealed["question_refs"] != [m["ref"] for m in pool["members"]]):
        raise ValueError("Prediction receipt does not belong to this pool")
    kb = sealed["kb"]
    validate_snapshot(kb)
    cases = [m["case"] for m in pool["members"]]
    predictions = sealed["predictions"]
    if predictions != predict_batch(cases, kb):
        raise ValueError("Prediction receipt does not match frozen public inputs")
    # No private loader has been invoked above this boundary.
    score = {"pool_version": pool["version"], "kb_version": kb["version"],
             "executable_hash": kb["executable_hash"], "predictor_version": PREDICTOR_VERSION,
             "prediction_receipt": prediction_receipt, "selected": len(cases), "scorable": 0,
             "unscorable": 0, "correct": 0, "answered": 0, "conflicts": 0, "wrong_assertions": 0,
             "all_pass": False, "per_question": {}, "per_rule": {}, "problems": [],
             "paired": {"total": len(pool["pairs"]), "both_correct": 0}}
    for rule in kb["rules"]:
        score["per_rule"][rule["rule_id"]] = {
            "revision": rule["revision"], "state": rule["state"], "applicable": 0, "correct": 0,
            "wrong": 0, "unknown": 0, "question_keys": [], "dataset_ids": [],
            "status": "retired" if rule["state"] == "retired" else "untested"}
    for member, prediction in zip(pool["members"], predictions):
        case, key = member["case"], member["ref"]["key"]
        row = {"question_ref": deepcopy(member["ref"]), "case": deepcopy(case),
               "prediction": deepcopy(prediction), "scorable": False, "correct": False,
               "answered": prediction["status"] == "answered", "assertions": [], "issues": []}
        score["per_question"][key] = row
        try:
            if prediction["status"] == "invalid":
                raise ValueError("Public specifications could not be executed")
            private = feedback_loader(deepcopy(member["ref"]))
            if canonical_hash(private) != member["feedback_hash"]:
                raise ValueError("Frozen feedback hash differs")
            feedback = _feedback_for_objective(private, case)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            score["unscorable"] += 1
            row["issues"].append({"code": "material_failure", "message": str(exc)})
            continue
        score["scorable"] += 1
        row.update(scorable=True, feedback=feedback)
        letters = {c["id"]: c["letter"] for c in case["question"]["choices"]}
        row["correct"] = row["answered"] and letters[prediction["answer_id"]] == feedback["correct_letter"]
        score["correct"] += int(row["correct"])
        score["answered"] += int(row["answered"])
        score["conflicts"] += int(prediction["status"] == "conflict")
        if not row["correct"]:
            kind = "wrong_answer" if row["answered"] else prediction["status"]
            score["problems"].append(_problem(kind, member))
        true_pairs = set(decisive_pairs(case["question"], feedback))
        for edge in prediction["edges"]:
            pair = (letters[edge["winner"]], letters[edge["loser"]])
            verdict = "correct" if pair in true_pairs else "wrong" if pair[::-1] in true_pairs else "unknown"
            for ref in edge["rules"]:
                evidence = score["per_rule"][ref["rule_id"]]
                if evidence["revision"] != ref["revision"] or evidence["state"] != "active":
                    raise ValueError("Prediction points to a different rule revision")
                evidence["applicable"] += 1
                evidence[verdict] += 1
                evidence["status"] = "research"
                if key not in evidence["question_keys"]:
                    evidence["question_keys"].append(key)
                dataset = case["question"].get("dataset_id")
                if dataset and dataset not in evidence["dataset_ids"]:
                    evidence["dataset_ids"].append(dataset)
                assertion = {"rule_ref": ref, "winner": edge["winner"], "loser": edge["loser"], "verdict": verdict}
                row["assertions"].append(assertion)
                if verdict == "wrong":
                    score["wrong_assertions"] += 1
                    score["problems"].append(_problem("rule_counterexample", member,
                        rule_ref=ref, winner=edge["winner"], loser=edge["loser"]))
    for pair in pool["pairs"]:
        keys = [m.get("key") for m in pair["members"]]
        if len(keys) == 2 and all(score["per_question"].get(k, {}).get("correct") for k in keys):
            score["paired"]["both_correct"] += 1
    score["all_pass"] = (score["selected"] > 0 and score["scorable"] == score["selected"]
                         and score["correct"] == score["selected"] and score["wrong_assertions"] == 0)
    score["accuracy"] = score["correct"] / score["scorable"] if score["scorable"] else None
    score["answer_coverage"] = score["answered"] / score["scorable"] if score["scorable"] else None
    reference = "scores/" + canonical_hash(score) + ".json"
    return _save_sealed(root, reference, score, kind="scores")
