"""Answer questions with several KB claims together, without any model.

Every applicable claim votes on every pair of options (all pairs: at answer time the
results are unknown). An option collects one point per pairwise win; the option with the
most points is the answer, and a tie for first place abstains. A claim whose own rules
disagree on a pair does not vote on it.
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

from kb_claim_pairwise_eval import predicted_winner


def pair_vote(rules: list[dict[str, Any]], a: dict[str, Any], b: dict[str, Any]) -> int | None:
    winners = {w for w in (predicted_winner(r, a, b) for r in rules) if w is not None}
    return winners.pop() if len(winners) == 1 else None


def answer(record: dict[str, Any], claims: list[dict[str, Any]]) -> str | None:
    views = record["candidates"]
    points: Counter = Counter({cid: 0 for cid in views})
    voted = False
    for a, b in itertools.combinations(sorted(views), 2):
        for c in claims:
            w = pair_vote(c["rules"], views[a], views[b])
            if w is not None:
                points[(a, b)[w]] += 1
                voted = True
    if not voted:
        return None
    ranked = points.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def evaluate(records: list[dict[str, Any]], claims: list[dict[str, Any]]) -> dict[str, Any]:
    answered = correct = 0
    for rec in records:
        pick = answer(rec, claims)
        if pick is not None:
            answered += 1
            correct += pick == rec["winner"]
    n = len(records)
    return {"questions": n, "claims": len(claims), "answered": answered, "correct": correct,
            "coverage": answered / n if n else None, "accuracy": correct / answered if answered else None,
            "overall": correct / n if n else None}
