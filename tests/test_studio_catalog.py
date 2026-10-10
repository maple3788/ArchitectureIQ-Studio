import copy
import json

import pytest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def baked(qid="q_abc", dataset="d_one", split="discovery"):
    ds = {"family": "univariate_regression", "dataset_id": dataset,
          "selection_metric": "test_mse", "params": {"expression": "sin(x)", "train_size": 12}}
    choices = []
    for letter in "ABC":
        spec = {"candidate_id": "c_" + letter, "family": ds["family"],
                # Old release specs can lack dataset binding; outer question is authoritative.
                "model": {"type": "mlp", "width": 8, "depth": 2, "activation": "relu",
                          "residual": False, "layer_norm": [False, False]},
                "optimizer": {"type": "SGD", "lr": 0.01}, "loss": {"loss_id": "mse"},
                "budget": {"training_steps": 4, "batch_size": 3, "total_samples_seen": 12}}
        choices.append({"letter": letter, "candidateId": spec["candidate_id"],
                        "files": {"candidate_spec.json": spec, "model.py": "class Model: pass",
                                  "train.py": "raise RuntimeError('NEVER EXECUTE')"}})
    return {"id": qid, "family": ds["family"], "datasetId": dataset, "type": "architecture_only",
            "profile": "fixture", "budget": 12, "metric": "test_mse", "split": split,
            "detail": {"prompt": "The complete canonical prompt", "dataset": {"files": {
                "dataset_spec.json": ds, "synthesize.py": "raise RuntimeError('NEVER EXECUTE')"}},
                "choices": choices},
            "reveal": {"correctLetter": "B", "ranked": [], "curves": [], "files": {
                "A": {"summary.json": {"metric": "test_mse", "seed_results": [
                    {"seed": 0, "failed": False, "final_test_mse": 3.0}]}}}}}


def bakefile(path, records):
    return write(path, {"schema_version": 1, "questions": [{"id": r["id"]} for r in records],
                        "byId": {r["id"]: r for r in records}})


def catalog(tmp_path):
    from architecture_iq.studio.catalog import Catalog
    return Catalog(tmp_path / "state")


def test_bake_projection_reuses_spec_features_and_keeps_private_data_out(tmp_path):
    c = catalog(tmp_path)
    raw = baked()
    raw["llmCot"] = "PRIVATE_CHAIN"
    raw["history"] = {"answer": "PRIVATE_HISTORY"}
    raw["detail"]["correctLetter"] = "PRIVATE_ANSWER"
    raw["detail"]["choices"][0]["files"]["summary.json"] = {"mean": "PRIVATE_METRIC"}
    raw["detail"]["choices"][0]["files"]["candidate_spec.json"]["reveal"] = "PRIVATE_SPEC"
    report = c.import_source(bakefile(tmp_path / "source.json", [raw]))
    assert report["found"] == report["added"] == 1
    key = c.list_questions()["items"][0]["key"]
    question = c.get_question(key)
    serialized = json.dumps(question)
    assert "PRIVATE_" not in serialized
    assert "reveal" not in question["detail"]
    assert question["public"]["prompt"] == raw["detail"]["prompt"]
    assert question["public"]["choices"][0]["view"]["family"] == raw["family"]
    assert question["public"]["choices"][0]["view"]["budget"] == 12
    assert question["detail"]["choices"][0]["files"]["candidate_spec.json"]["dataset_id"] == "d_one"
    assert question["detail"]["choices"][0]["files"]["train.py"] == "raise RuntimeError('NEVER EXECUTE')"
    assert "profile_hash" not in question["public"]
    private = c.get_question(key, include_private=True)["feedback"]
    assert private["correct_letter"] == "B"
    assert private["candidate_metrics"]["c_A"]["seed_results"][0]["final_test_mse"] == 3.0


