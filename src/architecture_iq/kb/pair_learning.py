"""Frozen paired units and bounded, explicitly unverified learning traces."""
from __future__ import annotations

import copy
import re
from collections.abc import Callable


PROTOCOLS = {"single", "paired_contrastive", "paired_progressive"}
ROLES = ("original", "counterfactual")
LEARNING_FIELDS = {
    "summary", "conditions", "exceptions", "interactions", "changed_factors",
    "controlled_factors", "competing_explanation", "next_test",
}


def member_question_id(member: dict, questions_by_id: dict) -> str:
    """Catalog IDs include revisions; native IDs can use the source identity."""
    identifier = member.get("key", member.get("id"))
    if not isinstance(identifier, str) or identifier not in questions_by_id:
        raise ValueError("Missing pair member in public questions")
    return identifier


def pair_members(pair: dict, questions_by_id: dict) -> dict[str, dict]:
    return {
        member["role"]: questions_by_id[member_question_id(member, questions_by_id)]
        for member in pair["members"]
    }


def validate_pair_manifest(questions: list[dict], pair_manifest: list[dict], *, require_discovery: bool = True) -> list[dict]:
    """Validate trusted catalog attestations against the frozen public inputs.

    This checks correspondence, not GT. Catalog construction verifies candidate
    specs and derives the public intervention; private labels never belong here.
    With require_discovery, every discovery question belongs to one KB-ready pair.
    Otherwise this is evaluation validation, independent of the stored split.
    """
    if not isinstance(pair_manifest, list) or not pair_manifest:
        raise ValueError("A complete pair manifest is required")
    by_id = {question["id"]: question for question in questions}
    used, pair_keys, pair_ids = set(), set(), set()
    allowed = {"schema_version", "pair_key", "pair_id", "family", "type", "split",
               "lineage_id", "ready", "kb_ready", "evaluation_ready", "issues",
               "members", "candidate_mapping", "intervention"}
    for pair in pair_manifest:
        if not isinstance(pair, dict) or set(pair) - allowed:
            raise ValueError("Invalid public pair manifest fields")
        if type(pair.get("schema_version")) is not int or pair["schema_version"] != 1:
            raise ValueError("Unsupported pair manifest schema version")
        key = pair.get("pair_key")
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) or key in pair_keys:
            raise ValueError("Invalid or duplicate pair key")
        pair_keys.add(key)
        if not isinstance(pair.get("pair_id"), str) or not pair["pair_id"] or pair["pair_id"] in pair_ids:
            raise ValueError("Invalid or duplicate pair identity")
        pair_ids.add(pair["pair_id"])
        if pair.get("ready") is not True or pair.get("issues"):
            raise ValueError("Pair is not ready")
        readiness = "kb_ready" if require_discovery and pair.get("split") == "discovery" else "evaluation_ready"
        if pair.get(readiness, pair.get("ready") if readiness == "evaluation_ready" else None) is not True:
            raise ValueError("Pair is not ready for its split")
        members = pair.get("members")
        if (not isinstance(members, list) or len(members) != 2
                or any(not isinstance(m, dict) for m in members)
                or {m.get("role") for m in members} != set(ROLES)):
            raise ValueError("Pair must have exactly one member of each role")
        resolved = {}
        for member in members:
            if set(member) - {"role", "key", "id", "dataset_id", "hash", "family", "type", "lineage_id", "split"}:
                raise ValueError("Invalid public pair member identity")
            if any(not isinstance(member.get(field), str) or not member[field]
                   for field in ("key", "id", "dataset_id", "hash")):
                raise ValueError("Incomplete pair member identity")
            if (member["key"] != member["id"] and
                    (not re.fullmatch(r"[0-9a-f]{64}", member["hash"])
                     or member["key"] != f"{member['id']}@{member['hash'][:24]}")):
                raise ValueError("Pair source and revision identity mismatch")
            identifier = member_question_id(member, by_id)
            if identifier in used:
                raise ValueError("Duplicate pair member")
            used.add(identifier)
            question = by_id[identifier]
            if member.get("dataset_id") != question["dataset_id"]:
                raise ValueError("Pair member dataset identity mismatch")
            for field in ("family", "lineage_id", "split", "pair_id"):
                if pair.get(field) != question.get(field) or (field in member and member[field] != question.get(field)):
                    raise ValueError(f"Pair public {field} identity mismatch")
            candidate_ids = [choice["id"] for choice in question["choices"]]
            if (any(not isinstance(cid, str) or not cid for cid in candidate_ids)
                    or len(set(candidate_ids)) != len(candidate_ids)):
                raise ValueError("Pair candidate identity must be unique within each member")
            resolved[member["role"]] = question
        mapping = pair.get("candidate_mapping")
        if not isinstance(mapping, list) or not mapping:
            raise ValueError("Pair candidate mapping required")
        identities = set()
        mapped = {role: set() for role in ROLES}
        for row in mapping:
            fields = {"choice_identity", "original_candidate_id", "counterfactual_candidate_id",
                      "original_letter", "counterfactual_letter"}
            if (not isinstance(row, dict) or set(row) != fields
                    or any(not isinstance(value, str) or not value for value in row.values())
                    or row["choice_identity"] in identities):
                raise ValueError("Invalid pair candidate mapping")
            identities.add(row["choice_identity"])
            for role in ROLES:
                candidate = (row[role + "_candidate_id"], row[role + "_letter"])
                available = {(c["id"], c["letter"]) for c in resolved[role]["choices"]}
                if candidate not in available or candidate in mapped[role]:
                    raise ValueError("Pair candidate mapping does not match public choices")
                mapped[role].add(candidate)
        if any(len(mapped[role]) != len(resolved[role]["choices"]) for role in ROLES):
            raise ValueError("Pair candidate mapping must cover all choices")
        intervention = pair.get("intervention")
        required = {"changes", "controls", "causal_status"}
        optional = {"notice", "selection_history", "limitations"}
        if (not isinstance(intervention, dict)
                or not required <= set(intervention) or set(intervention) - required - optional
                or not isinstance(intervention["changes"], list)
                or not isinstance(intervention["controls"], list)
                or any(not isinstance(v, str) for v in intervention["controls"])
                or not isinstance(intervention["causal_status"], str)
                or ("notice" in intervention and not isinstance(intervention["notice"], str))
                or ("selection_history" in intervention and intervention["selection_history"] not in {
                    "all_significant_pairs", "outcome_selected_release", "unknown"})
                or ("limitations" in intervention and (not isinstance(intervention["limitations"], list)
                    or any(not isinstance(v, str) for v in intervention["limitations"])))):
            raise ValueError("Pair needs a verified public intervention")
        for change in intervention["changes"]:
            if (not isinstance(change, dict) or set(change) != {"path", "before", "after", "kind"}
                    or not isinstance(change["path"], str) or change["kind"] not in {"factor", "dataset", "sampling"}):
                raise ValueError("Invalid public pair intervention change")
    if require_discovery and not {q["id"] for q in questions if q["split"] == "discovery"} <= used:
        raise ValueError("Every discovery question must belong to one complete pair")
    return copy.deepcopy(pair_manifest)


