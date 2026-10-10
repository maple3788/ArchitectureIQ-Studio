import json
from types import SimpleNamespace

import pytest


def fixture_config():
    return {
        "question_set": {
            "id": "set1",
            "questions": [
                {
                    "id": "q1",
                    "family": "univariate_regression",
                    "dataset_id": "d1",
                    "lineage_id": "d1",
                    "prompt": "PUBLIC QUESTION",
                    "choices": [
                        {"id": f"c{x}", "letter": x, "view": {}} for x in "ABC"
                    ],
                }
            ],
            "feedback": {"q1": {"correct_letter": "B"}},
        },
        "models": [
            {
                "id": "glm",
                "name": "GLM",
                "model": "glm",
                "revision": "frozen",
                "base_url": "http://127.0.0.1:1234/v1",
                "parameters": {
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "max_tokens": 64,
                    "extra": {},
                },
                "context_size": 32768,
            }
        ],
        "prompt": "Use only the public question.",
        "max_calls": 1,
        "max_tokens": 10000,
    }


def test_preview_is_full_public_request_and_no_feedback():
    from architecture_iq.studio.execution import preview_evaluation

    config = fixture_config()
    config["question_set"]["feedback"]["q1"]["secret"] = "HIDDEN_LABEL"
    preview = preview_evaluation(config)
    assert preview["request_count"] == 1
    payload = preview["requests"][0]["payload"]
    assert "PUBLIC QUESTION" in payload["messages"][0]["content"]
    assert "Use only the public question." in payload["messages"][0]["content"]
    assert "HIDDEN_LABEL" not in json.dumps(preview)
    assert "correct_letter" not in json.dumps(preview)


def test_evaluation_records_actual_response_scores_and_replays_without_calls(tmp_path):
    from architecture_iq.studio.jobs import JobStore
    from architecture_iq.studio.execution import execute_evaluation

    config = fixture_config()
    store = JobStore(tmp_path)
    job = store.create("evaluation", config)
    seen = []

    class Client:
        def __init__(self, observer):
            self.observer = observer

        def complete_conversation(self, messages, model):
            seen.append(messages)
            payload = {
                "model": model.name,
                "messages": messages,
                "max_tokens": model.max_tokens,
                "temperature": 0.0,
                "top_p": 1.0,
            }
            self.observer(
                {"payload": payload, "body_sha256": "exact-wire-hash", "url": "local"}
            )
            raw = {
                "model": "glm",
                "choices": [
                    {
                        "message": {
                            "content": '{"ranking":["B","A","C"],"citations":[],"rationale":"test"}',
                            "reasoning_content": "not the parsed answer",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 12},
            }
            return SimpleNamespace(raw=raw, finish_reason="stop", usage=raw["usage"])

    def factory(profile, observer):
        return Client(observer)
    result = execute_evaluation(store, job["id"], config, client_factory=factory)
    assert result["scores"]["glm"]["correct"] == 1
    record = store.get(job["id"])["records"][0]
    assert record["actual_request"]["body_sha256"] == "exact-wire-hash"
    assert record["answer"]["ranking"][0] == "B"
    assert record["feedback"]["correct_letter"] == "B"
    assert store.get(job['id'])['progress']['completed'] == 1
    execute_evaluation(store, job["id"], config, client_factory=factory)
    assert len(seen) == 1


def test_budget_rejects_before_model_request(tmp_path):
    from architecture_iq.studio.jobs import JobStore
    from architecture_iq.studio.execution import execute_evaluation

    config = fixture_config()
    config["max_tokens"] = 1
    store = JobStore(tmp_path)
    job = store.create("evaluation", config)

    def never(*_):
        raise AssertionError("must not construct client")

    with pytest.raises(ValueError, match="budget"):
        execute_evaluation(store, job["id"], config, client_factory=never)
    assert store.get(job["id"])["records"] == []


def test_model_identity_mismatch_is_failure_not_valid_answer(tmp_path):
    from architecture_iq.studio.jobs import JobStore
    from architecture_iq.studio.execution import execute_evaluation

    config = fixture_config()
    store = JobStore(tmp_path)
    job = store.create("evaluation", config)

    class Wrong:
        def complete_conversation(self, *_):
            return SimpleNamespace(
                raw={
                    "model": "wrong",
                    "choices": [
                        {
                            "message": {"content": '{"ranking":["B","A","C"]}'},
                            "finish_reason": "stop",
                        }
                    ],
                },
                finish_reason="stop",
                usage={},
            )

    with pytest.raises(RuntimeError, match="identity"):
        execute_evaluation(store, job["id"], config, client_factory=lambda *_: Wrong())
    assert store.get(job["id"])["records"][0]["status"] == "failed"


def test_transport_timeout_after_send_stays_uncertain(tmp_path):
    from architecture_iq.studio.jobs import JobStore
    from architecture_iq.studio.execution import execute_evaluation

    config = fixture_config()
    store = JobStore(tmp_path)
    job = store.create("evaluation", config)

    class Timeout:
        def __init__(self, observer):
            self.observer = observer

        def complete_conversation(self, *_):
            self.observer({"payload": {}, "body_sha256": "sent"})
            raise TimeoutError("response unknown")

    with pytest.raises(TimeoutError):
        execute_evaluation(
            store,
            job["id"],
            config,
            client_factory=lambda _, observer: Timeout(observer),
        )
    assert store.get(job["id"])["records"][0]["status"] == "uncertain"
    with pytest.raises(RuntimeError, match="uncertain"):
        execute_evaluation(store, job["id"], config, client_factory=lambda *_: None)


def test_replacing_runtime_lock_after_submission_blocks_client(tmp_path):
    from architecture_iq.studio.execution import create_client
    from architecture_iq.kb.store import canonical_hash

    lock = {"model_id": "glm", "model_parameters": {}, "process_identity": {"pid": 101}}
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    profile = {
        **fixture_config()["models"][0],
        "runtime_lock_path": str(path),
        "runtime_fingerprint": canonical_hash(lock),
    }
    create_client(profile, lambda *_: None)
    path.write_text(json.dumps({**lock, "process_identity": {"pid": 202}}))
    with pytest.raises(ValueError, match="runtime lock"):
        create_client(profile, lambda *_: None)
