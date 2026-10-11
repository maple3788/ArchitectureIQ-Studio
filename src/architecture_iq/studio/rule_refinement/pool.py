"""Frozen run-owned question pools and immutable challenge first-test ledgers."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from architecture_iq.kb.roles import _seal, read_receipt, exclusive_lock
from architecture_iq.kb.rules import public_views
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.studio.catalog import Catalog, _spec, _CANDIDATE_KEYS, _DATASET_KEYS
from architecture_iq.studio.datasets import DatasetStore, DatasetConflict
from architecture_iq.studio.pairs import pair_manifest
from .contracts import artifact_path, digest, fields, identifier, validate_pool
from .prediction import validate_public_case

NOVELTY_POLICY = "rule_challenge_v1"


def _case(record):
    # Catalog also returns code and source origins: neither is a model input.
    detail = record["detail"]
    dataset = _spec(detail["dataset"]["files"]["dataset_spec.json"],
                    _DATASET_KEYS - {"files", "synthesis", "task"})
    specs = [_spec(c["files"]["candidate_spec.json"], _CANDIDATE_KEYS - {"files"})
             for c in detail["choices"]]
    question = deepcopy(record["public"])
    value = {"ref": {"key": record["metadata"]["key"], "hash": record["metadata"]["hash"]},
             "question": question, "dataset_spec": dataset, "candidate_specs": specs,
             "objective": dataset.get("selection_metric")}
    validate_public_case(value)
    public_views(dataset, specs)  # Includes bounded expression validation.
    return value


def _identity(case):
    question, dataset = case["question"], case["dataset_spec"]
    instance = {k:v for k,v in dataset.items()
                if k not in {"dataset_id", "schema_version", "profile", "profile_hash", "selection_metric"}}
    candidate_content = [{k:v for k,v in spec.items()
                          if k not in {"candidate_id", "dataset_id", "profile", "schema_version"}}
                         for spec in case["candidate_specs"]]
    candidate_hashes = sorted(canonical_hash(spec) for spec in candidate_content)
    result = {k:question.get(k) for k in ("dataset_id", "lineage_id", "pair_id")}
    result.update(instance_hash=canonical_hash(instance),
                  question_fingerprint=canonical_hash({"instance": instance, "candidates": candidate_hashes,
                                                       "objective": case["objective"]}),
                  novelty_policy=NOVELTY_POLICY)
    return result


def check_independence(existing: dict, incoming: dict) -> dict:
    overlap, missing = [], []
    by_field = {key: set() for key in ("dataset_id", "lineage_id", "pair_id", "instance_hash", "question_fingerprint")}
    old_keys = {m["ref"]["key"] for m in existing["members"]}
    for member in existing["members"]:
        for key in by_field:
            if member["identity"].get(key):
                by_field[key].add(member["identity"][key])
    fresh_keys = []
    for member in incoming["members"]:
        key, identity = member["ref"]["key"], member["identity"]
        reasons = []
        for required in ("dataset_id", "lineage_id", "instance_hash", "question_fingerprint"):
            if not identity.get(required):
                missing.append({"key": key, "field": required})
                reasons.append(required)
        if key in old_keys:
            overlap.append({"key":key, "field":"question_key"})
            reasons.append("question_key")
        for field, old_values in by_field.items():
            if identity.get(field) in old_values:
                overlap.append({"key":key, "field":field})
                reasons.append(field)
        if not reasons:
            fresh_keys.append(key)
    return {"policy": NOVELTY_POLICY, "overlap": overlap, "missing_identity": missing,
            "eligible": bool(incoming["members"]) and not overlap and not missing,
            "eligible_keys": fresh_keys,
            "independent_instances": len({m["identity"].get("instance_hash") for m in incoming["members"]
                                         if m["ref"]["key"] in fresh_keys})}


class PoolStore:
    def __init__(self, root: Path, catalog: Catalog):
        self.root, self.catalog = Path(root), catalog

    def _save(self, members, *, parent_version=None, pairs=None, bindings=None, usage=None):
        value = {"parent_version": parent_version, "members": deepcopy(members), "pairs": deepcopy(pairs or []),
                 "source_bindings": deepcopy(bindings or []), "usage_refs": list(usage or [])}
        value["version"] = canonical_hash(value)
        validate_pool(value)
        path = self.root / "pools" / (value["version"] + ".json")
        if path.exists():
            if self.get(value["version"]) != value:
                raise ValueError("Pool snapshot differs")
        else:
            write_json_atomic(path, value)
        return value

    def get(self, version: str) -> dict:
        value = json.loads((self.root / "pools" / (digest(version) + ".json")).read_text())
        validate_pool(value)
        if value["version"] != version:
            raise ValueError("Pool identity differs")
        return value

    def freeze_members(self, keys: list[str], *, pairs: list[dict] | None = None,
                       source_bindings: list[dict] | None = None, purpose: str = "research") -> dict:
        if not isinstance(keys, list) or len(set(keys)) != len(keys) or purpose not in {"research", "evaluation"}:
            raise ValueError("Pool requires unique exact question keys and a known purpose")
        records, members, grouped = [], [], {}
        for key in keys:
            record = self.catalog.get_question(key, include_private=True)
            if not record["metadata"].get("evaluation_ready"):
                raise ValueError("Question materials unavailable")
            if purpose == "research" and record["public"].get("split") != "discovery":
                raise ValueError("Research inputs must belong to discovery")
            if purpose == "evaluation" and record["public"].get("split") not in {"development", "final"}:
                raise ValueError("Evaluation inputs must belong to a held-out split")
            case = _case(record)
            members.append({"ref": case["ref"], "case": case,
                            "feedback_hash": canonical_hash(record["feedback"]), "identity": _identity(case)})
            records.append(record)
            pair_id = case["question"].get("pair_id")
            if pair_id:
                grouped.setdefault(pair_id, []).append(record)
        manifests = []
        for group in grouped.values():
            if len(group) != 2:
                raise ValueError("Research pool must preserve complete question pairs")
            manifest = pair_manifest(group)
            if not manifest.get("evaluation_ready"):
                raise ValueError("Question pair identities or materials are unavailable")
            manifests.append(manifest)
        if pairs is not None:
            if not isinstance(pairs, list) or {p["pair_key"] for p in pairs} != {p["pair_key"] for p in manifests}:
                raise ValueError("Frozen pair manifests do not match members")
            for pair in pairs:
                current = next(p for p in manifests if p["pair_key"] == pair["pair_key"])
                if [(m["key"],m["hash"]) for m in current["members"]] != [(m["key"],m["hash"]) for m in pair["members"]]:
                    raise ValueError("Frozen pair revisions differ")
            manifests = deepcopy(pairs)
        return self._save(members, pairs=manifests, bindings=source_bindings)

    def initialize(self, binding: dict) -> dict:
        fields(binding, {"collection_id","revision","selection","keys","hashes","pair_keys"},
               {"collection_id","revision","selection","keys","hashes","pair_keys"})
        if not binding["keys"]:
            raise ValueError("Initial research pool must be nonempty")
        source = DatasetStore(self.catalog).get(binding["collection_id"], binding["revision"])
        if any(key not in source["keys"] for key in binding["keys"]):
            raise ValueError("Selected questions do not belong to the fixed Dataset")
        pairs = [p for p in source["pairs"] if p["pair_key"] in binding["pair_keys"]]
        pool = self.freeze_members(binding["keys"], pairs=pairs if source["selection_mode"] == "pairs" else None,
                                   source_bindings=[binding])
        if [m["ref"]["hash"] for m in pool["members"]] != binding["hashes"]:
            raise ValueError("Dataset question revisions differ")
        record = _seal({"binding": deepcopy(binding), "pool_version": pool["version"]})
        with exclusive_lock(self.root / "pool.lock"):
            initial_path = self.root / "pool_initial.json"
            if initial_path.exists():
                if read_receipt(initial_path) != record:
                    raise ValueError("Initial research binding is immutable")
            else:
                write_json_atomic(initial_path, record)
            if not (self.root / "pool_current.json").exists():
                write_json_atomic(self.root / "pool_current.json", _seal({"version": pool["version"]}))
        return pool

    def _current_unlocked(self):
        pointer = read_receipt(self.root / "pool_current.json")
        # Complete a journaled promotion if the process died before pointer publication.
        promotions = [read_receipt(p) for p in (self.root / "promotions").glob("*.json")]
        while True:
            pending = [p for p in promotions if p["base_version"] == pointer["version"]]
            if not pending:
                return self.get(pointer["version"])
            if len(pending) != 1:
                raise ValueError("Conflicting pool promotion journals")
            self.get(pending[0]["version"])
            pointer = _seal({"version": pending[0]["version"]})
            write_json_atomic(self.root / "pool_current.json", pointer)

    def current(self) -> dict:
        with exclusive_lock(self.root / "pool.lock"):
            return self._current_unlocked()

    def public_cases(self, version: str) -> list[dict]:
        pool = self.get(version)
        result = []
        for member in pool["members"]:
            record = self.catalog.get_question(member["ref"]["key"])
            if not record["metadata"].get("evaluation_ready"):
                raise ValueError("Frozen question source is unavailable")
            case = _case(record)
            if case != member["case"]:
                raise ValueError("Frozen public question integrity differs")
            result.append(deepcopy(case))
        return result

    def batches(self) -> list[dict]:
        return sorted((read_receipt(p) for p in (self.root / "batches").glob("*.json")), key=lambda b:b["index"])

    def record_first_test(self, batch_id: str, *, pool: dict, score: dict, generation: dict) -> dict:
        validate_pool(pool)
        if self.get(pool["version"]) != pool:
            raise ValueError("Unknown frozen challenge pool")
        saved_score = read_receipt(artifact_path(self.root, score["receipt_ref"], kind="scores"))
        if saved_score != score or score["pool_version"] != pool["version"]:
            raise ValueError("First score must be the sealed score of the complete challenge")
        prediction = read_receipt(artifact_path(self.root, score["prediction_receipt"], kind="predictions"))
        if prediction["pool_version"] != pool["version"] or prediction["kb"]["version"] != score["kb_version"]:
            raise ValueError("First score prediction binding differs")
        requested = generation.get("requested_question_count")
        if type(requested) is not int or requested < 1:
            raise ValueError("Challenge must record the requested question count")
        keys = [m["ref"]["key"] for m in pool["members"]]
        if keys != generation.get("question_keys"):
            raise ValueError("Challenge admission cannot filter or replace generated questions")
        reference = f"batches/{identifier(batch_id)}.json"
        path = artifact_path(self.root, reference, kind="batches")
        with exclusive_lock(self.root / "pool.lock"):
            if path.exists():
                prior = read_receipt(path)
                if prior["first_score"] != score or prior["generation"] != generation or prior["pool_version"] != pool["version"]:
                    raise ValueError("First test is immutable")
                return prior
            current = self._current_unlocked()
            previous = self.batches()
            seen_members = list(current["members"])
            for old in previous:
                seen_members.extend(self.get(old["pool_version"])["members"])
            novelty = check_independence({"members": seen_members}, pool)
            record = _seal({"batch_id": batch_id, "index": len(previous)+1, "state": "revealed",
                            "pool_version": pool["version"], "base_pool_version": current["version"],
                            "kb_version": score["kb_version"], "requested": requested, "actual": len(keys),
                            "eligible": len(novelty["eligible_keys"]), "novelty": novelty,
                            "first_score": deepcopy(score), "generation": deepcopy(generation),
                            "batch_passed": generation.get("outcome") == "complete" and requested == len(keys)
                                and novelty["eligible"] and score["all_pass"]})
            write_json_atomic(path, record)
            return record

    def promote(self, batch_id: str, *, expected_pool_version: str) -> dict:
        batch = read_receipt(artifact_path(self.root, f"batches/{identifier(batch_id)}.json", kind="batches"))
        path = self.root / "promotions" / (batch_id + ".json")
        with exclusive_lock(self.root / "pool.lock"):
            current = self._current_unlocked()
            if path.exists():
                saved = read_receipt(path)
                if saved["base_version"] != expected_pool_version:
                    raise DatasetConflict("Promotion was based on another pool")
                return self.get(saved["version"])
            if current["version"] != expected_pool_version or batch["base_pool_version"] != current["version"]:
                raise DatasetConflict("Research pool changed before admission")
            incoming = self.get(batch["pool_version"])
            self.public_cases(incoming["version"])
            members = {m["ref"]["key"]: m for m in current["members"]}
            for member in incoming["members"]:
                key = member["ref"]["key"]
                if key in members and member != members[key]:
                    raise ValueError("Question key cannot change frozen content")
                members[key] = member
            pairs = {p["pair_key"]:p for p in current["pairs"]}
            pairs.update({p["pair_key"]:p for p in incoming["pairs"]})
            updated = self._save(list(members.values()), parent_version=current["version"],
                                 pairs=list(pairs.values()), bindings=current["source_bindings"],
                                 usage=current["usage_refs"] + [f"batches/{batch_id}.json"])
            write_json_atomic(path, _seal({"batch_id":batch_id, "base_version":current["version"],
                                          "version":updated["version"], "first_test_hash":batch["receipt_hash"]}))
            write_json_atomic(self.root / "pool_current.json", _seal({"version":updated["version"]}))
            return updated
