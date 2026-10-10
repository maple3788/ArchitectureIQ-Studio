"""Paired research must teach from contrasts without contaminating blind answers."""
import copy
import json
from types import SimpleNamespace

import pytest

from architecture_iq.kb.orchestrator import prepare_run, run_round
from architecture_iq.kb.roles import read_receipt
from architecture_iq.kb.store import KBStore


def pair_inputs(protocol="paired_progressive"):
    questions = []
    for role, identifier, letters in (("original", "orig", "ABC"), ("counterfactual", "cf", "CAB")):
        questions.append({"id": identifier, "family": "univariate_regression", "dataset_id": "d-" + identifier,
            "lineage_id": "lineage", "split": "discovery", "pair_id": "pair1", "prompt": "FULL_" + identifier,
            "choices": [{"id": "candidate" + str(i), "letter": letter,
                         "view": {"family": "univariate_regression", "width": 10 + i}} for i, letter in enumerate(letters)]})
    pair = {"schema_version": 1, "pair_key": "a" * 64, "pair_id": "pair1", "family": "univariate_regression",
        "type": "architecture_only", "split": "discovery", "lineage_id": "lineage", "ready": True,
        "kb_ready": True, "evaluation_ready": True, "issues": [],
        "members": [{"role": role, "key": q["id"], "id": q["id"], "dataset_id": q["dataset_id"], "hash": q["id"]} for role, q in zip(("original", "counterfactual"), questions)],
        "candidate_mapping": [{"choice_identity": "candidate" + str(i), "original_candidate_id": "candidate" + str(i),
            "counterfactual_candidate_id": "candidate" + str(i), "original_letter": a, "counterfactual_letter": b} for i, (a, b) in enumerate(zip("ABC", "CAB"))],
        "intervention": {"changes": [{"path": "params.noise_std", "before": 0, "after": 1, "kind": "factor"}],
            "controls": ["model", "optimizer", "loss", "budget"], "causal_status": "single_factor_fixed_sampling", "notice": "A controlled contrast, not proof of mechanism."}}
    config = {"learning_protocol": protocol, "pair_manifest": [pair], "model": {"name": "fixed", "max_tokens": 100},
        "runtime_fingerprint": "frozen", "max_rounds": 1, "discovery_per_round": 2, "packet_size": 2,
        "max_calls_per_round": 30, "max_tokens_per_round": 100000, "enable_confirmation": False,
        "n_seeds": 2, "context_size": 32768, "wall_time_seconds": 60}
    private = {"orig": {"correct_letter": "A", "significance": {"reason": "ORIGINAL_GT"}},
               "cf": {"correct_letter": "A", "significance": {"reason": "CF_GT"}}}
    return config, questions, private, []


def learning(summary):
    return {"summary": summary, "conditions": ["noise matters"], "exceptions": [], "interactions": [],
            "changed_factors": ["noise_std"], "controlled_factors": ["model", "optimizer", "loss", "budget"],
            "competing_explanation": "optimization", "next_test": "Hold noise fixed and vary width."}


class PairClient:
    max_retries = 0
    def __init__(self, out):
        self.out, self.packets = out, []
    def complete(self, prompt, model):
        role = prompt.split("You are the ")[1].split(" in ")[0]
        packet = json.loads(prompt.split("DATA:\n")[1])
        self.packets.append((role, packet))
        if role == "solver":
            assert "ORIGINAL_GT" not in prompt and "CF_GT" not in prompt
            result = {"ranking": list("ABC"), "citations": [], "rationale": "Blind choice."}
        elif role == "pair_researcher":
            assert len(list((self.out / "rounds/1/answers").glob("*.json"))) == 2
            if packet["stage"] == "induction":
                assert "CF_GT" not in prompt and "FULL_cf" not in prompt
            else:
                assert "CF_GT" in prompt and "ORIGINAL_GT" in prompt
                assert "FULL_cf" not in prompt
            result = {"learning": learning(packet["stage"]), "hypothesis": None}
        elif role == "analyst":
            result = {"summary": "No confirmed result", "limitations": []}
        elif role == "curator":
            result = {"decisions": []}
        else:
            raise AssertionError(role)
        return SimpleNamespace(raw={"model": model.name, "choices": [{"message": {"content": json.dumps(result)}}]},
            finish_reason="stop", usage={"prompt_tokens": 100, "completion_tokens": 50})


