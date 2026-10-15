"""Mocked runtime integration: no model requests or GT execution."""

import importlib.util
import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runtime():
    path = Path(__file__).resolve().parents[1] / "tools/kb_consistency_runtime.py"
    spec = importlib.util.spec_from_file_location("kb_consistency_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_causal_hypothesis_survives_draft_parser(runtime):
    claim = {"text": "With budget 4096, A wins.", "rules": [],
             "explanation": {"text": "Because the optimizer adapts.", "status": "hypothesis"}}
    parsed = runtime._parse_claims(json.dumps({"claims": [claim]}), json.loads)
    assert parsed[0]["explanation"] == claim["explanation"]
    revised = runtime._parse_claims(json.dumps(claim), json.loads, revision=True)
    assert revised["explanation"] == claim["explanation"]


@pytest.mark.parametrize("reply", [False, "false", None])
def test_registration_preflight_covers_all_branches_before_writes(runtime, monkeypatch, tmp_path, reply):
    writes = []
    context, claim, review = _semantic_fixture()
    review["consistent"] = reply
    audit = runtime._policy().validate_audit(claim, context, review)
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    store = SimpleNamespace(config=lambda: {}, round_dir=lambda k: tmp_path)
    for branch in ("new", "splits", "revisions"):
        props = {"new": [], "splits": {}, "revisions": {}, "consistency": {}}
        key = {"new": "new0", "splits": "C1#0", "revisions": "C1"}[branch]
        props[branch] = {"new": [claim], "splits": {"C1": [claim]}, "revisions": {"C1": claim}}[branch]
        props["consistency"][key] = audit
        loop = _loop(props, writes)
        runtime.install(loop, tmp_path)
        with pytest.raises(ValueError, match="registration blocked"):
            loop.stage_register(store, 1, props)
    assert writes == []


def _semantic_fixture():
    context = {"status": "configured", "source": "frozen_runtime_profile", "config_hash": "f" * 64,
               "budget_values": [4096], "steps_values": [256]}
    claim = {"text": "For both candidates at budget 4096 and 256 steps, higher width wins.",
             "rules": [{"scope": [["budget", "in", [4096]], ["steps", "in", [256]]],
                        "predict": {"higher_better": "width"}}],
             "explanation": {"text": "More capacity may help.", "status": "hypothesis"}}
    review = {"consistent": True, "conditions_complete": True, "conclusion_matches": True,
              "conditions": [
                  {"quote": "budget 4096", "status": "matched", "rule_indices": [0],
                   "checks": [{"rule_index": 0, "path": "/scope/0", "expected": ["budget", "in", [4096]]}]},
                  {"quote": "256 steps", "status": "matched", "rule_indices": [0],
                   "checks": [{"rule_index": 0, "path": "/scope/1", "expected": ["steps", "in", [256]]}]},
              ], "issues": [], "explanation": {"text": "More capacity may help.", "status": "hypothesis"}}
    return context, claim, review


@pytest.mark.parametrize("change", ["text", "rules", "context", "missing_checks", "missing_audit", "causal"])
def test_cached_proposals_cannot_bypass_bound_semantic_gate(runtime, monkeypatch, tmp_path, change):
    context, claim, review = _semantic_fixture()
    if change == "missing_checks":
        review["conditions"][0].pop("checks")
    if change == "causal":
        claim["text"] += " This is because capacity causes improvement."
    audit = runtime._policy().validate_audit(claim, context, review)
    if change == "text":
        claim["text"] = claim["text"].replace("higher", "lower")
    elif change == "rules":
        claim["rules"][0]["predict"] = {"lower_better": "width"}
    elif change == "context":
        context["config_hash"] = "e" * 64
    props = {"new": [claim], "consistency": {} if change == "missing_audit" else {"new0": audit}}
    (tmp_path / "proposals.json").write_text(json.dumps(props))
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    writes = []
    loop = _loop(props, writes)
    runtime.install(loop, tmp_path)
    store = SimpleNamespace(config=lambda: {}, round_dir=lambda k: tmp_path)
    with pytest.raises(ValueError):
        loop.stage_register(store, 1, json.loads((tmp_path / "proposals.json").read_text()))
    assert writes == []


def test_existing_preregistration_receipt_is_rechecked(runtime, monkeypatch, tmp_path):
    context, claim, review = _semantic_fixture()
    audit = runtime._policy().validate_audit(claim, context, review)
    assert audit["status"] == "passed"
    props = {"new": [claim], "consistency": {"new0": audit}}
    receipt_claim = {**claim, "text": "A stale changed assertion", "consistency": audit}
    (tmp_path / "preregistered.json").write_text(json.dumps({"claims": [receipt_claim]}))
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    writes = []
    loop = _loop(props, writes)
    runtime.install(loop, tmp_path)
    with pytest.raises(ValueError):
        loop.stage_register(SimpleNamespace(config=lambda: {}, round_dir=lambda k: tmp_path), 1, props)
    assert writes == []


def test_valid_cached_audit_gets_legacy_fields_before_new_registration(runtime, monkeypatch, tmp_path):
    context, claim, review = _semantic_fixture()
    audit = runtime._policy().validate_audit(claim, context, review)
    props = {"new": [claim], "consistency": {"new0": audit}}
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    writes = []
    loop = _loop(props, writes)
    runtime.install(loop, tmp_path)
    loop.stage_register(SimpleNamespace(config=lambda: {}, round_dir=lambda k: tmp_path), 1, props)
    stored = writes[0]["consistency"]["new0"]
    assert stored["consistent"] is True
    assert stored["issue"] == ""
    assert stored["claim_hash"] == audit["claim_hash"]
    assert stored["conditions"] == audit["conditions"]
    assert "consistent" not in audit  # Caller/cached input was not rewritten.


@pytest.mark.parametrize("cached", [False, True])
def test_structured_audit_is_persisted_and_explanation_survives_registration(runtime, monkeypatch, tmp_path, cached):
    context, claim, review = _semantic_fixture()
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    monkeypatch.setattr(runtime, "require_authorized_execution", lambda: None)
    props = {"new": [claim], "splits": {"C1": [copy.deepcopy(claim)]},
             "revisions": {"C2": copy.deepcopy(claim)}, "consistency": {}}
    if cached:
        (tmp_path / "proposals.json").write_text(json.dumps(props))
    model_jobs = []
    class AuditPool:
        stats = {}
        def map(self, jobs):
            model_jobs.extend(jobs)
            return [json.dumps(review) for _ in jobs]
    loop = _loop(props, [])
    loop._pool = lambda store, cfg: AuditPool()
    def stage_propose(store, k, cfg):
        path = store.round_dir(k) / "proposals.json"
        if path.exists():
            return json.loads(path.read_text())
        prompt = loop.proposer.proposal_messages()
        assert "BOTH candidates" in prompt[-1]["content"]
        assert "4096" in prompt[-1]["content"]
        old = loop._pool(store, cfg).map([([], 0, "cons:1:new0")])
        props["consistency"] = {"new0": {"consistent": None} if isinstance(old[0], Exception)
                                else loop.proposer.parse_consistency(old[0])}
        return props
    loop.stage_propose = stage_propose
    persisted = []
    def stage_register(store, k, props):
        registered = []
        for key, draft in runtime.drafts(props):
            # The frozen runtime drops explanation while constructing versions.
            new = {"text": draft["text"], "rules": draft["rules"], "consistency": props["consistency"][key]}
            store.write_version(new)
            registered.append(new)
        return registered
    loop.stage_register = stage_register
    store = SimpleNamespace(config=lambda: {}, round_dir=lambda k: tmp_path,
                            write_version=lambda new: persisted.append(copy.deepcopy(new)))
    runtime.install(loop, tmp_path)
    audited = loop.stage_propose(store, 1, {})
    assert len(model_jobs) == 3  # Only structured audits reach the transport.
    assert all(job[2].startswith("semantic:") for job in model_jobs)
    assert set(audited["consistency"]) == {"new0", "C1#0", "C2"}
    assert all(a["status"] == "passed" for a in audited["consistency"].values())
    assert all(a["consistent"] is True and a["issue"] == "" for a in audited["consistency"].values())
    loop.stage_register(store, 1, audited)
    assert len(persisted) == 3
    assert all(c["explanation"] == claim["explanation"] for c in persisted)
    assert all(c["consistency"]["consistent"] is True for c in persisted)
    assert all(c["consistency"]["claim_hash"] == runtime._policy().claim_hash(c) for c in persisted)
    assert all(runtime._policy().gate_claim(c, context, c["consistency"]) == c for c in persisted)


@pytest.mark.parametrize("reply", [RuntimeError("mock outage"), "not JSON", '{"consistent": true}'])
def test_failed_or_malformed_model_check_is_persisted_but_cannot_register(runtime, monkeypatch, tmp_path, reply):
    context, claim, _ = _semantic_fixture()
    props = {"new": [claim]}
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    monkeypatch.setattr(runtime, "require_authorized_execution", lambda: None)
    writes = []
    loop = _loop(props, writes)
    loop._pool = lambda store, cfg: SimpleNamespace(map=lambda jobs: [reply], stats={})
    runtime.install(loop, tmp_path)
    store = SimpleNamespace(config=lambda: {}, round_dir=lambda k: tmp_path)
    audited = loop.stage_propose(store, 1, {})
    assert audited["consistency"]["new0"]["status"] in {"unchecked", "needs_review"}
    assert audited["consistency"]["new0"]["consistent"] is False
    assert audited["consistency"]["new0"]["issue"]
    assert (tmp_path / "proposals.json").exists()
    with pytest.raises(ValueError):
        loop.stage_register(store, 1, audited)
    assert writes == []


def test_passing_semantic_review_cannot_project_true_when_budget_gate_fails(runtime, monkeypatch, tmp_path):
    context, claim, review = _semantic_fixture()
    claim["text"] = claim["text"].replace("256 steps", "256 or 512 steps")
    claim["rules"][0]["scope"][1] = ["steps", "in", [256, 512]]
    review["conditions"][1]["quote"] = "256 or 512 steps"
    review["conditions"][1]["checks"][0]["expected"] = ["steps", "in", [256, 512]]
    assert runtime._policy().validate_audit(claim, context, review)["status"] == "passed"
    monkeypatch.setattr(runtime, "budget_context", lambda *args: context)
    monkeypatch.setattr(runtime, "require_authorized_execution", lambda: None)
    loop = _loop({"new": [claim]}, [])
    loop._pool = lambda store, cfg: SimpleNamespace(map=lambda jobs: [json.dumps(review)], stats={})
    runtime.install(loop, tmp_path)
    audited = loop.stage_propose(SimpleNamespace(round_dir=lambda k: tmp_path), 1, {})
    audit = audited["consistency"]["new0"]
    assert audit["consistent"] is False
    assert audit["status"] == "needs_review"
    assert any(issue["code"] == "registration_gate_failed" for issue in audit["issues"])


def test_bootstrap_only_initializes_new_run_and_rejects_unbound_history(runtime, monkeypatch, tmp_path):
    import architecture_iq
    root = tmp_path / "runtime"
    (root / "src/architecture_iq").mkdir(parents=True)
    monkeypatch.setattr(architecture_iq, "__file__", str(root / "src/architecture_iq/__init__.py"))
    (root / runtime.MANIFEST).write_text(json.dumps({"installed_hashes": {}}))
    monkeypatch.setattr(runtime, "require_authorized_execution", lambda: None)
    writes = []
    loop = _loop({}, writes)
    loop.cmd_init = lambda args: args.root.mkdir()
    loop.cmd_round = lambda args: writes.append("round")
    loop.cmd_forever = lambda args: writes.append("forever")
    runtime.bootstrap(loop, root)
    old = tmp_path / "historical"
    old.mkdir()
    original = old / "preregistered.sha256"
    original.write_text("frozen-hash\n")
    for operation in (loop.cmd_init, loop.cmd_round, loop.cmd_forever):
        with pytest.raises(ValueError):
            operation(SimpleNamespace(root=old))
    assert original.read_text() == "frozen-hash\n"
    assert not (old / runtime.RUN_MARKER).exists()
    assert writes == []
    fresh = tmp_path / "fresh-run"
    loop.cmd_init(SimpleNamespace(root=fresh))
    assert (fresh / runtime.RUN_MARKER).exists()
    loop.cmd_round(SimpleNamespace(root=fresh))
    assert writes == ["round"]


def test_bootstrap_rejects_source_changes_before_installing(runtime, monkeypatch, tmp_path):
    import architecture_iq
    monkeypatch.setattr(architecture_iq, "__file__", str(tmp_path / "src/architecture_iq/__init__.py"))
    (tmp_path / "frozen.py").write_text("changed")
    (tmp_path / runtime.MANIFEST).write_text(json.dumps({"installed_hashes": {"frozen.py": "0" * 64}}))
    loop = _loop({}, [])
    with pytest.raises(RuntimeError, match="changed"):
        runtime.bootstrap(loop, tmp_path)
    assert not getattr(loop, "_semantic_gate_installed", False)


def _loop(props, writes):
    def stage_register(store, k, props):
        writes.append(props)
        return []
    return SimpleNamespace(
        stage_propose=lambda store, k, cfg: props,
        stage_register=stage_register,
        stage_build=lambda store, k, cfg: None,
        _pool=lambda store, cfg: None,
        _json=lambda path: json.loads(path.read_text()),
        _dump=lambda path, data: path.write_text(json.dumps(data)),
        _proposer_cfg=lambda cfg: {"check_temperature": 0},
        proposer=SimpleNamespace(
            proposal_messages=lambda: [], revision_messages=lambda: [], extract_json=json.loads,
        ),
    )


def test_authorization_blocks_local_or_unbound_execution(runtime, monkeypatch):
    monkeypatch.setattr(runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST", "private-test-host")
    monkeypatch.setenv("ARCHITECTURE_IQ_KB_EXECUTION_HOST", "private-test-host")
    with pytest.raises(RuntimeError):
        runtime.require_authorized_execution()
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.delenv("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST")
    with pytest.raises(RuntimeError):
        runtime.require_authorized_execution()
    monkeypatch.setenv("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST", "other-host")
    with pytest.raises(RuntimeError):
        runtime.require_authorized_execution()


def test_preparation_copies_only_source_and_refuses_frozen_destination(runtime, tmp_path):
    source = tmp_path / "frozen"
    (source / "tools/kb_loop").mkdir(parents=True)
    (source / "src/architecture_iq").mkdir(parents=True)
    (source / "profiles").mkdir()
    original = 'import sys\nfrom pathlib import Path\ndef main():\n    pass\n' + runtime.ENTRY_ANCHOR
    (source / "tools/kb_loop/loop.py").write_text(original)
    (source / "src/architecture_iq/__init__.py").write_text("")
    (source / "records.jsonl").write_text("historical record\n")
    (source / ".env").write_text("PRIVATE=do-not-copy\n")
    (source / "profiles/v1.yaml").write_text("profile: v1\n")
    policy = tmp_path / "policy.py"
    policy.write_text("POLICY = 1\n")
    destination = tmp_path / "new"
    manifest = runtime.prepare_runtime(source, destination, policy_path=policy)
    assert (source / "tools/kb_loop/loop.py").read_text() == original
    assert not (destination / "records.jsonl").exists()
    assert not (destination / ".env").exists()
    assert (destination / "src/architecture_iq/kb/claim_consistency.py").read_bytes() == policy.read_bytes()
    assert "tools/kb_loop/loop.py" in manifest["installed_hashes"]
    before = (destination / runtime.MANIFEST).read_bytes()
    with pytest.raises(ValueError):
        runtime.prepare_runtime(source, destination, policy_path=policy)
    assert (destination / runtime.MANIFEST).read_bytes() == before


def test_preparation_rejects_unknown_entrypoint_without_writes(runtime, tmp_path):
    source = tmp_path / "source"
    (source / "tools/kb_loop").mkdir(parents=True)
    (source / "tools/kb_loop/loop.py").write_text("def main(): pass\nmain()\n")
    destination = tmp_path / "new"
    with pytest.raises(ValueError, match="anchor"):
        runtime.prepare_runtime(source, destination)
    assert not destination.exists()


def test_budget_context_uses_actual_family_defaults_and_minimum_steps(runtime, tmp_path):
    (tmp_path / "tools/kb_loop").mkdir(parents=True)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "tools/kb_loop/questions.py").write_text(
        'FAMILY_WEIGHTS = (("synthetic_tabular_classification", 1), ("synthetic_regression", 1))\n'
        'FAMILIES = tuple(f for f, _ in FAMILY_WEIGHTS)\nBUDGETS = (4096, 8192)\n')
    frozen_dsl = (
        "scope must hold for both candidates; eff_lr is lr/(1-momentum) for SGD, lr otherwise; "
        "disp is lr*steps for Adam/AdamW/RMSprop, 2*lr*sqrt(steps) for Adagrad, null for SGD; "
        "arch_key / opt_key are whole architecture / optimizer identity, for same/differ only."
    )
    proposer_path = tmp_path / "tools/kb_loop/proposer.py"
    proposer_path.write_text(f"DSL = {frozen_dsl!r}\n")
    shutil.copy(Path(__file__).resolve().parents[1] / "profiles/v1.5.yaml", tmp_path / "profiles/v1.5.yaml")
    context = runtime.budget_context(tmp_path, {"profile": "v1.5"})
    assert context["budget_values"] == [4096, 8192]
    assert context["steps_values"] == [256, 512]
    assert context["rule_semantics"] == frozen_dsl
    assert context["combinations"] == [
        {"family": "synthetic_tabular_classification", "budget": 4096, "batch_size": 16, "steps": 256},
        {"family": "synthetic_tabular_classification", "budget": 8192, "batch_size": 32, "steps": 256},
        {"family": "synthetic_regression", "budget": 4096, "batch_size": 16, "steps": 256},
        {"family": "synthetic_regression", "budget": 8192, "batch_size": 16, "steps": 512},
        {"family": "synthetic_regression", "budget": 8192, "batch_size": 32, "steps": 256},
    ]
    proposer_path.write_text(f"DSL = {frozen_dsl + ' Updated frozen semantics.'!r}\n")
    assert runtime.budget_context(tmp_path, {"profile": "v1.5"})["config_hash"] != context["config_hash"]
    proposer_path.write_text("DSL = derive_dsl_dynamically()\n")
    with pytest.raises(ValueError, match="DSL"):
        runtime.budget_context(tmp_path, {"profile": "v1.5"})
    proposer_path.unlink()
    with pytest.raises(ValueError, match="DSL"):
        runtime.budget_context(tmp_path, {"profile": "v1.5"})