def test_duplicates_add_source_aliases_and_same_id_conflicts_keep_both(tmp_path):
    c = catalog(tmp_path)
    original = baked()
    first = bakefile(tmp_path / "first.json", [original])
    r1 = c.import_source(first)
    r2 = c.import_source(first)
    assert r2["duplicates"] == 1 and r2["added"] == 0
    r3 = c.import_source(bakefile(tmp_path / "alias.json", [original]))
    assert r3["duplicates"] == 1
    assert len(c.list_sources()) == 2
    assert c.list_questions()["items"][0]["source_count"] == 2
    changed = copy.deepcopy(original)
    changed["detail"]["prompt"] += " amended"
    r4 = c.import_source(bakefile(tmp_path / "conflict.json", [changed]))
    assert r4["added"] == r4["conflicts"] == 1
    rows = c.list_questions()["items"]
    assert len(rows) == 2 and {r["id"] for r in rows} == {original["id"]}
    assert len({r["key"] for r in rows}) == 2
    assert c.list_questions(source_id=r1["source_id"])["total"] == 1


def test_public_record_projection_filters_nested_views_and_feedback(tmp_path):
    c = catalog(tmp_path)
    record = {"id": "public-q", "family": "f", "dataset_id": "d", "lineage_id": "l",
              "prompt": "Public prompt", "profile_hash": "verified-source-hash", "choices": [
                  {"id": "c" + letter, "letter": letter,
                   "view": {"family": "f", "lr": 0.1, "answer": "PRIVATE", "width": {"answer": "PRIVATE"}}}
                  for letter in "ABC"], "correct_letter": "A", "history": "PRIVATE"}
    p = write(tmp_path / "public_questions.json", [record])
    write(tmp_path / "private_feedback.json", {"public-q": {"correct_letter": "B"}})
    c.import_source(p)
    key = c.list_questions()["items"][0]["key"]
    result = c.get_question(key)
    assert "PRIVATE" not in json.dumps(result)
    assert result["public"]["profile_hash"] == "verified-source-hash"
    assert result["public"]["choices"][0]["view"] == {"family": "f", "lr": 0.1}
    assert c.get_question(key, include_private=True)["feedback"]["correct_letter"] == "B"


def test_raw_import_reads_known_artifacts_without_execution(tmp_path):
    c = catalog(tmp_path)
    root = tmp_path / "raw"
    dataset = root / "datasets" / "univariate_regression" / "d_one"
    baked_record = baked()
    write(dataset / "dataset_spec.json", baked_record["detail"]["dataset"]["files"]["dataset_spec.json"])
    (dataset / "synthesize.py").write_text("raise RuntimeError('NO EXECUTION')")
    raw_choices = []
    for choice in baked_record["detail"]["choices"]:
        candidate = dataset / "candidates" / "set" / choice["candidateId"]
        for filename, value in choice["files"].items():
            if filename.endswith("json"):
                write(candidate / filename, value)
            else:
                (candidate / filename).write_text(value)
        write(candidate / "results" / "summary.json", {"metric": "test_mse", "seed_results": []})
        raw_choices.append({"letter": choice["letter"], "candidate_id": choice["candidateId"],
                            "candidate_path": str(candidate.relative_to(root))})
    qdir = dataset / "questions" / "run" / "q_abc"
    write(qdir / "question.json", {"question_id": "q_abc", "family": baked_record["family"],
           "dataset_id": "d_one", "type": "architecture_only", "correct_letter": "B",
           "choices": raw_choices, "profile_hash": "raw-profile", "evaluation": {"selection_metric": "test_mse"}})
    (qdir / "prompt.txt").write_text("Raw canonical prompt")
    report = c.import_source(root)
    assert report["added"] == 1
    row = c.list_questions()["items"][0]
    detail = c.get_question(row["key"], include_private=True)
    assert detail["public"]["prompt"] == "Raw canonical prompt"
    assert detail["public"]["profile_hash"] == "raw-profile"
    assert detail["feedback"]["correct_letter"] == "B"
    assert "c_A" in detail["feedback"]["candidate_metrics"]
    # Canonical references are relative to data/, even when the registered
    # import is narrower (data/datasets/). Resolve only references still inside
    # that narrower source, without reading sibling artifacts.
    narrowed = type(c)(tmp_path / "narrow-state")
    narrow_report = narrowed.import_source(root / "datasets")
    assert narrow_report["added"] == 1
    narrow_key = narrowed.list_questions()["items"][0]["key"]
    assert narrowed.get_question(narrow_key, include_private=True)["feedback"]["candidate_metrics"] == detail["feedback"]["candidate_metrics"]


