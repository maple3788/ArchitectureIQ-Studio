from pathlib import Path

import pytest


def test_model_profile_rejects_wire_identity_and_token_overrides(tmp_path):
    from architecture_iq.studio.models import ModelRegistry

    registry = ModelRegistry(tmp_path)
    for extra in ({"model": "another"}, {"messages": []}, {"max_tokens": 99}):
        with pytest.raises(ValueError):
            registry.save(
                {
                    "id": "glm",
                    "name": "GLM",
                    "model": "glm",
                    "base_url": "http://127.0.0.1:18054/v1",
                    "parameters": {"max_tokens": 512, "extra": extra},
                }
            )


def test_model_profile_secret_is_reference_and_identity_is_versioned(tmp_path):
    from architecture_iq.studio.models import ModelRegistry

    registry = ModelRegistry(tmp_path)
    profile = {
        "id": "glm",
        "name": "GLM Flash",
        "model": "glm-5.3-flash",
        "base_url": "http://127.0.0.1:18054/v1",
        "api_key_env": "STUDIO_GLM_KEY",
        "parameters": {"temperature": 0, "max_tokens": 512},
    }
    one = registry.save(profile)
    assert one["id"] == "glm" and one["parameters"]["max_tokens"] == 512
    two = registry.save(
        {**profile, "parameters": {"temperature": 0, "max_tokens": 1024}}
    )
    assert one["revision"] != two["revision"]
    assert registry.get("glm")["revision"] == two["revision"]
    assert (
        registry.get("glm", revision=one["revision"])["parameters"]["max_tokens"] == 512
    )
    assert "api_key" not in one and "STUDIO_GLM_KEY" in str(one)
    with pytest.raises(ValueError):
        registry.save({**profile, "api_key": "do-not-store"})
    assert not any(
        "do-not-store" in p.read_text() for p in Path(tmp_path).rglob("*.json")
    )


def test_paths_resolve_inside_registered_roots(tmp_path):
    from architecture_iq.studio.models import resolve_path

    allowed = tmp_path / "sources"
    allowed.mkdir()
    (allowed / "ok.json").write_text("{}")
    outside = tmp_path / "secret"
    outside.write_text("private")
    (allowed / "escape").symlink_to(outside)
    assert resolve_path(str(allowed / "ok.json"), [allowed]) == allowed / "ok.json"
    with pytest.raises(ValueError):
        resolve_path(str(allowed / "escape"), [allowed])
    with pytest.raises(ValueError):
        resolve_path(str(allowed / ".." / "secret"), [allowed])


def test_transport_observer_records_final_payload_without_authorization(monkeypatch):
    import json
    import hashlib
    from tools.llm_eval.llm_client import LLMClient, ModelConfig

    recorded, sent = [], []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return json.dumps(
                {
                    "model": "glm",
                    "choices": [{"message": {"content": "A"}, "finish_reason": "stop"}],
                }
            ).encode()

    def open_request(request, **kwargs):
        sent.append(request)
        assert recorded, "request must be recorded before network side effects"
        return Reply()

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    client = LLMClient(
        base_url="http://127.0.0.1:18054/v1",
        api_key="secret-key",
        max_retries=0,
        request_observer=recorded.append,
    )
    client.complete(
        "actual prompt", ModelConfig(name="glm", max_tokens=12, extra={"seed": 7})
    )
    capture = recorded[0]
    assert capture["payload"] == json.loads(sent[0].data)
    assert capture["body_sha256"] == hashlib.sha256(sent[0].data).hexdigest()
    assert capture["payload"]["messages"] == [
        {"role": "user", "content": "actual prompt"}
    ]
    assert "secret-key" not in json.dumps(capture)


def test_preview_builder_uses_transport_token_limit_contract(monkeypatch):
    from tools.llm_eval.llm_client import ModelConfig, build_request_payload

    monkeypatch.setenv("OPENAI_MAX_TOKENS_PARAM", "max_completion_tokens")
    value = build_request_payload(
        [{"role": "user", "content": "public"}], ModelConfig(name="glm", max_tokens=32)
    )
    assert value["max_completion_tokens"] == 32
    assert "max_tokens" not in value


def test_model_health_is_invalidated_by_profile_revision(tmp_path):
    from architecture_iq.studio.models import ModelRegistry
    from architecture_iq.kb.store import write_json_atomic

    registry = ModelRegistry(tmp_path)
    value = {
        "id": "glm",
        "name": "GLM",
        "model": "glm",
        "base_url": "http://localhost:1/v1",
    }
    first = registry.save(value)
    write_json_atomic(
        registry.root / "glm/health.json",
        {"revision": first["revision"], "status": "verified", "verified": True},
    )
    assert registry.describe()[0]["health"]["verified"]
    registry.save({**value, "base_url": "http://localhost:2/v1"})
    assert registry.describe()[0]["health"]["status"] == "unchecked"


@pytest.mark.parametrize(
    "value",
    [
        {"id": 3},
        {
            "id": "glm",
            "name": "GLM",
            "model": "glm",
            "base_url": "http://localhost/v1",
            "parameters": [],
        },
    ],
)
def test_malformed_profile_reports_validation_error(tmp_path, value):
    from architecture_iq.studio.models import ModelRegistry

    with pytest.raises(ValueError):
        ModelRegistry(tmp_path).save(value)


def test_immutable_model_revision_detects_tampering(tmp_path):
    import json
    from architecture_iq.studio.models import ModelRegistry

    registry = ModelRegistry(tmp_path)
    profile = registry.save(
        {"id": "glm", "name": "GLM", "model": "glm", "base_url": "http://localhost/v1"}
    )
    path = registry.root / "glm" / f"{profile['revision']}.json"
    changed = json.loads(path.read_text())
    changed["model"] = "other"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="integrity"):
        registry.get("glm")
