"""Code checks a proposed or revised claim must pass before it is pre-registered.

- structure: rule keys, predicate shape and operators the DSL understands
- fields: only public candidate/dataset fields (no ids, seeds or results)
- simplicity: at most ``max_rules`` rules and ``max_conditions`` condition leaves per rule
- breadth: applies to enough historical questions, and is right on most of them
- novelty: does not duplicate an active claim's predictions
- regression (revisions only): no question the previous version got right turns wrong; a revision
  may drop questions out of its scope, but must keep at least ``min_coverage_kept`` of the previous
  version's applicable questions and reach the revision support rate on history
"""

from __future__ import annotations

import math
from typing import Any

from kb_loop.evidence import score_records

CANDIDATE_FIELDS = {
    "budget", "batch_size", "steps", "model_type", "params", "depth", "width", "residual", "activation",
    "smooth_activation", "ln_count", "ln_any", "ln_all", "num_layers", "d_model", "d_ff", "num_heads",
    "layer_residual", "opt", "adaptive", "sign_normalized", "lr", "weight_decay", "momentum", "beta1", "beta2",
    "eff_lr", "disp", "per_step", "arch_key", "opt_key",
}
DATASET_FIELDS = {
    "family", "task", "metric", "input_dim", "rule_family", "n_active_features", "spiral_turns", "vocab_size",
    "context_length", "train_size", "target_abs_mean", "target_std", "target_oscillatory", "n_used_inputs",
    "transition_alpha",
}
ALLOWED_FIELDS = CANDIDATE_FIELDS | DATASET_FIELDS
OPS = {"eq", "ne", "lt", "le", "gt", "ge", "in", "nin"}
RULE_KEYS = {"scope", "same", "differ", "max_param_ratio", "predict"}


class CheckError(ValueError):
    pass


def _leaves(pred: Any) -> list[list[Any]]:
    if not pred:
        return []
    if isinstance(pred, list):
        if pred and isinstance(pred[0], str):
            if len(pred) != 3:
                raise CheckError(f"predicate leaf must be [field, op, value]: {pred!r}")
            return [pred]
        return [leaf for p in pred for leaf in _leaves(p)]
    if isinstance(pred, dict):
        if len(pred) != 1 or next(iter(pred)) not in ("all", "any", "not"):
            raise CheckError(f"bad predicate {pred!r}")
        key, val = next(iter(pred.items()))
        return _leaves(val) if key != "not" else _leaves(val)
    raise CheckError(f"bad predicate {pred!r}")


def _check_field(field: Any) -> None:
    if not isinstance(field, str):
        raise CheckError(f"field must be a name, got {field!r}")
    if field not in ALLOWED_FIELDS:
        raise CheckError(f"field {field!r} is not a public candidate or dataset field")


def rule_conditions(rule: dict[str, Any]) -> int:
    """Condition leaves of one rule: scope plus the predicates naming winner/loser sides."""
    pred = rule.get("predict", {})
    n = len(_leaves(rule.get("scope")))
    for key in ("better", "worse", "winner", "loser"):
        n += len(_leaves(pred.get(key)))
    return n


def check_structure(rules: Any, cfg: dict[str, Any]) -> None:
    if not isinstance(rules, list) or not rules:
        raise CheckError("rules must be a non-empty list")
    if len(rules) > cfg.get("max_rules", 3):
        raise CheckError(f"{len(rules)} rules; at most {cfg.get('max_rules', 3)}")
    for rule in rules:
        if not isinstance(rule, dict) or "predict" not in rule:
            raise CheckError("each rule needs a predict")
        extra = set(rule) - RULE_KEYS
        if extra:
            raise CheckError(f"unknown rule keys {sorted(extra)}")
        for leaf in _leaves(rule.get("scope")):
            _check_field(leaf[0])
            if leaf[1] not in OPS:
                raise CheckError(f"unknown operator {leaf[1]!r}")
        for key in ("same", "differ"):
            for field in rule.get(key, []):
                _check_field(field)
        if "max_param_ratio" in rule and not isinstance(rule["max_param_ratio"], (int, float)):
            raise CheckError("max_param_ratio must be a number")
        pred = rule["predict"]
        forms = [k for k in ("better", "dominates", "higher_better", "lower_better") if k in pred]
        if len(forms) != 1:
            raise CheckError(f"predict needs exactly one of better/dominates/higher_better/lower_better: {pred!r}")
        if "better" in pred and "worse" not in pred:
            raise CheckError("better needs worse")
        if "dominates" in pred:
            for axis in pred["dominates"]:
                _check_field(axis[0])
                if axis[1] not in ("higher", "lower"):
                    raise CheckError(f"dominates axis direction must be higher/lower: {axis!r}")
        for key in ("higher_better", "lower_better"):
            if key in pred:
                _check_field(pred[key])
        for key in ("better", "worse", "winner", "loser"):
            for leaf in _leaves(pred.get(key)):
                _check_field(leaf[0])
                if leaf[1] not in OPS:
                    raise CheckError(f"unknown operator {leaf[1]!r}")
        if rule_conditions(rule) > cfg["max_conditions"]:
            raise CheckError(f"rule has {rule_conditions(rule)} conditions; at most {cfg['max_conditions']}")


