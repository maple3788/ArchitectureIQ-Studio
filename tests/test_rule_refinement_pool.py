from copy import deepcopy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from architecture_iq.studio.datasets import DatasetStore
from architecture_iq.studio.dataset_inputs import DatasetInputs
from architecture_iq.studio.rule_refinement.artifacts import RuleArtifactStore
from architecture_iq.studio.rule_refinement.prediction import predict_batch
from architecture_iq.studio.rule_refinement.scoring import seal_predictions, score_sealed_batch
from rule_refinement_fixtures import catalog_cases, raw_case, rule_entry
from test_studio_catalog import bakefile
from test_studio_pairs import import_pair


def setup(tmp_path, records=None):
    from architecture_iq.studio.rule_refinement.pool import PoolStore
    c,keys = catalog_cases(tmp_path,records)
    datasets = DatasetStore(c)
    ds = datasets.create(name="research",keys=[keys[0]],operation_id="create")
    binding = DatasetInputs(c,datasets).preview(
        {k:ds[k] for k in ("collection_id","revision")},{},purpose="research")["binding"]
    return PoolStore(tmp_path/"run"/"refinement",c), c,datasets,ds,binding,keys


def distinct_raw(qid, seed):
    raw = raw_case(qid, "d_"+qid)
    raw["detail"]["dataset"]["files"]["dataset_spec.json"]["params"]["instance_seed"] = seed
    return raw


def batch_score(store,pool, *, name="challenge-1",lower=False):
    kb = RuleArtifactStore(store.root).import_rules({"rules":[rule_entry(lower=lower)]},source_ref={"id":"fixture"})
    predictions = predict_batch(store.public_cases(pool["version"]),kb)
    seal = seal_predictions(store.root,batch_id=name,pool=pool,kb=kb,predictions=predictions)
    return score_sealed_batch(store.root,prediction_receipt=seal["receipt_ref"],pool=pool,
                             feedback_loader=lambda ref: store.catalog.get_question(ref["key"],include_private=True)["feedback"])


def generation(pool, *, requested=None):
    return {"child_id":"generation-fixture","requested_question_count": requested or len(pool["members"]),
            "question_keys":[m["ref"]["key"] for m in pool["members"]], "outcome":"complete"}


def test_dataset_edits_do_not_change_frozen_pool(tmp_path):
    s,c,ds,record,binding,keys = setup(tmp_path,[distinct_raw("one",1),distinct_raw("two",2)])
    frozen = s.initialize(binding)
    ds.revise(record["collection_id"],expected_revision=record["revision"],changes={"keys":keys},operation_id="edit")
    assert [m["ref"]["key"] for m in s.get(frozen["version"])["members"]] == binding["keys"]
    assert s.initialize(binding) == frozen
    assert s.current() == frozen


def test_first_result_is_immutable_and_full_batch_promotes_once(tmp_path):
    s,c,_,_,binding,keys = setup(tmp_path,[distinct_raw("one",1),distinct_raw("two",2),distinct_raw("three",3)])
    initial = s.initialize(binding)
    new_keys = [k for k in keys if k not in binding["keys"]]
    incoming = s.freeze_members(new_keys)
    first_score = batch_score(s,incoming,lower=True)
    record = s.record_first_test("challenge-1",pool=incoming,score=first_score,generation=generation(incoming))
    before = (s.root / "batches/challenge-1.json").read_bytes()
    promoted = s.promote("challenge-1",expected_pool_version=initial["version"])
    assert {m["ref"]["key"] for m in promoted["members"]} == set(keys)
    assert s.promote("challenge-1",expected_pool_version=initial["version"]) == promoted
    assert (s.root/"batches/challenge-1.json").read_bytes() == before
    assert record["first_score"]["correct"] == 0 and record["state"] == "revealed"
    assert s.batches()[0]["first_score"]["correct"] == 0
    assert s.current()["version"] == promoted["version"]
    later = batch_score(s,incoming,name="later")
    with pytest.raises(ValueError):
        s.record_first_test("challenge-1",pool=incoming,score=later,generation=generation(incoming))


