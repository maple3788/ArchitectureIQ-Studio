"""What one v1.5 question says about one claim.

A question is three candidates on one dataset instance whose winner fully
separates from both rivals (the v1.5 significance rule). Only comparisons with
that guarantee count as evidence: the winner against each rival, plus a pair of
rivals when their seed ranges happen to separate as well. With ``winner_only``
only the comparisons against the correct answer count: a claim is refuted when it
would have ruled the correct answer out, not when it misorders two losers.

A claim *applies* to a question when one of its rules predicts a winner on at
least one such comparison. It is *supported* when every predicted comparison
is right and *refuted* when any is wrong. Comparisons on which the claim's own
rules disagree are skipped and counted as conflicts.

``question_record`` reads the stored artifacts once (spec, summary, dataset
spec) and keeps only public views and the comparison list, so every later
scoring pass -- including regression checks of revised claims -- works from the
record alone.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from kb_claim_pairwise_eval import LOWER_IS_BETTER, _seed_values, candidate_view, dataset_view, predicted_winner


def _separates(better: list[float], worse: list[float], lower_is_better: bool) -> bool:
    if lower_is_better:
        return max(better) < min(worse)
    return min(better) > max(worse)


def question_record(question: dict[str, Any], data_root: Path, round_no: int, purpose: str,
                    targets: list[str] | None = None) -> dict[str, Any]:
    """Public evidence record of one stored question (question.json already loaded)."""
    first = data_root / question["choices"][0]["candidate_path"]
    ds_dir = first.parents[2]
    ds = dataset_view(json.loads((ds_dir / "dataset_spec.json").read_text()))
    metric = ds["metric"]
    lower = LOWER_IS_BETTER[metric]
    views: dict[str, dict[str, Any]] = {}
    seeds: dict[str, list[float]] = {}
    for ch in question["choices"]:
        cdir = data_root / ch["candidate_path"]
        spec = json.loads((cdir / "candidate_spec.json").read_text())
        summary = json.loads((cdir / "results" / "summary.json").read_text())
        views[ch["candidate_id"]] = candidate_view(spec, ds)
        seeds[ch["candidate_id"]] = _seed_values(summary, metric)
    winner = next(c["candidate_id"] for c in question["choices"] if c["letter"] == question["correct_letter"])
    rivals = [c for c in views if c != winner]
    comparisons = [[winner, r] for r in rivals if _separates(seeds[winner], seeds[r], lower)]
    for a, b in itertools.combinations(rivals, 2):
        if _separates(seeds[a], seeds[b], lower):
            comparisons.append([a, b])
        elif _separates(seeds[b], seeds[a], lower):
            comparisons.append([b, a])
    means = {c: sum(v) / len(v) for c, v in seeds.items()}
    return {
        "question_id": question["question_id"],
        "round": round_no,
        "purpose": purpose,
        "targets": list(targets or []),
        "family": question["family"],
        "type": question["type"],
        "dataset_id": question["dataset_id"],
        "winner": winner,
        "winner_separates": all([winner, r] in comparisons for r in rivals),
        "candidates": views,
        "comparisons": comparisons,
        "metric": metric,
        "means": means,
        "gaps": [relative_gap(means[b], means[w], lower) for b, w in comparisons],
    }


def relative_gap(better: float, worse: float, lower_is_better: bool = True) -> float:
    """How far apart two options are: (worse - better) / |better| for a loss."""
    diff = (worse - better) if lower_is_better else (better - worse)
    return diff / abs(better) if better else float("inf")


def strong_comparisons(record: dict[str, Any], min_gap: float = 0.0, winner_only: bool = False) -> list[list[str]]:
    """Comparisons whose two options differ by at least ``min_gap`` (relative; all of them when 0), and with
    ``winner_only`` only those of the correct answer against a rival."""
    comps = record["comparisons"]
    if min_gap:
        gaps = record.get("gaps")
        if gaps is None:
            raise ValueError(f"record {record['question_id']} has no gaps; backfill it before using min_gap")
        comps = [c for c, g in zip(comps, gaps) if g >= min_gap]
    if winner_only:
        comps = [c for c in comps if c[0] == record["winner"]]
    return comps


def claim_outcome(rules: list[dict[str, Any]], record: dict[str, Any], min_gap: float = 0.0,
                  winner_only: bool = False) -> dict[str, Any] | None:
    """Verdict of a claim on one question record, or None when it does not apply.

    Only comparisons whose options differ by at least ``min_gap`` count: a claim is neither
    supported nor refuted by a near-tie, even a seed-separated one.
    """
    views = record["candidates"]
    used, conflicts, correct = [], 0, True
    for better, worse in strong_comparisons(record, min_gap, winner_only):
        winners = set()
        for rule in rules:
            w = predicted_winner(rule, views[better], views[worse])
            if w is not None:
                winners.add(w)
        if not winners:
            continue
        if len(winners) > 1:
            conflicts += 1
            continue
        ok = winners.pop() == 0
        used.append([better, worse, ok])
        correct = correct and ok
    if not used:
        return None
    return {"outcome": "support" if correct else "refute", "pairs": used, "conflicts": conflicts}


def score_records(rules: list[dict[str, Any]], records: list[dict[str, Any]],
                  min_gap: float = 0.0, winner_only: bool = False) -> dict[str, dict[str, Any]]:
    """{question_id: verdict} over the questions the claim applies to."""
    out = {}
    for rec in records:
        v = claim_outcome(rules, rec, min_gap, winner_only)
        if v is not None:
            out[rec["question_id"]] = v
    return out
