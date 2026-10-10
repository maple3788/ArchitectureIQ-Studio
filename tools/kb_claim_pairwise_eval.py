#!/usr/bin/env python3
"""Check structured KB claims against candidate-pair ground truth.

A KB claim is compiled (outside this tool, without GT) into one or more
pairwise rules. Each rule names a scope both candidates must satisfy, the
fields that must be equal across the pair (ceteris paribus), and a prediction:

  {"better": P, "worse": Q}        the candidate matching P beats the one matching Q
  {"higher_better": "field"}       the candidate with the larger field value wins
  {"lower_better": "field"}        the candidate with the smaller field value wins
  {"dominates": [[f, "higher"|"lower"(, min_ratio)], ...], "winner": P, "loser": Q}
                                   the Pareto-better candidate on those axes wins

Predicate leaves are ``[field, op, value]`` with op in eq|ne|lt|le|gt|ge|in|nin;
a list of predicates is a conjunction, and {"all": [...]}, {"any": [...]},
{"not": P} combine them. Fields are the flat candidate view built by
``candidate_view``.

Every unordered pair of candidates inside one candidate set is a potential
experiment: same dataset instance, same total_samples_seen. GT comes only from
the stored ``results/summary.json`` written by the canonical GT runner. A pair
is *decisive* under the v1.5 criterion when it fully separates: the winner's
worst seed beats the loser's best seed. Rules are scored on decisive pairs;
mean-order agreement over all applicable pairs is reported alongside.

Usage:
  python tools/kb_claim_pairwise_eval.py \\
      --datasets-root data/datasets \\
      --rules configs/kb_claim_rules/kb_0008_evidence_ge1.json \\
      --kb-snapshot data/kb_0008.json \\
      --out data/evals/kb_claim_pairwise/kb_0008
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

LOWER_IS_BETTER = {"test_mse": True, "test_ce": True}
TASK_BY_FAMILY = {
    "univariate_regression": "regression",
    "multivariate_regression": "regression",
    "bigram_lm": "lm",
    "spiral_classification": "classification",
    "xor_classification": "classification",
    "synthetic_tabular_classification": "classification",
}
SIGN_NORMALIZED = {"Adam", "AdamW"}


# ---------------------------------------------------------------- dataset view


def _target_stats(params: dict[str, Any]) -> tuple[float | None, float | None]:
    """Monte Carlo |E[y]| and std(y) of a symbolic regression target on its domain."""
    expr = params.get("expression")
    if not expr:
        return None, None
    lo, hi = params.get("domain", [0.0, 1.0])
    names = sorted(set(re.findall(r"\bx\d*\b", expr)), key=lambda s: (len(s), s))
    env = {n: getattr(math, n) for n in ("sin", "cos", "tanh", "exp", "log", "sqrt", "pi")}
    env["abs"] = abs
    code = compile(expr, "<target>", "eval")
    rng = random.Random(0)
    ys = []
    for _ in range(4096):
        local = {n: rng.uniform(lo, hi) for n in names}
        ys.append(float(eval(code, {"__builtins__": {}}, {**env, **local})))
    mean = sum(ys) / len(ys)
    std = math.sqrt(sum((y - mean) ** 2 for y in ys) / len(ys))
    return abs(mean), std


def dataset_view(spec: dict[str, Any]) -> dict[str, Any]:
    params = spec.get("params", {})
    abs_mean, std = _target_stats(params)
    expr = params.get("expression") or ""
    return {
        "family": spec["family"],
        "task": TASK_BY_FAMILY.get(spec["family"]),
        "metric": spec["selection_metric"],
        "input_dim": params.get("input_dim", 1 if spec["family"] == "univariate_regression" else None),
        "rule_family": params.get("rule_family"),
        "n_active_features": len(params["active_features"]) if "active_features" in params else None,
        "spiral_turns": params.get("spiral_turns") if params.get("rule_family") == "spiral" else None,
        "vocab_size": params.get("vocab_size"),
        "context_length": params.get("context_length"),
        "train_size": params.get("train_size"),
        "target_abs_mean": abs_mean,
        "target_std": std,
        "target_oscillatory": ("sin(" in expr or "cos(" in expr) if expr else None,
    }


# -------------------------------------------------------------- candidate view


def candidate_view(spec: dict[str, Any], ds: dict[str, Any]) -> dict[str, Any]:
    m, o, b = spec["model"], spec["optimizer"], spec["budget"]
    steps = int(b["training_steps"])
    lr = float(o["lr"])
    opt = o["type"]
    momentum = float(o.get("momentum", 0.0)) if opt == "SGD" else None
    betas = o.get("betas")
    if opt in SIGN_NORMALIZED or opt == "RMSprop":
        disp = lr * steps
    elif opt == "Adagrad":
        disp = 2.0 * lr * math.sqrt(steps)
    else:  # SGD displacement depends on gradient scale; no spec-only proxy
        disp = None
    norms = m.get("layer_norm") or []
    view = dict(ds)
    view.update(
        {
            "budget": int(b["total_samples_seen"]),
            "batch_size": int(b["batch_size"]),
            "steps": steps,
            "model_type": m["type"],
            "params": spec.get("trainable_parameter_count"),
            "depth": m.get("depth"),
            "width": m.get("width"),
            "residual": m.get("residual"),
            "activation": m.get("activation"),
            "smooth_activation": m.get("activation") in ("gelu", "silu") if "activation" in m else None,
            "ln_count": sum(bool(v) for v in norms) if m["type"] == "mlp" else None,
            "ln_any": any(norms) if m["type"] == "mlp" else None,
            "ln_all": (all(norms) and bool(norms)) if m["type"] == "mlp" else None,
            "num_layers": m.get("num_layers"),
            "d_model": m.get("d_model"),
            "d_ff": m.get("d_ff"),
            "num_heads": m.get("num_heads"),
            "layer_residual": m.get("layer_residual"),
            "opt": opt,
            "adaptive": opt != "SGD",
            "sign_normalized": opt in SIGN_NORMALIZED,
            "lr": lr,
            "weight_decay": float(o.get("weight_decay", 0.0)),
            "momentum": momentum,
            "beta1": float(betas[0]) if betas else None,
            "beta2": float(betas[1]) if betas else None,
            # lr / (1 - m) for SGD, nominal lr otherwise
            "eff_lr": lr / (1.0 - momentum) if momentum is not None else lr,
            # Spec-only cumulative displacement proxy used by several claims.
            "disp": disp,
            # Average per-step size: Adagrad's decayed 2*lr/sqrt(T), SGD's lr/(1-m).
            "per_step": 2.0 * lr / math.sqrt(steps) if opt == "Adagrad" else (
                lr / (1.0 - momentum) if momentum is not None else lr
            ),
            # Identity keys for "everything else equal" constraints.
            "arch_key": json.dumps(
                {k: v for k, v in m.items() if k not in ("input_dim", "output_dim")}, sort_keys=True
            ),
            "opt_key": json.dumps(o, sort_keys=True),
        }
    )
    return view


# ------------------------------------------------------------------ predicates

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "in": lambda a, b: a in b,
    "nin": lambda a, b: a not in b,
}


def holds(pred: dict[str, Any] | None, view: dict[str, Any]) -> bool:
    """Evaluate a predicate; a missing (None) field never satisfies a leaf.

    A leaf is ``[field, op, value]``; a list of predicates is a conjunction.
    """
    if not pred:
        return True
    if isinstance(pred, list):
        if isinstance(pred[0], str):
            field, op, value = pred
        else:
            return all(holds(p, view) for p in pred)
    elif "all" in pred:
        return all(holds(p, view) for p in pred["all"])
    elif "any" in pred:
        return any(holds(p, view) for p in pred["any"])
    elif "not" in pred:
        return not holds(pred["not"], view)
    else:
        raise ValueError(f"bad predicate {pred!r}")
    if field not in view:
        raise KeyError(f"unknown field {field!r}")
    actual = view[field]
    if actual is None:
        return False
    if op in ("lt", "le", "gt", "ge") and isinstance(actual, (int, float)):
        # Grid values are logged floats; compare with a relative tolerance.
        if math.isclose(float(actual), float(value), rel_tol=1e-9):
            return op in ("le", "ge")
    return _OPS[op](actual, value)


def _dominates(pred: dict[str, Any], winner: dict[str, Any], loser: dict[str, Any]) -> bool:
    """winner Pareto-dominates loser on the listed (field, "higher"|"lower"[, min_ratio]) axes.

    At least as good on every axis and strictly better on one; an axis with a
    min_ratio must be strictly better by at least that factor.
    """
    if not (holds(pred.get("winner"), winner) and holds(pred.get("loser"), loser)):
        return False
    strict = False
    for axis in pred["dominates"]:
        field, direction = axis[0], axis[1]
        min_ratio = float(axis[2]) if len(axis) > 2 else None
        vw, vl = winner[field], loser[field]
        if vw is None or vl is None:
            return False
        better, worse = (vw, vl) if direction == "higher" else (vl, vw)
        if better < worse:
            return False
        if min_ratio is not None:
            if worse <= 0 or better / worse < min_ratio:
                return False
            strict = True
        elif better > worse:
            strict = True
    return strict


def predicted_winner(rule: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> int | None:
    """Return 0 if rule predicts a wins, 1 if b wins, None if the rule does not apply."""
    if not (holds(rule.get("scope"), a) and holds(rule.get("scope"), b)):
        return None
    for field in rule.get("same", []):
        if a[field] != b[field]:
            return None
    for field in rule.get("differ", []):
        if a[field] == b[field]:
            return None
    pred = rule["predict"]
    if "better" in pred:
        ab = holds(pred["better"], a) and holds(pred["worse"], b)
        ba = holds(pred["better"], b) and holds(pred["worse"], a)
        if ab == ba:
            return None
        return 0 if ab else 1
    if "dominates" in pred:
        ab = _dominates(pred, a, b)
        ba = _dominates(pred, b, a)
        if ab == ba:
            return None
        return 0 if ab else 1
    field = pred.get("higher_better") or pred.get("lower_better")
    va, vb = a[field], b[field]
    if va is None or vb is None or va == vb:
        return None
    min_ratio = float(pred.get("min_ratio", 1.0))
    if min(va, vb) > 0 and max(va, vb) / min(va, vb) < min_ratio:
        return None
    a_higher = va > vb
    if "higher_better" in pred:
        return 0 if a_higher else 1
    return 1 if a_higher else 0


# ------------------------------------------------------------------ GT loading


def _seed_values(summary: dict[str, Any], metric: str) -> list[float]:
    lower = LOWER_IS_BETTER[metric]
    bad = math.inf if lower else -math.inf
    return [bad if r["failed"] else float(r[f"final_{metric}"]) for r in summary["seed_results"]]


def load_sets(datasets_root: Path) -> list[dict[str, Any]]:
    sets = []
    ds_cache: dict[Path, dict[str, Any]] = {}
    for set_path in sorted(datasets_root.glob("*/*/candidates/*/set.json")):
        ds_dir = set_path.parents[2]
        if ds_dir not in ds_cache:
            ds_cache[ds_dir] = dataset_view(json.loads((ds_dir / "dataset_spec.json").read_text()))
        ds = ds_cache[ds_dir]
        set_meta = json.loads(set_path.read_text())
        cands = []
        for spec_path in sorted(set_path.parent.glob("c_*/candidate_spec.json")):
            summary_path = spec_path.parent / "results" / "summary.json"
            if not summary_path.exists():
                continue
            summary = json.loads(summary_path.read_text())
            if summary.get("excluded"):
                continue
            spec = json.loads(spec_path.read_text())
            metric = ds["metric"]
            cands.append(
                {
                    "id": spec["candidate_id"],
                    "view": candidate_view(spec, ds),
                    "mean": float(summary[f"mean_{metric}"]),
                    "seeds": _seed_values(summary, metric),
                    "seed_ids": [r["seed"] for r in summary["seed_results"]],
                }
            )
        sets.append(
            {
                "set_id": set_meta["set_id"],
                "dataset_id": set_meta["dataset_id"],
                "family": set_meta["family"],
                "varying_axes": set_meta["varying_axes"],
                "metric": ds["metric"],
                "candidates": cands,
            }
        )
    return sets


def pair_outcome(a: dict[str, Any], b: dict[str, Any], metric: str) -> dict[str, Any]:
    """GT relation of a vs b: mean winner and whether the seed ranges separate."""
    lower = LOWER_IS_BETTER[metric]
    sign = 1.0 if lower else -1.0
    ma, mb = sign * a["mean"], sign * b["mean"]
    mean_winner = None if ma == mb else (0 if ma < mb else 1)
    sa = [sign * v for v in a["seeds"]]
    sb = [sign * v for v in b["seeds"]]
    separated = None
    if a["seed_ids"] == b["seed_ids"]:
        if max(sa) < min(sb):
            separated = 0
        elif max(sb) < min(sa):
            separated = 1
    return {"mean_winner": mean_winner, "separated_winner": separated}


# -------------------------------------------------------------------- scoring


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return centre - half, centre + half


def cluster_bootstrap(rows: list[dict[str, Any]], n_boot: int = 2000, seed: int = 0) -> tuple[float | None, float | None]:
    """95% CI of decisive-pair precision, resampling whole datasets."""
    by_ds: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_ds[r["dataset_id"]].append(int(r["correct"]))
    keys = sorted(by_ds)
    if len(keys) < 2:
        return None, None
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        k = n = 0
        for _ in keys:
            vals = by_ds[keys[rng.randrange(len(keys))]]
            k += sum(vals)
            n += len(vals)
        stats.append(k / n)
    stats.sort()
    return stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1]


def score_claim(claim: dict[str, Any], sets: list[dict[str, Any]]) -> dict[str, Any]:
    applications: dict[tuple[str, str, str], dict[str, Any]] = {}
    conflicts = 0
    for s in sets:
        for a, b in itertools.combinations(s["candidates"], 2):
            winners = set()
            for rule in claim.get("rules", []):
                w = predicted_winner(rule, a["view"], b["view"])
                if w is not None:
                    winners.add(w)
            if not winners:
                continue
            key = (s["set_id"], a["id"], b["id"])
            if len(winners) > 1:
                conflicts += 1
                continue
            w = winners.pop()
            out = pair_outcome(a, b, s["metric"])
            applications[key] = {
                "set_id": s["set_id"],
                "dataset_id": s["dataset_id"],
                "family": s["family"],
                "pair": [a["id"], b["id"]],
                "predicted": [a["id"], b["id"]][w],
                "mean_correct": None if out["mean_winner"] is None else out["mean_winner"] == w,
                "decisive": out["separated_winner"] is not None,
                "correct": out["separated_winner"] == w,
            }
    rows = list(applications.values())
    decisive = [r for r in rows if r["decisive"]]
    k = sum(r["correct"] for r in decisive)
    mean_rows = [r for r in rows if r["mean_correct"] is not None]
    k_mean = sum(r["mean_correct"] for r in mean_rows)
    lo, hi = wilson(k, len(decisive))
    blo, bhi = cluster_bootstrap(decisive)
    by_family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in decisive:
        by_family[r["family"]][0] += int(r["correct"])
        by_family[r["family"]][1] += 1
    return {
        "n_applicable": len(rows),
        "n_conflicting": conflicts,
        "n_decisive": len(decisive),
        "n_datasets": len({r["dataset_id"] for r in decisive}),
        "precision": k / len(decisive) if decisive else None,
        "wilson_95": [lo, hi],
        "dataset_bootstrap_95": [blo, bhi],
        "mean_order_precision": k_mean / len(mean_rows) if mean_rows else None,
        "by_family": {f: {"correct": c, "decisive": n} for f, (c, n) in sorted(by_family.items())},
        "applications": rows,
    }


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets-root", type=Path, required=True)
    ap.add_argument("--rules", type=Path, required=True)
    ap.add_argument("--kb-snapshot", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-decisive", type=int, default=10, help="claims below this are excluded from the credibility correlation")
    args = ap.parse_args()

    sets = load_sets(args.datasets_root)
    kb = {c["id"]: c for c in json.loads(args.kb_snapshot.read_text())["claims"]}
    compiled = json.loads(args.rules.read_text())

    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for claim in compiled["claims"]:
        # Pre-registered hypotheses are not KB claims and carry no evidence counts.
        kb_claim = kb.get(claim["id"], {})
        row = {
            "id": claim["id"],
            "status": claim["status"],
            "credibility": kb_claim.get("credibility"),
            "support_count": kb_claim.get("support_count"),
            "failure_count": kb_claim.get("failure_count"),
        }
        if claim["status"] != "untestable":
            scored = score_claim(claim, sets)
            (args.out / "applications").mkdir(exist_ok=True)
            (args.out / "applications" / f"{claim['id']}.json").write_text(
                json.dumps(scored.pop("applications"), indent=1)
            )
            row.update(scored)
        results.append(row)

    scored_rows = [r for r in results if r.get("n_decisive", 0) >= args.min_decisive]
    all_decisive = sum(r.get("n_decisive", 0) for r in results)
    summary = {
        "datasets_root": str(args.datasets_root),
        "kb_snapshot": str(args.kb_snapshot),
        "rules": str(args.rules),
        "n_sets": len(sets),
        "n_candidates": sum(len(s["candidates"]) for s in sets),
        "n_pairs": sum(len(s["candidates"]) * (len(s["candidates"]) - 1) // 2 for s in sets),
        "n_decisive_pairs": sum(
            pair_outcome(a, b, s["metric"])["separated_winner"] is not None
            for s in sets
            for a, b in itertools.combinations(s["candidates"], 2)
        ),
        "n_claims": len(results),
        "status_counts": {
            st: sum(r["status"] == st for r in results) for st in ("testable", "partial", "untestable")
        },
        "min_decisive": args.min_decisive,
        "n_claims_scored": len(scored_rows),
        "pooled_precision": (
            sum(r["precision"] * r["n_decisive"] for r in scored_rows) / sum(r["n_decisive"] for r in scored_rows)
            if scored_rows
            else None
        ),
        "unweighted_mean_precision": (
            sum(r["precision"] for r in scored_rows) / len(scored_rows) if scored_rows else None
        ),
        "spearman_credibility_vs_precision": spearman(
            [r["credibility"] for r in scored_rows if r["credibility"] is not None],
            [r["precision"] for r in scored_rows if r["credibility"] is not None],
        ),
        "total_decisive_applications": all_decisive,
        "claims": results,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1))

    print(
        f"sets={summary['n_sets']} candidates={summary['n_candidates']} pairs={summary['n_pairs']} "
        f"decisive_pairs={summary['n_decisive_pairs']}"
    )
    print(f"claims={summary['n_claims']} status={summary['status_counts']} scored(n_dec>={args.min_decisive})={len(scored_rows)}")
    print(f"pooled precision={summary['pooled_precision']}  unweighted={summary['unweighted_mean_precision']}")
    print(f"spearman(credibility, precision)={summary['spearman_credibility_vs_precision']}")
    print(f"{'id':8} {'status':10} {'cred':>5} {'s':>5} {'f':>5} {'n_app':>6} {'n_dec':>5} {'ds':>3} {'prec':>5} {'boot95':>13} {'mean':>5}")

    def num(value: float | None, fmt: str) -> str:
        return format(value, fmt) if value is not None else "-".rjust(len(format(0.0, fmt)))

    for r in sorted(results, key=lambda r: -(r["credibility"] if r["credibility"] is not None else 2.0)):
        head = (
            f"{r['id']:8} {r['status']:10} {num(r['credibility'], '5.2f')} "
            f"{num(r['support_count'], '5.1f')} {num(r['failure_count'], '5.1f')}"
        )
        if "n_decisive" not in r:
            print(head)
            continue
        b = r["dataset_bootstrap_95"]
        boot = "      -      " if b[0] is None else f"[{b[0]:.2f},{b[1]:.2f}]"
        print(
            f"{head} {r['n_applicable']:6d} {r['n_decisive']:5d} {r['n_datasets']:3d} "
            f"{num(r['precision'], '5.2f')} {boot:>13} {num(r['mean_order_precision'], '5.2f')}"
        )


if __name__ == "__main__":
    main()
