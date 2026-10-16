"""Where a claim is right and where it is wrong, over all of its historical comparisons.

The reviser sees only a handful of example questions, but its draft is checked against
every historical question. ``condition_table`` closes that gap: for each simple condition
on a compared pair (both candidates satisfy a predicate, or the pair is equal / ordered on
a field) it reports how often the claim's prediction was right when the condition holds
and when it does not. ``stratified`` picks examples across (family, question type) cells
instead of uniformly at random.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Callable

CATEGORICAL = ("family", "task", "model_type", "opt", "activation", "residual", "ln_any", "ln_all", "adaptive",
               "sign_normalized", "rule_family", "layer_residual", "smooth_activation", "target_oscillatory",
               "vocab_size", "context_length", "transition_alpha", "spiral_turns")
NUMERIC = ("lr", "steps", "batch_size", "budget", "depth", "width", "params", "ln_count", "weight_decay", "momentum",
           "beta2", "disp", "eff_lr", "input_dim", "target_abs_mean", "target_std", "num_layers", "d_model",
           "n_active_features", "n_used_inputs")
SAME = ("opt", "opt_key", "arch_key", "lr", "steps", "batch_size", "depth", "width", "residual", "activation",
        "ln_count", "model_type", "weight_decay")
RATIO = ("disp", "eff_lr", "params", "lr", "steps")

Pair = tuple[dict[str, Any], dict[str, Any], bool]  # (predicted winner view, predicted loser view, prediction right)


def claim_pairs(verdicts: dict[str, dict[str, Any]], records_by_id: dict[str, dict[str, Any]]) -> list[Pair]:
    """Every comparison the claim predicted on, oriented as (predicted winner, predicted loser, right?)."""
    out = []
    for qid, v in verdicts.items():
        views = records_by_id[qid]["candidates"]
        for better, worse, ok in v["pairs"]:
            win, lose = (better, worse) if ok else (worse, better)
            out.append((views[win], views[lose], ok))
    return out


def _quantiles(values: list[float], qs=(0.25, 0.5, 0.75)) -> list[float]:
    xs = sorted(values)
    return sorted({xs[int(q * (len(xs) - 1))] for q in qs}) if xs else []


def _conditions(pairs: list[Pair]) -> list[tuple[str, Callable[[Pair], bool]]]:
    conds: list[tuple[str, Callable[[Pair], bool]]] = []
    for f in CATEGORICAL:
        values = {v.get(f) for w, l, _ in pairs for v in (w, l)} - {None}
        for val in sorted(values, key=str):
            conds.append((f"both {f} == {val!r}", lambda p, f=f, val=val: p[0].get(f) == val and p[1].get(f) == val))
    for f in NUMERIC:
        vals = [v[f] for w, l, _ in pairs for v in (w, l) if isinstance(v.get(f), (int, float)) and not isinstance(v.get(f), bool)]
        for t in _quantiles(vals):
            conds.append((f"both {f} >= {t:g}", lambda p, f=f, t=t: (p[0].get(f) is not None and p[1].get(f) is not None
                                                                      and p[0][f] >= t and p[1][f] >= t)))
            conds.append((f"both {f} <= {t:g}", lambda p, f=f, t=t: (p[0].get(f) is not None and p[1].get(f) is not None
                                                                      and p[0][f] <= t and p[1][f] <= t)))
    for f in SAME:
        conds.append((f"same {f}", lambda p, f=f: p[0].get(f) is not None and p[0].get(f) == p[1].get(f)))
    for f in RATIO:
        for r in (2.0, 4.0):
            def ratio(p: Pair, f: str = f, r: float = r) -> bool:
                a, b = p[0].get(f), p[1].get(f)
                return bool(a) and bool(b) and a > 0 and b > 0 and max(a, b) / min(a, b) >= r
            conds.append((f"{f} differs by >= {r:g}x", ratio))
        conds.append((f"predicted winner has higher {f}", lambda p, f=f: (p[0].get(f) or 0) > (p[1].get(f) or 0)))
    return conds


def condition_table(pairs: list[Pair], top: int = 16, min_n: int = 8) -> list[str]:
    """Conditions that best separate right from wrong predictions, as one line each."""
    if not pairs:
        return []
    k_all = sum(ok for *_, ok in pairs)
    base = k_all / len(pairs)
    rows = []
    for name, cond in _conditions(pairs):
        hold = [ok for p in pairs if cond(p) for ok in (p[2],)]
        n_h, n_o = len(hold), len(pairs) - len(hold)
        if n_h < min_n or n_o < min_n:
            continue
        k_h = sum(hold)
        k_o = k_all - k_h
        score = abs(k_h / n_h - base) * math.sqrt(n_h)
        rows.append((score, f"{name}: right {k_h}/{n_h} ({k_h / n_h:.0%}) | otherwise {k_o}/{n_o} ({k_o / n_o:.0%})"))
    header = f"all predicted comparisons: right {k_all}/{len(pairs)} ({base:.0%})"
    return [header] + [line for _, line in sorted(rows, reverse=True)[:top]]


def stratified(records: list[dict[str, Any]], n: int, rng: random.Random) -> list[dict[str, Any]]:
    """Up to ``n`` records spread round-robin over (family, question type) cells."""
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        cells[(r["family"], r["type"])].append(r)
    groups = [cells[k] for k in sorted(cells)]
    for g in groups:
        rng.shuffle(g)
    rng.shuffle(groups)
    out: list[dict[str, Any]] = []
    while len(out) < n and any(groups):
        for g in groups:
            if g and len(out) < n:
                out.append(g.pop())
    return out
