"""Atomic, immutable KB snapshots with deterministic evidence-gated publication."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from .evidence import summarize_confirmation, validate_evidence, validate_sampling_envelope, verify_evidence_sources

_STATUSES = {"legacy_unverified", "proposed", "exploring", "replicated_in_scope", "refuted", "retired"}
_SEMANTIC = ("text", "rule", "experiment", "boundary", "competing_explanation")
_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be finite JSON") from exc


def canonical_hash(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    """Durably replace one JSON file, cleaning temporary files on failure."""
    path = Path(path)
    payload = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _nonempty(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _claim_shape(claim: dict) -> None:
    if not isinstance(claim, dict):
        raise ValueError("claim must be an object")
    for key in ("id", "text"):
        _nonempty(claim.get(key), key)
    if type(claim.get("revision")) is not int or claim["revision"] < 1:
        raise ValueError("claim revision must be a positive integer")
    if not isinstance(claim.get("status"), str) or claim["status"] not in _STATUSES:
        raise ValueError("invalid claim status")
    if type(claim.get("enabled")) is not bool:
        raise ValueError("claim enabled must be boolean")
    evidence = claim.get("evidence_ids")
    if not isinstance(evidence, list) or any(not isinstance(item, str) or not item for item in evidence) or len(set(evidence)) != len(evidence):
        raise ValueError("claim evidence_ids must be distinct strings")
    if claim.get("rule") is None:
        if claim["status"] != "legacy_unverified" or claim["enabled"]:
            raise ValueError("only disabled legacy claims may lack a compiled rule")
    else:
        from .rules import validate_rule
        validate_rule(claim["rule"])
    canonical_hash(claim)


class KBStore:
    """CURRENT is the commit point; completed snapshots are content addressed.

    ``initialize`` imports historical claims, preserving their metadata while
    clearing scientific authority. ``apply_patch`` is a program API: the
    coordinator must admit proposals only from its Curator role. This layer
    independently checks revisions, source files, outcomes and confirmation.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        with _LOCK_GUARD:
            self._thread_lock = _LOCKS.setdefault(str(self.root), threading.RLock())

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, (self.root / ".lock").open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _publish(self, payload: dict) -> dict:
        snapshot = {**payload, "version": canonical_hash(payload)}
        destination = self.root / "snapshots" / f'{snapshot["version"]}.json'
        if destination.exists():
            if json.loads(destination.read_text(encoding="utf-8")) != snapshot:
                raise ValueError("immutable snapshot integrity violation")
        else:
            write_json_atomic(destination, snapshot)
        # A crash here can leave a harmless unreachable snapshot, never a
        # half-published current version. The previous pointer remains valid.
        write_json_atomic(self.root / "CURRENT", {"version": snapshot["version"]})
        return deepcopy(snapshot)

    def initialize(self, claims: list[dict]) -> dict:
        with self._locked():
            if (self.root / "CURRENT").exists():
                return self.current()
            if not isinstance(claims, list):
                raise ValueError("initial claims must be a list")
            imported = []
            seen = set()
            for original in claims:
                if not isinstance(original, dict):
                    raise ValueError("initial claim must be an object")
                claim = deepcopy(original)
                if claim.get("evidence_ids"):
                    claim["legacy_evidence_ids"] = claim["evidence_ids"]
                claim.update(status="legacy_unverified", enabled=False, evidence_ids=[])
                claim.setdefault("revision", 1)
                claim.setdefault("rule", None)
                _claim_shape(claim)
                if claim["id"] in seen:
                    raise ValueError("duplicate claim ID")
                seen.add(claim["id"])
                imported.append(claim)
            return self._publish({"parent_version": None, "claims": sorted(imported, key=lambda item: item["id"]), "evidence": []})

    def current(self) -> dict:
        try:
            pointer = json.loads((self.root / "CURRENT").read_text(encoding="utf-8"))
            version = pointer["version"]
            if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
                raise ValueError("invalid CURRENT snapshot hash")
            snapshot = json.loads((self.root / "snapshots" / f"{version}.json").read_text(encoding="utf-8"))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid KB snapshot or CURRENT pointer") from exc
        if not isinstance(snapshot, dict) or snapshot.get("version") != version or canonical_hash({key: value for key, value in snapshot.items() if key != "version"}) != version:
            raise ValueError("KB snapshot hash integrity violation")
        return snapshot

    def apply_patch(self, patch: dict, evidence: list[dict]) -> dict:
        with self._locked():
            previous = self.current()
            if not isinstance(patch, dict):
                raise ValueError("stale or missing patch parent_version")
            # This receipt shares CURRENT's atomic commit. If publication
            # succeeded but its caller crashed before writing its round result,
            # replay returns that exact snapshot instead of creating a version
            # or rejecting the already committed operation. Bind full evidence
            # records as well as operations so altered interpretations cannot
            # masquerade as the same request merely by reusing evidence IDs.
            applied_patch_hash = canonical_hash({"patch": patch, "evidence": evidence})
            if patch.get("parent_version") != previous["version"]:
                if (patch.get("parent_version") == previous.get("parent_version")
                        and applied_patch_hash == previous.get("applied_patch_hash")):
                    return previous
                raise ValueError("stale or missing patch parent_version")
            operations = patch.get("operations")
            if not isinstance(operations, list) or not isinstance(evidence, list):
                raise ValueError("patch operations and evidence must be lists")
            if set(patch) - {"parent_version", "operations"}:
                raise ValueError("unknown patch fields")
            if not operations:
                return previous
            ledger = deepcopy(previous.get("evidence", []))
            ledger_by_key = {(item["id"], item["claim_id"], item["revision"]): item for item in ledger}
            for record in evidence:
                validate_evidence(record)
                key = (record["id"], record["claim_id"], record["revision"])
                if key in ledger_by_key:
                    if ledger_by_key[key] != record:
                        raise ValueError("immutable evidence source was changed")
                else:
                    verify_evidence_sources(record)
                    ledger_by_key[key] = deepcopy(record)
                    ledger.append(deepcopy(record))
            self._check_study_history(ledger)
            claims = {item["id"]: deepcopy(item) for item in previous["claims"]}
            for operation in operations:
                if not isinstance(operation, dict):
                    raise ValueError("patch operation must be an object")
                _nonempty(operation.get("reason"), "operation reason")
                op = operation.get("op")
                if op == "upsert":
                    if set(operation) - {"op", "claim", "reason"}:
                        raise ValueError("unknown upsert operation fields")
                    claim = deepcopy(operation.get("claim"))
                    _claim_shape(claim)
                    old = claims.get(claim["id"])
                    if old is None:
                        if claim["revision"] != 1 or claim.get("parent_revision") is not None:
                            raise ValueError("new claims must start at revision 1 without a parent")
                    else:
                        semantic_change = any(old.get(field) != claim.get(field) for field in _SEMANTIC)
                        revision_changed = claim["revision"] != old["revision"]
                        if semantic_change or revision_changed:
                            if claim["revision"] != old["revision"] + 1 or claim.get("parent_revision") != old["revision"]:
                                raise ValueError("semantic change requires next revision and matching parent_revision")
                            if set(old["evidence_ids"]) & set(claim["evidence_ids"]):
                                raise ValueError("a new semantic revision cannot inherit evidence")
                            if claim["status"] == "replicated_in_scope" and not claim["evidence_ids"]:
                                raise ValueError("new revision requires fresh independent confirmation")
                    self._check_claim_evidence(claim, ledger_by_key)
                    claims[claim["id"]] = claim
                elif op in {"retire", "set_enabled"}:
                    allowed = {"op", "id", "reason"} | ({"enabled"} if op == "set_enabled" else set())
                    if set(operation) - allowed:
                        raise ValueError("unknown patch operation fields")
                    identifier = operation.get("id")
                    if not isinstance(identifier, str) or identifier not in claims:
                        raise ValueError("operation references an unknown claim")
                    claim = claims[identifier]
                    if op == "retire":
                        claim.update(status="retired", enabled=False)
                    else:
                        if type(operation.get("enabled")) is not bool:
                            raise ValueError("set_enabled requires a boolean")
                        claim["enabled"] = operation["enabled"]
                        self._check_claim_evidence(claim, ledger_by_key)
                else:
                    raise ValueError("unknown patch operation")
            result = sorted(claims.values(), key=lambda item: item["id"])
            if result == previous["claims"] and ledger == previous.get("evidence", []):
                return previous
            return self._publish({"parent_version": previous["version"], "claims": result,
                                  "evidence": ledger, "applied_patch_hash": applied_patch_hash})

    @staticmethod
    def _check_claim_evidence(claim: dict, ledger: dict) -> None:
        if claim["enabled"] and claim["status"] != "replicated_in_scope":
            raise ValueError("unverified or retired claims cannot be enabled")
        records = []
        confirmation_envelopes = []
        for identifier in claim["evidence_ids"]:
            key = (identifier, claim["id"], claim["revision"])
            if key not in ledger:
                raise ValueError("claim references missing or wrong-revision evidence")
            record = ledger[key]
            plan = verify_evidence_sources(record, claim=claim)
            records.append(record)
            if record["phase"] == "confirmation":
                confirmation_envelopes.append(plan.get("sampling_envelope"))
        if claim["status"] == "replicated_in_scope":
            confirmation = [item for item in records if item["phase"] == "confirmation"]
            if not summarize_confirmation(confirmation)["passed"]:
                raise ValueError("claim has not passed independent confirmation")
            for envelope in confirmation_envelopes:
                validate_sampling_envelope(envelope)
            envelope = confirmation_envelopes[0]
            if any(other != envelope for other in confirmation_envelopes):
                raise ValueError("confirmation evidence has different sampling envelopes")
            if "validated_scope" in claim and claim["validated_scope"] != envelope:
                raise ValueError("proposed validated_scope differs from the confirmed sampling envelope")
            claim["validated_scope"] = deepcopy(envelope)
        else:
            # This is derived confirmation authority, never inherited by a new
            # hypothesis revision or supplied by a role's unverified metadata.
            claim.pop("validated_scope", None)

    @staticmethod
    def _check_study_history(ledger: list[dict]) -> None:
        batches: set[str] = set()
        revision_batches: dict[tuple[str, int], str] = {}
        observed: dict[str, tuple[str, str, int]] = {}
        for record in ledger:
            batch = record.get("plan_hash", "")
            identity = (batch, record["claim_id"], record["revision"])
            if record["phase"] == "confirmation":
                revision = (record["claim_id"], record["revision"])
                if revision in revision_batches and revision_batches[revision] != batch:
                    raise ValueError("a frozen revision may have only one confirmation attempt")
                revision_batches[revision] = batch
                batches.add(batch)
                if len(batches) > 3:
                    raise ValueError("global confirmation limit of three attempts exceeded")
            for lineage in ("lineage:" + record["lineage_id"], "dataset:" + record["dataset_id"], "source:" + record["id"]):
                prior = observed.get(lineage)
                if prior is not None and prior != identity and record["phase"] == "confirmation":
                    raise ValueError("confirmation reuses an already observed source or lineage")
                observed.setdefault(lineage, identity)