def test_pairmap_unifies_lineage_and_frozen_sets_reject_cross_split(tmp_path):
    c = catalog(tmp_path)
    one, two = baked("q_orig", "d_orig"), baked("q_cf", "d_cf", "final")
    pairmap = write(tmp_path / "pairmap.json", [{"family": one["family"],
         "original_question": "orig/q_orig", "counterfactual_question": "cf/q_cf",
         "original_dataset": "d_orig", "counterfactual_dataset": "d_cf"}])
    c.import_source(bakefile(tmp_path / "pairs.json", [one, two]), pairmap_path=pairmap)
    rows = c.list_questions()["items"]
    assert rows[0]["pair_id"] == rows[1]["pair_id"] and rows[0]["pair_id"]
    assert rows[0]["lineage_id"] == rows[1]["lineage_id"]
    with pytest.raises(ValueError, match="split"):
        c.create_question_set("leaking", [row["key"] for row in rows])


def test_set_freezes_order_hashes_feedback_and_survives_source_change(tmp_path):
    c = catalog(tmp_path)
    path = bakefile(tmp_path / "source.json", [baked("q_1", "d1"), baked("q_2", "d2")])
    c.import_source(path)
    keys = [r["key"] for r in c.list_questions()["items"]][::-1]
    saved = c.create_question_set("selected", keys)
    assert saved["keys"] == keys and len(saved["hashes"]) == 2
    assert "feedback" not in saved
    before = c.get_question_set(saved["id"], include_private=True)
    changed = baked("q_1", "d1")
    changed["detail"]["prompt"] = "new prompt"
    c.import_source(bakefile(path, [changed]))
    assert c.get_question_set(saved["id"], include_private=True) == before
    assert [q["id"] for q in before["questions"]] == keys
    assert set(before["feedback"]) == set(keys)
    assert c.list_question_sets()[0]["id"] == saved["id"]
    reopened = type(c)(tmp_path / "state")
    assert reopened.get_question_set(saved["id"], include_private=True) == before
    with pytest.raises(ValueError):
        c.create_question_set("duplicate", [keys[0], keys[0]])


def test_large_catalog_paginates_filters_and_reports_broken_entries(tmp_path):
    c = catalog(tmp_path)
    records = [baked("q_" + str(i), "d" + str(i)) for i in range(125)]
    payload = {"byId": {r["id"]: r for r in records}, "questions": [{"id": r["id"]} for r in records]}
    payload["questions"].append({"id": "missing"})
    payload["byId"]["broken"] = {"id": "broken", "family": records[0]["family"]}
    report = c.import_source(write(tmp_path / "big.json", payload))
    assert report["found"] == 127
    assert report["errors"] and any(e["id"] == "missing" for e in report["entries"])
    assert any(e["id"] == "broken" for e in report["entries"])
    assert c.list_questions(limit=13, offset=13)["total"] == 126
    assert len(c.list_questions(limit=13, offset=13)["items"]) == 13
    assert c.list_questions(search="q_124", family=records[0]["family"], question_type="architecture_only")["total"] == 1
    broken = next(r for r in c.list_questions(search="broken")["items"])
    assert not broken["ready"] and broken["issues"]
    assert c.stats()["questions"] == 126
    assert c.list_sources()[0]["report"]["found"] == 127


def test_raw_references_cannot_escape_registered_source_root(tmp_path):
    c = catalog(tmp_path)
    outside = tmp_path / "outside"
    write(outside / "candidate_spec.json", {"candidate_id": "secret"})
    source = tmp_path / "raw"
    qdir = source / "questions" / "q_bad"
    write(qdir / "question.json", {"question_id": "q_bad", "family": "f", "dataset_id": "d",
          "choices": [{"letter": "A", "candidate_id": "secret", "candidate_path": str(outside)}]})
    (qdir / "prompt.txt").write_text("safe")
    report = c.import_source(source)
    assert report["entries"][0]["issues"]
    assert "outside source root" in json.dumps(report)
    assert not c.list_questions()["items"][0]["ready"]


def test_nonfinite_source_is_an_explicit_import_error(tmp_path):
    c = catalog(tmp_path)
    report = c.import_source(write(tmp_path / "bad.json", {"byId": {"q": {"id": "q", "budget": float("nan")}}}))
    assert report["errors"] and c.stats()["questions"] == 0


