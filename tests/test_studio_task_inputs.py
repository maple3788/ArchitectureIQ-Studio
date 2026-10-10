"""Separate Task sets retain frozen splits and use native workflow validation."""
import copy
import json
from types import SimpleNamespace

import pytest


def question(identifier, split="discovery", **changes):
    return {"id": identifier, "family": "univariate_regression",
            "dataset_id": "dataset-" + identifier, "lineage_id": "lineage-" + identifier,
            "prompt": "PUBLIC " + identifier, "split": split,
            "choices": [{"id": identifier + letter, "letter": letter,
                         "view": {"family": "univariate_regression"}} for letter in "ABC"], **changes}


def question_set(identifier, questions):
    return {"id": identifier, "hash": identifier, "keys": [q["id"] for q in questions],
            "questions": questions,
            "feedback": {q["id"]: {"correct_letter": "B", "secret": "PRIVATE"} for q in questions}}


def coordinator():
    return {"max_rounds": 1, "discovery_per_round": 1, "model": {"max_tokens": 64},
            "context_size": 32768}


def test_combines_active_task_without_mutating_sets_or_splits():
    from architecture_iq.studio.task_inputs import workflow_inputs
    data = question_set("data", [question("research")])
    task = question_set("task", [question("heldout", "final")])
    before = copy.deepcopy((data, task))
    public, private = workflow_inputs(data, task, phase="final")
    assert [q["id"] for q in public] == ["research", "heldout"]
    assert [q["split"] for q in public] == ["discovery", "final"]
    assert set(private) == {"research", "heldout"}
    assert (data, task) == before


@pytest.mark.parametrize("shared", ["id", "dataset_id", "lineage_id", "pair_id"])
def test_separate_task_rejects_cross_set_identity_even_when_split_equal(shared):
    from architecture_iq.studio.task_inputs import workflow_inputs
    a, b = question("research"), question("heldout", "final")
    a[shared] = b[shared] = "shared"
    with pytest.raises(ValueError, match="Task.*overlap"):
        workflow_inputs(question_set("data", [a]), question_set("task", [b]), phase="final")


def test_task_requires_existing_target_split_and_rejects_duplicate_keys():
    from architecture_iq.studio.task_inputs import workflow_inputs
    data = question_set("data", [question("research")])
    with pytest.raises(ValueError, match="Task.*final"):
        workflow_inputs(data, question_set("task", [question("heldout", "development")]), phase="final")
    duplicate = question("heldout", "final")
    with pytest.raises(ValueError, match="Duplicate.*Task"):
        workflow_inputs(data, question_set("task", [duplicate, duplicate]), phase="final")


def test_disabled_task_is_retained_but_not_added_to_execution_and_bundle_is_compatible():
    from architecture_iq.studio.task_inputs import workflow_inputs
    data = question_set("data", [question("research"), question("bundled", "final")])
    task = question_set("task", [question("separate", "final")])
    public, private = workflow_inputs(data, task, phase=None)
    assert public == data["questions"] and private == data["feedback"]
    assert workflow_inputs(data, phase="final") == (data["questions"], data["feedback"])


def test_active_separate_task_replaces_bundled_holdout_and_reports_exclusions():
    from architecture_iq.studio.task_inputs import workflow_inputs, task_summary
    data = question_set("data", [question("research"), question("old-final", "final"),
                                 question("old-dev", "development")])
    task = question_set("task", [question("new-final", "final")])
    public, private = workflow_inputs(data, task, phase="final")
    assert [q["id"] for q in public] == ["research", "new-final"]
    assert set(private) == {"research", "new-final"}
    assert len(data["questions"]) == 3
    summary = task_summary(data, task, phase="final", enabled=True)
    assert summary["effective_research_count"] == summary["effective_evaluation_count"] == 1
    assert summary["omitted_data_evaluation_count"] == 2


def test_pure_validator_enforces_pair_split_and_does_not_write(tmp_path):
    from architecture_iq.kb.inputs import validate_public_inputs
    questions = [question("research", pair_id="pair"), question("heldout", "final", pair_id="pair")]
    with pytest.raises(ValueError, match="pair.*split"):
        validate_public_inputs(coordinator(), questions, question_set("x", questions)["feedback"])
    assert not list(tmp_path.iterdir())


def test_task_reference_is_typed_frozen_and_not_a_coordinator_setting():
    from architecture_iq.studio.workflow import default_workflow, compile_workflow, validate_workflow
    spec = default_workflow("scientific")
    spec["settings"]["task_question_set_id"] = "task-one"
    before = compile_workflow(spec)
    assert "task_question_set_id" not in before["config"]
    spec["settings"]["task_question_set_id"] = "task-two"
    assert compile_workflow(spec)["execution_hash"] != before["execution_hash"]
    for invalid in ("", None, 3):
        spec["settings"]["task_question_set_id"] = invalid
        assert not validate_workflow(spec)["valid"]


def test_public_job_redacts_both_frozen_sets():
    from architecture_iq.studio.execution import public_job
    data = question_set("data", [question("research")])
    task = question_set("task", [question("heldout", "final")])
    result = public_job({"config": {"question_set": data, "task_question_set": task}})
    assert "PRIVATE" not in json.dumps(result) and "correct_letter" not in json.dumps(result)
    assert result["config"]["task_question_set"]["question_count"] == 1
    assert result["config"]["question_set"]["id"] == "data"
    assert "feedback" in task


def test_execute_workflow_passes_combined_inputs_to_canonical_prepare(tmp_path, monkeypatch):
    from architecture_iq.studio.execution import execute_workflow
    from architecture_iq.studio.workflow import default_workflow
    from architecture_iq.kb import cli, orchestrator
    from architecture_iq.kb.store import canonical_hash
    spec = default_workflow("scientific")
    spec["edges"] = [e for e in spec["edges"] if not (e["source"] == "loop" and e["target"] == "end")]
    spec["edges"] += [{"id": a + b, "source": a, "target": b, "source_handle": "out",
                       "target_handle": "in", "mapping": {}, "condition": c}
                      for a, b, c in [("loop", "evaluate", "done"), ("evaluate", "end", "always")]]
    lock = tmp_path / "runtime.json"
    lock.write_text("{}")
    monkeypatch.setattr(cli, "read_runtime_lock", lambda *a, **k: None)
    monkeypatch.setattr(cli, "verify_live_runtime", lambda *a, **k: None)
    data = question_set("data", [question("research")])
    task = question_set("task", [question("heldout", "final")])

    class Prepared(Exception):
        pass

    def prepared(out, config, public, private, legacy):
        assert [q["id"] for q in public] == ["research", "heldout"]
        assert set(private) == {"research", "heldout"}
        raise Prepared()

    monkeypatch.setattr(orchestrator, "prepare_run", prepared)
    config = {"workflow": spec, "question_set": data, "task_question_set": task,
              "models": [{"id": "glm", "model": "glm", "base_url": "http://localhost:1/v1",
                          "parameters": {"max_tokens": 64}, "runtime_lock_path": str(lock),
                          "runtime_fingerprint": canonical_hash({})}]}
    with pytest.raises(Prepared):
        execute_workflow(SimpleNamespace(directory=lambda _: tmp_path), "run", config)
