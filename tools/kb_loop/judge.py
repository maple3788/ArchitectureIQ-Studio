"""Status transitions, decided by code from the ledger and the frozen thresholds.

candidate -> verified   >= min_applicable post-registration questions, support rate >= promote_rate
                        and one-sided Clopper-Pearson lower bound >= promote_lower_bound
                        (alpha divided by the number of claims tested this round)
candidate -> revise     judged and support rate below promote_rate (a rate above it with a bound
                        still short stays candidate and keeps collecting questions)
verified  -> flagged    support rate < flag_rate on the last ``recent_rounds`` rounds
                        (>= recent_min_applicable questions), or the cumulative lower bound
                        falls under promote_lower_bound
flagged / revise -> retired   once ``max_revisions`` revisions have been spent

A claim marked ``needs_revision`` goes to the proposer; an accepted revision
becomes the claim's next version, back in ``candidate`` status.
"""

from __future__ import annotations

import math
from typing import Any


def _log_binom_tail(k: int, n: int, p: float) -> float:
    """log P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 0.0
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return 0.0
    terms = [
        math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)
        for i in range(k, n + 1)
    ]
    m = max(terms)
    return m + math.log(sum(math.exp(t - m) for t in terms))


def cp_lower(k: int, n: int, alpha: float) -> float:
    """One-sided Clopper-Pearson lower confidence bound for a binomial proportion."""
    if n == 0 or k == 0:
        return 0.0
    lo, hi, target = 0.0, k / n, math.log(alpha)
    for _ in range(60):
        mid = (lo + hi) / 2
        if _log_binom_tail(k, n, mid) > target:
            hi = mid
        else:
            lo = mid
    return lo


def claim_rows(ledger: list[dict[str, Any]], claim: dict[str, Any]) -> list[dict[str, Any]]:
    """Ledger rows of the claim's current version on questions newer than its registration."""
    return [r for r in ledger
            if r["claim_id"] == claim["id"] and r["version"] == claim["version"] and r["round"] > claim["registered_round"]]


def _rate(rows: list[dict[str, Any]]) -> tuple[int, int]:
    return sum(r["outcome"] == "support" for r in rows), len(rows)


def judge_round(claims: dict[str, dict[str, Any]], ledger: list[dict[str, Any]], round_no: int,
                cfg: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return updated claims and the list of status events for this round."""
    tests: list[tuple[str, int, int, list[dict[str, Any]]]] = []
    for cid, c in claims.items():
        if c["status"] == "retired":
            continue
        rows = claim_rows(ledger, c)
        s, n = _rate(rows)
        if c["status"] == "candidate" and n >= cfg["min_applicable"]:
            tests.append((cid, s, n, rows))
        elif c["status"] in ("verified", "flagged") and n:
            tests.append((cid, s, n, rows))
    alpha = cfg["alpha"] / max(1, len(tests))
    out = {cid: dict(c) for cid, c in claims.items()}
    events = []
    for cid, s, n, rows in tests:
        c = out[cid]
        lb = cp_lower(s, n, alpha)
        stats = {"support": s, "applicable": n, "rate": s / n, "lower_bound": lb, "alpha": alpha}
        c["stats"] = stats
        before = c["status"]
        if before == "candidate":
            if s / n < cfg["promote_rate"]:
                c["needs_revision"] = True  # wrong too often: revise
            elif lb >= cfg["promote_lower_bound"]:
                c["status"], c["needs_revision"] = "verified", False
            # right often enough but the bound is not there yet: keep collecting evidence
        else:
            recent = [r for r in rows if r["round"] > round_no - cfg["recent_rounds"]]
            rs, rn = _rate(recent)
            failing = (rn >= cfg["recent_min_applicable"] and rs / rn < cfg["flag_rate"]) or lb < cfg["promote_lower_bound"]
            stats.update({"recent_support": rs, "recent_applicable": rn})
            if failing:
                c["status"], c["needs_revision"] = "flagged", True
            elif before == "flagged":
                c["status"], c["needs_revision"] = "verified", False
        if c.get("needs_revision") and c.get("revisions", 0) >= cfg["max_revisions"]:
            c["status"], c["needs_revision"] = "retired", False
        if c["status"] != before or c.get("needs_revision"):
            events.append({"round": round_no, "claim_id": cid, "version": c["version"], "from": before,
                           "to": c["status"], "needs_revision": bool(c.get("needs_revision")), **stats})
    return out, events