def test_evaluation_readiness_is_distinct_from_kb_readiness(tmp_path):
    c = catalog(tmp_path)
    record = baked()
    record["detail"]["choices"] = record["detail"]["choices"][:2]
    c.import_source(bakefile(tmp_path / "two.json", [record]))
    row = c.list_questions()["items"][0]
    assert row["ready"] and row["evaluation_ready"] and not row["kb_ready"]
    assert "profile_hash" in row["missing_metadata"]
    assert c.create_question_set("evaluation pair", [row["key"]])["questions"]


def test_stored_record_modification_is_detected(tmp_path):
    c = catalog(tmp_path)
    c.import_source(bakefile(tmp_path / "source.json", [baked()]))
    row = c.list_questions()["items"][0]
    path = tmp_path / "state" / "records" / (row["hash"] + ".json")
    record = json.loads(path.read_text())
    record["public"]["prompt"] = "tampered"
    write(path, record)
    with pytest.raises(ValueError, match="integrity"):
        c.get_question(row["key"])


def test_directory_import_finds_arbitrary_bake_names_and_reports_symlink_escape(tmp_path):
    c = catalog(tmp_path)
    source = tmp_path / "source"
    bakefile(source / "nested" / "release-hard500.json", [baked()])
    write(source / "ignored" / "candidate_spec.json", {"candidate_id": "only-spec"})
    outside = bakefile(tmp_path / "outside.json", [baked("q_outside")])
    (source / "questions.json").symlink_to(outside)
    report = c.import_source(source)
    assert report["added"] == 1
    assert c.list_questions()["total"] == 1
    assert any("outside source root" in e["error"] for e in report["errors"])


def test_unchanged_concurrent_import_is_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    c = catalog(tmp_path)
    path = bakefile(tmp_path / "source.json", [baked()])
    with ThreadPoolExecutor(max_workers=3) as pool:
        reports = list(pool.map(c.import_source, [path] * 3))
    assert sum(r["added"] for r in reports) == 1
    assert sum(r["duplicates"] for r in reports) == 2
    assert len(c.list_sources()) == c.stats()["questions"] == 1


def test_set_file_integrity_is_checked_and_bad_selection_does_not_write(tmp_path):
    c = catalog(tmp_path)
    c.import_source(bakefile(tmp_path / "source.json", [baked()]))
    key = c.list_questions()["items"][0]["key"]
    with pytest.raises(KeyError):
        c.create_question_set("missing", ["unknown-key"])
    assert c.list_question_sets() == []
    saved = c.create_question_set("valid", [key])
    path = tmp_path / "state" / "sets" / (saved["hash"] + ".json")
    stored = json.loads(path.read_text())
    stored["questions"][0]["prompt"] = "edited"
    write(path, stored)
    with pytest.raises(ValueError, match="integrity"):
        c.get_question_set(saved["id"])


def test_display_metadata_uses_allowlists_and_symlink_directories_are_reported(tmp_path):
    c = catalog(tmp_path)
    source = tmp_path / "source"
    raw = baked()
    raw.update(metric={"correctLetter": "PRIVATE"}, profileHash={"answer": "PRIVATE"},
               budget={"total_samples_seen": 12, "hidden_score": "PRIVATE"})
    bakefile(source / "bake.json", [raw])
    other = tmp_path / "outside-dir"
    bakefile(other / "bake.json", [baked("q_outside")])
    (source / "linked").symlink_to(other, target_is_directory=True)
    report = c.import_source(source)
    assert any("outside source root" in e["error"] for e in report["errors"])
    row = c.list_questions()["items"][0]
    assert "PRIVATE" not in json.dumps(c.get_question(row["key"]))
    assert row["budget"] == {"total_samples_seen": 12}


def test_structural_spec_allowlists_strip_unknown_private_fields_before_fingerprints(tmp_path):
    c = catalog(tmp_path)
    raw = baked()
    spec = raw["detail"]["choices"][0]["files"]["candidate_spec.json"]
    spec["model"]["unexpected_family_params"] = {"llmResponse": "MODEL_SENTINEL"}
    spec["optimizer"]["final_test_mse"] = "OPT_SENTINEL"
    spec["loss"]["llmResponse"] = "LOSS_SENTINEL"
    c.import_source(bakefile(tmp_path / "source.json", [raw]))
    question = c.get_question(c.list_questions()["items"][0]["key"])
    assert "SENTINEL" not in json.dumps(question)
    view = question["public"]["choices"][0]["view"]
    assert json.loads(view["loss_key"]) == {"loss_id": "mse"}
    assert json.loads(view["opt_key"]) == {"type": "SGD", "lr": 0.01}
    assert "unexpected_family_params" not in json.loads(view["arch_key"])


