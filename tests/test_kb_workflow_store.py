"""Publication is atomic and a revision cannot inherit scientific authority."""
from copy import deepcopy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from architecture_iq.kb.store import KBStore, canonical_hash, write_json_atomic


def claim(**kwargs):
    result = {"id": "claim", "revision": 1, "text": "A conditional hypothesis",
              "rule": None, "status": "legacy_unverified", "enabled": False,
              "evidence_ids": []}
    result.update(kwargs)
    return result


def patch(snapshot, *operations):
    return {"parent_version": snapshot["version"], "operations": list(operations)}


def test_legacy_authority_is_not_imported(tmp_path):
    store = KBStore(tmp_path)
    snapshot = store.initialize([claim(status="replicated_in_scope", enabled=True, credibility=.99)])
    imported = snapshot["claims"][0]
    assert imported["status"] == "legacy_unverified"
    assert imported["enabled"] is False
    assert imported["credibility"] == .99
    assert store.initialize([]) == snapshot


def test_unverified_cannot_enable_or_claim_confirmation(tmp_path):
    store = KBStore(tmp_path)
    snapshot = store.initialize([claim()])
    for operation in (
        {"op": "set_enabled", "id": "claim", "enabled": True, "reason": "model agrees"},
        {"op": "upsert", "claim": claim(status="replicated_in_scope"), "reason": "passed"},
    ):
        with pytest.raises(ValueError):
            store.apply_patch(patch(snapshot, operation), [])
    assert store.current() == snapshot


def test_semantic_change_requires_next_revision_and_resets_evidence(tmp_path):
    store = KBStore(tmp_path)
    snapshot = store.initialize([claim(evidence_ids=["old-fact"])])
    revised = deepcopy(snapshot["claims"][0])
    revised["text"] = "Narrower hypothesis"
    operation = {"op": "upsert", "claim": revised, "reason": "new scope"}
    with pytest.raises(ValueError, match="revision"):
        store.apply_patch(patch(snapshot, operation), [])
    revised.update(revision=2, parent_revision=1, evidence_ids=[])
    new = store.apply_patch(patch(snapshot, operation), [])
    assert new["claims"][0]["evidence_ids"] == []
    assert new["claims"][0]["enabled"] is False
    assert new["claims"][0]["status"] != "replicated_in_scope"
    assert json.loads((tmp_path / "snapshots" / f'{snapshot["version"]}.json').read_text()) == snapshot


def test_stale_patch_and_noop(tmp_path):
    store = KBStore(tmp_path)
    first = store.initialize([claim()])
    assert store.apply_patch(patch(first), []) == first
    second = store.apply_patch(patch(first, {"op": "retire", "id": "claim", "reason": "obsolete"}), [])
    assert second["version"] != first["version"]
    with pytest.raises(ValueError, match="parent|stale"):
        store.apply_patch(patch(first), [])


def test_concurrent_publish_has_one_winner(tmp_path):
    store = KBStore(tmp_path)
    first = store.initialize([claim()])
    def publish(index):
        proposal = patch(first, {"op": "retire", "id": "claim", "reason": f"proposal {index}"})
        try:
            return store.apply_patch(proposal, [])["version"]
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, range(2)))
    assert sum(result is not None for result in results) == 1
    assert store.current()["claims"][0]["status"] == "retired"


def test_failed_pointer_write_keeps_readable_previous_version(tmp_path, monkeypatch):
    import architecture_iq.kb.store as module
    store = KBStore(tmp_path)
    first = store.initialize([claim()])
    original = module.os.replace
    def fail_pointer(source, destination):
        if str(destination).endswith("CURRENT"):
            raise OSError("interrupted publication")
        return original(source, destination)
    monkeypatch.setattr(module.os, "replace", fail_pointer)
    with pytest.raises(OSError):
        store.apply_patch(patch(first, {"op": "retire", "id": "claim", "reason": "obsolete"}), [])
    assert store.current() == first


def test_hashes_and_current_detect_mutation(tmp_path):
    assert canonical_hash({"x": 1, "y": 2}) == canonical_hash({"y": 2, "x": 1})
    with pytest.raises(ValueError):
        canonical_hash({"metric": float("nan")})
    store = KBStore(tmp_path)
    snapshot = store.initialize([])
    path = tmp_path / "snapshots" / f'{snapshot["version"]}.json'
    corrupted = deepcopy(snapshot)
    corrupted["claims"] = [claim()]
    write_json_atomic(path, corrupted)
    with pytest.raises(ValueError, match="hash|integrity"):
        store.current()


def test_proposed_rule_without_evidence_is_valid(tmp_path):
    store = KBStore(tmp_path)
    first = store.initialize([])
    proposed = claim(rule={"predict": {"lower_better": "width"}}, status="proposed")
    second = store.apply_patch(patch(first, {"op": "upsert", "claim": proposed, "reason": "testable hypothesis"}), [])
    assert second["claims"] == [proposed]


