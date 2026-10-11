"""Strict shared identities and limits for the research rule protocol."""
from __future__ import annotations

from copy import deepcopy
import re
from pathlib import Path
from typing import TypedDict

from architecture_iq.kb.store import canonical_hash

PROTOCOL = "rule_refinement_v1"
PREDICTOR_VERSION = "rule_top1_v1"
METHOD_ID = "rule_refinement"
DEFAULT_LIMITS = {
    "max_revision_attempts": 12, "max_no_progress": 3, "max_generation_attempts": 3,
    "questions_per_batch": 16, "max_new_questions": 48, "required_fresh_passes": 2,
}
RESOURCE_LIMITS = {"max_model_calls", "max_tokens", "max_candidate_seed_runs", "wall_time_seconds"}


class QuestionRef(TypedDict):
    key: str
    hash: str


class PublicCase(TypedDict):
    ref: QuestionRef
    question: dict
    dataset_spec: dict
    candidate_specs: list[dict]
    objective: str


class RuleRevision(TypedDict):
    rule_id: str
    revision: str
    parents: list[dict]
    text: str
    rationale: str
    rule: dict
    state: str
    source_refs: list[dict]


class RuleKB(TypedDict):
    kind: str
    schema_version: int
    version: str
    parent_version: str | None
    rules: list[RuleRevision]
    executable_hash: str
    import_issues: list[dict]


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError("Missing or unsupported fields")
    canonical_hash(value)  # Reject non-finite/unsupported JSON, including nested content.


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
        raise ValueError("Invalid artifact identifier")
    return value


def digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Invalid content hash")
    return value


def text(value, *, required=True, maximum=32000):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise ValueError("Expected bounded text")
    return value


def validate_limits(value: dict) -> dict:
    fields(value, set(DEFAULT_LIMITS) | RESOURCE_LIMITS, RESOURCE_LIMITS)
    result = {**DEFAULT_LIMITS, **deepcopy(value)}
    if any(type(v) is not int or v <= 0 for v in result.values()):
        raise ValueError("All limits must be positive integers")
    if result["required_fresh_passes"] > result["max_generation_attempts"]:
        raise ValueError("Fresh-pass target exceeds generation attempt limit")
    if result["required_fresh_passes"] * result["questions_per_batch"] > result["max_new_questions"]:
        raise ValueError("Fresh-pass target exceeds new question budget")
    return result


def artifact_path(root: Path, reference: str, *, kind: str) -> Path:
    if not isinstance(reference, str):
        raise ValueError("Invalid artifact reference")
    parts = reference.split("/")
    if len(parts) != 2 or parts[0] != kind or not parts[1].endswith(".json"):
        raise ValueError("Invalid artifact reference")
    identifier(parts[1][:-5])
    path = Path(root) / reference
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Artifact escapes run directory")
    return path


def validate_pool(value: dict) -> None:
    fields(value, {"version", "parent_version", "members", "pairs", "source_bindings", "usage_refs"},
           {"version", "parent_version", "members", "pairs", "source_bindings", "usage_refs"})
    if value["version"] != canonical_hash({k:v for k,v in value.items() if k != "version"}):
        raise ValueError("Research pool integrity failure")
    if value["parent_version"] is not None:
        digest(value["parent_version"])
    for name in ("members", "pairs", "source_bindings", "usage_refs"):
        if not isinstance(value[name], list):
            raise ValueError("Pool collections must be arrays")
    keys = set()
    for member in value["members"]:
        fields(member, {"ref", "case", "feedback_hash", "identity"}, {"ref", "case", "feedback_hash", "identity"})
        fields(member["ref"], {"key", "hash"}, {"key", "hash"})
        text(member["ref"]["key"])
        digest(member["ref"]["hash"])
        digest(member["feedback_hash"])
        if member["ref"]["key"] in keys or member["case"].get("ref") != member["ref"]:
            raise ValueError("Duplicate or mismatched pool member")
        keys.add(member["ref"]["key"])
