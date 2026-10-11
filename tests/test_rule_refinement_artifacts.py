from copy import deepcopy
import json

import pytest

from rule_refinement_fixtures import limits, rule_entry


def make_store(tmp_path):
    from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
    return RuleArtifactStore(tmp_path)


def initial(store, entries=None):
    return store.import_rules({"rules": entries or [rule_entry()]}, source_ref={"id": "fixture"})


def patch(kb, *operations):
    return {"base_version": kb["version"], "operations": list(operations),
            "rationale": "Repair bounded conditions", "case_refs": []}


def target(rule):
    return {"rule_id": rule["rule_id"], "revision": rule["revision"]}


def test_revision_is_immutable_and_split_preserves_parents(tmp_path):
    store = make_store(tmp_path)
    original = initial(store)
    before = (tmp_path / "kb" / (original["version"] + ".json")).read_bytes()
    old = original["rules"][0]
    divided = store.apply_patch(original["version"], patch(original, {
        "op": "split", "targets": [target(old)],
        "entries": [rule_entry((32, 16)), rule_entry((16, 8))]}))
    active = [r for r in divided["rules"] if r["state"] == "active"]
    assert len(active) == 2
    assert all(r["parents"] == [target(old)] for r in active)
    assert (tmp_path / "kb" / (original["version"] + ".json")).read_bytes() == before
    assert not (tmp_path / "CURRENT").exists()
    merged = store.apply_patch(divided["version"], patch(divided, {
        "op": "merge", "targets": [target(r) for r in active], "entries": [rule_entry()]}))
    active = [r for r in merged["rules"] if r["state"] == "active"]
    assert len(active) == 1 and len(active[0]["parents"]) == 2
    retired = store.apply_patch(merged["version"], patch(merged, {"op": "retire", **target(active[0])}))
    assert not [r for r in retired["rules"] if r["state"] == "active"]


def test_text_change_and_duplicate_dsl_do_not_create_executable_progress(tmp_path):
    store = make_store(tmp_path)
    old = initial(store)
    edited = store.apply_patch(old["version"], patch(old, {
        "op": "edit", **target(old["rules"][0]), "entry": rule_entry(text="Updated explanation")}))
    duplicate = store.apply_patch(old["version"], patch(old, {"op": "add", "entry": rule_entry()}))
    assert edited["version"] != old["version"]
    assert edited["executable_hash"] == old["executable_hash"] == duplicate["executable_hash"]
    assert store.apply_patch(old["version"], patch(old, {"op": "add", "entry": rule_entry()})) == duplicate


@pytest.mark.parametrize("field", ["correct_letter", "candidate_id", "dataset_id", "path"])
def test_hidden_fields_and_forged_evidence_are_rejected(tmp_path, field):
    entry = rule_entry()
    entry["rule"]["scope"] = [field, "eq", "memorized"]
    with pytest.raises(ValueError):
        initial(make_store(tmp_path), [entry])
    entry = {**rule_entry(), "evidence": {"status": "replicated_in_scope"}}
    with pytest.raises(ValueError):
        initial(make_store(tmp_path), [entry])


def test_unknown_patch_fields_stale_targets_and_conflicting_operations_reject(tmp_path):
    store = make_store(tmp_path)
    kb = initial(store)
    op = {"op": "retire", **target(kb["rules"][0])}
    for value in [{**patch(kb, op), "score": 1}, patch(kb, op, op),
                  patch(kb, {**op, "revision": "0"*64}), {**patch(kb, op), "base_version": "0"*64}]:
        with pytest.raises(ValueError):
            store.apply_patch(kb["version"], value)


def test_limits_match_approved_defaults_and_require_resources():
    from architecture_iq.studio.rule_refinement.contracts import validate_limits
    result = validate_limits(limits())
    assert [result[k] for k in ("max_revision_attempts", "max_no_progress", "max_generation_attempts",
                                "questions_per_batch", "max_new_questions", "required_fresh_passes")] == [12,3,3,16,48,2]
    for value in [{}, limits(max_tokens=0), limits(max_tokens=True), limits(max_model_calls=float("nan")),
                  limits(required_fresh_passes=4), limits(max_new_questions=8), limits(extra=1)]:
        with pytest.raises(ValueError):
            validate_limits(value)


def test_hash_tampering_and_unsafe_references_fail(tmp_path):
    store = make_store(tmp_path)
    kb = initial(store)
    path = tmp_path / "kb" / (kb["version"] + ".json")
    altered = deepcopy(kb)
    altered["rules"][0]["text"] = "tampered"
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError):
        store.get(kb["version"])
    with pytest.raises(ValueError):
        store.get("../escape")
    with pytest.raises(ValueError):
        store.save_proposal("../escape", {})


def test_legacy_clauses_preserve_source_and_report_uncompiled(tmp_path):
    store = make_store(tmp_path)
    snapshot = store.import_rules({
        "claims": [{"id": "legacy", "text": "two clauses"}, {"id": "prose", "text": "unknown"}],
        "compiled_rules": {"schema_version": "kb_claim_rules_v1", "claims": [
            {"id": "legacy", "status": "testable", "rules": [rule_entry()["rule"], rule_entry(lower=True)["rule"]]},
            {"id": "prose", "status": "untestable", "rules": []}]}}, source_ref={"id": "old"})
    assert len(snapshot["rules"]) == 2
    assert [r["source_refs"][0]["source_clause_index"] for r in snapshot["rules"]] == [1, 2]
    assert snapshot["import_issues"] == [{"source_id": "prose", "reason": "uncompiled"}]
    assert all(r["state"] == "active" for r in snapshot["rules"])
    assert "replicated_in_scope" not in json.dumps(snapshot)


def test_research_import_rejects_self_parent_even_when_outer_hash_is_recomputed(tmp_path):
    from architecture_iq.kb.store import canonical_hash
    store = make_store(tmp_path)
    value = initial(store)
    r = value["rules"][0]
    r["parents"] = [target(r)]
    value["version"] = canonical_hash({k: v for k,v in value.items() if k != "version"})
    with pytest.raises(ValueError):
        store.import_rules(value, source_ref={"id": "external"})


def test_proposals_are_idempotent_but_cannot_be_overwritten(tmp_path):
    store = make_store(tmp_path)
    assert store.save_proposal("attempt-1", {"raw": "bad"}) == store.save_proposal("attempt-1", {"raw": "bad"})
    with pytest.raises(ValueError):
        store.save_proposal("attempt-1", {"raw": "different"})
