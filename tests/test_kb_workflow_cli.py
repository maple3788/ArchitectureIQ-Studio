"""CLI boundaries: host, identity drift, and offline preparation."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import json

import pytest


def cli_module():
    assert importlib.util.find_spec("architecture_iq.kb.cli") is not None, (
        "workflow CLI is missing"
    )
    return importlib.import_module("architecture_iq.kb.cli")


def runtime_fixture(tmp_path):
    template = "fixture chat template"
    artifact = tmp_path / "runtime-binary"
    artifact.write_bytes(b"fixture")
    st = artifact.stat()
    model = {
        "name": "glm-5.3-flash",
        "max_tokens": 8192,
        "temperature": 0.0,
        "top_p": 1.0,
        "extra": {"seed": 20261007, "top_k": 0, "min_p": 0.0, "repeat_penalty": 1.0},
    }
    lock = {
        "model_id": "glm-5.3-flash",
        "endpoint": "http://127.0.0.1:18053/v1",
        "model_path": "/models/model.gguf",
        "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        "context_size": 32768,
        "model_parameters": model,
        "file_verifications": [
            {
                "path": str(artifact),
                "sha256_from_attestation": hashlib.sha256(b"fixture").hexdigest(),
                "current_state": {
                    "size": st.st_size,
                    "mtime_ns": st.st_mtime_ns,
                    "ctime_ns": st.st_ctime_ns,
                    "device": st.st_dev,
                    "inode": st.st_ino,
                },
            }
        ],
    }
    lock_file = tmp_path / "runtime.json"
    lock_file.write_text(json.dumps(lock))
    canonical = json.dumps(
        lock, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    config = {
        "model": model,
        "runtime_fingerprint": hashlib.sha256(canonical).hexdigest(),
    }
    responses = {
        "/health": {"status": "ok"},
        "/v1/models": {"data": [{"id": "glm-5.3-flash"}]},
        "/props": {
            "model_alias": "glm-5.3-flash",
            "model_path": "/models/model.gguf",
            "chat_template": template,
            "default_generation_settings": {
                "n_ctx": 32768,
                "params": {
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "seed": 20261007,
                    "top_k": 0,
                    "min_p": 0.0,
                    "repeat_penalty": 1.0,
                },
            },
        },
    }
    return config, lock_file, responses


def install_runtime_responses(monkeypatch, cli, responses):
    def open_response(url, timeout):
        from urllib.parse import urlparse

        assert timeout <= 15
        return io.BytesIO(json.dumps(responses[urlparse(url).path]).encode())

    monkeypatch.setattr(cli.urllib.request, "urlopen", open_response)


@pytest.mark.parametrize(
    "execute,system,host",
    [
        (False, "Linux", "execution.example.test"),
        (True, "Darwin", "execution.example.test"),
        (True, "Linux", ""),
        (True, "Linux", "another-host"),
    ],
)
def test_execution_requires_all_three_explicit_gates(
    monkeypatch, execute, system, host
):
    cli = cli_module()
    monkeypatch.setattr(cli.platform, "system", lambda: system)
    monkeypatch.setenv("ARCHITECTURE_IQ_KB_EXECUTION_HOST", host)
    monkeypatch.setenv("ARCHITECTURE_IQ_KB_AUTHORIZED_HOST", "execution.example.test")
    with pytest.raises(ValueError, match="execute|Linux|EXECUTION_HOST"):
        cli.require_execution_host(execute)


def test_offline_lock_rejects_changed_contents_and_placeholder(tmp_path):
    cli = cli_module()
    config, path, _ = runtime_fixture(tmp_path)
    assert cli.read_runtime_lock(path, config)["context_size"] == 32768
    changed = json.loads(path.read_text())
    changed["context_size"] = 8192
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="fingerprint"):
        cli.read_runtime_lock(path, config)
    config["runtime_fingerprint"] = "REPLACE_WITH_REAL_RUNTIME_FINGERPRINT"
    with pytest.raises(ValueError, match="fingerprint"):
        cli.read_runtime_lock(path, config)


@pytest.mark.parametrize(
    "drift",
    [
        "model",
        "model_path",
        "template",
        "context",
        "health",
        "models",
        "endpoint",
        "decoding",
    ],
)
def test_live_runtime_drift_blocks_execution(tmp_path, monkeypatch, drift):
    cli = cli_module()
    config, path, responses = runtime_fixture(tmp_path)
    if drift == "model":
        responses["/props"]["model_alias"] = "other"
    if drift == "model_path":
        responses["/props"]["model_path"] = "/models/other.gguf"
    if drift == "template":
        responses["/props"]["chat_template"] = "different template"
    if drift == "context":
        responses["/props"]["default_generation_settings"]["n_ctx"] = 8192
    if drift == "health":
        responses["/health"]["status"] = "loading model"
    if drift == "decoding":
        responses["/props"]["default_generation_settings"]["params"]["seed"] = 7
    if drift == "models":
        responses["/v1/models"]["data"] = [{"id": "other"}]
    install_runtime_responses(monkeypatch, cli, responses)
    url = (
        "http://127.0.0.1:9999/v1"
        if drift == "endpoint"
        else config.get("base_url", "http://127.0.0.1:18053/v1")
    )
    with pytest.raises(
        ValueError, match="runtime|model|template|context|health|endpoint|decoding"
    ):
        cli.verify_live_runtime(path, config, url)


def test_matching_live_runtime_is_accepted(tmp_path, monkeypatch):
    cli = cli_module()
    config, path, responses = runtime_fixture(tmp_path)
    install_runtime_responses(monkeypatch, cli, responses)
    result = cli.verify_live_runtime(path, config, "http://127.0.0.1:18053/v1")
    assert result["model_id"] == "glm-5.3-flash"


def test_stat_drift_invalidates_attested_files(tmp_path):
    cli = cli_module()
    config, lock_path, _ = runtime_fixture(tmp_path)
    binary = tmp_path / "binary"
    binary.write_bytes(b"old")
    stat = binary.stat()
    lock = json.loads(lock_path.read_text())
    lock["file_verifications"] = [
        {
            "path": str(binary),
            "sha256_from_attestation": hashlib.sha256(b"old").hexdigest(),
            "current_state": {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "ctime_ns": stat.st_ctime_ns,
                "device": stat.st_dev,
                "inode": stat.st_ino,
            },
        }
    ]
    lock_path.write_text(json.dumps(lock))
    config["runtime_fingerprint"] = hashlib.sha256(
        json.dumps(
            lock, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    cli.read_runtime_lock(lock_path, config, verify_files=True)
    binary.write_bytes(b"changed")
    with pytest.raises(ValueError, match="runtime file"):
        cli.read_runtime_lock(lock_path, config, verify_files=True)


def test_cli_blocks_model_calls_before_loading_a_run(tmp_path, monkeypatch):
    cli = cli_module()
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "run",
                "--out",
                str(tmp_path / "nonexistent"),
                "--round",
                "1",
                "--runtime-lock",
                str(tmp_path / "nonexistent.json"),
                "--execute",
            ]
        )
    assert exc.value.code == 2


def test_request_parameter_drift_is_rejected_before_network(tmp_path):
    cli = cli_module()
    config, path, _ = runtime_fixture(tmp_path)
    config["model"]["extra"]["seed"] = 7
    with pytest.raises(ValueError, match="model parameters"):
        cli.read_runtime_lock(path, config)


@pytest.mark.parametrize("legacy_envelope", [False, True])
def test_prepare_and_status_freeze_inputs_offline(
    tmp_path, monkeypatch, capsys, legacy_envelope
):
    cli = cli_module()
    config, lock_path, _ = runtime_fixture(tmp_path)
    config.update(
        max_rounds=1, discovery_per_round=1, enable_confirmation=False, n_seeds=2
    )
    public = [
        {
            "id": "q1",
            "family": "univariate_regression",
            "dataset_id": "d1",
            "lineage_id": "lineage1",
            "prompt": "Choose from public code.",
            "choices": [
                {
                    "id": "c" + letter,
                    "letter": letter,
                    "view": {"family": "univariate_regression", "width": width},
                }
                for letter, width in zip("ABC", (16, 32, 64))
            ],
        }
    ]
    legacy = [
        {"id": "old", "text": "Legacy knowledge without independent confirmation."}
    ]
    inputs = {
        "config.json": config,
        "public.json": public,
        "private.json": {"q1": {"correct_letter": "B"}},
        "legacy.json": {"claims": legacy} if legacy_envelope else legacy,
    }
    for name, value in inputs.items():
        (tmp_path / name).write_text(json.dumps(value))

    def disallow_network(*args, **kwargs):
        raise AssertionError("Offline prepare/status must not contact a model")

    monkeypatch.setattr(cli.urllib.request, "urlopen", disallow_network)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("ARCHITECTURE_IQ_KB_EXECUTION_HOST", raising=False)
    out = tmp_path / "run"
    assert (
        cli.main(
            [
                "prepare",
                "--config",
                str(tmp_path / "config.json"),
                "--public",
                str(tmp_path / "public.json"),
                "--private",
                str(tmp_path / "private.json"),
                "--legacy",
                str(tmp_path / "legacy.json"),
                "--runtime-lock",
                str(lock_path),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["config"]["runtime_fingerprint"] == config["runtime_fingerprint"]
    assert (
        json.loads((out / "private_feedback.json").read_text())["q1"]["correct_letter"]
        == "B"
    )
    assert cli.main(["status", "--out", str(out)]) == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["completed_rounds"] == 0
    assert reported["claims"] == 1
    assert reported["enabled"] == 0
    assert not (out / "calls").exists()


def process_fixture(tmp_path, monkeypatch, cli, config, lock_path):
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / "54321"
    proc_dir.mkdir(parents=True)
    command = b"/engine/llama-server\0--alias\0glm-5.3-flash\0"
    proc_dir.joinpath("cmdline").write_bytes(command)
    proc_dir.joinpath("stat").write_text(
        "54321 (llama-server (worker)) "
        + " ".join(["S"] + ["0"] * 18 + ["12345"])
        + "\n"
    )
    executable = str(tmp_path / "runtime-binary")
    proc_dir.joinpath("exe").symlink_to(executable)
    lock = json.loads(lock_path.read_text())
    lock["process_identity"] = {
        "pid": 54321,
        "start_ticks": 12345,
        "cmdline_sha256": hashlib.sha256(command).hexdigest(),
        "executable_path": executable,
    }
    lock_path.write_text(json.dumps(lock))
    config["runtime_fingerprint"] = hashlib.sha256(
        json.dumps(
            lock, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    monkeypatch.setattr(cli, "_PROC_ROOT", proc_root, raising=False)
    return proc_dir


@pytest.mark.parametrize(
    "change", ["start_ticks", "cmdline", "executable", "missing_process"]
)
def test_process_restart_or_command_change_invalidates_runtime(
    tmp_path, monkeypatch, change
):
    cli = cli_module()
    config, lock_path, _ = runtime_fixture(tmp_path)
    proc = process_fixture(tmp_path, monkeypatch, cli, config, lock_path)
    cli.read_runtime_lock(lock_path, config, verify_files=True)
    if change == "start_ticks":
        proc.joinpath("stat").write_text(
            "54321 (llama-server (worker)) "
            + " ".join(["S"] + ["0"] * 18 + ["99999"])
            + "\n"
        )
    elif change == "cmdline":
        proc.joinpath("cmdline").write_bytes(b"/engine/llama-server\0--other-option\0")
    elif change == "executable":
        proc.joinpath("exe").unlink()
        proc.joinpath("exe").symlink_to("/engine/replacement")
    else:
        proc.joinpath("stat").unlink()
    with pytest.raises(ValueError, match="runtime process"):
        cli.read_runtime_lock(lock_path, config, verify_files=True)


def test_client_runtime_hook_rechecks_service_on_every_invocation(
    tmp_path, monkeypatch
):
    from urllib.parse import urlparse

    cli = cli_module()
    config, lock_path, responses = runtime_fixture(tmp_path)
    calls = []

    def open_response(url, timeout):
        path = urlparse(url).path
        calls.append(path)
        return io.BytesIO(json.dumps(responses[path]).encode())

    monkeypatch.setattr(cli.urllib.request, "urlopen", open_response)
    client = cli._client(
        "http://127.0.0.1:18053/v1", runtime_lock=lock_path, config=config
    )
    assert callable(client.verify_runtime)
    client.verify_runtime()
    responses["/props"]["chat_template"] = "changed between inferences"
    with pytest.raises(ValueError, match="template"):
        client.verify_runtime()
    assert calls == [
        "/health",
        "/v1/models",
        "/props",
        "/health",
        "/v1/models",
        "/props",
    ]


def test_client_runtime_hook_rechecks_process_metadata(tmp_path, monkeypatch):
    cli = cli_module()
    config, lock_path, responses = runtime_fixture(tmp_path)
    proc = process_fixture(tmp_path, monkeypatch, cli, config, lock_path)
    install_runtime_responses(monkeypatch, cli, responses)
    client = cli._client(
        "http://127.0.0.1:18053/v1", runtime_lock=lock_path, config=config
    )
    client.verify_runtime()
    proc.joinpath("cmdline").write_bytes(b"restarted with different arguments")
    with pytest.raises(ValueError, match="runtime process"):
        client.verify_runtime()


def test_legacy_rules_require_legacy_before_opening_inputs(tmp_path, capsys):
    cli = cli_module()
    args = ["prepare", "--legacy-rules", str(tmp_path / "rules.json")]
    for option in ("--config", "--public", "--private", "--runtime-lock", "--out"):
        args.extend([option, str(tmp_path / option.removeprefix("--"))])
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert "--legacy-rules requires --legacy" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_prepare_imports_compiled_legacy_clauses_into_disabled_kb(tmp_path, capsys):
    from architecture_iq.kb.store import KBStore

    cli = cli_module()
    config, runtime_lock, _ = runtime_fixture(tmp_path)
    config.update(
        max_rounds=1, discovery_per_round=1, enable_confirmation=False, n_seeds=2
    )
    public = [
        {
            "id": "q1",
            "family": "univariate_regression",
            "dataset_id": "d1",
            "lineage_id": "lineage1",
            "prompt": "Choose from public code.",
            "choices": [
                {
                    "id": "c" + letter,
                    "letter": letter,
                    "view": {"family": "univariate_regression", "width": width},
                }
                for letter, width in zip("ABC", (16, 32, 64))
            ],
        }
    ]
    inputs = {
        "config.json": config,
        "public.json": public,
        "private.json": {"q1": {"correct_letter": "B"}},
        "legacy.json": {
            "claims": [{"id": "K1", "text": "Conditional architecture claim."}]
        },
        "rules.json": {
            "schema_version": "kb_claim_rules_v1",
            "claims": [
                {
                    "id": "K1",
                    "status": "testable",
                    "rules": [
                        {"predict": {"lower_better": "width"}},
                        {"predict": {"higher_better": "depth"}},
                    ],
                }
            ],
        },
    }
    for name, value in inputs.items():
        (tmp_path / name).write_text(json.dumps(value))
    args = [
        "prepare",
        "--out",
        str(tmp_path / "run"),
        "--runtime-lock",
        str(runtime_lock),
    ]
    for option, name in [
        ("--config", "config.json"),
        ("--public", "public.json"),
        ("--private", "private.json"),
        ("--legacy", "legacy.json"),
        ("--legacy-rules", "rules.json"),
    ]:
        args.extend([option, str(tmp_path / name)])
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["config"]["enable_confirmation"] is False
    claims = KBStore(tmp_path / "run" / "kb").current()["claims"]
    assert {claim["id"] for claim in claims} == {"K1.clause-1", "K1.clause-2"}
    assert all(
        claim["rule"]
        and claim["status"] == "legacy_unverified"
        and not claim["enabled"]
        for claim in claims
    )
