"""Source-reported rule context, separate from Studio execution evidence.

Metadata never certifies a rule. Model-authored patches cannot set it, and any
changed conclusion loses the source document's validation status.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from architecture_iq.kb.rules import CONTROL_FIELDS
from architecture_iq.kb.store import canonical_hash
from .contracts import fields, text

VALIDITY_STATUSES = frozenset({"proposed", "replicated_in_scope", "refuted", "inconclusive", "legacy_unverified"})
METADATA_FIELDS = frozenset({"claim_id", "clause_index", "validity_status", "validation_origin", "inject",
    "inject_same", "parents", "operation", "dev_evidence", "usage_note", "role", "kind", "status", "revision"})
SOURCE_CLAIM_FIELDS = METADATA_FIELDS - {"claim_id", "clause_index", "validation_origin"}


def validate_document(value: dict) -> None:
    """Bound passive source/protocol JSON without interpreting it as instructions."""
    if not isinstance(value, dict):
        raise ValueError("Source document and confirmation protocol must be objects")
    canonical_hash(value)
    if len(json.dumps(value, ensure_ascii=False)) > 2_000_000:
        raise ValueError("Source document exceeds the stored metadata limit")


def validate_metadata(value: dict) -> None:
    fields(value, METADATA_FIELDS, {"validity_status", "validation_origin", "inject"})
    if not isinstance(value["validity_status"], str) or value["validity_status"] not in VALIDITY_STATUSES:
        raise ValueError("Unknown rule validity status")
    if not isinstance(value["validation_origin"], str) or value["validation_origin"] not in {"source_reported", "modified_in_studio"}:
        raise ValueError("Unknown validation origin")
    if value["validation_origin"] == "modified_in_studio" and value["validity_status"] != "proposed":
        raise ValueError("Studio modifications require fresh confirmation")
    if type(value["inject"]) is not bool:
        raise ValueError("inject must be a boolean")
    if "inject_same" in value:
        controls = value["inject_same"]
        if (not isinstance(controls, list) or len(controls) > 64 or
                any(not isinstance(item, str) or item not in CONTROL_FIELDS for item in controls) or
                len(set(controls)) != len(controls)):
            raise ValueError("inject_same must contain unique public control fields")
    if "parents" in value:
        parents = value["parents"]
        if not isinstance(parents, list) or len(parents) > 128:
            raise ValueError("Invalid symbolic rule parents")
        for parent in parents:
            text(parent, maximum=1000)
    for name in ("clause_index", "revision"):
        if name in value and (type(value[name]) is not int or not 1 <= value[name] <= 100000):
            raise ValueError(f"{name} must be a positive integer")
    for name in ("claim_id", "operation", "dev_evidence", "usage_note", "kind"):
        if name in value:
            text(value[name], maximum=16000 if name in {"dev_evidence", "usage_note"} else 1000)
    if "role" in value and (not isinstance(value["role"], str) or value["role"] not in {"confirmatory", "exploratory", "descriptive"}):
        raise ValueError("Unknown confirmation role")
    if "status" in value and (not isinstance(value["status"], str) or value["status"] not in {"testable", "partial", "untestable"}):
        raise ValueError("Unknown rule compilation status")


def source_metadata(claim: dict, clause_index: int, *, role: str | None = None) -> dict:
    result = {key: deepcopy(claim[key]) for key in SOURCE_CLAIM_FIELDS if key in claim}
    result.update(claim_id=claim["id"], clause_index=clause_index,
                  validity_status=claim.get("validity_status", "proposed"),
                  validation_origin="source_reported", inject=claim.get("inject", True))
    if role is not None:
        if "role" in result and result["role"] != role:
            raise ValueError("Source and confirmation protocol roles disagree")
        result["role"] = role
    validate_metadata(result)
    return result


def modified_metadata(targets: list[dict]) -> dict:
    # One source retains its descriptive context. A merge has no single source
    # claim identity; its exact parents/source_refs carry all source identities.
    result = deepcopy(targets[0].get("metadata", {})) if len(targets) == 1 else {}
    result.update(validity_status="proposed", validation_origin="modified_in_studio",
                  inject=all(rule.get("metadata", {}).get("inject", True) for rule in targets))
    if len(targets) > 1:
        result["parents"] = list(dict.fromkeys(parent for rule in targets
            for parent in rule.get("metadata", {}).get("parents", [])))
        # Never relax a parent's injection equality conditions when merging.
        result["inject_same"] = list(dict.fromkeys(field for rule in targets
            for field in rule.get("metadata", {}).get("inject_same", rule["rule"].get("same", []))))
    validate_metadata(result)
    return result


def resolve_parents(symbolic: list[str], parent_snapshot: dict | None) -> list[dict]:
    if parent_snapshot is None:
        return []
    # Source documents use e.g. "v9 R1 (REPLICATED ...)", "K0074 (depth half)"
    # and "R2 usage limit". Match only the first claim token, never substrings.
    wanted = set()
    parent_label = parent_snapshot.get("source_document", {}).get("version_label")
    # The library's display label is "KB v9"; legacy imports may use "v9".
    # Do not guess versions from arbitrary titles or match v9 inside v90.
    label_match = re.fullmatch(r"(?:KB )?(v[0-9]+)", parent_label) if isinstance(parent_label, str) else None
    normalized_label = label_match.group(1) if label_match else None
    for parent in symbolic:
        match = re.match(r"^(?:(v[0-9]+)\s+)?([A-Za-z0-9][A-Za-z0-9_-]*)(?:\s|$)", parent)
        if match and (not parent_label or not match.group(1) or match.group(1) == normalized_label):
            wanted.add(match.group(2))
    return [{"rule_id": rule["rule_id"], "revision": rule["revision"]}
            for rule in parent_snapshot["rules"]
            if (rule.get("metadata", {}).get("claim_id") in wanted or
                any(ref.get("source_claim_id") in wanted for ref in rule["source_refs"]))]