def test_progressive_separates_blind_transfer_and_knowledge_authority(tmp_path):
    prepare_run(tmp_path, *pair_inputs())
    client = PairClient(tmp_path)
    result = run_round(tmp_path, client, lambda *a: [], round_index=1)
    assert [role for role, packet in client.packets] == ["solver", "solver", "pair_researcher", "solver", "pair_researcher", "analyst", "curator"]
    trace = result["learning_traces"][0]
    assert trace["scientific_status"] == "unverified" and trace["model_weights_fixed"]
    assert trace["induction"]["learning"]["summary"] == "induction"
    assert trace["revision"]["learning"]["summary"] == "revision"
    transfer = [packet for role, packet in client.packets if role == "solver"][2]
    assert transfer["knowledge"] == [] and transfer["provisional_learning"]["status"] == "unverified"
    assert len(result["answers"]) == 2 and "transfer" in trace
    assert KBStore(tmp_path / "kb").current()["claims"] == []
    assert read_receipt(tmp_path / "rounds/1/learning" / ("a" * 64 + ".json"))["result"] == trace
    count = len(client.packets)
    assert run_round(tmp_path, client, lambda *a: [], round_index=1) == result
    assert len(client.packets) == count


def test_contrastive_has_no_transfer_or_provisional_calls(tmp_path):
    prepare_run(tmp_path, *pair_inputs("paired_contrastive"))
    client = PairClient(tmp_path)
    result = run_round(tmp_path, client, lambda *a: [], round_index=1)
    assert [role for role, packet in client.packets].count("solver") == 2
    assert [role for role, packet in client.packets].count("pair_researcher") == 1
    assert "transfer" not in result["learning_traces"][0]


@pytest.mark.parametrize("mutation,match", [
    (lambda c,q: c.update(discovery_per_round=1), "even"),
    (lambda c,q: c.update(packet_size=1), "even"),
    (lambda c,q: c.update(pair_manifest=[]), "pair"),
    (lambda c,q: c["pair_manifest"][0]["members"][1].update(role="original"), "role"),
    (lambda c,q: c["pair_manifest"][0]["candidate_mapping"][0].update(counterfactual_letter="X"), "mapping"),
    (lambda c,q: c.update(max_calls_per_round=5), "call"),
])
def test_pair_protocol_rejects_invalid_frozen_design(tmp_path, mutation, match):
    config, questions, private, legacy = pair_inputs()
    mutation(config, questions)
    with pytest.raises(ValueError, match=match):
        prepare_run(tmp_path, config, questions, private, legacy)
    assert not (tmp_path / "manifest.json").exists()


def test_pair_score_uses_candidate_identity_not_shuffled_letters():
    from architecture_iq.kb.evaluation import score_evaluation
    config, questions, private, _ = pair_inputs()
    answers = {q["id"]: {"valid": True, "ranking": list("ABC"), "knowledge_count": 0} for q in questions}
    scores = score_evaluation(questions, {"clean": answers}, private, pair_manifest=config["pair_manifest"])["clean"]
    assert scores["pair_joint_correct"] == 1
    assert scores["pair_winner_change_correct"] == 1 and scores["pair_winner_change_total"] == 1
    # Same winner identity maps original A to counterfactual C, despite changed letters.
    answers["cf"]["ranking"] = list("CAB")
    scores = score_evaluation(questions, {"clean": answers}, private, pair_manifest=config["pair_manifest"])["clean"]
    assert scores["pair_winner_change_correct"] == 0


