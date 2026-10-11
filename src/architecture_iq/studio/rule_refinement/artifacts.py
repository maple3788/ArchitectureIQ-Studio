"""Immutable research rules, lineage-preserving proposals and candidate snapshots."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from architecture_iq.kb.legacy import import_legacy_claims
from architecture_iq.kb.roles import exclusive_lock, _seal, read_receipt
from architecture_iq.kb.rules import validate_rule
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from .contracts import PREDICTOR_VERSION, digest, fields, identifier, text
from .metadata import (modified_metadata, resolve_parents, source_metadata,
                       validate_document, validate_metadata)


def executable_hash(rules: list[dict]) -> str:
    unique = {canonical_hash(r["rule"]): r["rule"] for r in rules if r["state"] == "active"}
    return canonical_hash({"predictor": PREDICTOR_VERSION, "rules": [unique[k] for k in sorted(unique)]})


def _entry(value: dict) -> dict:
    fields(value, {"text", "rationale", "rule"}, {"text", "rule"})
    text(value["text"], maximum=16000)
    text(value.get("rationale", ""), required=False)
    validate_rule(value["rule"])
    return {"text": value["text"], "rationale": value.get("rationale", ""), "rule": deepcopy(value["rule"])}


def _revision(rule_id: str, entry: dict, *, parents: list[dict], source_refs: list[dict], state="active", metadata=None) -> dict:
    value = {"rule_id": identifier(rule_id), **_entry(entry), "parents": deepcopy(parents),
             "source_refs": deepcopy(source_refs), "state": state}
    if metadata is not None:
        validate_metadata(metadata)
        value["metadata"] = deepcopy(metadata)
    return {**value, "revision": canonical_hash(value)}


def validate_snapshot(value: dict) -> None:
    fields(value, {"kind", "schema_version", "version", "parent_version", "rules", "executable_hash", "import_issues", "source_document", "confirmation_protocol"},
           {"kind", "schema_version", "version", "parent_version", "rules", "executable_hash", "import_issues"})
    if value["kind"] != "research_rules" or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported research rule snapshot")
    if value["version"] != canonical_hash({k: v for k, v in value.items() if k != "version"}):
        raise ValueError("KB snapshot integrity failure")
    if value["parent_version"] is not None:
        digest(value["parent_version"])
        if value["parent_version"] == value["version"]:
            raise ValueError("Cyclic KB parent")
    for name in ("source_document", "confirmation_protocol"):
        if name in value:
            validate_document(value[name])
    rules = value["rules"]
    if not isinstance(rules, list) or len(rules) > 1000 or not isinstance(value["import_issues"], list):
        raise ValueError("Invalid research rule collection")
    seen = set()
    for rule in rules:
        fields(rule, {"rule_id", "revision", "parents", "text", "rationale", "rule", "state", "source_refs", "metadata"},
               {"rule_id", "revision", "parents", "text", "rationale", "rule", "state", "source_refs"})
        if "metadata" in rule:
            validate_metadata(rule["metadata"])
        identifier(rule["rule_id"])
        if rule["rule_id"] in seen or rule["state"] not in {"active", "retired"}:
            raise ValueError("Duplicate rule identity or invalid state")
        seen.add(rule["rule_id"])
        _entry({k: rule[k] for k in ("text", "rationale", "rule")})
        if not isinstance(rule["parents"], list) or not isinstance(rule["source_refs"], list):
            raise ValueError("Invalid rule provenance")
        for parent in rule["parents"]:
            fields(parent, {"rule_id", "revision"}, {"rule_id", "revision"})
            identifier(parent["rule_id"])
            digest(parent["revision"])
            if parent == {"rule_id": rule["rule_id"], "revision": rule["revision"]}:
                raise ValueError("Cyclic rule parent")
        if rule["revision"] != canonical_hash({k: v for k, v in rule.items() if k != "revision"}):
            raise ValueError("Rule revision integrity failure")
    if value["executable_hash"] != executable_hash(rules):
        raise ValueError("Executable rule hash mismatch")


class RuleArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _save(self, rules, *, parent_version=None, import_issues=None, source_document=None, confirmation_protocol=None):
        value = {"kind": "research_rules", "schema_version": 1, "parent_version": parent_version,
                 "rules": rules, "executable_hash": executable_hash(rules), "import_issues": import_issues or []}
        for key, metadata in (("source_document", source_document), ("confirmation_protocol", confirmation_protocol)):
            if metadata is not None:
                validate_document(metadata)
                value[key] = deepcopy(metadata)
        value["version"] = canonical_hash(value)
        validate_snapshot(value)
        return self._save_snapshot(value)

    def _save_snapshot(self, value):
        path = self.root / "kb" / (value["version"] + ".json")
        with exclusive_lock(self.root / "artifacts.lock"):
            if path.exists():
                if self.get(value["version"]) != value:
                    raise ValueError("Immutable snapshot differs")
            else:
                write_json_atomic(path, value)
        return deepcopy(value)

    def get(self, version: str) -> dict:
        value = json.loads((self.root / "kb" / (digest(version) + ".json")).read_text())
        validate_snapshot(value)
        if value["version"] != version:
            raise ValueError("Snapshot reference mismatch")
        return value

    def import_rules(self, source: dict, *, source_ref: dict, source_document: dict | None = None,
                     confirmation_protocol: dict | None = None, parent_version: str | None = None,
                     parent_snapshot: dict | None = None) -> dict:
        canonical_hash(source_ref)
        if not isinstance(source, dict):
            raise ValueError("Rule import requires an object")
        canonical_hash(source)
        if source.get("kind") == "research_rules":
            validate_snapshot(source)
            if any(value is not None for value in (source_document, confirmation_protocol, parent_version, parent_snapshot)):
                raise ValueError("Frozen snapshot metadata cannot be overwritten during import")
            return self._save_snapshot(deepcopy(source))
        if parent_snapshot is not None:
            validate_snapshot(parent_snapshot)
            if parent_version is not None and parent_version != parent_snapshot["version"]:
                raise ValueError("Parent snapshot and version differ")
            parent_version = parent_snapshot["version"]
        if parent_version is not None:
            digest(parent_version)
        if source_document is not None:
            validate_document(source_document)
        if confirmation_protocol is not None:
            validate_document(confirmation_protocol)
        if source.get("schema_version") == "kb_claim_rules_v1":
            return self._import_native(source, source_ref=source_ref, source_document=source_document,
                                       confirmation_protocol=confirmation_protocol,
                                       parent_version=parent_version, parent_snapshot=parent_snapshot)
        entries, issues = [], []
        if "compiled_rules" in source:
            fields(source, {"claims", "compiled_rules"}, {"claims", "compiled_rules"})
            claims = import_legacy_claims(source["claims"], source["compiled_rules"])
        elif "claims" in source:
            # A server-selected existing formal snapshot is copied as hypotheses only.
            if not isinstance(source["claims"], list):
                raise ValueError("Invalid source claims")
            claims = deepcopy(source["claims"])
        else:
            fields(source, {"rules"}, {"rules"})
            if not isinstance(source["rules"], list):
                raise ValueError("Rules must be a list")
            claims = None
            for index, entry in enumerate(source["rules"]):
                entries.append((_entry(entry), {**source_ref, "source_index": index}))
        if claims is not None:
            for claim in claims:
                if claim.get("rule") is None:
                    issues.append({"source_id": claim.get("id"), "reason": "uncompiled"})
                    continue
                entry = _entry({"text": claim["text"], "rule": claim["rule"]})
                ref = {**source_ref, "source_claim_id": claim.get("source_claim_id", claim["id"])}
                if "source_clause_index" in claim:
                    ref["source_clause_index"] = claim["source_clause_index"]
                entries.append((entry, ref))
        rules = [_revision("rule_" + canonical_hash({"entry": entry, "source": ref, "ordinal": i})[:24],
                           entry, parents=[], source_refs=[ref]) for i, (entry, ref) in enumerate(entries)]
        return self._save(rules, import_issues=issues, parent_version=parent_version,
                          source_document=source_document, confirmation_protocol=confirmation_protocol)

    def _import_native(self, source, *, source_ref, source_document, confirmation_protocol,
                       parent_version, parent_snapshot):
        claims = source.get("claims")
        if not isinstance(claims, list) or len(claims) > 1000:
            raise ValueError("Native rules require a bounded claims list")
        document = {k: deepcopy(v) for k, v in source.items() if k != "claims"}
        for key, value in (source_document or {}).items():
            if key in document and document[key] != value:
                raise ValueError("Source document metadata cannot overwrite original fields")
            document[key] = deepcopy(value)
        protocol_roles = {}
        if confirmation_protocol is not None:
            for claim in confirmation_protocol.get("claims", []):
                if isinstance(claim, dict) and isinstance(claim.get("id"), str) and "role" in claim:
                    if claim["id"] in protocol_roles:
                        raise ValueError("Duplicate confirmation claim identity")
                    protocol_roles[claim["id"]] = claim["role"]
        rules, issues, seen = [], [], set()
        for claim in claims:
            if not isinstance(claim, dict):
                raise ValueError("Native claim must be an object")
            claim_id = text(claim.get("id"), maximum=1000)
            text(claim.get("text"), maximum=16000)
            if claim_id in seen:
                raise ValueError("Duplicate native claim identity")
            seen.add(claim_id)
            clauses = claim.get("rules", [])
            if not isinstance(clauses, list) or len(clauses) > 128:
                raise ValueError("Native claim rules must be a bounded list")
            metadata = source_metadata(claim, 1, role=protocol_roles.get(claim_id))
            if claim.get("status") == "untestable" and clauses:
                raise ValueError("Untestable claim cannot contain executable clauses")
            if not clauses:
                issues.append({"source_id": claim_id, "reason": "uncompiled"})
            for index, clause in enumerate(clauses, 1):
                entry = _entry({"text": claim["text"], "rule": clause})
                metadata["clause_index"] = index
                ref = {**source_ref, "source_claim_id": claim_id, "source_clause_index": index}
                rid = "rule_" + canonical_hash({"entry": entry, "metadata": metadata, "source": ref})[:24]
                rules.append(_revision(rid, entry, metadata=metadata,
                    parents=resolve_parents(metadata.get("parents", []), parent_snapshot), source_refs=[ref]))
        return self._save(rules, import_issues=issues, parent_version=parent_version,
                          source_document=document, confirmation_protocol=confirmation_protocol)

    def apply_patch(self, base_version: str, patch: dict) -> dict:
        base = self.get(base_version)
        fields(patch, {"base_version", "operations", "rationale", "case_refs"},
               {"base_version", "operations", "rationale", "case_refs"})
        if patch["base_version"] != base_version:
            raise ValueError("Patch base version differs")
        text(patch["rationale"], required=False)
        if (not isinstance(patch["case_refs"], list) or
                any(not isinstance(ref, str) or len(ref) > 300 for ref in patch["case_refs"])):
            raise ValueError("Invalid case references")
        operations = patch["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= 128:
            raise ValueError("Patch requires 1–128 operations")
        rules = {r["rule_id"]: deepcopy(r) for r in base["rules"]}
        used = set()
        for ordinal, operation in enumerate(operations):
            if not isinstance(operation, dict):
                raise ValueError("Invalid patch operation")
            op = operation.get("op")
            expected = {"add": {"op", "entry"}, "edit": {"op", "rule_id", "revision", "entry"},
                        "retire": {"op", "rule_id", "revision"},
                        "split": {"op", "targets", "entries"}, "merge": {"op", "targets", "entries"}}
            if op not in expected:
                raise ValueError("Unsupported patch operation")
            fields(operation, expected[op], expected[op])
            targets = ([] if op == "add" else [{"rule_id": operation["rule_id"], "revision": operation["revision"]}]
                       if op in {"edit", "retire"} else operation["targets"])
            if not isinstance(targets, list):
                raise ValueError("Invalid patch targets")
            if op == "split" and len(targets) != 1 or op == "merge" and len(targets) < 2:
                raise ValueError("Invalid split/merge targets")
            parents, sources, source_rules = [], [], []
            for target in targets:
                fields(target, {"rule_id", "revision"}, {"rule_id", "revision"})
                identifier(target["rule_id"])
                old = rules.get(target["rule_id"])
                if (not old or old["state"] != "active" or old["revision"] != target["revision"]
                        or old["rule_id"] in used):
                    raise ValueError("Stale, conflicting or inactive patch target")
                used.add(old["rule_id"])
                parents.append(deepcopy(target))
                sources.extend(deepcopy(old["source_refs"]))
                source_rules.append(deepcopy(old))
            if op in {"retire", "split", "merge"}:
                for target in targets:
                    old = rules[target["rule_id"]]
                    entry = {k: old[k] for k in ("text", "rationale", "rule")}
                    rules[old["rule_id"]] = _revision(old["rule_id"], entry, parents=[target],
                                                    source_refs=old["source_refs"], state="retired", metadata=old.get("metadata"))
            entries = [] if op == "retire" else [operation["entry"]] if op in {"add", "edit"} else operation["entries"]
            if (not isinstance(entries, list) or op == "split" and len(entries) < 2
                    or op == "merge" and len(entries) != 1):
                raise ValueError("Invalid split/merge entries")
            for i, entry in enumerate(entries):
                rid = (targets[0]["rule_id"] if op == "edit" else
                       "rule_" + canonical_hash({"base": base_version, "patch": patch, "op": ordinal, "entry": i})[:24])
                rules[rid] = _revision(rid, entry, parents=parents, source_refs=sources,
                                       metadata=modified_metadata(source_rules))
        return self._save(list(rules.values()), parent_version=base_version, import_issues=base["import_issues"],
                          source_document=base.get("source_document"),
                          confirmation_protocol=base.get("confirmation_protocol"))

    def save_proposal(self, attempt_id: str, proposal: dict) -> dict:
        path = self.root / "proposals" / (identifier(attempt_id) + ".json")
        record = _seal({"attempt_id": attempt_id, "proposal": deepcopy(proposal)})
        with exclusive_lock(self.root / "artifacts.lock"):
            if path.exists():
                prior = read_receipt(path)
                if prior != record:
                    raise ValueError("Proposal is immutable")
                return prior
            write_json_atomic(path, record)
        return record
