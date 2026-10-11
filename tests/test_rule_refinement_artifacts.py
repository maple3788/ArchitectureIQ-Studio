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


def native_document(*, status="replicated_in_scope", inject=False, parents=None):
    return {"schema_version": "kb_claim_rules_v1", "kind": "kb-revision-proposal",
            "parent": "kb_v9_revision.json", "legacy_disposition": {"K1": "superseded by R2"},
            "claims": [{"id": "R2", "text": "A scoped source claim", "revision": 1,
                        "status": "testable", "kind": "architecture", "validity_status": status,
                        "inject": inject, "inject_same": [], "parents": parents or ["K1"],
                        "operation": "merge", "dev_evidence": "49/49 independent lineages",
                        "usage_note": "Do not inject into parameter-banded comparisons",
                        "rules": [rule_entry()["rule"], rule_entry(lower=True)["rule"]]}]}


def test_native_document_splits_clauses_and_preserves_source_restrictions(tmp_path):
    store = make_store(tmp_path)
    protocol = {"kind": "pre-registration", "decision_rule": {"alpha": "0.05/6"},
                "claims": [{"id": "R2", "role": "confirmatory", "rules": [rule_entry()["rule"]]}]}
    snapshot = store.import_rules(native_document(), source_ref={"id": "v10"},
                                  source_document={"version_label": "v10", "file_sha256": "a"*64},
                                  confirmation_protocol=protocol)
    assert len(snapshot["rules"]) == 2
    for index, rule in enumerate(snapshot["rules"], 1):
        assert rule["metadata"] == {
            "claim_id": "R2", "clause_index": index, "revision": 1,
            "status": "testable", "kind": "architecture", "validity_status": "replicated_in_scope",
            "validation_origin": "source_reported", "inject": False, "inject_same": [],
            "parents": ["K1"], "operation": "merge", "dev_evidence": "49/49 independent lineages",
            "usage_note": "Do not inject into parameter-banded comparisons", "role": "confirmatory"}
        assert rule["source_refs"][0]["source_clause_index"] == index
    assert snapshot["source_document"]["parent"] == "kb_v9_revision.json"
    assert snapshot["source_document"]["legacy_disposition"] == {"K1": "superseded by R2"}
    assert snapshot["source_document"]["version_label"] == "v10"
    assert snapshot["confirmation_protocol"] == protocol
    assert store.get(snapshot["version"]) == snapshot


def test_native_version_links_resolve_exact_parent_claims(tmp_path):
    store = make_store(tmp_path)
    v9 = store.import_rules(native_document(status="proposed"), source_ref={"id": "v9"})
    v10 = store.import_rules(native_document(parents=["v9 R2 (replicated)"]), source_ref={"id": "v10"},
                            parent_version=v9["version"], parent_snapshot=v9)
    assert v10["parent_version"] == v9["version"]
    assert all(r["parents"] == [target(p) for p in v9["rules"]] for r in v10["rules"])
    with pytest.raises(ValueError):
        store.import_rules(native_document(), source_ref={"id": "v10"},
                           parent_version="b"*64, parent_snapshot=v9)


@pytest.mark.parametrize("op", ["edit", "split", "merge", "retire"])
def test_patch_cannot_inherit_confirmed_status_or_reenable_injection(tmp_path, op):
    store = make_store(tmp_path)
    before = store.import_rules(native_document(), source_ref={"id": "v10"})
    first, second = before["rules"]
    operation = ({"op": op, **target(first), "entry": rule_entry()} if op == "edit" else
                 {"op": op, **target(first)} if op == "retire" else
                 {"op": op, "targets": [target(first)] if op == "split" else [target(first), target(second)],
                  "entries": [rule_entry(), rule_entry(lower=True)] if op == "split" else [rule_entry()]})
    after = store.apply_patch(before["version"], patch(before, operation))
    assert after["source_document"] == before["source_document"]
    for rule in after["rules"]:
        assert rule["metadata"]["inject"] is False
        if rule["parents"] and rule["state"] == "active":
            assert rule["metadata"]["validity_status"] == "proposed"
            assert rule["metadata"]["validation_origin"] == "modified_in_studio"
        else:
            assert rule["metadata"]["validity_status"] == "replicated_in_scope"
    assert store.get(before["version"]) == before


