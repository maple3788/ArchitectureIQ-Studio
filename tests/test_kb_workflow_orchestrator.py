import copy
import json

import pytest

from architecture_iq.kb.orchestrator import prepare_run, run_round, status, evaluate_run


def inputs():
    question = {
        "id": "q1",
        "family": "univariate_regression",
        "dataset_id": "d1",
        "lineage_id": "l1",
        "prompt": "Choose based only on public code.",
        "choices": [
            {
                "id": f"c{x}",
                "letter": x,
                "view": {"family": "univariate_regression", "width": i},
            }
            for i, x in enumerate("ABC", 1)
        ],
    }
    config = {
        "model": {"name": "glm-5.3-flash", "max_tokens": 100},
        "runtime_fingerprint": "runtime-test",
        "max_rounds": 1,
        "discovery_per_round": 1,
        "packet_size": 3,
        "max_calls_per_round": 30,
        "max_tokens_per_round": 100000,
        "max_candidate_seed_runs": 40,
        "exploration_count": 1,
        "n_seeds": 2,
        "enable_confirmation": False,
        "seed_start": 81000000,
        "profile": "v1.5",
        "wall_time_seconds": 60,
    }
    return (
        config,
        [question],
        {"q1": {"correct_letter": "B", "significance": {"reason": "GT_SECRET"}}},
        [],
    )


class Client:
    """Role boundary double; coordinator behavior and disk writes are real."""

    def __init__(self, *, invalid_solver=False, reject=True):
        self.prompts = []
        self.invalid_solver = invalid_solver
        self.reject = reject

    def complete(self, prompt, model):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        role = prompt.split("You are the ")[1].split(" in ")[0]
        if role == "solver":
            assert "GT_SECRET" not in prompt
            output = {
                "ranking": ["B", "A", "C"],
                "citations": [],
                "rationale": "public features",
            }
            if self.invalid_solver:
                output = {"ranking": ["A", "A", "C"]}
        elif role == "discoverer":
            assert "GT_SECRET" in prompt
            output = (
                {"hypothesis": None}
                if self.reject
                else {
                    "hypothesis": {
                        "text": "Wider is better within this family.",
                        "rule": {
                            "scope": [["family", "eq", "univariate_regression"]],
                            "same": ["depth", "opt_key", "budget", "batch_size"],
                            "predict": {"higher_better": "width"},
                        },
                        "experiment": {
                            "family": "univariate_regression",
                            "factor": "width",
                        },
                        "boundary": "may fail with too little training",
                        "competing_explanation": "optimization",
                    }
                }
            )
        elif role == "skeptic":
            output = {
                "accept": True,
                "reason": "controlled factor",
                "counterexample": "small budgets",
                "experiment": {"family": "univariate_regression", "factor": "width"},
            }
        elif role == "analyst":
            output = {"summary": "No confirmed claim.", "limitations": []}
        else:
            packet = json.loads(prompt.split("DATA:\n")[1])
            output = {
                "decisions": [
                    {
                        "id": c["id"],
                        "action": "upsert",
                        "enabled": False,
                        "reason": "exploratory only",
                    }
                    for c in packet["candidates"]
                ]
            }
        return SimpleNamespace(
            raw={
                "model": model.name,
                "choices": [{"message": {"content": json.dumps(output)}}],
            },
            usage={"prompt_tokens": 100, "completion_tokens": 100},
            finish_reason="stop",
        )


class Backend:
    def __init__(self):
        self.calls = 0

    def __call__(self, request, out, max_candidate_seed_runs):
        self.calls += 1
        return []  # Explicitly no scientific evidence; cannot promote.


def test_repeated_hypothesis_across_packets_is_tested_only_once(tmp_path):
    config, questions, private, legacy = inputs()
    config.update(discovery_per_round=2, packet_size=1)
    second = copy.deepcopy(questions[0])
    second.update(id="q2", dataset_id="d2", lineage_id="l2")
    questions.append(second)
    private["q2"] = copy.deepcopy(private["q1"])
    prepare_run(tmp_path, config, questions, private, legacy)
    client, backend = Client(reject=False), Backend()
    result = run_round(tmp_path, client, backend, round_index=1)
    assert result["status"] == "complete" and backend.calls == 1
    assert sum("You are the skeptic in" in p for p in client.prompts) == 1
    assert len(result["candidates"]) == 1 and result["rejections"]


