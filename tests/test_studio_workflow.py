"""Graph edits must configure the scientific coordinator, never bypass it."""
import copy
import json
from pathlib import Path

import pytest

from architecture_iq.studio.workflow import default_workflow, validate_workflow, compile_workflow
from architecture_iq.kb.orchestrator import prepare_run, run_round
from architecture_iq.kb.roles import RoleCaller, INSTRUCTIONS, read_receipt
from test_kb_workflow_orchestrator import inputs, Client, Backend
from test_kb_workflow_roles import Model


def bypass_optional(spec, node_id, source, target, condition="always"):
    spec["edges"] = [e for e in spec["edges"] if node_id not in (e["source"], e["target"])]
    spec["edges"].append({"id": f"{source}-{target}", "source": source, "target": target,
                          "source_handle": "out", "target_handle": "in", "mapping": {},
                          "condition": condition})


def enable_optional(spec, node_id, source, target, condition="always"):
    spec["edges"] = [e for e in spec["edges"] if (e["source"], e["target"]) != (source, target)]
    for a, b, c in [(source, node_id, condition), (node_id, target, "always")]:
        spec["edges"].append({"id": f"{a}-{b}", "source": a, "target": b,
                              "source_handle": "out", "target_handle": "in", "mapping": {}, "condition": c})
    if node_id == "confirmation":
        spec["settings"].update(enable_confirmation=True, n_seeds=10, max_candidate_seed_runs=1600)


def test_default_template_compiles_with_safe_routes_and_schema():
    spec = default_workflow("scientific")
    assert validate_workflow(spec) == {"valid": True, "errors": []}
    compiled = compile_workflow(spec)
    assert compiled["config"]["enable_confirmation"] is False
    assert compiled["config"]["enable_evaluation"] is False
    assert compiled["evaluate_phase"] is None
    assert compiled["role_instructions"] == {}
    assert {n["id"] for n in spec["nodes"]} == {
        "input", "solver", "commit", "reveal", "discoverer", "skeptic", "experiment",
        "confirmation", "analyst", "curator", "publish", "loop", "evaluate", "end"}
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).parents[1] / "contracts/kb_workflow.schema.json").read_text())
    jsonschema.validate(spec, schema)


@pytest.mark.parametrize("mutation", ["private", "missing", "publish_bypass", "unsupported_mapping", "unbounded", "role", "unknown_config"])
def test_invalid_edges_and_stage_edits_block_compilation(mutation):
    spec = default_workflow("scientific")
    if mutation == "missing":
        spec["nodes"] = [n for n in spec["nodes"] if n["id"] != "commit"]
    elif mutation == "private":
        spec["edges"].append({"id": "leak", "source": "reveal", "target": "solver",
                              "source_handle": "out", "target_handle": "in", "mapping": {}, "condition": "always"})
    elif mutation == "publish_bypass":
        next(e for e in spec["edges"] if e["target"] == "publish")["source"] = "analyst"
    elif mutation == "unsupported_mapping":
        spec["edges"][0]["mapping"] = {"feedback": "question"}
    elif mutation == "unbounded":
        spec["settings"]["max_rounds"] = 4
    elif mutation == "role":
        next(n for n in spec["nodes"] if n["id"] == "solver")["config"]["role"] = "curator"
    else:
        spec["settings"]["private_feedback"] = "arbitrary-file"
    report = validate_workflow(spec)
    assert report["valid"] is False and report["errors"]
    with pytest.raises(ValueError):
        compile_workflow(spec)


def test_optional_paths_configure_runtime_and_positions_do_not_change_execution():
    spec = default_workflow("scientific")
    enable_optional(spec, "confirmation", "experiment", "analyst")
    enable_optional(spec, "evaluate", "loop", "end", "done")
    original = compile_workflow(spec)
    assert original["evaluate_phase"] == "final"
    assert original["config"]["enable_evaluation"] is True
    spec["nodes"][0]["position"] = {"x": 901, "y": -15}
    moved = compile_workflow(spec)
    assert moved["execution_hash"] == original["execution_hash"]
    assert moved["workflow_hash"] != original["workflow_hash"]
    bypass_optional(spec, "confirmation", "experiment", "analyst")
    spec["settings"]["enable_confirmation"] = False
    bypass_optional(spec, "evaluate", "loop", "end", "done")
    compiled = compile_workflow(spec)
    assert compiled["config"]["enable_confirmation"] is False
    assert compiled["config"]["enable_evaluation"] is False
    assert compiled["execution_hash"] != original["execution_hash"]
    spec["settings"]["enable_confirmation"] = True
    assert not validate_workflow(spec)["valid"]


