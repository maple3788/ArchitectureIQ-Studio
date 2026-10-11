"""Offline scoring: task utility is separate from scientific rule evidence."""

from __future__ import annotations

import itertools
import math


def _summary_metric(summary: dict) -> str | None:
    """Read legacy/runner metric names without rewriting stored ground truth."""
    if not isinstance(summary, dict):
        return None
    declared = [summary[key] for key in ("metric", "selection_metric")
                if summary.get(key) is not None]
    if not declared or any(not isinstance(value, str) or not value for value in declared):
        return None
    return declared[0] if all(value == declared[0] for value in declared) else None


def _decisive_pairs(question: dict, feedback: dict) -> list[tuple[str, str]]:
    metrics = feedback.get("candidate_metrics", {})
    pairs = []
    for a, b in itertools.combinations(question["choices"], 2):
        ma, mb = metrics.get(a["id"], {}), metrics.get(b["id"], {})
        metric = _summary_metric(ma)
        if not metric or metric != _summary_metric(mb):
            continue
        higher = feedback.get("higher_is_better")
        if higher is None:
            # Backward-compatible historical loss artifacts have an explicit
            # recognized selection metric. Unknown metric directions abstain.
            if metric not in ("test_mse", "test_ce"):
                continue
            higher = False
        if type(higher) is not bool:
            continue
        sa, sb = ma.get("seed_results", []), mb.get("seed_results", [])
        if not sa or not sb:
            continue
        if any(r.get("failed", True) for r in sa + sb):
            continue
        try:
            va = {r["seed"]: float(r["final_" + metric]) for r in sa}
            vb = {r["seed"]: float(r["final_" + metric]) for r in sb}
        except (KeyError, TypeError, ValueError):
            continue
        if (
            len(va) != len(sa)
            or len(vb) != len(sb)
            or set(va) != set(vb)
            or not all(math.isfinite(v) for v in [*va.values(), *vb.values()])
        ):
            continue
        sign = -1 if higher else 1
        xa, xb = [sign * v for v in va.values()], [sign * v for v in vb.values()]
        if max(xa) < min(xb):
            pairs.append((a["letter"], b["letter"]))
        elif max(xb) < min(xa):
            pairs.append((b["letter"], a["letter"]))
    return pairs


def decisive_pairs(question: dict, feedback: dict) -> list[tuple[str, str]]:
    """Expose the existing stored-GT criterion without changing historical scoring."""
    return _decisive_pairs(question, feedback)


def score_evaluation(questions: list[dict], outputs: dict, private: dict, *, pair_manifest: list[dict] | None = None) -> dict:
    correct = {
        arm: {
            q["id"]: bool(
                answers[q["id"]]["valid"]
                and answers[q["id"]]["ranking"][0] == private[q["id"]]["correct_letter"]
            )
            for q in questions
        }
        for arm, answers in outputs.items()
    }
    pairs = {}
    for q in questions:
        if q.get("pair_id"):
            pairs.setdefault(q["pair_id"], []).append(q["id"])
    complete_pairs = [ids for ids in pairs.values() if len(ids) == 2]
    identity_pairs = []
    if pair_manifest is not None:
        from .pair_learning import validate_pair_manifest, pair_members

        if not isinstance(pair_manifest, list):
            raise ValueError("Pair manifest must be a list")
        by_id = {q["id"]: q for q in questions}
        selected = [p for p in pair_manifest if any(
            m.get("key") in by_id or m.get("id") in by_id for m in p.get("members", [])
        )]
        if selected:
            validate_pair_manifest(questions, selected, require_discovery=False)
        for pair in selected:
            members = pair_members(pair, by_id)
            identities = {
                role: {row[role + "_letter"]: row["choice_identity"] for row in pair["candidate_mapping"]}
                for role in ("original", "counterfactual")
            }
            identity_pairs.append((members, identities))
        complete_pairs = [[members[role]["id"] for role in ("original", "counterfactual")]
                          for members, _ in identity_pairs]
    known = {q["id"]: _decisive_pairs(q, private[q["id"]]) for q in questions}
    total_pairs = sum(
        len(q["choices"]) * (len(q["choices"]) - 1) // 2 for q in questions
    )
    decisive = sum(map(len, known.values()))
    scores = {}
    for arm, answers in outputs.items():
        pairwise_correct = 0
        for q in questions:
            answer = answers[q["id"]]
            if not answer["valid"]:
                continue
            rank = {letter: i for i, letter in enumerate(answer["ranking"])}
            pairwise_correct += sum(rank[a] < rank[b] for a, b in known[q["id"]])
        base = correct.get("clean", correct[arm])
        scores[arm] = {
            "correct": sum(correct[arm].values()),
            "total": len(questions),
            "invalid": sum(not a["valid"] for a in answers.values()),
            "pairwise_correct": pairwise_correct,
            "pairwise_total": decisive,
            "pairwise_accuracy": pairwise_correct / decisive if decisive else None,
            "pairwise_unresolved": total_pairs - decisive,
            "pair_joint_correct": sum(
                all(correct[arm][x] for x in ids) for ids in complete_pairs
            ),
            "pair_total": len(complete_pairs),
            "incomplete_pair_groups": len(pairs) - len(complete_pairs),
            "covered_questions": sum(
                a.get("knowledge_count", 0) > 0 for a in answers.values()
            ),
            "invalid_citation_questions": sum(
                bool(a.get("invalid_citations")) for a in answers.values()
            ),
            "helpful_changes": sum(
                not base[q] and value for q, value in correct[arm].items()
            ),
            "harmful_changes": sum(
                base[q] and not value for q, value in correct[arm].items()
            ),
        }
        if pair_manifest is not None:
            change_correct = 0
            for members, identities in identity_pairs:
                original, counterfactual = (members[role]["id"] for role in ("original", "counterfactual"))
                if not (answers[original]["valid"] and answers[counterfactual]["valid"]):
                    continue
                expected_change = (identities["original"][private[original]["correct_letter"]]
                                   != identities["counterfactual"][private[counterfactual]["correct_letter"]])
                predicted_change = (identities["original"][answers[original]["ranking"][0]]
                                    != identities["counterfactual"][answers[counterfactual]["ranking"][0]])
                change_correct += predicted_change == expected_change
            scores[arm].update(pair_winner_change_correct=change_correct,
                               pair_winner_change_total=len(identity_pairs))
    return scores