def test_precomputed_control_keys_are_structurally_projected(tmp_path):
    c = catalog(tmp_path)
    raw = {"id": "public-q", "family": "f", "dataset_id": "d", "prompt": "canonical", "correct_letter": "A",
           "choices": [{"id": letter, "letter": letter, "view": {"family": "f", "loss_key": json.dumps({
               "loss_id": "mse", "llmResponse": "SENTINEL"}), "opt_key": "UNSTRUCTURED_SENTINEL"}}
               for letter in "ABC"]}
    c.import_source(write(tmp_path / "public.json", [raw]))
    question = c.get_question(c.list_questions()["items"][0]["key"])
    assert "SENTINEL" not in json.dumps(question)
    assert question["public"]["choices"][0]["view"]["loss_key"] == '{"loss_id":"mse"}'


def test_explicit_pair_ids_enforce_shared_lineage_and_split_isolation(tmp_path):
    c = catalog(tmp_path)
    first, second = baked("q_first", "d_first"), baked("q_second", "d_second", "final")
    first["pair_id"] = second["pair_id"] = "explicit-pair"
    # Source-provided lineage aliases must not defeat the explicit pair link.
    first["lineage_id"], second["lineage_id"] = "alias1", "alias2"
    c.import_source(bakefile(tmp_path / "source.json", [first, second]))
    rows = c.list_questions()["items"]
    assert rows[0]["lineage_id"] == rows[1]["lineage_id"]
    with pytest.raises(ValueError, match="split"):
        c.create_question_set("invalid", [row["key"] for row in rows])


@pytest.mark.parametrize("pairmap_kind", ["missing", "invalid", "unmatched"])
def test_supplied_unresolved_pairmap_blocks_question_readiness(tmp_path, pairmap_kind):
    c = catalog(tmp_path)
    p = tmp_path / "pairmap.json"
    if pairmap_kind == "invalid":
        write(p, {"unrecognized": "format"})
    if pairmap_kind == "unmatched":
        write(p, [{"family": "univariate_regression", "original_question": "other1", "counterfactual_question": "other2"}])
    report = c.import_source(bakefile(tmp_path / "source.json", [baked()]), pairmap_path=p)
    assert report["errors"]
    assert all(not row["ready"] for row in c.list_questions()["items"])
    assert c.stats()["ready"] == 0
    key = c.list_questions()["items"][0]["key"]
    with pytest.raises(ValueError, match="ready"):
        c.create_question_set("unresolved", [key])


@pytest.mark.parametrize("location,value", [("params", []), ("model", []), ("optimizer", []),
                                          ("loss", []), ("budget", []), ("betas", [0.9, {}])])
def test_malformed_nested_specs_report_bad_entry_and_import_good_siblings(tmp_path, location, value):
    c = catalog(tmp_path)
    bad = baked("q_bad")
    if location == "params":
        bad["detail"]["dataset"]["files"]["dataset_spec.json"]["params"] = value
    elif location == "betas":
        bad["detail"]["choices"][0]["files"]["candidate_spec.json"]["optimizer"]["betas"] = value
    else:
        bad["detail"]["choices"][0]["files"]["candidate_spec.json"][location] = value
    report = c.import_source(bakefile(tmp_path / "source.json", [bad, baked("q_good")]))
    assert report["found"] == 2
    assert report["errors"] and any(e.get("id") == "q_bad" for e in report["entries"])
    assert c.list_questions(search="q_good")["total"] == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_source_ordering_diagnostics_do_not_create_false_revisions(tmp_path, reverse):
    c = catalog(tmp_path)
    raw = baked()
    ordered = bakefile(tmp_path / "ordered.json", [raw])
    by_id = write(tmp_path / "by-id-only.json", {"byId": {raw["id"]: raw}})
    paths = [by_id, ordered] if reverse else [ordered, by_id]
    reports = [c.import_source(path) for path in paths]
    assert reports[1]["duplicates"] == 1 and reports[1]["conflicts"] == 0
    assert c.list_questions()["total"] == 1
    assert c.list_questions()["items"][0]["source_count"] == 2
    # The source-level problem remains visible without changing question identity.
    assert any("absent from ordered summaries" in json.dumps(source["report"]) for source in c.list_sources())


