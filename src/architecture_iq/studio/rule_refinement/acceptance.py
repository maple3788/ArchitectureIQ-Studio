"""Pure, same-pool nonregression decisions for candidate rule versions."""
from __future__ import annotations


def advance_protection(protected_keys: list[str], accepted_score: dict) -> list[str]:
    if not isinstance(protected_keys, list) or any(not isinstance(k,str) for k in protected_keys):
        raise ValueError("Protected questions must be exact keys")
    questions = accepted_score["per_question"]
    if set(protected_keys) - set(questions):
        raise ValueError("Protected question is absent from the frozen pool")
    return sorted(set(protected_keys) | {key for key,row in questions.items()
                                        if row["scorable"] and row["correct"]})


def compare_candidate(before: dict, after: dict, *, protected_keys: list[str]) -> dict:
    for field in ("pool_version", "predictor_version"):
        if before[field] != after[field]:
            raise ValueError("Candidate comparison requires the same pool and predictor")
    old, new = before["per_question"], after["per_question"]
    if set(old) != set(new) or any(old[key]["question_ref"] != new[key]["question_ref"] for key in old):
        raise ValueError("Candidate comparison requires identical question/GT references")
    # Pool version binds each member's stored GT hash; never compare two different pools.
    protected = advance_protection(protected_keys, before)
    decision = {"accepted": False, "reason": "no_progress", "before_score": before["receipt_ref"],
                "after_score": after["receipt_ref"], "protected_keys": protected,
                "newly_correct": [], "regressed": []}
    if any(score["selected"] == 0 or score["unscorable"] != 0 or score["scorable"] != score["selected"]
           or len(score["per_question"]) != score["selected"]
           or not all(row["scorable"] for row in score["per_question"].values()) for score in (before,after)):
        return {**decision, "reason": "incomplete_pool"}
    regressed = [key for key in protected if not new[key]["correct"]]
    if regressed:
        return {**decision, "reason": "regression", "regressed": regressed}
    if before["executable_hash"] == after["executable_hash"]:
        return decision
    if after["correct"] == before["correct"] and after["answered"] < before["answered"]:
        return {**decision, "reason": "reduced_answer_coverage"}
    def priority(score):
        return (score["correct"], -score["conflicts"], -score["wrong_assertions"], score["answered"])
    if priority(after) <= priority(before):
        return decision
    return {**decision, "accepted": True, "reason": "improved",
            "newly_correct": sorted(key for key,row in new.items() if row["correct"] and not old[key]["correct"]),
            "protected_keys": advance_protection(protected, after)}