def test_prompt_edit_is_frozen_and_reaches_actual_role_request(tmp_path):
    spec = default_workflow("scientific")
    next(n for n in spec["nodes"] if n["id"] == "solver")["config"]["prompt"] = "Compare width first."
    compiled = compile_workflow(spec)
    config, questions, private, legacy = inputs()
    config["role_instructions"] = compiled["role_instructions"]
    manifest = prepare_run(tmp_path, config, questions, private, legacy)
    assert manifest["config"]["role_instructions"] == {"solver": "Compare width first."}
    client = Client()
    run_round(tmp_path, client, Backend(), round_index=1)
    solver = next(p for p in client.prompts if "You are the solver in" in p)
    assert "Compare width first." in solver
    assert INSTRUCTIONS["solver"] in solver
    assert "untrusted research data" in solver and "GT_SECRET" not in solver
    record = next(read_receipt(p) for p in (tmp_path / "calls").glob("*.json") if read_receipt(p)["role"] == "solver")
    assert record["request"]["role_instruction"] == "Compare width first."
    changed = copy.deepcopy(config)
    changed["role_instructions"]["solver"] = "Use another strategy."
    with pytest.raises(ValueError, match="changed"):
        prepare_run(tmp_path, changed, questions, private, legacy)


def test_prompt_override_cannot_replay_with_changed_instructions(tmp_path):
    client = Client()
    first = RoleCaller(tmp_path, client, Model(), fingerprint="test", instructions={"solver": "First prompt"})
    first.call("solver", {}, key="q", round_index=1)
    second = RoleCaller(tmp_path, client, Model(), fingerprint="test", instructions={"solver": "Second prompt"})
    with pytest.raises(ValueError, match="changed"):
        second.call("solver", {}, key="q", round_index=1)
    assert len(client.prompts) == 1


def test_pause_at_completed_call_boundary_replays_without_repeating_call(tmp_path):
    prepare_run(tmp_path, *inputs())
    client, events = Client(), []
    class Pause(Exception):
        pass
    def control(event):
        if event["node_id"] == "solver" and event["state"] == "complete":
            raise Pause()
    with pytest.raises(Pause):
        run_round(tmp_path, client, Backend(), round_index=1, stage_observer=events.append, control_callback=control)
    assert len(client.prompts) == 1
    assert events[-1]["node_id"] == "solver" and events[-1]["safe_boundary"] is True
    assert next(read_receipt(p) for p in (tmp_path / "calls").glob("*.json"))["status"] == "complete"
    result = run_round(tmp_path, client, Backend(), round_index=1, stage_observer=events.append)
    assert result["status"] == "complete"
    assert sum("You are the solver in" in p for p in client.prompts) == 1
    assert all(e["round_index"] == 1 for e in events)
    assert any(e["node_id"] == "publish" and e["state"] == "complete" for e in events)


@pytest.mark.parametrize("confirmation", [True, False])
def test_confirmation_route_changes_coordinator_experiment_phases(tmp_path, confirmation):
    spec = default_workflow("scientific")
    spec["settings"].update(max_rounds=1, discovery_per_round=1, exploration_count=1,
                            max_tokens_per_round=100000, wall_time_seconds=60)
    if confirmation:
        enable_optional(spec, "confirmation", "experiment", "analyst")
    config, questions, private, legacy = inputs()
    config.update(compile_workflow(spec)["config"])
    prepare_run(tmp_path, config, questions, private, legacy)
    observed = []
    def backend(request, out, budget):
        observed.append((request["phase"], request["count"], request["n_seeds"]))
        return []
    result = run_round(tmp_path, Client(reject=False), backend, round_index=1)
    assert result["confirmation_attempted"] is confirmation
    assert observed == ([("exploration", 1, 10), ("confirmation", 48, 10)] if confirmation else [("exploration", 1, 2)])


@pytest.mark.parametrize("bad", [None, [], {"solver": 1}, {"shell": "Run anything"}])
def test_invalid_frozen_role_instructions_rejected_at_prepare(tmp_path, bad):
    config, questions, private, legacy = inputs()
    config["role_instructions"] = bad
    if bad is None:
        # Omission/None intentionally retain the existing default behavior.
        assert prepare_run(tmp_path, config, questions, private, legacy)["config"]["role_instructions"] == {}
    else:
        with pytest.raises(ValueError, match="instruction|role"):
            prepare_run(tmp_path, config, questions, private, legacy)


def test_enabled_confirmation_route_requires_scientific_counts():
    spec = default_workflow("scientific")
    enable_optional(spec, "confirmation", "experiment", "analyst")
    spec["settings"]["n_seeds"] = 2
    report = validate_workflow(spec)
    assert not report["valid"]
    assert any("48 independent datasets and ten seeds" in error for error in report["errors"])
    with pytest.raises(ValueError):
        compile_workflow(spec)


def prepared_evaluation(tmp_path, phase):
    config, questions, private, legacy = inputs()
    evaluation_question = copy.deepcopy(questions[0])
    evaluation_question.update(id="eval-q", dataset_id="eval-d", lineage_id="eval-l", split=phase)
    questions.append(evaluation_question)
    private["eval-q"] = copy.deepcopy(private["q1"])
    prepare_run(tmp_path, config, questions, private, legacy)
    run_round(tmp_path, Client(), Backend(), round_index=1)