def test_patch_metadata_cannot_forge_source_certification_and_add_is_proposed(tmp_path):
    store = make_store(tmp_path)
    before = initial(store)
    forged = {**rule_entry(), "metadata": {"validity_status": "replicated_in_scope",
              "validation_origin": "source_reported", "inject": True}}
    with pytest.raises(ValueError):
        store.apply_patch(before["version"], patch(before, {"op": "add", "entry": forged}))
    after = store.apply_patch(before["version"], patch(before, {"op": "add", "entry": rule_entry()}))
    added = next(r for r in after["rules"] if r["rule_id"] != before["rules"][0]["rule_id"])
    assert added["metadata"]["validity_status"] == "proposed"
    assert added["metadata"]["validation_origin"] == "modified_in_studio"


@pytest.mark.parametrize("field,value", [("inject", 1), ("inject_same", ["correct_letter"]),
    ("inject_same", ["depth", "depth"]), ("validity_status", "always_true"),
    ("parents", [False]), ("role", "auto-certified")])
def test_native_document_rejects_unsafe_or_invalid_metadata(tmp_path, field, value):
    doc = native_document()
    doc["claims"][0][field] = value
    with pytest.raises(ValueError):
        make_store(tmp_path).import_rules(doc, source_ref={"id": "bad"})


def test_schema_one_snapshot_without_metadata_imports_without_rehashing(tmp_path):
    from architecture_iq.kb.store import canonical_hash
    from architecture_iq.studio.rule_refinement.artifacts import executable_hash
    old_rule = {"rule_id": "old_rule", **rule_entry(), "rationale": "", "parents": [],
                "source_refs": [{"id": "frozen"}], "state": "active"}
    old_rule["revision"] = canonical_hash(old_rule)
    snapshot = {"kind": "research_rules", "schema_version": 1, "parent_version": None,
                "rules": [old_rule], "executable_hash": executable_hash([old_rule]), "import_issues": []}
    snapshot["version"] = canonical_hash(snapshot)
    store = make_store(tmp_path)
    assert store.import_rules(snapshot, source_ref={"id": "archive"}) == snapshot
    assert store.get(snapshot["version"]) == snapshot
    with pytest.raises(ValueError):
        store.import_rules(snapshot, source_ref={"id": "archive"}, source_document={"version_label": "changed"})


@pytest.mark.parametrize("field,value", [("validity_status", []), ("role", {}), ("status", []),
                                      ("revision", True), ("inject_same", [{}])])
def test_malformed_native_metadata_raises_validation_error(tmp_path, field, value):
    document = native_document()
    document["claims"][0][field] = value
    with pytest.raises(ValueError):
        make_store(tmp_path).import_rules(document, source_ref={"id": "malformed"})


def test_source_parent_tokens_do_not_match_partial_or_different_version_ids(tmp_path):
    store = make_store(tmp_path)
    parent = store.import_rules(native_document(), source_ref={"id": "v9"},
                                source_document={"version_label": "v9"})
    child = store.import_rules(native_document(parents=["R20 (different claim)", "v8 R2 (older version)"]),
                              source_ref={"id": "v10"}, parent_snapshot=parent)
    assert all(rule["parents"] == [] for rule in child["rules"])


def test_metadata_tampering_is_detected_and_document_overrides_are_rejected(tmp_path):
    store = make_store(tmp_path)
    before = store.import_rules(native_document(), source_ref={"id": "v10"})
    changed = deepcopy(before)
    changed["rules"][0]["metadata"]["inject"] = True
    with pytest.raises(ValueError):
        store.import_rules(changed, source_ref={"id": "tampered"})
    with pytest.raises(ValueError):
        store.import_rules(native_document(), source_ref={"id": "v10"},
                           source_document={"parent": "invented_history.json"})


@pytest.mark.parametrize("label,matched", [("v9", True), ("KB v9", True),
                                        ("v90", False), ("KB v90", False),
                                        ("custom KB v9 rules", False)])
def test_display_version_labels_preserve_exact_library_rule_parents(tmp_path, label, matched):
    store = make_store(tmp_path)
    parent = store.import_rules(native_document(), source_ref={"id": "kb-v9"},
                                source_document={"version_label": label})
    child = store.import_rules(native_document(parents=["v9 R2 (REPLICATED on controlled_arch_v2)"]),
                              source_ref={"id": "kb-v10"}, parent_snapshot=parent)
    expected = [target(rule) for rule in parent["rules"]] if matched else []
    assert all(rule["parents"] == expected for rule in child["rules"])
