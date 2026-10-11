"""Synthetic research cases. No generated code or model is ever executed."""
from copy import deepcopy
from test_studio_catalog import baked, bakefile


def rule_entry(width=None, *, lower=False, text="Prefer wider models"):
    rule = {"predict": {"lower_better" if lower else "higher_better": "width"}}
    if width is not None:
        rule["scope"] = ["width", "in", list(width)]
    return {"text": text, "rule": rule, "rationale": ""}


def limits(**changes):
    return {"max_model_calls": 20, "max_tokens": 200000, "max_candidate_seed_runs": 200,
            "wall_time_seconds": 3600, **changes}


def raw_case(qid="q_rule", dataset="d_rule", *, widths=(32, 16, 8), correct="A",
             losses=(1.0, 2.0, 3.0), split="discovery"):
    result = baked(qid, dataset, split)
    choices = []
    metrics = {}
    for index, width in enumerate(widths):
        letter = chr(65 + index)
        choice = deepcopy(result["detail"]["choices"][0])
        choice.update(letter=letter, candidateId="c_" + letter)
        spec = choice["files"]["candidate_spec.json"]
        spec["candidate_id"] = "c_" + letter
        spec["model"]["width"] = width
        choices.append(choice)
        metrics[letter] = {"summary.json": {"metric": "test_mse", "seed_results": [
            {"seed": seed, "failed": False, "final_test_mse": losses[index] + seed * .01}
            for seed in (0, 1)]}}
    result["detail"]["choices"] = choices
    result["reveal"].update(correctLetter=correct, files=metrics)
    return result


def catalog_cases(tmp_path, records=None):
    from architecture_iq.studio.catalog import Catalog
    catalog = Catalog(tmp_path / "state")
    catalog.import_source(bakefile(tmp_path / "source.json", records or [raw_case()]))
    return catalog, [q["key"] for q in catalog.list_questions()["items"]]


def public_case(raw=None):
    """Independent small public input for pure prediction tests."""
    from architecture_iq.kb.store import canonical_hash
    raw = raw or raw_case()
    choices = raw["detail"]["choices"]
    question = {"id": raw["id"], "family": raw["family"], "split": raw["split"],
                "dataset_id": raw["datasetId"], "lineage_id": raw["datasetId"],
                "choices": [{"id": c["candidateId"], "letter": c["letter"]} for c in choices]}
    return {"ref": {"key": raw["id"], "hash": canonical_hash(raw)},
            "question": question,
            "dataset_spec": deepcopy(raw["detail"]["dataset"]["files"]["dataset_spec.json"]),
            "candidate_specs": [deepcopy(c["files"]["candidate_spec.json"]) for c in choices],
            "objective": "test_mse"}


def stored_feedback(raw=None):
    raw = raw or raw_case()
    return {"correct_letter": raw["reveal"]["correctLetter"], "higher_is_better": False,
            "candidate_metrics": {c["candidateId"]: deepcopy(raw["reveal"]["files"][c["letter"]]["summary.json"])
                                  for c in raw["detail"]["choices"]}}


def pool_fixture(cases=None, feedback=None):
    from architecture_iq.kb.store import canonical_hash
    cases = cases if cases is not None else [public_case()]
    feedback = feedback if feedback is not None else {c["ref"]["key"]: stored_feedback() for c in cases}
    value = {"parent_version": None, "members": [
        {"ref": deepcopy(c["ref"]), "case": deepcopy(c), "feedback_hash": canonical_hash(feedback[c["ref"]["key"]]),
         "identity": {"dataset_id": c["question"]["dataset_id"], "lineage_id": c["question"]["lineage_id"]}}
        for c in cases], "pairs": [], "source_bindings": [], "usage_refs": []}
    return {**value, "version": canonical_hash(value)}
