import json

import pytest


def test_job_definition_frozen_and_idempotency_bound(tmp_path):
    from architecture_iq.studio.jobs import JobStore

    store = JobStore(tmp_path)
    first = store.create(
        "evaluation", {"keys": ["q1"], "model": "glm"}, idempotency_key="request-one"
    )
    again = store.create(
        "evaluation", {"keys": ["q1"], "model": "glm"}, idempotency_key="request-one"
    )
    assert again["id"] == first["id"]
    with pytest.raises(ValueError):
        store.create("evaluation", {"keys": ["q2"]}, idempotency_key="request-one")
    frozen = store.directory(first["id"]) / "definition.json"
    contents = json.loads(frozen.read_text())
    contents["config"]["keys"] = ["changed"]
    frozen.write_text(json.dumps(contents))
    with pytest.raises(ValueError, match="integrity"):
        store.get(first["id"])


def test_pause_control_does_not_rewrite_config(tmp_path):
    from architecture_iq.studio.jobs import JobStore

    store = JobStore(tmp_path)
    job = store.create("evaluation", {"keys": ["q1"]})
    store.control(job["id"], "pause")
    assert store.get(job["id"])["control"]["action"] == "pause"
    store.control(job["id"], "resume")
    assert store.get(job["id"])["control"]["action"] == "resume"
    assert store.get(job["id"])["config"] == {"keys": ["q1"]}


def test_pending_attempt_prevents_duplicate_execution(tmp_path):
    from architecture_iq.studio.jobs import JobStore

    store = JobStore(tmp_path)
    job = store.create("evaluation", {})
    store.reserve(job["id"], "q1-glm", {"prompt": "public"})
    with pytest.raises(RuntimeError, match="uncertain"):
        store.reserve(job["id"], "q1-glm", {"prompt": "public"})
    assert len(store.get(job["id"])["records"]) == 1
    store.finish(job["id"], "q1-glm", {"status": "complete", "answer": "B"})
    assert store.reserve(job["id"], "q1-glm", {"prompt": "public"})["answer"] == "B"


def test_record_request_is_written_before_response_and_survives_restart(tmp_path):
    from architecture_iq.studio.jobs import JobStore

    store = JobStore(tmp_path)
    job = store.create("evaluation", {})
    store.reserve(job["id"], "q1-glm", {"prompt": "public"})
    wire = {
        "payload": {"messages": [{"role": "user", "content": "public"}]},
        "body_sha256": "abc",
    }
    store.update_record(job["id"], "q1-glm", {"actual_request": wire})
    reloaded = JobStore(tmp_path).get(job["id"])
    assert reloaded["records"][0]["actual_request"] == wire
    assert reloaded["records"][0]["status"] == "pending"


def test_fast_worker_completion_is_not_overwritten_by_launch(tmp_path, monkeypatch):
    from architecture_iq.studio.jobs import JobStore
    from types import SimpleNamespace

    store = JobStore(tmp_path)
    job = store.create("evaluation", {})

    def launch(*args, **kwargs):
        store.update(job["id"], status="complete")
        return SimpleNamespace(pid=123)

    monkeypatch.setattr("subprocess.Popen", launch)
    store.launch(job["id"])
    assert store.get(job["id"])["status"] == "complete"


def test_dead_worker_is_interrupted_and_not_resumable(tmp_path):
    from architecture_iq.studio.jobs import JobStore

    store = JobStore(tmp_path)
    job = store.create("evaluation", {})
    store.update(job["id"], status="running", pid=2147483647)
    assert store.get(job["id"])["status"] == "interrupted"
    with pytest.raises(ValueError):
        store.control(job["id"], "resume")