def test_discovery_contract_explains_both_directions_and_boolean_preferences():
    from architecture_iq.kb.orchestrator import _dsl_packet
    from architecture_iq.kb.rules import validate_rule

    examples = _dsl_packet()["prediction_examples"]
    assert any("lower_better" in example for example in examples)
    assert any("higher_better" in example for example in examples)
    assert any(set(example) == {"better", "worse"} for example in examples)
    for example in examples:
        validate_rule({"predict": example})


def test_next_round_can_revise_exploring_claim_without_serving_it_to_solver(tmp_path):
    from architecture_iq.kb.store import KBStore

    config, questions, private, legacy = inputs()
    config.update(max_rounds=2, packet_size=1)
    second = copy.deepcopy(questions[0])
    second.update(id="q2", dataset_id="d2", lineage_id="l2")
    questions.append(second)
    private["q2"] = copy.deepcopy(private["q1"])
    prepare_run(tmp_path, config, questions, private, legacy)
    run_round(tmp_path, Client(reject=False), Backend(), round_index=1)
    original = KBStore(tmp_path / "kb").current()["claims"][0]

    class RevisionClient(Client):
        def complete(self, prompt, model):
            packet = json.loads(prompt.split("DATA:\n")[1])
            if "You are the solver in" in prompt:
                assert packet["knowledge"] == []
            response = super().complete(prompt, model)
            if "You are the discoverer in" in prompt:
                agenda = packet["legacy_agenda"]
                assert agenda and agenda[0]["id"] == original["id"]
                assert agenda[0]["status"] == "exploring"
                assert agenda[0]["evidence_summary"]["support"] == 0
                data = json.loads(response.raw["choices"][0]["message"]["content"])
                data["hypothesis"]["revises"] = original["id"]
                data["hypothesis"]["text"] = "Revised conditional width hypothesis."
                response.raw["choices"][0]["message"]["content"] = json.dumps(data)
            return response

    run_round(tmp_path, RevisionClient(reject=False), Backend(), round_index=2)
    revised = KBStore(tmp_path / "kb").current()["claims"][0]
    assert revised["id"] == original["id"] and revised["revision"] == 2
    assert revised["parent_revision"] == 1 and revised["enabled"] is False


def test_research_agenda_counts_unique_current_revision_evidence_only():
    from architecture_iq.kb.orchestrator import _research_agenda

    claim = {
        "id": "H1",
        "revision": 2,
        "text": "Working hypothesis",
        "status": "exploring",
        "enabled": False,
        "experiment": {"family": "univariate_regression"},
        "rule": None,
        "evidence_ids": ["e1", "e2"],
    }
    first = {"id": "e1", "claim_id": "H1", "revision": 2, "outcome": "support"}
    evidence = [
        first,
        copy.deepcopy(first),
        {"id": "e2", "claim_id": "H1", "revision": 2, "outcome": "refute"},
        {"id": "e3", "claim_id": "H1", "revision": 1, "outcome": "support"},
    ]
    note = _research_agenda(inputs()[1], {"claims": [claim], "evidence": evidence})[0]
    assert note["evidence_summary"] == {"support": 1, "refute": 1, "inconclusive": 0}
    assert note["enabled"] is False and note["status"] == "exploring"


def test_initial_research_agenda_keeps_recorded_legacy_packet_shape():
    from architecture_iq.kb.orchestrator import _research_agenda

    claim = {
        "id": "K1",
        "revision": 1,
        "text": "Old assertion",
        "enabled": False,
        "status": "legacy_unverified",
        "rule": {"predict": {"higher_better": "width"}},
    }
    assert _research_agenda(inputs()[1], {"claims": [claim], "evidence": []}) == [
        {"id": "K1", "text": "Old assertion"}
    ]


