import json

import pytest

from fastapi.testclient import TestClient


def make_client(tmp_path):
    from services.kb_workflow_api.app import create_app

    source = tmp_path / "sources"
    source.mkdir(exist_ok=True)
    return TestClient(
        create_app(
            state_root=tmp_path / "state",
            allowed_roots=[source],
            execution_enabled=False,
        )
    ), source


def test_offline_api_has_real_empty_state_and_blocks_execution(tmp_path):
    client, _ = make_client(tmp_path)
    result = client.get("/api/studio/bootstrap")
    assert result.status_code == 200, result.text
    assert result.json()["stats"]["questions"] == 0
    assert result.json()["service"]["execution_enabled"] is False
    assert (
        client.post("/api/studio/runs", json={"kind": "evaluation"}).status_code == 409
    )


def test_source_path_escape_blocked_without_read(tmp_path):
    client, _ = make_client(tmp_path)
    outside = tmp_path / "private.json"
    outside.write_text('{"secret":"SENTINEL"}')
    result = client.post("/api/studio/sources/import", json={"path": str(outside)})
    assert result.status_code == 422
    assert "SENTINEL" not in result.text


def test_import_selection_preview_and_no_private_feedback(tmp_path):
    client, source = make_client(tmp_path)
    question = {
        "id": "q_test",
        "family": "univariate_regression",
        "dataset_id": "d1",
        "lineage_id": "d1",
        "prompt": "PUBLIC ONLY",
        "choices": [{"id": "c" + x, "letter": x, "view": {}} for x in "ABC"],
        "feedback": {"correct_letter": "B", "secret": "PRIVATE_MARKER"},
    }
    (source / "questions.json").write_text(json.dumps([question]))
    response = client.post(
        "/api/studio/sources/import", json={"path": str(source / "questions.json")}
    )
    assert response.status_code == 200, response.text
    listing = client.get("/api/studio/questions").json()
    assert listing["total"] == 1
    key = listing["items"][0]["key"]
    detail = client.get("/api/studio/questions/" + key).json()
    assert "PRIVATE_MARKER" not in json.dumps(detail)
    selected = client.post(
        "/api/studio/question-sets", json={"name": "test", "keys": [key]}
    ).json()
    model = client.post(
        "/api/studio/models",
        json={
            "id": "glm",
            "name": "GLM",
            "model": "glm",
            "base_url": "http://127.0.0.1:18054/v1",
            "parameters": {"max_tokens": 64},
        },
    )
    assert model.status_code == 200, model.text
    preview = client.post(
        "/api/studio/runs/preview",
        json={
            "kind": "evaluation",
            "question_set_id": selected["id"],
            "model_ids": ["glm"],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["request_count"] == 1
    assert "PUBLIC ONLY" in preview.text and "PRIVATE_MARKER" not in preview.text


def test_workflow_direct_paths_roundtrip_and_freeze(tmp_path):
    client, source = make_client(tmp_path)
    spec = client.get("/api/studio/workflow/default?method_id=scientific").json()
    spec["settings"].update(
        output_root=str(tmp_path / "state"), kb_path=str(source / "kb.json")
    )
    result = client.post("/api/studio/workflows/validate", json=spec)
    assert result.status_code == 200 and result.json()["valid"], result.text
    saved = client.post("/api/studio/workflows", json=spec)
    assert saved.status_code == 200, saved.text
    listing = client.get("/api/studio/workflows").json()
    assert listing["items"][0]["workflow"]["settings"]["kb_path"] == str(
        source / "kb.json"
    )


def test_queued_job_api_does_not_expose_private_feedback(tmp_path):
    client, _ = make_client(tmp_path)
    from architecture_iq.studio.jobs import JobStore

    store = JobStore(tmp_path / "state")
    job = store.create(
        "evaluation",
        {
            "question_set": {
                "id": "test",
                "questions": [],
                "feedback": {"q": {"correct_letter": "B", "secret": "PRIVATE_MARKER"}},
            }
        },
    )
    for path in ["/api/studio/runs", "/api/studio/runs/" + job["id"]]:
        response = client.get(path)
        assert response.status_code == 200
        assert (
            "PRIVATE_MARKER" not in response.text
            and "correct_letter" not in response.text
        )


def test_submit_rejects_missing_or_stale_preview_before_launch(tmp_path, monkeypatch):
    from services.kb_workflow_api.app import create_app
    from architecture_iq.kb import cli
    from architecture_iq.studio.jobs import JobStore

    monkeypatch.setattr(cli, "require_execution_host", lambda *_: None)
    launches = []
    monkeypatch.setattr(
        JobStore, "launch", lambda self, identifier: launches.append(identifier)
    )
    app = create_app(
        state_root=tmp_path / "state", allowed_roots=[tmp_path], execution_enabled=True
    )
    client = TestClient(app)
    q = {
        "id": "q",
        "family": "univariate_regression",
        "dataset_id": "d",
        "lineage_id": "d",
        "prompt": "PUBLIC",
        "choices": [{"id": "c" + x, "letter": x, "view": {}} for x in "ABC"],
        "feedback": {"correct_letter": "B"},
    }
    path = tmp_path / "input.json"
    path.write_text(json.dumps([q]))
    app.state.catalog.import_source(path)
    key = app.state.catalog.list_questions()["items"][0]["key"]
    selected = app.state.catalog.create_question_set("test", [key])
    model = {
        "id": "glm",
        "name": "GLM",
        "model": "glm",
        "base_url": "http://localhost:1/v1",
        "parameters": {"max_tokens": 64},
    }
    app.state.models.save(model)
    body = {
        "kind": "evaluation",
        "question_set_id": selected["id"],
        "model_ids": ["glm"],
    }
    assert client.post("/api/studio/runs", json=body).status_code == 409
    preview = client.post("/api/studio/runs/preview", json=body).json()
    app.state.models.save({**model, "parameters": {"max_tokens": 128}})
    response = client.post(
        "/api/studio/runs",
        json={**body, "expected_config_hash": preview["config_hash"]},
    )
    assert response.status_code == 409, response.text
    assert not launches and not app.state.jobs.list()
    fresh = client.post("/api/studio/runs/preview", json=body).json()
    response = client.post(
        "/api/studio/runs", json={**body, "expected_config_hash": fresh["config_hash"]}
    )
    assert response.status_code == 200, response.text
    assert len(launches) == 1
    assert response.json()["config"]["models"][0]["parameters"]["max_tokens"] == 128


def task_preview_setup(tmp_path, monkeypatch, *, task_split="final", task_changes=None,
                       enabled=True, execute=False):
    from services.kb_workflow_api.app import create_app
    from architecture_iq.kb import cli, orchestrator
    from architecture_iq.studio.jobs import JobStore
    from test_studio_task_inputs import question
    from test_studio_workflow import enable_optional

    monkeypatch.setattr(cli, "read_runtime_lock", lambda *a, **k: None)
    monkeypatch.setattr(cli, "require_execution_host", lambda *a, **k: None)
    monkeypatch.setattr(JobStore, "launch", lambda *a: None)
    monkeypatch.setattr(orchestrator, "prepare_run", lambda *a, **k: pytest.fail("preview must not prepare/write a run"))
    app = create_app(state_root=tmp_path / "state", allowed_roots=[tmp_path], execution_enabled=execute)
    source = tmp_path / "input.json"
    inputs = [question("research"), question("task", task_split, **(task_changes or {}))]
    for item in inputs:
        item["feedback"] = {"correct_letter": "B", "secret": "PRIVATE"}
    source.write_text(json.dumps(inputs))
    app.state.catalog.import_source(source)
    rows = app.state.catalog.list_questions()["items"]
    keys = {row["id"]: row["key"] for row in rows}
    data = app.state.catalog.create_question_set("Data", [keys["research"]])
    task = app.state.catalog.create_question_set("Task", [keys["task"]])
    lock = tmp_path / "runtime-lock.json"
    lock.write_text("{}")
    app.state.models.save({"id": "glm", "name": "GLM", "model": "glm",
                           "base_url": "http://localhost:1/v1", "parameters": {"max_tokens": 64},
                           "runtime_lock_path": str(lock)})
    client = TestClient(app)
    spec = client.get("/api/studio/workflow/default?method_id=scientific").json()
    spec["settings"].update(model_id="glm", question_set_id=data["id"], task_question_set_id=task["id"])
    if enabled:
        enable_optional(spec, "evaluate", "loop", "end", "done")
    return client, app, {"kind": "workflow", "workflow": spec}, data, task


def test_separate_task_preview_is_pure_public_and_phase_qualified(tmp_path, monkeypatch):
    client, app, body, data, task = task_preview_setup(tmp_path, monkeypatch)
    response = client.post("/api/studio/runs/preview", json=body)
    assert response.status_code == 200, response.text
    summary = response.json()["task"]
    assert summary == {"configured": True, "enabled": True, "phase": "final", "source": "separate",
                       "question_set_id": task["id"], "count": 1, "executed_count": 1,
                       "split_counts": {"discovery": 0, "development": 0, "final": 1},
                       "effective_research_count": 1, "effective_evaluation_count": 1,
                       "omitted_data_research_count": 0,
                       "omitted_data_evaluation_count": 0,
                       "notice": "独立 Task 题集用于本次评测；Data 中 0 道旧评测题不参与，原题集仍完整冻结。"}
    assert "PRIVATE" not in response.text and "correct_letter" not in response.text
    assert not app.state.jobs.list()
    assert not list((tmp_path / "state").glob("**/kb/CURRENT"))
    assert client.get("/api/studio/questions?split=final").json()["items"][0]["id"] == "task"
    assert client.get("/api/studio/questions?split=development").json()["total"] == 0
    assert client.get("/api/studio/questions?split=unknown").status_code == 422
    filtered = client.post("/api/studio/question-sets", json={"name": "filtered Task", "filters": {"split": "final"}})
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["keys"] == task["keys"]


@pytest.mark.parametrize("changes,split", [({}, "discovery"), ({}, "development"),
                                           ({"dataset_id": "dataset-research"}, "final"),
                                           ({"lineage_id": "lineage-research"}, "final")])
def test_task_preview_rejects_wrong_phase_or_research_overlap_before_launch(tmp_path, monkeypatch, changes, split):
    client, app, body, *_ = task_preview_setup(tmp_path, monkeypatch, task_split=split, task_changes=changes)
    response = client.post("/api/studio/runs/preview", json=body)
    assert response.status_code == 422, response.text
    assert not app.state.jobs.list()


def test_disabled_evaluation_retains_task_reference_without_execution(tmp_path, monkeypatch):
    client, _, body, _, task = task_preview_setup(tmp_path, monkeypatch, enabled=False)
    response = client.post("/api/studio/runs/preview", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["task"]["question_set_id"] == task["id"]
    assert response.json()["task"]["enabled"] is False
    assert response.json()["task"]["executed_count"] == 0
    assert response.json()["compiled"]["config"].get("task_question_set_id") is None


def test_separate_task_replaces_data_holdout_without_rewriting_frozen_bundle(tmp_path, monkeypatch):
    from test_studio_task_inputs import question
    client, app, body, data, task = task_preview_setup(tmp_path, monkeypatch, execute=True)
    old = question("old-heldout", "final")
    old["choices"] = old["choices"][:2]  # Not executed by the three-choice research core.
    old["feedback"] = {"correct_letter": "B"}
    path = tmp_path / "old-heldout.json"
    path.write_text(json.dumps([old]))
    app.state.catalog.import_source(path)
    key = next(row["key"] for row in app.state.catalog.list_questions()["items"] if row["id"] == "old-heldout")
    bundle = app.state.catalog.create_question_set("old bundle", [*data["keys"], key])
    body["workflow"]["settings"]["question_set_id"] = bundle["id"]
    response = client.post("/api/studio/runs/preview", json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["request_count"] == 1
    assert "PUBLIC old-heldout" not in json.dumps(preview["requests"])
    assert "PUBLIC task" not in json.dumps(preview["requests"])
    assert preview["task"]["omitted_data_evaluation_count"] == 1
    assert preview["task"]["effective_evaluation_count"] == 1
    response = client.post("/api/studio/runs", json={**body, "expected_config_hash": preview["config_hash"]})
    assert response.status_code == 200, response.text
    frozen = app.state.jobs.get(response.json()["id"])["config"]
    assert len(frozen["question_set"]["questions"]) == 2
    assert frozen["question_set"]["questions"][1]["split"] == "final"


def test_legacy_bundled_task_preview_remains_available_without_separate_reference(tmp_path, monkeypatch):
    client, app, body, data, task = task_preview_setup(tmp_path, monkeypatch)
    bundle = app.state.catalog.create_question_set("bundle", [*data["keys"], *task["keys"]])
    settings = body["workflow"]["settings"]
    settings["question_set_id"] = bundle["id"]
    settings.pop("task_question_set_id")
    response = client.post("/api/studio/runs/preview", json=body)
    assert response.status_code == 200, response.text
    summary = response.json()["task"]
    assert summary["source"] == "bundled" and summary["configured"] is False
    assert summary["executed_count"] == 1
    assert summary["omitted_data_evaluation_count"] == 0
    assert response.json()["request_count"] == 1  # Only real research-side preview.


def test_workflow_preview_covers_only_scheduled_discovery_and_freezes_extra_inputs(tmp_path, monkeypatch):
    from test_studio_task_inputs import question
    client, app, body, data, _ = task_preview_setup(tmp_path, monkeypatch, execute=True)
    more = [question("extra-1"), question("extra-2")]
    for item in more:
        item["feedback"] = {"correct_letter": "B"}
    path = tmp_path / "extras.json"
    path.write_text(json.dumps(more))
    app.state.catalog.import_source(path)
    keys = {row["id"]: row["key"] for row in app.state.catalog.list_questions()["items"]}
    full = app.state.catalog.create_question_set("three research", [*data["keys"], keys["extra-1"], keys["extra-2"]])
    body["workflow"]["settings"]["question_set_id"] = full["id"]
    response = client.post("/api/studio/runs/preview", json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["request_count"] == 1
    assert preview["requests"][0]["question_key"] == data["keys"][0]
    assert preview["task"]["effective_research_count"] == 1
    assert preview["task"]["omitted_data_research_count"] == 2
    assert "另 2 道研究题不执行" in preview["task"]["notice"]
    response = client.post("/api/studio/runs", json={**body, "expected_config_hash": preview["config_hash"]})
    assert response.status_code == 200, response.text
    frozen = app.state.jobs.get(response.json()["id"])["config"]["question_set"]
    assert frozen["keys"] == full["keys"] and len(frozen["questions"]) == 3
    assert set(frozen["feedback"]) == set(full["keys"])


def test_task_identity_is_frozen_and_guarded_by_preview_hash(tmp_path, monkeypatch):
    client, app, body, data, task = task_preview_setup(tmp_path, monkeypatch, execute=True)
    preview = client.post("/api/studio/runs/preview", json=body).json()
    changed = json.loads(json.dumps(body))
    changed["workflow"]["settings"].pop("task_question_set_id")
    response = client.post("/api/studio/runs", json={**changed, "expected_config_hash": preview["config_hash"]})
    assert response.status_code != 200 and not app.state.jobs.list()
    response = client.post("/api/studio/runs", json={**body, "expected_config_hash": preview["config_hash"]})
    assert response.status_code == 200, response.text
    frozen = response.json()["config"]
    assert frozen["question_set"]["id"] == data["id"]
    assert frozen["task_question_set"]["id"] == task["id"]
    assert "PRIVATE" not in response.text and "correct_letter" not in response.text
    assert app.state.jobs.get(response.json()["id"])["config"]["task_question_set"]["feedback"]


def test_methods_catalog_and_round_decision_api(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get('/api/studio/methods')
    assert response.status_code == 200
    assert {item['id'] for item in response.json()['items']} == {'basic_learning', 'scientific', 'paired_progressive', 'expel', 'paired_expel', 'rule_refinement'}
    store = client.app.state.jobs
    job = store.create('workflow', {})
    store.offer_round_decision(job['id'], round_index=1, kb_version='kb1', next_round_index=None,
                              next_question_ids=[], next_round_reason='round_cap', evaluate_available=False)
    path = f"/api/studio/runs/{job['id']}/round-decision"
    unavailable = client.post(path, json={'round_index': 1, 'action': 'continue'})
    assert unavailable.status_code == 409
    response = client.post(path, json={'round_index': 1, 'action': 'finish'})
    assert response.status_code == 200 and response.json()['round_decision']['action'] == 'finish'
    repeated = client.post(path, json={'round_index': 1, 'action': 'finish'})
    assert repeated.status_code == 200
    assert client.post(path, json={'round_index': 1, 'action': 'evaluate'}).status_code == 409
    assert client.post(path, json={'round_index': True, 'action': 'finish'}).status_code == 422
    snapshot = client.get(f"/api/studio/runs/{job['id']}").json()
    assert snapshot['transport']['stage_events'] == 'polling'
    assert snapshot['transport']['text_events'] == 'unavailable'
    assert snapshot['transport']['separate_cursors'] is True


def test_experience_preview_counts_consolidation_and_task_arms_and_freezes_recipe(tmp_path, monkeypatch):
    client, app, body, _, _ = task_preview_setup(tmp_path, monkeypatch, execute=True)
    base = client.post('/api/studio/runs/preview', json=body).json()
    body['workflow']['settings']['method_id'] = 'expel'
    response = client.post('/api/studio/runs/preview', json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['learning']['max_calls_per_round'] == base['learning']['max_calls_per_round'] + 1
    assert len(preview['evaluation_arms']) == 6
    assert preview['evaluation_budget']['max_calls'] == 6
    assert preview['evaluation_budget']['output_reserve'] == 384
    started = client.post('/api/studio/runs', json={**body, 'expected_config_hash': preview['config_hash']})
    assert started.status_code == 200, started.text
    frozen = app.state.jobs.definition(started.json()['id'])['config']['method']
    assert frozen['id'] == 'expel' and frozen['hash'] == preview['compiled']['method']['hash']