def pair_call_budget(config: dict) -> int:
    """Worst-case round calls, including one skeptic per research proposal."""
    pairs = config["discovery_per_round"] // 2
    return (pairs * (6 if config.get("learning_protocol") == "paired_progressive" else 4) + 2
            + int(config.get("experience_mode", "off") != "off"))


def validate_pair_config(config: dict, questions: list[dict]) -> list[dict]:
    protocol = config.get("learning_protocol", "single")
    if protocol not in PROTOCOLS:
        raise ValueError("Unknown learning_protocol")
    if protocol == "single":
        manifests = config.get("pair_manifest")
        if manifests:
            validated = validate_pair_manifest(questions, manifests, require_discovery=False)
            if any(pair["split"] == "discovery" for pair in validated):
                raise ValueError("Discovery pairs require a paired learning protocol")
        elif manifests is not None and not isinstance(manifests, list):
            raise ValueError("Pair manifest must be a list")
        return []
    for field in ("discovery_per_round", "packet_size"):
        if config[field] % 2:
            raise ValueError(f"{field} must be even for paired learning")
    pairs = validate_pair_manifest(questions, config.get("pair_manifest"))
    if pair_call_budget(config) > config["max_calls_per_round"]:
        raise ValueError("Paired learning exceeds round call budget")
    return pairs