def test_unpublished_previous_proposal_remains_research_context(tmp_path):
    config, questions, private, legacy = inputs()
    config.update(max_rounds=2, packet_size=1)
    second = copy.deepcopy(questions[0])
    second.update(id="q2", dataset_id="d2", lineage_id="l2")
    questions.append(second)
    private["q2"] = copy.deepcopy(private["q1"])
    prepare_run(tmp_path, config, questions, private, legacy)

    class NoPublish(Client):
        def complete(self, prompt, model):
            response = super().complete(prompt, model)
            if "You are the curator in" in prompt:
                response.raw["choices"][0]["message"]["content"] = '{"decisions":[]}'
            return response

    first = run_round(tmp_path, NoPublish(reject=False), Backend(), round_index=1)
    assert first["kb_before"] == first["kb_after"]

    class ReadHistory(Client):
        def complete(self, prompt, model):
            packet = json.loads(prompt.split("DATA:\n")[1])
            if "You are the solver in" in prompt:
                assert "prior_research" not in packet and packet["knowledge"] == []
            if "You are the discoverer in" in prompt:
                observation = packet["prior_research"][0]
                assert observation["id"] == first["candidates"][0]["id"]
                assert observation["published_in_kb"] is False
                assert observation["evidence"] == {}
            return super().complete(prompt, model)

    second_result = run_round(tmp_path, ReadHistory(), Backend(), round_index=2)
    assert second_result["status"] == "complete"
    assert second_result["kb_after"] == first["kb_after"]


def test_feedback_is_revealed_after_committed_answer_and_replay_is_inert(tmp_path):
    config, questions, private, legacy = inputs()
    prepare_run(tmp_path, config, questions, private, legacy)
    client = Client()
    result = run_round(tmp_path, client, Backend(), round_index=1)
    assert result["status"] == "complete"
    assert result["answers"]["q1"]["valid"] is True
    assert result["answers"]["q1"]["ranking"][0] == "B"
    calls = len(client.prompts)
    assert run_round(tmp_path, client, Backend(), round_index=1) == result
    assert len(client.prompts) == calls
    assert status(tmp_path)["completed_rounds"] == 1


def test_invalid_solver_answer_stays_invalid_and_feedback_can_teach(tmp_path):
    prepare_run(tmp_path, *inputs())
    client = Client(invalid_solver=True)
    result = run_round(tmp_path, client, Backend(), round_index=1)
    assert result["answers"]["q1"]["valid"] is False
    assert sum("You are the solver in" in p for p in client.prompts) == 1


def test_changed_frozen_inputs_and_excess_rounds_are_rejected(tmp_path):
    prepare_run(tmp_path, *inputs())
    p = tmp_path / "public_questions.json"
    data = json.loads(p.read_text())
    data[0]["prompt"] = "mutated"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity|changed"):
        run_round(tmp_path, Client(), Backend(), round_index=1)
    other = tmp_path / "other"
    prepare_run(other, *inputs())
    with pytest.raises(ValueError, match="[Rr]ound"):
        run_round(other, Client(), Backend(), round_index=2)


def test_no_evidence_cannot_create_enabled_scientific_claim(tmp_path):
    prepare_run(tmp_path, *inputs())
    backend = Backend()
    result = run_round(tmp_path, Client(reject=False), backend, round_index=1)
    assert backend.calls == 1
    from architecture_iq.kb.store import KBStore

    claims = KBStore(tmp_path / "kb").current()["claims"]
    assert len(claims) == 1
    assert claims[0]["status"] == "exploring"
    assert claims[0]["enabled"] is False
    assert result["confirmation_attempted"] is False


def test_lineage_cannot_cross_discovery_and_final(tmp_path):
    config, questions, private, legacy = inputs()
    final = copy.deepcopy(questions[0])
    final.update(id="q2", split="final")
    with pytest.raises(ValueError, match="lineage"):
        prepare_run(
            tmp_path,
            config,
            [*questions, final],
            {**private, "q2": private["q1"]},
            legacy,
        )


def test_final_evaluation_requires_finished_rounds(tmp_path):
    config, questions, private, legacy = inputs()
    final = copy.deepcopy(questions[0])
    final.update(id="q2", dataset_id="d2", lineage_id="l2", split="final")
    prepare_run(
        tmp_path, config, [*questions, final], {**private, "q2": private["q1"]}, legacy
    )
    with pytest.raises(RuntimeError, match="round"):
        evaluate_run(tmp_path, Client(), phase="final")