def many_pairs(count=3, protocol="paired_contrastive"):
    config, _, _, legacy = pair_inputs(protocol)
    questions, feedback, pairs = [], {}, []
    for index in range(count):
        _, qs, private, _ = pair_inputs(protocol)
        pair = copy.deepcopy(config["pair_manifest"][0])
        pair.update(pair_key=f"{index:064x}", pair_id=f"pair{index}", lineage_id=f"lineage{index}")
        for member, q in zip(pair["members"], qs):
            old = q["id"]
            q.update(id=f"{old}{index}", dataset_id=f"d-{old}{index}",
                     lineage_id=pair["lineage_id"], pair_id=pair["pair_id"])
            member.update(id=q["id"], key=q["id"], dataset_id=q["dataset_id"])
            feedback[q["id"]] = private[old]
        questions.extend(qs)
        pairs.append(pair)
    config.update(pair_manifest=pairs, discovery_per_round=count * 2,
                  max_calls_per_round=100, max_tokens_per_round=1000000)
    return config, questions, feedback, legacy


def test_pairs_stay_atomic_when_originals_and_counterfactuals_are_interleaved(tmp_path):
    config, questions, private, legacy = many_pairs()
    config.update(max_rounds=3, discovery_per_round=2)
    interleaved = questions[::2] + questions[1::2]
    manifest = prepare_run(tmp_path, config, interleaved, private, legacy)
    assert list(manifest["round_questions"].values()) == [
        ["orig0", "cf0"], ["orig1", "cf1"], ["orig2", "cf2"]]


def test_more_than_four_pairs_are_all_researched(tmp_path):
    config, questions, private, legacy = many_pairs(5)
    prepare_run(tmp_path, config, questions, private, legacy)

    class ManyClient(PairClient):
        def complete(self, prompt, model):
            role = prompt.split("You are the ")[1].split(" in ")[0]
            packet = json.loads(prompt.split("DATA:\n")[1])
            if role != "pair_researcher":
                return super().complete(prompt, model)
            assert len(list((self.out / "rounds/1/answers").glob("*.json"))) == 10
            self.packets.append((role, packet))
            result = {"learning": learning("contrastive"), "hypothesis": None}
            return SimpleNamespace(raw={"model": model.name, "choices": [{"message": {"content": json.dumps(result)}}]},
                                   finish_reason="stop", usage={"prompt_tokens": 100, "completion_tokens": 50})

    client = ManyClient(tmp_path)
    result = run_round(tmp_path, client, lambda *a: [], round_index=1)
    assert len(result["learning_traces"]) == 5
    assert sum(role == "pair_researcher" for role, _ in client.packets) == 5


@pytest.mark.parametrize("mutation,match", [
    (lambda c,q: c["pair_manifest"][0]["members"][1].update(dataset_id="other"), "identity"),
    (lambda c,q: c["pair_manifest"][0].update(split="final"), "split"),
    (lambda c,q: c["pair_manifest"][0]["candidate_mapping"].pop(), "mapping"),
    (lambda c,q: c["pair_manifest"][0].update(correct_letter="A"), "public"),
    (lambda c,q: c["pair_manifest"][0].update(ready=False), "ready"),
    (lambda c,q: c.update(learning_protocol="unknown"), "protocol"),
])
def test_pair_manifest_rejects_conflicting_public_attestations(tmp_path, mutation, match):
    config, questions, private, legacy = pair_inputs()
    mutation(config, questions)
    with pytest.raises(ValueError, match=match):
        prepare_run(tmp_path, config, questions, private, legacy)
    assert not (tmp_path / "manifest.json").exists()


def test_paired_discovery_can_keep_ordinary_heldout_tasks(tmp_path):
    config, questions, private, legacy = pair_inputs()
    task = copy.deepcopy(questions[0])
    task.update(id="heldout", dataset_id="heldout-data", lineage_id="heldout", split="final")
    task.pop("pair_id")
    questions.append(task)
    private[task["id"]] = {"correct_letter": "A"}
    manifest = prepare_run(tmp_path, config, questions, private, legacy)
    assert manifest["round_questions"] == {"1": ["orig", "cf"]}


