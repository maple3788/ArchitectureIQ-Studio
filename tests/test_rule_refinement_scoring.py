from copy import deepcopy
import json

import pytest

from architecture_iq.kb.roles import read_receipt
from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
from architecture_iq.studio.rule_refinement.prediction import predict_batch
from rule_refinement_fixtures import public_case, raw_case, rule_entry, stored_feedback, pool_fixture


def setup_batch(tmp_path, raw=None, entries=None):
    case = public_case(raw)
    feedback = {case["ref"]["key"]: stored_feedback(raw)}
    pool = pool_fixture([case], feedback)
    kb = RuleArtifactStore(tmp_path).import_rules({"rules": entries or [rule_entry()]}, source_ref={"id":"fixture"})
    return pool, kb, feedback


def evaluate(root, pool, kb, feedback, *, batch="batch-1"):
    from architecture_iq.studio.rule_refinement.scoring import seal_predictions, score_sealed_batch
    predictions = predict_batch([m["case"] for m in pool["members"]], kb)
    receipt = seal_predictions(root, batch_id=batch, pool=pool, kb=kb, predictions=predictions)
    return score_sealed_batch(root, prediction_receipt=receipt["receipt_ref"], pool=pool,
                              feedback_loader=lambda ref: feedback[ref["key"]])


def test_all_predictions_sealed_before_any_feedback_read(tmp_path):
    from architecture_iq.studio.rule_refinement.scoring import seal_predictions, score_sealed_batch
    cases = [public_case(raw_case("first")), public_case(raw_case("second"))]
    pool = pool_fixture(cases)
    kb = RuleArtifactStore(tmp_path).import_rules({"rules": [rule_entry()]}, source_ref={"id":"fixture"})
    receipt = seal_predictions(tmp_path, batch_id="batch", pool=pool, kb=kb, predictions=predict_batch(cases,kb))
    observed = []
    def feedback_loader(ref):
        sealed = read_receipt(tmp_path / receipt["receipt_ref"])
        assert len(sealed["predictions"]) == 2
        assert [p["answer_id"] for p in sealed["predictions"]] == ["c_A", "c_A"]
        observed.append(ref["key"])
        return stored_feedback()
    score = score_sealed_batch(tmp_path, prediction_receipt=receipt["receipt_ref"], pool=pool, feedback_loader=feedback_loader)
    assert observed == ["first","second"]
    assert score["correct"] == 2 and score["all_pass"]
    assert score["per_rule"][kb["rules"][0]["rule_id"]]["correct"] == 6


def test_top1_correct_but_false_lower_assertion_blocks_pass(tmp_path):
    pool,kb,gt = setup_batch(tmp_path, raw_case(losses=(1,3,2)))
    score = evaluate(tmp_path,pool,kb,gt)
    assert score["correct"] == 1 and score["wrong_assertions"] == 1
    assert not score["all_pass"]
    problems = score["problems"]
    assert len(problems) == 1 and problems[0]["type"] == "rule_counterexample"
    assert problems[0]["winner"] == "c_B" and problems[0]["loser"] == "c_C"


def test_unscorable_cannot_disappear_from_completion(tmp_path):
    pool,kb,gt = setup_batch(tmp_path)
    score = evaluate(tmp_path,pool,kb,{})
    assert score["selected"] == score["unscorable"] == 1
    assert score["scorable"] == 0 and score["accuracy"] is None
    assert score["all_pass"] is False and score["problems"] == []


def test_conflicts_and_uncovered_stay_in_accuracy_denominator(tmp_path):
    pool,kb,gt = setup_batch(tmp_path, entries=[rule_entry(),rule_entry(lower=True)])
    conflict = evaluate(tmp_path,pool,kb,gt)
    assert conflict["correct"] == conflict["answered"] == 0
    assert conflict["scorable"] == conflict["conflicts"] == 1 and conflict["accuracy"] == 0
    empty = RuleArtifactStore(tmp_path).import_rules({"rules":[]},source_ref={"id":"empty"})
    uncovered = evaluate(tmp_path,pool,empty,gt,batch="empty-rules")
    assert uncovered["scorable"] == 1 and uncovered["correct"] == 0
    assert uncovered["problems"][0]["type"] == "uncovered"