def test_semantic_revision_links_to_legacy_without_inheriting_authority(tmp_path):
    config, questions, private, _ = inputs()
    legacy = [{"id": "K1", "text": "Old broad assertion", "revision": 1, "rule": None}]
    prepare_run(tmp_path, config, questions, private, legacy)

    class RevisionClient(Client):
        def complete(self, prompt, model):
            response = super().complete(prompt, model)
            if "You are the discoverer in" in prompt:
                data = json.loads(response.raw["choices"][0]["message"]["content"])
                data["hypothesis"]["revises"] = "K1"
                response.raw["choices"][0]["message"]["content"] = json.dumps(data)
            return response

    run_round(tmp_path, RevisionClient(reject=False), Backend(), round_index=1)
    from architecture_iq.kb.store import KBStore

    claims = KBStore(tmp_path / "kb").current()["claims"]
    assert len(claims) == 1
    assert claims[0]["id"] == "K1"
    assert claims[0]["revision"] == 2 and claims[0]["parent_revision"] == 1
    assert claims[0]["evidence_ids"] == [] and claims[0]["enabled"] is False


def test_hidden_nested_public_view_is_rejected(tmp_path):
    config, questions, private, legacy = inputs()
    questions[0]["choices"][0]["view"]["notes"] = {"correct": "B"}
    with pytest.raises(ValueError, match="view|public"):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_public_context_size_is_rejected_before_network(tmp_path):
    config, questions, private, legacy = inputs()
    config["context_size"] = 200
    questions[0]["prompt"] = "x " * 10000
    with pytest.raises(ValueError, match="context"):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_agent_cannot_override_program_generated_identity(tmp_path):
    prepare_run(tmp_path, *inputs())

    class InjectionClient(Client):
        def complete(self, prompt, model):
            response = super().complete(prompt, model)
            if "You are the discoverer in" in prompt:
                data = json.loads(response.raw["choices"][0]["message"]["content"])
                data["hypothesis"].update(id="../../escaped", revision=9)
                response.raw["choices"][0]["message"]["content"] = json.dumps(data)
            return response

    backend = Backend()
    result = run_round(tmp_path, InjectionClient(reject=False), backend, round_index=1)
    assert backend.calls == 0
    assert result["candidates"] == []
    assert result["rejections"]


def test_dataset_identity_cannot_cross_splits_under_lineage_alias(tmp_path):
    config, questions, private, legacy = inputs()
    final = copy.deepcopy(questions[0])
    final.update(id="q2", lineage_id="fake-new-lineage", split="final")
    with pytest.raises(ValueError, match="dataset"):
        prepare_run(
            tmp_path,
            config,
            [*questions, final],
            {**private, "q2": private["q1"]},
            legacy,
        )


@pytest.mark.parametrize("citations", [[{}], [[]], {}, [1]])
def test_malformed_citations_commit_invalid_answer(citations):
    from architecture_iq.kb.orchestrator import _answer

    question = inputs()[1][0]
    answer = _answer({"ranking": ["A", "B", "C"], "citations": citations}, question, [])
    assert answer["valid"] is False and answer["invalid_citations"] is True


def test_malformed_curator_id_is_rejected_without_abandoning_round(tmp_path):
    prepare_run(tmp_path, *inputs())

    class BadCurator(Client):
        def complete(self, prompt, model):
            result = super().complete(prompt, model)
            if "You are the curator in" in prompt:
                result.raw["choices"][0]["message"]["content"] = (
                    '{"decisions":[{"id":[],"action":"retire"}]}'
                )
            return result

    assert (
        run_round(tmp_path, BadCurator(), Backend(), round_index=1)["status"]
        == "complete"
    )


def test_experiments_receive_all_frozen_source_exclusions(tmp_path):
    prepare_run(tmp_path, *inputs())
    received = []

    def backend(request, out, max_candidate_seed_runs):
        received.append(request)
        return []

    run_round(tmp_path, Client(reject=False), backend, round_index=1)
    assert received[0]["excluded_dataset_ids"] == ["d1"]
    assert "l1" in received[0]["excluded_lineage_ids"]