def test_pair_transfer_never_receives_counterfactual_baseline_and_maps_events(tmp_path):
    prepare_run(tmp_path, *pair_inputs())
    events = []

    class BoundaryClient(PairClient):
        def complete(self, prompt, model):
            result = super().complete(prompt, model)
            role, packet = self.packets[-1]
            if role == "solver" and packet["question"]["id"] == "cf":
                if "provisional_learning" in packet:
                    assert "SEALED_CF_BASELINE" not in prompt
                    assert "original" not in packet and "feedback" not in packet
                else:
                    result.raw["choices"][0]["message"]["content"] = json.dumps(
                        {"ranking": list("ABC"), "citations": [], "rationale": "SEALED_CF_BASELINE"})
            if role == "pair_researcher" and packet["stage"] == "induction":
                assert "SEALED_CF_BASELINE" not in prompt
                assert "pair" not in packet and "counterfactual" not in packet
            return result

    result = run_round(tmp_path, BoundaryClient(tmp_path), lambda *a: [], round_index=1,
                       stage_observer=events.append)
    assert result["answers"]["cf"]["rationale"] == "SEALED_CF_BASELINE"
    research_events = [e for e in events if e.get("role") == "pair_researcher"]
    assert len(research_events) == 6
    assert all(e["node_id"] == "discoverer" for e in research_events)


def test_unsupported_hypothesis_remains_unverified_learning(tmp_path):
    prepare_run(tmp_path, *pair_inputs("paired_contrastive"))

    class UnsupportedClient(PairClient):
        def complete(self, prompt, model):
            response = super().complete(prompt, model)
            if self.packets[-1][0] == "pair_researcher":
                raw = {"learning": learning("Observed noise interaction"), "hypothesis": {
                    "text": "Noise favors wider models", "rule": {"unsupported": True},
                    "experiment": {"family": "univariate_regression", "factor": "noise"},
                    "boundary": "Unknown", "competing_explanation": "Optimization"}}
                response.raw["choices"][0]["message"]["content"] = json.dumps(raw)
            return response

    result = run_round(tmp_path, UnsupportedClient(tmp_path), lambda *a: [], round_index=1)
    assert result["rejections"] and not result["candidates"]
    assert result["learning_traces"][0]["contrastive"]["learning"]["summary"] == "Observed noise interaction"
    assert KBStore(tmp_path / "kb").current()["claims"] == []


def test_pair_preflight_reserves_progressive_calls_and_skeptic(tmp_path):
    config, questions, private, legacy = pair_inputs()
    config["max_calls_per_round"] = 7
    with pytest.raises(ValueError, match="call budget"):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_catalog_manifest_shape_is_accepted_with_public_limitations(tmp_path):
    config, questions, private, legacy = pair_inputs()
    pair = config["pair_manifest"][0]
    pair.pop("evaluation_ready")
    for member, question in zip(pair["members"], questions):
        member.update({field: question[field] for field in ("family", "lineage_id", "split")}, type="architecture_only")
    pair["intervention"] = {"changes": [{"path": "params.noise_std", "before": 0,
                                         "after": 1, "kind": "dataset"}],
                            "controls": ["model", "optimizer", "loss", "budget"],
                            "causal_status": "single_factor_fixed_sampling", "selection_history": "unknown",
                            "limitations": ["Selection history is unknown."]}
    prepare_run(tmp_path, config, questions, private, legacy)


def test_catalog_pair_set_validates_in_native_protocol(tmp_path):
    from test_studio_pairs import import_pair
    from architecture_iq.kb.pair_learning import validate_pair_manifest
    catalog, *_ = import_pair(tmp_path, renamed=True, letter_shuffle=True)
    pair = catalog.list_question_pairs()["items"][0]
    saved = catalog.save_question_pair_set([pair["pair_key"]], name="Pairs")
    assert validate_pair_manifest(saved["questions"], saved["pairs"]) == [pair]