def test_exploration_outcomes_attach_but_never_promote(tmp_path):
    from test_kb_workflow_evidence import artifacts
    source = artifacts(tmp_path / "sources")
    store = KBStore(tmp_path / "kb")
    first = store.initialize([])
    explored = claim(rule={"predict": {"lower_better": "width"}}, status="exploring", evidence_ids=[source["id"]])
    second = store.apply_patch(patch(first, {"op": "upsert", "claim": explored, "reason": "experiment completed"}), [source])
    assert second["claims"][0]["evidence_ids"] == [source["id"]]
    assert second["claims"][0]["status"] == "exploring"
    explored["status"] = "replicated_in_scope"
    with pytest.raises(ValueError, match="confirmation"):
        store.apply_patch(patch(second, {"op": "upsert", "claim": explored, "reason": "analyst claims passed"}), [source])
    assert store.current() == second


def test_same_revision_cannot_retry_confirmation_batch(tmp_path, monkeypatch):
    # File verification has dedicated real-file tests. Here isolate the study
    # history boundary with already-verified experiment receipts.
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    monkeypatch.setattr(module, "verify_evidence_sources", lambda item, **kwargs: {})
    store = KBStore(tmp_path)
    first = store.initialize([])
    explored = claim(rule={"predict": {"lower_better": "width"}}, status="exploring")
    evidence = [record(i, outcome="inconclusive", plan_hash="1" * 64) for i in range(48)]
    second = store.apply_patch(patch(first, {"op": "upsert", "claim": explored, "reason": "failed confirmation retained"}), evidence)
    retry = [record(i + 100, plan_hash="2" * 64) for i in range(48)]
    explored["status"] = "replicated_in_scope"
    explored["evidence_ids"] = [item["id"] for item in retry]
    with pytest.raises(ValueError, match="revision|attempt"):
        store.apply_patch(patch(second, {"op": "upsert", "claim": explored, "reason": "reroll"}), retry)
    assert store.current() == second


def test_confirmation_publication_and_semantic_reset(tmp_path, monkeypatch):
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    monkeypatch.setattr(module, "verify_evidence_sources", lambda item, **kwargs: {"sampling_envelope": confirmed_envelope()})
    store = KBStore(tmp_path)
    first = store.initialize([])
    evidence = [record(i, plan_hash="1" * 64) for i in range(48)]
    verified = claim(rule={"predict": {"lower_better": "width"}}, status="replicated_in_scope", enabled=True,
                     evidence_ids=[item["id"] for item in evidence])
    second = store.apply_patch(patch(first, {"op": "upsert", "claim": verified, "reason": "independent confirmation"}), evidence)
    assert second["claims"][0]["enabled"]
    revised = deepcopy(second["claims"][0])
    revised.update(text="different hypothesis", revision=2, parent_revision=1)
    with pytest.raises(ValueError, match="inherit"):
        store.apply_patch(patch(second, {"op": "upsert", "claim": revised, "reason": "change semantics"}), evidence)
    revised.update(status="proposed", enabled=False, evidence_ids=[])
    third = store.apply_patch(patch(second, {"op": "upsert", "claim": revised, "reason": "change semantics"}), evidence)
    assert third["claims"][0]["evidence_ids"] == []
    assert len(third["evidence"]) == 48
    assert "validated_scope" not in third["claims"][0]


def test_confirmation_cannot_reuse_explored_lineage(tmp_path, monkeypatch):
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    monkeypatch.setattr(module, "verify_evidence_sources", lambda item, **kwargs: {})
    store = KBStore(tmp_path)
    first = store.initialize([])
    proposed = claim(rule={"predict": {"lower_better": "width"}}, status="exploring")
    first_evidence = record(0, phase="exploration", plan_hash="0" * 64)
    second = store.apply_patch(patch(first, {"op": "upsert", "claim": proposed, "reason": "explore"}), [first_evidence])
    reused = record(1, lineage_id="lineage-0", plan_hash="1" * 64)
    with pytest.raises(ValueError, match="source|lineage"):
        store.apply_patch(patch(second, {"op": "upsert", "claim": proposed, "reason": "not independent"}), [reused])


def test_study_cannot_take_a_fourth_confirmation_attempt(tmp_path, monkeypatch):
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    monkeypatch.setattr(module, "verify_evidence_sources", lambda item, **kwargs: {})
    store = KBStore(tmp_path)
    snapshot = store.initialize([])
    for i in range(4):
        proposed = claim(id=f"c-{i}", rule={"predict": {"lower_better": "width"}}, status="exploring")
        evidence = record(i, claim_id=f"c-{i}", plan_hash=f"{i:064x}")
        change = patch(snapshot, {"op": "upsert", "claim": proposed, "reason": "confirmation attempt"})
        if i < 3:
            snapshot = store.apply_patch(change, [evidence])
        else:
            with pytest.raises(ValueError, match="three|limit"):
                store.apply_patch(change, [evidence])
    assert store.current() == snapshot