def history_requirement(cfg: dict[str, Any], n_records: int) -> int:
    return max(1, min(cfg["min_history_applicable"], math.ceil(0.1 * n_records)))


def check_history(verdicts: dict[str, dict[str, Any]], cfg: dict[str, Any], n_records: int,
                  min_rate: float) -> dict[str, Any]:
    need = history_requirement(cfg, n_records)
    n = len(verdicts)
    s = sum(v["outcome"] == "support" for v in verdicts.values())
    if n < need:
        raise CheckError(f"applies to {n} historical questions; needs {need}")
    if s / n < min_rate:
        raise CheckError(f"historical support {s}/{n} below {min_rate}")
    conflicts = sum(v["conflicts"] for v in verdicts.values())
    if conflicts:
        raise CheckError(f"its own rules disagree on {conflicts} comparisons")
    return {"history_applicable": n, "history_support": s}


def _pair_preds(verdicts: dict[str, dict[str, Any]]) -> dict[tuple[str, str, str], bool]:
    return {(q, b, w): ok for q, v in verdicts.items() for b, w, ok in v["pairs"]}


def check_novelty(verdicts: dict[str, dict[str, Any]], others: dict[str, dict[str, dict[str, Any]]],
                  cfg: dict[str, Any]) -> None:
    mine = _pair_preds(verdicts)
    if not mine:
        return
    # A narrow claim whose few comparisons all sit inside an existing claim, predicted the same way, adds nothing.
    need = min(cfg.get("duplicate_min_shared", 10), len(mine))
    for cid, other in others.items():
        theirs = _pair_preds(other)
        shared = mine.keys() & theirs.keys()
        if len(shared) < need or len(shared) < 0.8 * len(mine):
            continue
        agree = sum(mine[k] == theirs[k] for k in shared) / len(shared)
        if agree >= cfg["duplicate_agreement"]:
            raise CheckError(f"duplicates {cid}: same prediction on {agree:.0%} of {len(shared)} shared comparisons")


def check_regression(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> None:
    flipped = [q for q, v in old.items() if v["outcome"] == "support" and new.get(q, {}).get("outcome") == "refute"]
    if flipped:
        raise CheckError(f"now wrong on {len(flipped)} questions the previous version got right")
    if len(new) < cfg["min_coverage_kept"] * len(old):
        raise CheckError(f"coverage fell from {len(old)} to {len(new)} questions")


def check_claim(rules: list[dict[str, Any]], records: list[dict[str, Any]], others: dict[str, dict[str, dict[str, Any]]],
                cfg: dict[str, Any], min_rate: float, previous: dict[str, dict[str, Any]] | None = None,
                min_gap: float = 0.0, winner_only: bool = False) -> dict[str, Any]:
    """Run every check; raise CheckError with the first failure. Returns history stats."""
    try:
        check_structure(rules, cfg)
    except CheckError:
        raise
    except (TypeError, KeyError, IndexError, AttributeError, ValueError) as exc:
        # Model output that is not even shaped like a rule is a rejection, never a crash.
        raise CheckError(f"malformed rule: {exc!r}") from exc
    try:
        verdicts = score_records(rules, records, min_gap, winner_only)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise CheckError(f"rule fails to evaluate: {exc!r}") from exc
    if previous is not None:
        check_regression(previous, verdicts, cfg)
    stats = check_history(verdicts, cfg, len(records), min_rate)
    check_novelty(verdicts, others, cfg)
    return stats
