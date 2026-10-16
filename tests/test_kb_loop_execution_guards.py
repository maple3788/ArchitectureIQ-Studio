"""Exercise real runner guards without network requests or generated-code execution."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from kb_loop import loop, questions, qwen  # noqa: E402


@pytest.fixture(autouse=True)
def unauthorized(monkeypatch):
    monkeypatch.delenv("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST", raising=False)
    monkeypatch.delenv("ARCHITECTURE_IQ_KB_EXECUTION_HOST", raising=False)


def forbidden(*args, **kwargs):
    raise AssertionError("execution reached a side effect before authorization")


def test_direct_http_rejects_before_constructing_or_sending_request(monkeypatch):
    monkeypatch.setattr(qwen.urllib.request, "Request", forbidden)
    monkeypatch.setattr(qwen.urllib.request, "urlopen", forbidden)
    with pytest.raises(RuntimeError, match="matching nonempty"):
        qwen.http_transport("https://unused.invalid", {}, 1)


def test_explicit_mock_transport_remains_available_without_authorization(tmp_path):
    pool = qwen.ReplicaPool(["https://unused.invalid"], "mock", tmp_path / "cache",
                           transport=lambda *args: {"choices": [{"message": {"content": '{"ok": true}'}}]})
    assert pool.complete([{"role": "user", "content": "test"}]) == '{"ok": true}'
    assert pool.complete([{"role": "user", "content": "test"}]) == '{"ok": true}'
    assert pool.stats["calls"] == 1
    assert pool.stats["cached"] == 1


def test_status_is_available_locally_without_creating_run_directories(tmp_path, capsys):
    root = tmp_path / "run"
    loop.cmd_status(argparse.Namespace(root=root))
    assert '"round": 1' in capsys.readouterr().out
    assert not root.exists()


def test_direct_build_rejects_before_torch_or_dataset_side_effects(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=forbidden))
    with pytest.raises(RuntimeError, match="matching nonempty"):
        questions.build_one({}, "v1.5", 12, 1, 1, str(tmp_path / "claims"), frozenset())
    assert not (tmp_path / "claims").exists()


def test_batch_build_rejects_before_starting_workers(monkeypatch, tmp_path):
    monkeypatch.setattr(questions, "ProcessPoolExecutor", forbidden)
    with pytest.raises(RuntimeError, match="matching nonempty"):
        questions.build_items([], profile="v1.5", count=12, ds_attempts=1, set_attempts=1,
                              workers=1, claims_dir=tmp_path / "claims", reserved=frozenset(),
                              log_path=tmp_path / "build.jsonl")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ["cmd_init", "cmd_round", "cmd_forever", "run_round", "stage_register",
                                 "stage_plan", "stage_build", "stage_score", "stage_judge", "stage_propose",
                                 "stage_report", "_pool"])
def test_raw_mutating_entrypoints_reject_before_writes(entry, monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "_semantic_gate_installed", False, raising=False)
    root = tmp_path / "run"
    store = loop.Store(root)
    monkeypatch.setattr(loop, "_round_size", forbidden)
    monkeypatch.setattr(loop.time, "sleep", forbidden)
    monkeypatch.setattr(loop.Store, "config", forbidden)
    config, seeds = tmp_path / "config.yaml", tmp_path / "seed.json"
    config.write_text("profile: v1.5\n")
    seeds.write_text('{"claims": []}')
    args = argparse.Namespace(root=root, config=config, seed_claims=seeds, reference=None,
                              round=None, pilot=False, max_rounds=1, until_round=None)
    with pytest.raises(RuntimeError, match="prepared runtime"):
        if entry == "run_round":
            loop.run_round(store, 1, 1)
        elif entry == "stage_register":
            loop.stage_register(store, 1, {"needs_revision": [], "new": [], "consistency": {}})
        elif entry == "stage_plan":
            loop.stage_plan(store, 1, 1, {})
        elif entry in {"stage_build", "stage_score", "stage_judge", "stage_propose"}:
            getattr(loop, entry)(store, 1, {})
        elif entry == "stage_report":
            getattr(loop, entry)(store, 1)
        elif entry == "_pool":
            loop._pool(store, {})
        else:
            getattr(loop, entry)(args)
    assert not root.exists()


def test_prepared_bootstrap_initializes_binds_and_rejects_direct_historical_registration(tmp_path):
    from kb_consistency_runtime import prepare_runtime
    from test_kb_consistency_runtime import _semantic_fixture

    destination = tmp_path / "runtime"
    prepare_runtime(ROOT, destination)
    (tmp_path / "semantic-fixture.json").write_text(json.dumps(_semantic_fixture()))
    script = '''
import argparse, copy, hashlib, json, platform
from pathlib import Path
import torch
platform.system = lambda: "Linux"
from kb_loop import loop
import kb_consistency_runtime as runtime
root = Path("run")
Path("config.yaml").write_text("profile: v1.5\\n")
Path("seed.json").write_text('{"claims": []}')
loop.cmd_init(argparse.Namespace(root=root, config=Path("config.yaml"), seed_claims=Path("seed.json"), reference=None))
assert (root / "consistency-runtime-binding.json").is_file()
context, claim, review = json.loads(Path("semantic-fixture.json").read_text())
runtime.budget_context = lambda *args: context
audit = runtime._policy().validate_audit(claim, context, review)
props = {"needs_revision": [], "new": [claim], "consistency": {"new0": audit}}
registered = loop.stage_register(loop.Store(root), 1, props)
assert len(registered) == 1
assert registered[0]["explanation"] == claim["explanation"]
assert registered[0]["consistency"]["consistent"] is True
receipt = root / "rounds/round_0001/preregistered.json"
assert json.loads(receipt.read_text())["claims"] == registered
assert (receipt.parent / "preregistered.sha256").read_text().strip() == hashlib.sha256(receipt.read_bytes()).hexdigest()
versions = [json.loads(line) for line in (root / "claim_versions.jsonl").read_text().splitlines()]
assert versions == registered
assert json.loads((root / "claims.json").read_text())["claims"][registered[0]["id"]] == registered[0]

# A valid first draft cannot write anything when a later draft has no audit.
bad_batch = copy.deepcopy(props)
bad_batch["new"].append(copy.deepcopy(claim))
before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
try:
    loop.stage_register(loop.Store(root), 2, bad_batch)
except ValueError as exc:
    assert "registration blocked for new1" in str(exc)
else:
    raise AssertionError("mixed batch with an unaudited draft was registered")
assert before == {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
assert not (root / "rounds/round_0002").exists()

historical = Path("historical")
historical.mkdir()
(historical / "config.yaml").write_text("profile: v1.5\\n")
try:
    loop.stage_register(loop.Store(historical), 1, props)
except (RuntimeError, ValueError) as exc:
    assert "bound" in str(exc)
else:
    raise AssertionError("unbound historical registration was accepted")
assert not (historical / "rounds").exists()
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(destination / "src"), str(destination / "tools"))),
                                 "PYTHONDONTWRITEBYTECODE": "1", "ARCHITECTURE_IQ_KB_AUTHORIZED_HOST": "mock-test-host",
                                 "ARCHITECTURE_IQ_KB_EXECUTION_HOST": "mock-test-host"},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
