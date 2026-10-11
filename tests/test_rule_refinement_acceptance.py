from copy import deepcopy

import pytest


def report(outcomes, *, conflicts=None, wrong_assertions=0, executable="a", pool="pool"):
    rows={f"q{i}":{"question_ref":{"key":f"q{i}","hash":str(i)*64},
                   "correct":outcome=="correct","scorable":True,
                   "answered":outcome in {"correct","wrong"},
                   "prediction":{"status":"answered" if outcome in {"correct","wrong"} else outcome}}
          for i,outcome in enumerate(outcomes)}
    return {"pool_version":pool,"kb_version":executable*64,"executable_hash":executable*64,
            "predictor_version":"rule_top1_v1","receipt_ref":"scores/"+executable+".json",
            "selected":len(outcomes),"scorable":len(outcomes),"unscorable":0,
            "correct":outcomes.count("correct"),"answered":sum(o in {"correct","wrong"} for o in outcomes),
            "conflicts":outcomes.count("conflict") if conflicts is None else conflicts,
            "wrong_assertions":wrong_assertions,"per_question":rows}


def test_any_protected_regression_rejects_even_with_higher_total():
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    old=report(["correct","wrong","wrong"])
    new=report(["wrong","correct","correct"],executable="b")
    decision=compare_candidate(old,new,protected_keys=["q0"])
    assert not decision["accepted"] and decision["reason"]=="regression"
    assert decision["regressed"]==["q0"] and decision["protected_keys"]==["q0"]
    assert "q1" not in decision["protected_keys"]
    # The current accepted baseline is protected even if a caller omitted its keys.
    assert not compare_candidate(old,new,protected_keys=[])["accepted"]


@pytest.mark.parametrize("old,new,accepted",[
    (report(["correct","conflict","wrong"]),report(["correct","wrong","wrong"],wrong_assertions=4,executable="b"),True),
    (report(["correct","wrong"],wrong_assertions=2),report(["correct","wrong"],wrong_assertions=1,executable="b"),True),
    (report(["correct","uncovered"]),report(["correct","wrong"],executable="b"),True),
    (report(["correct","wrong"]),report(["correct","conflict"],executable="b"),False),
    (report(["correct","wrong"],wrong_assertions=1),report(["correct","wrong"],wrong_assertions=2,executable="b"),False),
])
def test_same_score_repairs_follow_lexicographic_order(old,new,accepted):
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    assert compare_candidate(old,new,protected_keys=["q0"])["accepted"] is accepted


def test_wrong_to_uncovered_is_not_progress():
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    old=report(["correct","wrong"],wrong_assertions=2)
    new=report(["correct","uncovered"],executable="b")
    decision=compare_candidate(old,new,protected_keys=["q0"])
    assert not decision["accepted"] and decision["reason"]=="reduced_answer_coverage"


def test_additional_correct_answers_are_first_priority_without_regression():
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    old=report(["correct","wrong","wrong","wrong"])
    new=report(["correct","correct","uncovered","uncovered"],executable="b")
    decision=compare_candidate(old,new,protected_keys=["q0"])
    assert decision["accepted"] and decision["protected_keys"]==["q0","q1"]


@pytest.mark.parametrize("change",["pool","predictor","ref","keys","foreign_protection"])
def test_pool_mismatch_rejected_before_comparison(change):
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    old=report(["correct","wrong"])
    new=report(["correct","correct"],executable="b")
    keys=["q0"]
    if change=="pool": new["pool_version"]="expanded"
    elif change=="predictor": new["predictor_version"]="v2"
    elif change=="ref": new["per_question"]["q0"]["question_ref"]["hash"]="changed"
    elif change=="keys": new["per_question"]["another"]=new["per_question"].pop("q1")
    else: keys=["unknown"]
    with pytest.raises(ValueError):
        compare_candidate(old,new,protected_keys=keys)


def test_same_executable_hash_is_not_progress():
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    old=report(["correct","wrong"])
    new=deepcopy(old); new["kb_version"]="metadata-only"
    assert compare_candidate(old,new,protected_keys=["q0"])["reason"]=="no_progress"


def test_incomplete_scores_cannot_be_accepted():
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate
    old=report(["correct","wrong"])
    new=report(["correct","correct"],executable="b")
    new.update(scorable=1,unscorable=1)
    new["per_question"]["q1"].update(scorable=False,correct=False)
    new["correct"]=1
    assert compare_candidate(old,new,protected_keys=["q0"])["reason"]=="incomplete_pool"


def test_expanded_baseline_protects_newly_correct_questions_but_not_rejected_ones():
    from architecture_iq.studio.rule_refinement.acceptance import compare_candidate, advance_protection
    expanded=report(["correct","correct","wrong"])
    protected=advance_protection(["q0"],expanded)
    assert protected==["q0","q1"]
    rejected=report(["correct","wrong","correct"],executable="b")
    decision=compare_candidate(expanded,rejected,protected_keys=protected)
    assert decision["protected_keys"]==["q0","q1"]
    assert not decision["accepted"]
