import json
from types import SimpleNamespace

import pytest

from architecture_iq.kb.roles import RoleCaller, parse_json_response, role_prompt


class Model:
    name = "glm-5.3-flash"
    max_tokens = 100

    def to_dict(self):
        return {"name": self.name, "max_tokens": self.max_tokens}


class Client:
    def __init__(self, *, actual="glm-5.3-flash", fail=False):
        self.count = 0
        self.actual = actual
        self.fail = fail

    def complete(self, prompt, config):
        self.count += 1
        if self.fail:
            raise TimeoutError("uncertain transport outcome")
        return SimpleNamespace(
            raw={
                "model": self.actual,
                "choices": [
                    {
                        "message": {
                            "content": '{"ranking":["B","A","C"]}',
                            "reasoning_content": '{"ranking":["A","B","C"]}',
                        }
                    }
                ],
            },
            usage={"prompt_tokens": 30, "completion_tokens": 20},
            finish_reason="stop",
        )


def caller(tmp_path, client, **limits):
    return RoleCaller(
        tmp_path,
        client,
        Model(),
        fingerprint="locked-runtime",
        max_calls=limits.get("max_calls", 5),
        max_tokens=limits.get("max_tokens", 10000),
    )


def test_replay_returns_saved_response_without_calling_model(tmp_path):
    client = Client()
    c = caller(tmp_path, client)
    first = c.call("solver", {"question": "compare choices"}, key="q1", round_index=1)
    assert first["ranking"] == ["B", "A", "C"]
    assert (
        c.call("solver", {"question": "compare choices"}, key="q1", round_index=1)
        == first
    )
    assert client.count == 1


def test_same_operation_cannot_change_input_or_runtime(tmp_path):
    c = caller(tmp_path, Client())
    c.call("solver", {"question": "original"}, key="q1", round_index=1)
    with pytest.raises(ValueError, match="changed"):
        c.call("solver", {"question": "changed"}, key="q1", round_index=1)
    c.fingerprint = "other-runtime"
    with pytest.raises(ValueError, match="changed"):
        c.call("solver", {"question": "original"}, key="q1", round_index=1)


def test_timeout_reservation_prevents_unaccounted_retry(tmp_path):
    client = Client(fail=True)
    c = caller(tmp_path, client)
    with pytest.raises(TimeoutError):
        c.call("solver", {"question": "q"}, key="q1", round_index=1)
    with pytest.raises(RuntimeError, match="uncertain|pending"):
        c.call("solver", {"question": "q"}, key="q1", round_index=1)
    assert client.count == 1
    assert c.usage(1)["calls"] == 1


def test_call_and_token_reservations_precede_network(tmp_path):
    client = Client()
    c = caller(tmp_path, client, max_calls=1)
    c.call("solver", {"q": "a"}, key="q1", round_index=1)
    with pytest.raises(RuntimeError, match="budget"):
        c.call("solver", {"q": "b"}, key="q2", round_index=1)
    assert client.count == 1
    tiny = caller(tmp_path / "tiny", client, max_tokens=10)
    with pytest.raises(RuntimeError, match="budget"):
        tiny.call("solver", {"q": "a"}, key="q1", round_index=1)
    assert client.count == 1


def test_model_identity_change_is_saved_and_fatal(tmp_path):
    c = caller(tmp_path, Client(actual="other-model"))
    with pytest.raises(RuntimeError, match="model"):
        c.call("solver", {"q": "a"}, key="q1", round_index=1)
    assert c.usage(1)["calls"] == 1
    with pytest.raises(RuntimeError):
        c.call("solver", {"q": "a"}, key="q1", round_index=1)


def test_malformed_response_is_charged_and_not_reanswered(tmp_path):
    class Bad(Client):
        def complete(self, prompt, config):
            response = super().complete(prompt, config)
            response.raw["choices"][0]["message"]["content"] = "I choose B"
            return response

    client = Bad()
    c = caller(tmp_path, client)
    assert c.call("solver", {}, key="q1", round_index=1)["_invalid"]
    assert c.call("solver", {}, key="q1", round_index=1)["_invalid"]
    assert client.count == 1


def test_parser_rejects_multiple_objects_and_accepts_json_fence():
    assert parse_json_response('```json\n{"ok":true}\n```') == {"ok": True}
    with pytest.raises(ValueError):
        parse_json_response('{"ok":true} {"ok":false}')


def test_unknown_role_does_not_get_generic_privileges():
    with pytest.raises(ValueError):
        role_prompt("shell", {})


def test_context_failure_reports_pre_send_budget_without_network_or_receipt(tmp_path):
    client = Client()
    payload = {"episodes": [{"question": "训练反馈" * 100}]}
    input_bytes = len(role_prompt("discoverer", payload).encode("utf-8"))
    c = RoleCaller(
        tmp_path, client, Model(), fingerprint="locked", max_context=1000
    )
    with pytest.raises(ValueError, match="Role payload exceeds conservative context budget") as caught:
        c.call("discoverer", payload, key="packet-0", round_index=1)
    message = str(caught.value)
    assert f"input_utf8_bytes={input_bytes}" in message
    assert "output_reserved=100" in message
    assert "overhead_reserved=256" in message
    assert "context_limit=1000" in message
    assert "role=discoverer" in message
    assert "smaller packets" not in message
    assert client.count == 0
    assert not list((tmp_path / "calls").glob("*.json"))


def test_response_tampering_rejected_on_resume(tmp_path):
    c = caller(tmp_path, Client())
    c.call("solver", {"q": "a"}, key="q1", round_index=1)
    receipt = next((tmp_path / "calls").glob("*.json"))
    data = json.loads(receipt.read_text())
    data["result"] = {"ranking": ["A", "B", "C"]}
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        c.call("solver", {"q": "a"}, key="q1", round_index=1)


@pytest.mark.parametrize(
    "extra", [{"max_completion_tokens": 100000}, {"messages": []}, {"model": "other"}]
)
def test_transport_overrides_rejected_before_reservation(tmp_path, extra):
    class OverrideModel(Model):
        def to_dict(self):
            return {**super().to_dict(), "extra": extra}

    with pytest.raises(ValueError, match="override|extra"):
        RoleCaller(tmp_path, Client(), OverrideModel(), fingerprint="locked")


def test_runtime_rechecked_after_call_before_accepting_result(tmp_path):
    client = Client()
    checks = []

    def verify():
        checks.append(1)
        if len(checks) > 1:
            raise ValueError("runtime changed")

    client.verify_runtime = verify
    c = caller(tmp_path, client)
    with pytest.raises(ValueError, match="runtime"):
        c.call("solver", {}, key="q1", round_index=1)
    assert client.count == 1
    with pytest.raises(RuntimeError, match="uncertain|pending"):
        c.call("solver", {}, key="q1", round_index=1)