@pytest.mark.parametrize("kind", ["top1_only","overlap","unknown_direction"])
def test_uncertain_pair_gt_is_not_support_or_error(tmp_path,kind):
    pool,kb,gt = setup_batch(tmp_path)
    feedback = gt["q_rule"]
    if kind == "top1_only":
        feedback.pop("candidate_metrics")
    elif kind == "overlap":
        for value in feedback["candidate_metrics"].values():
            value["seed_results"] = [{"seed":0,"failed":False,"final_test_mse":1},
                                      {"seed":1,"failed":False,"final_test_mse":4}]
    else:
        feedback["higher_is_better"] = "unknown"
    pool = pool_fixture([pool["members"][0]["case"]],gt)
    score = evaluate(tmp_path,pool,kb,gt)
    assert score["correct"] == 1
    evidence = score["per_rule"][kb["rules"][0]["rule_id"]]
    assert evidence["correct"] == evidence["wrong"] == 0 and evidence["unknown"] == 3


def test_objective_mismatch_is_material_failure_not_rule_counterexample(tmp_path):
    pool,kb,gt = setup_batch(tmp_path)
    gt["q_rule"]["candidate_metrics"]["c_A"]["metric"] = "test_ce"
    pool = pool_fixture([pool["members"][0]["case"]],gt)
    score = evaluate(tmp_path,pool,kb,gt)
    assert score["unscorable"] == 1 and score["problems"] == []
    assert not score["all_pass"]


def test_hash_changed_feedback_is_not_used_for_learning(tmp_path):
    pool,kb,gt = setup_batch(tmp_path)
    gt["q_rule"]["correct_letter"] = "C"
    score = evaluate(tmp_path,pool,kb,gt)
    assert score["unscorable"] == 1 and not score["problems"]


def test_missing_prediction_and_mutated_answer_cannot_be_sealed(tmp_path):
    from architecture_iq.studio.rule_refinement.scoring import seal_predictions
    pool,kb,_ = setup_batch(tmp_path)
    good = predict_batch([pool["members"][0]["case"]],kb)
    bad = deepcopy(good)
    bad[0]["answer_id"] = "c_B"
    for predictions in ([],good + good,bad):
        with pytest.raises(ValueError):
            seal_predictions(tmp_path,batch_id="bad",pool=pool,kb=kb,predictions=predictions)
    assert not (tmp_path/"predictions"/"bad.json").exists()


def test_tampered_receipt_fails_before_loading_gt(tmp_path):
    from architecture_iq.studio.rule_refinement.scoring import seal_predictions, score_sealed_batch
    pool,kb,_ = setup_batch(tmp_path)
    receipt = seal_predictions(tmp_path,batch_id="one",pool=pool,kb=kb,
                               predictions=predict_batch([pool["members"][0]["case"]],kb))
    path = tmp_path / receipt["receipt_ref"]
    value = json.loads(path.read_text())
    value["predictions"][0]["answer_id"]="c_B"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        score_sealed_batch(tmp_path,prediction_receipt=receipt["receipt_ref"],pool=pool,
                           feedback_loader=lambda _: pytest.fail("GT accessed before validating seal"))


def test_empty_pool_never_passes_and_unmatched_rules_remain_untested(tmp_path):
    kb = RuleArtifactStore(tmp_path).import_rules({"rules":[rule_entry((128,256))]},source_ref={"id":"fixture"})
    empty = evaluate(tmp_path,pool_fixture([]),kb,{})
    assert not empty["all_pass"] and empty["accuracy"] is None
    assert empty["per_rule"][kb["rules"][0]["rule_id"]]["status"] == "untested"


def test_score_and_prediction_receipts_cannot_be_rebound_or_overwritten(tmp_path):
    from architecture_iq.studio.rule_refinement.scoring import seal_predictions
    pool,kb,gt = setup_batch(tmp_path)
    score = evaluate(tmp_path,pool,kb,gt)
    before = (tmp_path/score["receipt_ref"]).read_bytes()
    assert evaluate(tmp_path,pool,kb,gt) == score
    assert (tmp_path/score["receipt_ref"]).read_bytes() == before
    other = RuleArtifactStore(tmp_path).import_rules({"rules":[]},source_ref={"id":"empty"})
    with pytest.raises(ValueError):
        seal_predictions(tmp_path,batch_id="batch-1",pool=pool,kb=other,
                         predictions=predict_batch([pool["members"][0]["case"]],other))