@pytest.mark.parametrize("phase", ["development", "final"])
def test_evaluation_pause_occurs_after_receipt_and_resume_does_not_repeat_call(tmp_path, phase):
    from architecture_iq.kb.orchestrator import evaluate_run
    prepared_evaluation(tmp_path, phase)
    client, events = Client(), []
    class Pause(Exception):
        pass
    def pause(event):
        if event["state"] == "complete" and event.get("key"):
            assert event["safe_boundary"] is True and event["phase"] == phase
            calls = [read_receipt(p) for p in (tmp_path / "calls").glob("*.json")]
            receipt = next(r for r in calls if r["key"] == event["key"])
            assert receipt["status"] == "complete"
            assert len(client.prompts) == 1
            assert not list((tmp_path / "evals").glob("**/result.json"))
            raise Pause()
    with pytest.raises(Pause):
        evaluate_run(tmp_path, client, phase=phase, stage_observer=events.append, control_callback=pause)
    result = evaluate_run(tmp_path, client, phase=phase, stage_observer=events.append)
    assert len(client.prompts) == 3
    assert all("GT_SECRET" not in prompt for prompt in client.prompts)
    assert result["kb_unchanged"] and result["scores"]["current"]["correct"] == 1
    assert events[-1]["node_id"] == "evaluate" and events[-1]["state"] == "complete"
    assert not events[-1].get("key")
    assert any(e["state"] == "running" and e["safe_boundary"] is False for e in events)
    assert evaluate_run(tmp_path, client, phase=phase) == result
    assert len(client.prompts) == 3


def test_evaluation_pending_call_is_never_retried_or_reported_complete(tmp_path):
    from architecture_iq.kb.orchestrator import evaluate_run
    prepared_evaluation(tmp_path, "final")
    events, calls = [], []
    class Uncertain:
        def complete(self, *args):
            calls.append(args)
            raise TimeoutError("Uncertain transport")
    client = Uncertain()
    with pytest.raises(TimeoutError):
        evaluate_run(tmp_path, client, phase="final", stage_observer=events.append)
    with pytest.raises(RuntimeError, match="pending|uncertain"):
        evaluate_run(tmp_path, client, phase="final", stage_observer=events.append)
    assert len(calls) == 1
    assert not any(e["state"] == "complete" for e in events)
    receipt = next(read_receipt(p) for p in (tmp_path / "calls").glob("*.json") if read_receipt(p)["key"].startswith("eval-"))
    assert receipt["status"] == "pending"


def test_workflow_schema_accepts_direct_server_path_references():
    jsonschema = pytest.importorskip("jsonschema")
    spec = default_workflow("scientific")
    spec["settings"].update(output_root="/allowed/output", runtime_lock_path="/allowed/runtime.json",
                            kb_path="/allowed/kb.json", rules_path="/allowed/rules.json")
    assert validate_workflow(spec)["valid"]
    schema = json.loads((Path(__file__).parents[1] / "contracts/kb_workflow.schema.json").read_text())
    jsonschema.validate(spec, schema)
    compiled = compile_workflow(spec)
    assert not ({"output_root", "runtime_lock_path", "kb_path", "rules_path"} & compiled["config"].keys())


def test_studio_workflow_execution_publishes_evaluation_call_stages(tmp_path, monkeypatch):
    from architecture_iq.kb import cli
    from architecture_iq.studio import execution
    from architecture_iq.studio.jobs import JobStore
    from test_studio_execution import fixture_config
    spec = default_workflow("scientific")
    spec["settings"]["loop_mode"] = "automatic"
    enable_optional(spec, "evaluate", "loop", "end", "done")
    _, questions, private, _ = inputs()
    evaluation_question = copy.deepcopy(questions[0])
    evaluation_question.update(id="eval-q", dataset_id="eval-d", lineage_id="eval-l", split="final")
    questions.append(evaluation_question)
    private["eval-q"] = copy.deepcopy(private["q1"])
    config = fixture_config()
    lock = tmp_path / "runtime.json"
    lock.write_text('{}')
    config["workflow"] = spec
    config["models"][0]["runtime_lock_path"] = str(lock)
    from architecture_iq.kb.store import canonical_hash
    config["models"][0]["runtime_fingerprint"] = canonical_hash({})
    config["question_set"].update(questions=questions, feedback=private)
    monkeypatch.setattr(cli, "read_runtime_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "verify_live_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(execution, "create_client", lambda *args: Client())
    store = JobStore(tmp_path / "studio")
    job = store.create("workflow", config)
    result = execution.execute_workflow(store, job["id"], config)
    assert result["evaluation"]["scores"]["current"]["correct"] == 1
    events = store.events(job["id"])
    completed_calls = [e for e in events if e.get("type") == "stage" and e.get("node_id") == "evaluate" and e.get("state") == "complete" and e.get("key")]
    assert len(completed_calls) == 3
    assert all(e["safe_boundary"] is True for e in completed_calls)