def test_formal_task_does_not_receive_provisional_learning(tmp_path):
    from architecture_iq.kb.orchestrator import evaluate_run
    config, questions, private, legacy = pair_inputs()
    heldout = copy.deepcopy(questions[0])
    heldout.update(id="heldout", dataset_id="heldout-data", lineage_id="heldout", split="final")
    heldout.pop("pair_id")
    questions.append(heldout)
    private["heldout"] = {"correct_letter": "A"}
    prepare_run(tmp_path, config, questions, private, legacy)
    client = PairClient(tmp_path)
    run_round(tmp_path, client, lambda *a: [], round_index=1)
    count = len(client.packets)
    result = evaluate_run(tmp_path, client, phase="final")
    assert result["kb_unchanged"]
    assert len(client.packets[count:]) == 3
    for role, packet in client.packets[count:]:
        assert role == "solver" and set(packet) == {"question", "knowledge"}
        assert packet["question"]["id"] == "heldout" and packet["knowledge"] == []


def test_single_protocol_cannot_cut_discovery_pairs(tmp_path):
    config, questions, private, legacy = pair_inputs("single")
    config.update(discovery_per_round=1, packet_size=1)
    with pytest.raises(ValueError, match="paired.*protocol"):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_single_protocol_accepts_valid_task_pairs_only(tmp_path):
    config, questions, private, legacy = pair_inputs("single")
    for question in questions:
        question["split"] = "final"
    config["pair_manifest"][0]["split"] = "final"
    discovery = copy.deepcopy(questions[0])
    discovery.update(id="single", dataset_id="single-data", lineage_id="single", split="discovery")
    discovery.pop("pair_id")
    questions.insert(0, discovery)
    private["single"] = {"correct_letter": "A"}
    config.update(discovery_per_round=1, packet_size=1)
    prepare_run(tmp_path, config, questions, private, legacy)
    config["pair_manifest"][0]["candidate_mapping"][0]["counterfactual_letter"] = "X"
    with pytest.raises(ValueError, match="mapping"):
        prepare_run(tmp_path / "invalid", config, questions, private, legacy)


@pytest.mark.parametrize("field", ["schema_version", "key", "candidate_id"])
def test_pair_rejects_unbound_public_identity(tmp_path, field):
    config, questions, private, legacy = pair_inputs()
    pair = config["pair_manifest"][0]
    if field == "schema_version":
        pair["schema_version"] = 2
    elif field == "key":
        pair["members"][0]["key"] = "wrong-revision"
    else:
        questions[0]["choices"][1]["id"] = questions[0]["choices"][0]["id"]
        pair["candidate_mapping"][1]["original_candidate_id"] = pair["candidate_mapping"][0]["original_candidate_id"]
    with pytest.raises(ValueError):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_manifest_member_source_identity_matches_its_public_revision(tmp_path):
    config, questions, private, legacy = pair_inputs()
    config["pair_manifest"][0]["members"][0]["id"] = "wrong-source"
    with pytest.raises(ValueError, match="identity"):
        prepare_run(tmp_path, config, questions, private, legacy)


def test_evaluation_scores_two_choice_discovery_pair_without_kb_readiness():
    from architecture_iq.kb.evaluation import score_evaluation
    from architecture_iq.kb.pair_learning import validate_pair_manifest

    config, questions, private, _ = pair_inputs()
    for question in questions:
        question["choices"] = question["choices"][:2]
    pair = config["pair_manifest"][0]
    pair["candidate_mapping"] = pair["candidate_mapping"][:2]
    pair.update(kb_ready=False, evaluation_ready=True)
    answers = {"orig": {"valid": True, "ranking": list("AB")},
               "cf": {"valid": True, "ranking": list("AC")}}

    scores = score_evaluation(questions, {"clean": answers}, private,
                              pair_manifest=config["pair_manifest"])["clean"]
    assert scores["correct"] == 2
    assert scores["pair_joint_correct"] == scores["pair_total"] == 1
    assert scores["pair_winner_change_correct"] == scores["pair_winner_change_total"] == 1
    with pytest.raises(ValueError, match="not ready"):
        validate_pair_manifest(questions, config["pair_manifest"])
