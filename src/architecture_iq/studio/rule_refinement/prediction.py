"""Spec-only pairwise rule execution and bounded top-choice graph reasoning."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from itertools import combinations

from architecture_iq.kb.rules import public_views, match_rule, match_rule_for_injection
from .artifacts import validate_snapshot
from .contracts import PREDICTOR_VERSION, fields, text, digest


def validate_public_case(case: dict) -> None:
    fields(case, {"ref", "question", "dataset_spec", "candidate_specs", "objective"},
           {"ref", "question", "dataset_spec", "candidate_specs", "objective"})
    fields(case["ref"], {"key", "hash"}, {"key", "hash"})
    text(case["ref"]["key"])
    digest(case["ref"]["hash"])
    text(case["objective"])
    dataset, specs, question = case["dataset_spec"], case["candidate_specs"], case["question"]
    if not isinstance(dataset, dict) or dataset.get("selection_metric") != case["objective"]:
        raise ValueError("Public objective differs from dataset specification")
    if not isinstance(question, dict) or not isinstance(specs, list):
        raise ValueError("Invalid public question/specifications")
    choices = question.get("choices")
    if not isinstance(choices, list) or not 2 <= len(choices) <= 20 or len(specs) != len(choices):
        raise ValueError("Question needs 2–20 matching candidate specifications")
    ids, letters = set(), set()
    for choice, spec in zip(choices, specs):
        if not isinstance(choice, dict) or not isinstance(spec, dict):
            raise ValueError("Invalid candidate")
        cid, letter = choice.get("id"), choice.get("letter")
        text(cid)
        text(letter)
        if cid in ids or letter in letters or spec.get("candidate_id") != cid:
            raise ValueError("Candidate identity or letter is not unique/matching")
        ids.add(cid)
        letters.add(letter)
        if spec.get("selection_metric", case["objective"]) != case["objective"]:
            raise ValueError("Cannot combine different candidate objectives")


def _cycle(graph):
    colors, trail = {}, []
    def visit(node):
        if colors.get(node) == 1:
            return trail[trail.index(node):] + [node]
        if colors.get(node) == 2:
            return None
        colors[node] = 1
        trail.append(node)
        for child in sorted(graph[node]):
            found = visit(child)
            if found:
                return found
        trail.pop()
        colors[node] = 2
        return None
    for node in sorted(graph):
        found = visit(node)
        if found:
            return found
    return None


def _paths(graph, origin):
    paths, queue = {origin: [origin]}, deque([origin])
    while queue:
        node = queue.popleft()
        for child in sorted(graph[node]):
            if child not in paths:
                paths[child] = paths[node] + [child]
                queue.append(child)
    return {k: v for k, v in paths.items() if k != origin}


def predict_question(case: dict, kb: dict) -> dict:
    result = {"question_ref": deepcopy(case.get("ref")), "kb_version": kb.get("version"),
              "executable_hash": kb.get("executable_hash"), "predictor_version": PREDICTOR_VERSION,
              "status": "invalid", "answer_id": None, "edges": [], "paths": {}, "issues": []}
    try:
        validate_public_case(case)
        validate_snapshot(kb)
        views = public_views(case["dataset_spec"], case["candidate_specs"])
        ids = [c["id"] for c in case["question"]["choices"]]
        edges = {}
        for a, b in combinations(range(len(ids)), 2):
            for rule in kb["rules"]:
                if rule["state"] != "active":
                    continue
                predicted = match_rule(rule["rule"], views[a], views[b])
                if predicted is None:
                    continue
                winner, loser = (ids[a], ids[b]) if predicted == 0 else (ids[b], ids[a])
                edges.setdefault((winner, loser), []).append(
                    {"rule_id": rule["rule_id"], "revision": rule["revision"]})
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        result["issues"] = [{"code": "invalid_case", "message": str(exc)}]
        return result
    result["edges"] = [{"winner": a, "loser": b, "rules": sorted(rules, key=lambda r: r["rule_id"])}
                       for (a, b), rules in sorted(edges.items())]
    graph = {node: set() for node in ids}
    indegree = {node: 0 for node in ids}
    for a, b in edges:
        graph[a].add(b)
        indegree[b] += 1
    opposing = [[a, b] for a, b in sorted(edges) if a < b and (b, a) in edges]
    cycle = _cycle(graph)
    if opposing:
        result["issues"].append({"code": "opposite_edges", "pairs": opposing})
    if cycle:
        result["issues"].append({"code": "cycle", "path": cycle})
    if result["issues"]:
        result["status"] = "conflict"
        return result
    maxima = sorted(node for node in ids if indegree[node] == 0)
    paths = _paths(graph, maxima[0]) if len(maxima) == 1 else {}
    if len(maxima) == 1 and len(paths) == len(ids) - 1:
        result.update(status="answered", answer_id=maxima[0], paths=paths)
    else:
        reachability = {node: _paths(graph, node) for node in ids}
        unresolved = [[a, b] for a, b in combinations(sorted(ids), 2)
                      if b not in reachability[a] and a not in reachability[b]]
        result.update(status="uncovered", issues=[{"code": "incomparable", "maxima": maxima,
                                                  "unresolved": unresolved}])
    return result


def predict_batch(cases: list[dict], kb: dict) -> list[dict]:
    return [predict_question(case, kb) for case in cases]


def match_question_for_injection(case: dict, kb: dict) -> dict:
    """Return public-spec context applicability evidence, without choosing an answer.

    The matching contract intentionally differs from ``predict_question``:
    source-reported replication and injection permission gate these references,
    and a documented ``inject_same`` may loosen equal-control requirements.
    No GT, model call or independent validation experiment is involved.
    Opposing matches remain visible for the caller; they are never voted on.
    """
    result = {"question_ref": deepcopy(case.get("ref")), "kb_version": kb.get("version"),
              "executable_hash": kb.get("executable_hash"), "status": "invalid",
              "matches": [], "rule_ids": [], "claim_ids": [], "issues": []}
    try:
        validate_public_case(case)
        validate_snapshot(kb)
        views = public_views(case["dataset_spec"], case["candidate_specs"])
        ids = [choice["id"] for choice in case["question"]["choices"]]
        matches = []
        for a, b in combinations(range(len(ids)), 2):
            for rule in kb["rules"]:
                predicted = match_rule_for_injection(rule, views[a], views[b])
                if predicted is None:
                    continue
                winner, loser = (ids[a], ids[b]) if predicted == 0 else (ids[b], ids[a])
                metadata = rule["metadata"]
                matches.append({"rule_id": rule["rule_id"], "revision": rule["revision"],
                                "claim_id": metadata["claim_id"], "clause_index": metadata["clause_index"],
                                "winner": winner, "loser": loser})
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        result["issues"] = [{"code": "invalid_case", "message": str(exc)}]
        return result
    result.update(status="matched" if matches else "unmatched", matches=matches,
                  rule_ids=sorted({match["rule_id"] for match in matches}),
                  claim_ids=sorted({match["claim_id"] for match in matches}))
    return result