def test_relabelled_question_and_shared_lineage_are_not_fresh(tmp_path):
    from architecture_iq.studio.rule_refinement.pool import check_independence
    original = distinct_raw("one",1)
    reordered = deepcopy(original)
    reordered.update(id="renamed",datasetId="d_renamed")
    reordered["detail"]["dataset"]["files"]["dataset_spec.json"]["dataset_id"] = "d_renamed"
    reordered["detail"]["choices"].reverse()
    for i,c in enumerate(reordered["detail"]["choices"]):
        c["letter"] = "ABC"[i]
        c["candidateId"] = "changed_"+str(i)
        c["files"]["candidate_spec.json"]["candidate_id"] = c["candidateId"]
    reordered["reveal"]["correctLetter"] = "C"
    s,c,_,_,binding,keys = setup(tmp_path,[original,reordered])
    frozen = s.initialize(binding)
    incoming = s.freeze_members([k for k in keys if k not in binding["keys"]])
    novelty = check_independence(frozen,incoming)
    assert not novelty["eligible"]
    assert any(r["field"] in {"instance_hash","question_fingerprint"} for r in novelty["overlap"])
    changed = deepcopy(incoming)
    changed["members"][0]["identity"]["lineage_id"] = frozen["members"][0]["identity"]["lineage_id"]
    assert not check_independence(frozen,changed)["eligible"]


@pytest.mark.parametrize("split",["development","final"])
def test_holdout_is_rejected_without_changing_source_split(tmp_path,split):
    s,c,_,_,_,keys = setup(tmp_path,[raw_case(split=split)])
    with pytest.raises(ValueError,match="discovery"):
        s.freeze_members(keys)
    assert c.get_question(keys[0])["public"]["split"] == split


def test_half_pairs_are_rejected_and_complete_pairs_preserved(tmp_path):
    from architecture_iq.studio.rule_refinement.pool import PoolStore
    c,*_ = import_pair(tmp_path)
    s = PoolStore(tmp_path/"run",c)
    pair = c.list_question_pairs()["items"][0]
    keys = [m["key"] for m in pair["members"]]
    with pytest.raises(ValueError,match="pair"):
        s.freeze_members(keys[:1])
    pool = s.freeze_members(keys,pairs=[pair])
    assert pool["pairs"] == [pair]


def test_corrupt_source_and_modified_feedback_are_not_silently_replaced(tmp_path):
    s,c,_,_,binding,keys = setup(tmp_path)
    frozen = s.initialize(binding)
    record_path = c.root/"records"/(frozen["members"][0]["ref"]["hash"]+".json")
    value=json.loads(record_path.read_text()); value["feedback"]["correct_letter"]="C"
    record_path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match="integrity"):
        s.public_cases(frozen["version"])


def test_public_cases_strip_code_paths_private_fields_and_nested_unknowns(tmp_path):
    raw = raw_case()
    raw["detail"]["choices"][0]["files"]["model.py"] = "SOURCE_CODE_SENTINEL"
    raw["detail"]["choices"][0]["files"]["candidate_spec.json"]["model"]["secret"] = "GT_SENTINEL"
    raw["detail"]["dataset"]["files"]["dataset_spec.json"]["files"] = {"synthesize":"/private/path"}
    s,_,_,_,binding,_ = setup(tmp_path,[raw])
    frozen = s.initialize(binding)
    encoded = json.dumps(s.public_cases(frozen["version"]))
    assert not any(secret in encoded for secret in ("SOURCE_CODE_SENTINEL","GT_SENTINEL","/private/path","feedback","sources"))
    assert s.public_cases(frozen["version"])[0]["candidate_specs"][0]["model"]["width"] == 32


def test_first_score_must_be_sealed_and_match_the_incoming_pool(tmp_path):
    s,_,_,_,binding,keys = setup(tmp_path)
    s.initialize(binding)
    incoming = s.freeze_members(keys)
    score = batch_score(s,incoming)
    modified = deepcopy(score); modified["correct"] = 100
    with pytest.raises(ValueError):
        s.record_first_test("challenge-1",pool=incoming,score=modified,generation=generation(incoming))
    assert s.batches() == []


def test_two_expansions_cannot_overwrite_each_other(tmp_path):
    from architecture_iq.studio.rule_refinement.pool import PoolStore
    s,c,_,_,binding,keys = setup(tmp_path,[distinct_raw("one",1),distinct_raw("two",2),distinct_raw("three",3)])
    initial=s.initialize(binding)
    for i,key in enumerate(k for k in keys if k not in binding["keys"]):
        incoming=s.freeze_members([key]); name=f"batch-{i}"
        s.record_first_test(name,pool=incoming,score=batch_score(s,incoming,name=name),generation=generation(incoming))
    def promote(index):
        try:
            return PoolStore(s.root,c).promote(f"batch-{index}",expected_pool_version=initial["version"])["version"]
        except RuntimeError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(promote,[0,1]))
    assert results.count("conflict") == 1
    assert len(s.current()["members"]) == 2