def test_committed_patch_replay_after_restart_returns_identical_version(tmp_path):
    store = KBStore(tmp_path)
    first = store.initialize([claim()])
    proposal = patch(first, {"op": "retire", "id": "claim", "reason": "obsolete"})
    committed = store.apply_patch(proposal, [])
    snapshots_before = sorted(path.name for path in (tmp_path / "snapshots").iterdir())
    resumed = KBStore(tmp_path).apply_patch(deepcopy(proposal), [])
    assert resumed == committed
    assert sorted(path.name for path in (tmp_path / "snapshots").iterdir()) == snapshots_before


def test_replay_does_not_accept_changed_operations_or_evidence(tmp_path):
    store = KBStore(tmp_path)
    first = store.initialize([claim()])
    proposal = patch(first, {"op": "retire", "id": "claim", "reason": "obsolete"})
    committed = store.apply_patch(proposal, [])
    changed = deepcopy(proposal)
    changed["operations"][0]["reason"] = "different proposal"
    with pytest.raises(ValueError, match="parent|stale"):
        store.apply_patch(changed, [])
    with pytest.raises(ValueError, match="parent|stale"):
        store.apply_patch(proposal, [{"id": "new evidence"}])
    assert store.current() == committed


def confirmed_envelope():
    return {"family": "univariate_regression", "model_type": "mlp", "profile_hash": "frozen-profile",
            "budget_values": [1024], "optimizer_types": ["adam"], "loss_types": ["mse"],
            "intervention": "width", "family_options": {},
            "pair_sampling": "uniform_applicable_pairs_from_factor_variants",
            "controls": {"equal": ["opt_key", "loss_key", "budget", "batch_size"], "architecture_intervention": "width"}}


def test_confirmation_scope_is_derived_from_verified_sampling_plan(tmp_path, monkeypatch):
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    envelope = confirmed_envelope()
    monkeypatch.setattr(module, "verify_evidence_sources", lambda item, **kwargs: {"sampling_envelope": deepcopy(envelope)})
    store = KBStore(tmp_path)
    initial = store.initialize([])
    evidence = [record(i, plan_hash="1" * 64) for i in range(48)]
    proposed = claim(rule={"predict": {"lower_better": "width"}}, status="replicated_in_scope",
                     evidence_ids=[item["id"] for item in evidence])
    published = store.apply_patch(patch(initial, {"op": "upsert", "claim": proposed, "reason": "confirmed"}), evidence)
    assert published["claims"][0]["validated_scope"] == envelope
    assert "validated_scope" not in proposed


def test_broad_rule_cannot_claim_confirmation_in_other_family(tmp_path, monkeypatch):
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    envelope = confirmed_envelope()
    monkeypatch.setattr(module, "verify_evidence_sources", lambda item, **kwargs: {"sampling_envelope": deepcopy(envelope)})
    store = KBStore(tmp_path)
    initial = store.initialize([])
    evidence = [record(i, plan_hash="1" * 64) for i in range(48)]
    wider = {**envelope, "family": "xor_classification"}
    proposed = claim(rule={"predict": {"lower_better": "width"}}, status="replicated_in_scope",
                     evidence_ids=[item["id"] for item in evidence], validated_scope=wider)
    with pytest.raises(ValueError, match="scope|envelope"):
        store.apply_patch(patch(initial, {"op": "upsert", "claim": proposed, "reason": "unwarranted transfer"}), evidence)
    assert store.current() == initial


def test_confirmation_cannot_pool_different_sampling_envelopes(tmp_path, monkeypatch):
    from test_kb_workflow_evidence import record
    import architecture_iq.kb.store as module
    envelope = confirmed_envelope()
    def verified(item, **kwargs):
        actual = deepcopy(envelope)
        if item["dataset_id"] == "dataset-47":
            actual["family_options"] = {"input_dim": 4}
        return {"sampling_envelope": actual}
    monkeypatch.setattr(module, "verify_evidence_sources", verified)
    store = KBStore(tmp_path)
    initial = store.initialize([])
    evidence = [record(i, plan_hash="1" * 64) for i in range(48)]
    proposed = claim(rule={"predict": {"lower_better": "width"}}, status="replicated_in_scope",
                     evidence_ids=[item["id"] for item in evidence])
    with pytest.raises(ValueError, match="scope|envelope"):
        store.apply_patch(patch(initial, {"op": "upsert", "claim": proposed, "reason": "mixed distributions"}), evidence)