def test_legacy_stored_public_fingerprints_are_projected_without_rewriting_history(tmp_path):
    import hashlib
    import sqlite3
    c = catalog(tmp_path)
    c.import_source(bakefile(tmp_path / "source.json", [baked()]))
    row = c.list_questions()["items"][0]
    record = json.loads((c.root / "records" / (row["hash"] + ".json")).read_text())
    # Recreate a valid older-version persisted record, which predates the new
    # structural projection. Its content hash still verifies.
    record["public"]["id"] = row["id"]
    record["metadata"].pop("key")
    record["metadata"].pop("hash")
    record["public"]["choices"][0]["view"]["loss_key"] = '{"loss_id":"mse","llmResponse":"LEGACY_SENTINEL"}'
    record["detail"]["choices"][0]["files"]["candidate_spec.json"]["optimizer"]["final_test_mse"] = "LEGACY_SENTINEL"
    digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    key = row["id"] + "@" + digest[:24]
    record["public"]["id"] = key
    record["metadata"].update(key=key, hash=digest)
    stored_path = write(c.root / "records" / (digest + ".json"), record)
    with sqlite3.connect(c.db) as conn:
        conn.execute("UPDATE questions SET key=?,hash=?,summary=? WHERE key=?", (key, digest, json.dumps(record["metadata"]), row["key"]))
        conn.execute("UPDATE aliases SET key=? WHERE key=?", (key, row["key"]))
    original_bytes = stored_path.read_bytes()
    assert "LEGACY_SENTINEL" not in json.dumps(c.get_question(key))
    assert stored_path.read_bytes() == original_bytes


def paired_counterfactual(tmp_path):
    raw = baked("q_cf", "d_cf")
    raw["detail"]["dataset"]["datasetId"] = "d_cf"
    for choice in raw["detail"]["choices"]:
        choice["files"]["candidate_spec.json"].update(dataset_id="d_orig", profile_hash="verified-profile")
    pair = {"family": raw["family"], "original_question": "q_orig", "counterfactual_question": "q_cf",
            "original_dataset": "d_orig", "counterfactual_dataset": "d_cf"}
    return raw, pair


def test_verified_dataflip_reuse_binds_public_views_and_preserves_source_spec(tmp_path):
    c = catalog(tmp_path)
    raw, pair = paired_counterfactual(tmp_path)
    path = bakefile(tmp_path / "cf.json", [raw])
    source_bytes = path.read_bytes()
    report = c.import_source(path, pairmap_path=write(tmp_path / "pairmap.json", [pair]))
    assert report["added"] == 1 and not report["errors"]
    row = c.list_questions()["items"][0]
    assert row["ready"] and row["kb_ready"]
    q = c.get_question(row["key"], include_private=True)
    assert q["public"]["dataset_id"] == "d_cf"
    assert q["public"]["choices"][0]["view"]["target_oscillatory"]
    display = q["detail"]["choices"][0]
    assert display["files"]["candidate_spec.json"]["dataset_id"] == "d_cf"
    binding = display["provenance"]["dataset_binding"]
    assert binding["verification"] == "pairmap"
    assert binding["original_dataset_id"] == "d_orig"
    assert binding["effective_dataset_id"] == "d_cf"
    assert binding["ground_truth_dataset_id"] is None
    assert display["provenance"]["source_candidate_spec"]["dataset_id"] == "d_orig"
    assert display["provenance"]["source_candidate_spec"]["profile_hash"] == "verified-profile"
    assert q["feedback"]["candidate_metrics"]["c_A"] == raw["reveal"]["files"]["A"]["summary.json"]
    assert path.read_bytes() == source_bytes
    assert c.create_question_set("verified CF", [row["key"]])["questions"][0]["dataset_id"] == "d_cf"


@pytest.mark.parametrize("defect", ["no_pairmap", "wrong_candidate_source", "wrong_paired_dataset",
                                      "wrong_embedded_dataset", "wrong_detail_dataset", "wrong_gt_dataset",
                                      "original_member", "incomplete_pairmap"])