def test_short_batch_can_join_research_but_never_counts_as_complete_pass(tmp_path):
    s,_,_,_,binding,keys=setup(tmp_path,[distinct_raw("one",1),distinct_raw("two",2)])
    initial=s.initialize(binding)
    incoming=s.freeze_members([k for k in keys if k not in binding["keys"]])
    first=s.record_first_test("short",pool=incoming,score=batch_score(s,incoming,name="short"),
                             generation={**generation(incoming,requested=2),"outcome":"partial"})
    assert first["first_score"]["all_pass"] is True
    assert not first["batch_passed"]
    assert len(s.promote("short",expected_pool_version=initial["version"])["members"]) == 2


def test_missing_instance_identity_and_prior_failed_batches_are_not_fresh(tmp_path):
    from architecture_iq.studio.rule_refinement.pool import check_independence
    s,_,_,_,binding,keys=setup(tmp_path,[distinct_raw("one",1),distinct_raw("two",2)])
    initial=s.initialize(binding)
    incoming=s.freeze_members([k for k in keys if k not in binding["keys"]])
    broken=deepcopy(incoming); broken["members"][0]["identity"].pop("lineage_id")
    assert check_independence(initial,broken)["missing_identity"]
    assert not check_independence(initial,broken)["eligible"]
    s.record_first_test("failed",pool=incoming,score=batch_score(s,incoming,lower=True,name="failed"),
                        generation=generation(incoming))
    second=s.record_first_test("again",pool=incoming,score=batch_score(s,incoming,name="again"),generation=generation(incoming))
    assert not second["batch_passed"] and not second["novelty"]["eligible"]


def test_profile_label_does_not_make_an_identical_dataset_independent(tmp_path):
    from architecture_iq.studio.rule_refinement.pool import check_independence
    first = distinct_raw("one",1)
    second = distinct_raw("two",1)
    second["detail"]["dataset"]["files"]["dataset_spec.json"]["profile_hash"] = "a"*64
    s,_,_,_,binding,keys=setup(tmp_path,[first,second])
    old=s.initialize(binding)
    new=s.freeze_members([k for k in keys if k not in binding["keys"]])
    assert any(item["field"] == "instance_hash" for item in check_independence(old,new)["overlap"])


def test_repeated_instance_within_new_batch_cannot_count_as_complete_pass(tmp_path):
    s,c,datasets,_,_,keys=setup(tmp_path,[distinct_raw("old",1),distinct_raw("new_a",2),distinct_raw("new_b",2)])
    old_key=next(key for key in keys if c.get_question(key)["metadata"]["id"] == "old")
    dataset=datasets.create(name="old only",keys=[old_key],operation_id="old-only")
    binding=DatasetInputs(c,datasets).preview({k:dataset[k] for k in ("collection_id","revision")},{},purpose="research")["binding"]
    initial=s.initialize(binding)
    incoming=s.freeze_members([key for key in keys if key not in binding["keys"]])
    first=s.record_first_test("duplicates",pool=incoming,score=batch_score(s,incoming,name="duplicates"),
                              generation=generation(incoming))
    assert first["first_score"]["all_pass"]
    assert not first["batch_passed"]
    assert first["eligible"] == 1
    assert first["novelty"]["independent_instances"] == 1
    assert any(item["field"] == "instance_hash" for item in first["novelty"]["overlap"])
    # Repeated research material still joins the pool; only independence is denied.
    assert len(s.promote("duplicates",expected_pool_version=initial["version"])["members"]) == 3


def test_incoming_complete_pair_is_one_unit_but_relabelled_pair_is_not_new(tmp_path):
    from architecture_iq.studio.rule_refinement.pool import PoolStore,check_independence
    c,*_=import_pair(tmp_path)
    pair=c.list_question_pairs()["items"][0]
    store=PoolStore(tmp_path/"run",c)
    incoming=store.freeze_members([m["key"] for m in pair["members"]],pairs=[pair])
    assert check_independence({"members":[]},incoming)["eligible"]
    duplicate=deepcopy(incoming)
    for member in duplicate["members"]:
        member["ref"]["key"] += "_renamed"
        for field in ("dataset_id","lineage_id","pair_id"):
            member["identity"][field] += "_renamed"
    for manifest in duplicate["pairs"]:
        for member in manifest["members"]:
            member["key"] += "_renamed"
    combined={"members":incoming["members"]+duplicate["members"],"pairs":incoming["pairs"]+duplicate["pairs"]}
    novelty=check_independence({"members":[]},combined)
    assert not novelty["eligible"]
    assert novelty["eligible_keys"] == [m["ref"]["key"] for m in incoming["members"]]