def test_crash_after_publication_replays_without_model_or_training(
    tmp_path, monkeypatch
):
    import architecture_iq.kb.orchestrator as workflow
    from architecture_iq.kb.store import KBStore

    prepare_run(tmp_path, *inputs())
    client, backend = Client(reject=False), Backend()
    save = workflow._save

    def fail_final(path, value):
        if path.name == "result.json":
            raise OSError("simulated full disk after CURRENT publication")
        save(path, value)

    monkeypatch.setattr(workflow, "_save", fail_final)
    with pytest.raises(OSError, match="full disk"):
        run_round(tmp_path, client, backend, round_index=1)
    published = KBStore(tmp_path / "kb").current()
    calls = len(client.prompts)
    monkeypatch.setattr(workflow, "_save", save)
    result = run_round(tmp_path, client, backend, round_index=1)
    assert result["kb_after"] == published["version"]
    assert len(client.prompts) == calls and backend.calls == 1
    assert len(KBStore(tmp_path / "kb").current()["claims"]) == 1


def test_knowledge_cannot_serve_a_broader_rule_than_its_experimental_scope():
    from architecture_iq.kb.orchestrator import _knowledge

    # The authored assertion deliberately omits all controls. Its independently
    # verified scope must still restrict what reaches the solver.
    scope = {
        "family": "xor_classification",
        "profile_hash": "a" * 64,
        "model_type": "mlp",
        "budget_values": [8192],
        "optimizer_types": ["Adam"],
        "loss_types": ["cross_entropy"],
        "intervention": "width",
        "pair_sampling": "uniform_applicable_pairs_from_factor_variants",
        "family_options": {},
        "controls": {
            "equal": ["opt_key", "loss_key", "budget", "batch_size"],
            "architecture_intervention": "width",
        },
    }
    claim = {
        "id": "K1",
        "revision": 1,
        "text": "Wider helps",
        "status": "replicated_in_scope",
        "enabled": True,
        "rule": {"predict": {"higher_better": "width"}},
        "validated_scope": scope,
    }
    choices = []
    for letter, width in zip("ABC", (16, 32, 64)):
        arch = {
            "type": "mlp",
            "width": width,
            "depth": 2,
            "activation": "relu",
            "residual": False,
            "layer_norm": [False, False],
        }
        view = {
            "family": "xor_classification",
            "model_type": "mlp",
            "width": width,
            "opt": "Adam",
            "opt_key": json.dumps({"type": "Adam", "lr": 0.001}),
            "loss_key": json.dumps({"loss_id": "cross_entropy"}),
            "budget": 8192,
            "batch_size": 32,
            "arch_key": json.dumps(arch),
        }
        choices.append({"letter": letter, "view": view})
    question = {
        "family": "xor_classification",
        "profile_hash": "a" * 64,
        "choices": choices,
    }
    assert _knowledge(question, [claim])[0]["validated_scope"] == scope
    question["family"] = "univariate_regression"
    assert _knowledge(question, [claim]) == []
    assert _knowledge(question, [claim], legacy=True) == []
    claim["status"] = "legacy_unverified"
    claim["enabled"] = False
    assert _knowledge(question, [claim]) == []
    assert (
        _knowledge(question, [claim], legacy=True)[0]["status"] == "legacy_unverified"
    )


def test_discovery_brief_retains_committed_ranking_without_duplicating_raw_response():
    from architecture_iq.kb.orchestrator import _answer_brief, _feedback_brief

    answer = {
        "valid": True,
        "ranking": ["A", "B", "C"],
        "citations": [],
        "rationale": "x" * 9000,
        "raw": {"rationale": "x" * 9000},
    }
    brief = _answer_brief(answer)
    assert brief["ranking"] == answer["ranking"] and brief["valid"] is True
    assert "raw" not in brief and len(brief["rationale"]) <= 1200
    feedback = {
        "correct_letter": "A",
        "candidate_metrics": {
            "c1": {
                "metric": "test_ce",
                "mean": 0.2,
                "seed_results": [
                    {
                        "seed": 0,
                        "failed": False,
                        "final_test_ce": 0.2,
                        "final_test_accuracy": 0.9,
                        "unused_large_array": [1] * 1000,
                    }
                ],
            }
        },
    }
    trimmed = _feedback_brief(feedback)
    seed = trimmed["candidate_metrics"]["c1"]["seed_results"][0]
    assert seed == {"seed": 0, "failed": False, "final_test_ce": 0.2}
    assert (
        len(
            feedback["candidate_metrics"]["c1"]["seed_results"][0]["unused_large_array"]
        )
        == 1000
    )
