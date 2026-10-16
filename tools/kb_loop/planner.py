"""Plan one round: which v1.5 questions to build.

Explore items follow the main500 mix (family weights, question types, budgets,
family options cycling) and are never steered. Target items feed claims that
need evidence: the planner picks a family, question type, budget and family
options the claim's scope allows; the builder then picks a dataset instance and
one of the valid three-way subsets the claim applies to (``questions.build_one``).
Every target question is still built and filtered by the unchanged v1.5 rules.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

from kb_claim_pairwise_eval import holds
from kb_loop.checks import _leaves
from kb_loop.questions import BUDGETS, FAMILY_WEIGHTS, QUESTION_TYPES, family_options

MODEL_FIELDS = {"params", "depth", "width", "residual", "activation", "smooth_activation", "ln_count", "ln_any",
                "ln_all", "num_layers", "d_model", "d_ff", "num_heads", "layer_residual", "arch_key", "model_type"}
OPT_FIELDS = {"opt", "adaptive", "sign_normalized", "lr", "weight_decay", "momentum", "beta1", "beta2", "eff_lr",
              "disp", "per_step", "opt_key", "batch_size", "steps"}


def predict_fields(rules: list[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for rule in rules:
        pred = rule["predict"]
        fields |= {pred[k] for k in ("higher_better", "lower_better") if k in pred}
        fields |= {axis[0] for axis in pred.get("dominates", [])}
        for key in ("better", "worse", "winner", "loser"):
            fields |= {leaf[0] for leaf in _leaves(pred.get(key))}
        fields |= set(rule.get("differ", []))
    return fields


def claim_kind(rules: list[dict[str, Any]]) -> str:
    f = predict_fields(rules)
    model, opt = bool(f & MODEL_FIELDS), bool(f & OPT_FIELDS)
    if model and opt:
        return "mixed"
    return "architecture" if model else "optimizer" if opt else "mixed"


TYPES_FOR_KIND = {"architecture": ("architecture_only", "mixed"), "optimizer": ("optimizer_only", "mixed"),
                  "mixed": ("mixed",)}


def _families_in_scope(rules: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[str]:
    fams = set()
    for rec in records:
        if any(all(holds(r.get("scope"), v) for v in rec["candidates"].values()) for r in rules):
            fams.add(rec["family"])
    return sorted(fams)


def required_leaves(scope: Any) -> list[list[Any]]:
    """Leaves a scope requires outright (top-level conjunction and "all"); "any" / "not" parts are skipped."""
    if not scope:
        return []
    if isinstance(scope, list):
        if isinstance(scope[0], str):
            return [scope]
        return [leaf for p in scope for leaf in required_leaves(p)]
    if isinstance(scope, dict) and "all" in scope:
        return required_leaves(scope["all"])
    return []


def allows(leaves: list[list[Any]], field: str, value: Any) -> bool:
    """Every required leaf on ``field`` accepts ``value`` (no leaf on it: anything goes)."""
    return all(holds(leaf, {field: value}) for leaf in leaves if leaf[0] == field)


def steered_setup(rule: dict[str, Any], family: str, steps_by_budget: dict[int, set[int]],
                  rng: random.Random) -> tuple[int, dict[str, Any]]:
    """Budget and family options the rule's scope allows (random among them; unconstrained if none fit)."""
    leaves = required_leaves(rule.get("scope"))
    has_steps = any(leaf[0] == "steps" for leaf in leaves)
    budgets = [b for b in BUDGETS if allows(leaves, "budget", b)
               and (not has_steps or any(allows(leaves, "steps", st) for st in steps_by_budget.get(b, ())))]
    budget = rng.choice(budgets or list(BUDGETS))
    choices = rng.sample(range(1000), 200)
    fits = [j for j in choices if all(allows(leaves, f, v) for f, v in family_options(family, j).items())]
    return budget, family_options(family, (fits or choices)[0])


def explore_item(i: int, counter: Counter) -> dict[str, Any]:
    weighted = [f for f, w in FAMILY_WEIGHTS for _ in range(w)]
    family = weighted[i % len(weighted)]
    j = counter[family]
    counter[family] += 1
    return {"family": family, "question_type": QUESTION_TYPES[j % len(QUESTION_TYPES)],
            "budget": BUDGETS[(j // len(QUESTION_TYPES)) % len(BUDGETS)], "family_options": family_options(family, j)}


def target_order(claims: dict[str, dict[str, Any]], ledger_counts: Counter, round_no: int) -> list[str]:
    """Claims needing evidence first: thin candidates, fresh revisions, flagged, then verified."""
    def key(cid: str) -> tuple:
        c = claims[cid]
        n = ledger_counts[(cid, c["version"])]
        tier = {"candidate": 0, "flagged": 1, "verified": 2}[c["status"]]
        return (tier, n)

    return sorted((cid for cid, c in claims.items() if c["status"] != "retired"), key=key)


def plan_round(round_no: int, claims: dict[str, dict[str, Any]], ledger: list[dict[str, Any]],
               records: list[dict[str, Any]], n_total: int, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rng = random.Random(cfg["seed_base"] + round_no)
    counts = Counter((r["claim_id"], r["version"]) for r in ledger if r["round"] > claims.get(r["claim_id"], {}).get("registered_round", -1))
    order = target_order(claims, counts, round_no)
    n_target = round(n_total * cfg["target_fraction"]) if order else 0
    items: list[dict[str, Any]] = []
    explore_counter: Counter = Counter()
    explore_counter.update({f: round_no * 7 for f, _ in FAMILY_WEIGHTS})  # rotate options/budgets across rounds
    steps_by_budget: dict[int, set[int]] = {}
    for rec in records:
        for v in rec["candidates"].values():
            if v.get("budget") and v.get("steps"):
                steps_by_budget.setdefault(v["budget"], set()).add(v["steps"])
    for i in range(n_total):
        if i < n_target:
            cid = order[i % len(order)]
            c = claims[cid]
            fams = _families_in_scope(c["rules"], records) or [f for f, _ in FAMILY_WEIGHTS]
            family = rng.choice(fams)
            qtype = rng.choice(TYPES_FOR_KIND[claim_kind(c["rules"])])
            budget, options = steered_setup(rng.choice(c["rules"]), family, steps_by_budget, rng)
            item = {"family": family, "question_type": qtype, "budget": budget,
                    "family_options": options, "purpose": "target", "targets": [cid]}
        else:
            item = {**explore_item(i, explore_counter), "purpose": "explore", "targets": []}
        item["item_id"] = f"r{round_no:04d}-{i:04d}"
        item["seed_base"] = cfg["seed_base"] + round_no * cfg["seed_stride"] + i * 101
        items.append(item)
    return items