def ordered_pair_questions(questions: list[dict], pairs: list[dict]) -> list[dict]:
    """Order units by first occurrence; keep original/CF adjacent at all cuts."""
    by_id = {question["id"]: question for question in questions}
    positions = {question["id"]: index for index, question in enumerate(questions)}
    ordered = sorted(pairs, key=lambda pair: min(positions[member_question_id(m, by_id)] for m in pair["members"]))
    return [pair_members(pair, by_id)[role] for pair in ordered for role in ROLES]


def validate_learning_response(raw: dict) -> dict:
    """Narrative learning cannot acquire scientific authority through output fields."""
    learning = raw.get("learning")
    if raw.get("_invalid") or set(raw) - {"learning", "hypothesis"} or not isinstance(learning, dict) or set(learning) != LEARNING_FIELDS:
        raise ValueError("Malformed pair learning response")
    for field in LEARNING_FIELDS:
        value = learning[field]
        if field in {"summary", "competing_explanation", "next_test"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValueError(f"Invalid pair learning {field}")
        elif (not isinstance(value, list) or len(value) > 32
              or any(not isinstance(item, str) or len(item) > 2000 for item in value)):
            raise ValueError(f"Invalid pair learning {field}")
    return copy.deepcopy(raw)


def research_pair(*, pair: dict, protocol: str, original: dict, counterfactual: dict,
                  answers: dict, feedback: dict, knowledge: list[dict], context: dict,
                  call: Callable, answer: Callable, check_time: Callable) -> dict:
    """Construct stage-specific capabilities; transfer never receives CF labels."""
    trace = {"pair_key": pair["pair_key"], "pair_id": pair["pair_id"], "protocol": protocol,
             "scientific_status": "unverified", "model_weights_fixed": True}
    original_episode = {"question": original, "answer": answers[original["id"]],
                        "feedback": feedback[original["id"]]}

    def research(stage, payload):
        check_time()
        raw = call("pair_researcher", {"stage": stage, **payload, **context},
                   key=f"pair-{pair['pair_key']}-{stage}")
        try:
            return validate_learning_response(raw)
        except ValueError as exc:
            return {"_invalid": True, "error": str(exc), "raw": raw}

    if protocol == "paired_progressive":
        trace["induction"] = research("induction", {"original": original_episode})
        # Failed induction remains a durable note but supplies no malformed draft.
        provisional = {"status": "unverified", "model_weights_fixed": True,
                       "learning": trace["induction"].get("learning"),
                       "instruction": "Treat this provisional observation as fallible; it is not a verified KB claim."}
        check_time()
        transfer = call("solver", {"question": counterfactual, "knowledge": knowledge,
                                  "provisional_learning": provisional},
                        key=f"pair-{pair['pair_key']}-transfer")
        trace["transfer"] = answer(transfer, counterfactual, knowledge)
    payload = {
        "original": original_episode,
        "pair": {"pair_key": pair["pair_key"], "pair_id": pair["pair_id"],
                 "candidate_mapping": pair["candidate_mapping"], "intervention": pair["intervention"]},
        "counterfactual": {"question_id": counterfactual["id"],
                           "answer": answers[counterfactual["id"]],
                           "feedback": feedback[counterfactual["id"]]},
    }
    if protocol == "paired_progressive":
        payload.update(induction=trace["induction"], transfer=trace["transfer"])
    stage = "revision" if protocol == "paired_progressive" else "contrastive"
    trace[stage] = research(stage, payload)
    return trace