def test_dataflip_rebinding_never_suppresses_unverified_dataset_mismatch(tmp_path, defect):
    c = catalog(tmp_path)
    raw, pair = paired_counterfactual(tmp_path)
    if defect == "wrong_candidate_source":
        raw["detail"]["choices"][0]["files"]["candidate_spec.json"]["dataset_id"] = "unrelated"
    elif defect == "wrong_paired_dataset":
        pair["counterfactual_dataset"] = "other-cf"
    elif defect == "wrong_embedded_dataset":
        raw["detail"]["dataset"]["files"]["dataset_spec.json"]["dataset_id"] = "other-embedded"
    elif defect == "wrong_detail_dataset":
        raw["detail"]["dataset"]["datasetId"] = "other-detail"
    elif defect == "wrong_gt_dataset":
        raw["reveal"]["files"]["A"]["summary.json"]["dataset_id"] = "d_orig"
    elif defect == "original_member":
        raw["id"] = "q_orig"
    elif defect == "incomplete_pairmap":
        pair.pop("original_dataset")
    path = bakefile(tmp_path / "cf.json", [raw])
    pair_path = None if defect == "no_pairmap" else write(tmp_path / "pairmap.json", [pair])
    report = c.import_source(path, pairmap_path=pair_path)
    row = c.list_questions()["items"][0]
    assert not row["ready"] and report["errors"]
    with pytest.raises(ValueError, match="ready"):
        c.create_question_set("wrong data", [row["key"]])


@pytest.mark.parametrize("source_kind", ["bake", "raw"])
def test_catalog_frozen_runner_summaries_score_pairs_without_rewriting_gt(tmp_path, source_kind):
    from architecture_iq.kb.evaluation import score_evaluation
    c = catalog(tmp_path)
    record = baked()
    summaries = {"c_" + letter: {"candidate_id": "c_" + letter, "selection_metric": "test_mse",
        "execution": "candidate_py_files", "seed_results": [
            {"seed": seed, "failed": False, "final_test_mse": start + seed} for seed in range(2)]}
        for letter, start in zip("ABC", (1, 4, 7))}
    record["reveal"]["correctLetter"] = "A"
    record["reveal"]["files"] = {letter: {"summary.json": summaries["c_" + letter]} for letter in "ABC"}
    source = tmp_path / "source"
    if source_kind == "bake":
        c.import_source(bakefile(source / "bake.json", [record]))
    else:
        dataset = source / "datasets" / record["family"] / record["datasetId"]
        write(dataset / "dataset_spec.json", record["detail"]["dataset"]["files"]["dataset_spec.json"])
        choices = []
        for choice in record["detail"]["choices"]:
            candidate = dataset / "candidates" / "set" / choice["candidateId"]
            write(candidate / "candidate_spec.json", choice["files"]["candidate_spec.json"])
            write(candidate / "results" / "summary.json", summaries[choice["candidateId"]])
            choices.append({"letter": choice["letter"], "candidate_id": choice["candidateId"],
                            "candidate_path": str(candidate.relative_to(source))})
        qdir = dataset / "questions" / "run" / record["id"]
        write(qdir / "question.json", {"question_id": record["id"], "family": record["family"],
            "dataset_id": record["datasetId"], "choices": choices, "correct_letter": "A",
            "evaluation": {"selection_metric": "test_mse"}})
        (qdir / "prompt.txt").write_text(record["detail"]["prompt"])
        c.import_source(source)
    key = c.list_questions()["items"][0]["key"]
    frozen = c.create_question_set("scoring", [key])
    selected = c.get_question_set(frozen["id"], include_private=True)
    assert selected["feedback"][key]["candidate_metrics"] == summaries
    before = copy.deepcopy(selected)
    files = [*source.rglob("*.json"), *c.root.joinpath("records").glob("*.json"), *c.root.joinpath("sets").glob("*.json")]
    bytes_before = {path: path.read_bytes() for path in files}
    answers = {"clean": {key: {"valid": True, "ranking": list("ABC"), "knowledge_count": 0,
                               "invalid_citations": False}}}
    result = score_evaluation(selected["questions"], answers, selected["feedback"])["clean"]
    assert result["pairwise_total"] == result["pairwise_correct"] == 3
    assert result["pairwise_unresolved"] == 0
    assert selected == before and c.get_question_set(frozen["id"], include_private=True) == before
    assert {path: path.read_bytes() for path in files} == bytes_before
