"""Independent-source evidence identities and conservative confirmation gates.

Role outputs never establish scientific outcomes. ``verify_evidence_sources``
checks the frozen plan and the actual generated-code GT before publication.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OUTCOMES = {"support", "refute", "inconclusive"}


def _text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def _positive_int(value: Any, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _hashes(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("source_hashes must bind nonempty artifact paths to SHA256 hashes")
    for path, digest in value.items():
        _text(path, "source path")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError("source_hashes contains an invalid SHA256 hash")


def validate_evidence(record: dict, *, check_id: bool = True) -> None:
    """Validate transport shape without treating it as scientific verification."""
    if not isinstance(record, dict):
        raise ValueError("evidence must be an object")
    for key in ("claim_id", "lineage_id", "dataset_id"):
        _text(record.get(key), key)
    _positive_int(record.get("revision"), "revision")
    if record.get("phase") not in ("exploration", "confirmation"):
        raise ValueError("evidence phase must be exploration or confirmation")
    if not isinstance(record.get("outcome"), str) or record["outcome"] not in _OUTCOMES:
        raise ValueError("evidence outcome must be support, refute or inconclusive")
    candidates = record.get("candidate_ids")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("evidence requires exactly two candidate_ids")
    for candidate in candidates:
        _text(candidate, "candidate ID")
    if len(set(candidates)) != 2:
        raise ValueError("duplicate candidate IDs")
    seeds = record.get("seed_ids")
    if (not isinstance(seeds, list) or not seeds
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("seed_ids must be distinct nonnegative integers")
    _hashes(record.get("source_hashes"))
    if check_id and record.get("id") != evidence_id(record):
        raise ValueError("evidence ID does not match source identity")


def evidence_id(record: dict) -> str:
    """Identify a fact independently of claims, paths, aliases and interpretations.

    The frozen plan is deliberately excluded: wrapping the same artifacts in a
    different plan does not create an independent experiment. Content, rather
    than filesystem spelling or candidate aliases, identifies each source.
    """
    if not isinstance(record, dict):
        raise ValueError("evidence must be an object")
    _hashes(record.get("source_hashes"))
    seeds = record.get("seed_ids")
    if (not isinstance(seeds, list) or not seeds
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("seed_ids must be distinct nonnegative integers")
    artifacts = {digest for path, digest in record["source_hashes"].items()
                 if path != record.get("plan_path") and Path(path).name not in {"plan.json", "plan.sha256"}}
    if not artifacts:
        raise ValueError("evidence requires source artifacts beyond the plan")
    payload = {"artifacts": sorted(artifacts), "seed_ids": sorted(seeds)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "e_" + hashlib.sha256(raw.encode()).hexdigest()


def summarize_confirmation(
    records: list[dict], *, expected_count: int = 48, max_attempts: int = 3, alpha: float = .05,
) -> dict:
    """Summarize one frozen batch; this alone does not establish provenance.

    Small smoke batches can be complete but never pass the scientific gate.
    Exploratory records likewise cannot pass. Inconclusive outcomes count in n.
    """
    _positive_int(expected_count, "expected_count")
    _positive_int(max_attempts, "max_attempts")
    if max_attempts != 3:
        raise ValueError("the preregistered study allows exactly three confirmation attempts")
    if (isinstance(alpha, bool) or not isinstance(alpha, (int, float))
            or not 0 < alpha <= .05 or not math.isfinite(alpha)):
        raise ValueError("alpha must be finite and in (0, .05]")
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    ids: set[str] = set()
    lineages: set[str] = set()
    datasets: set[str] = set()
    claims: set[tuple[str, int]] = set()
    batches: set[str | None] = set()
    for record in records:
        validate_evidence(record)
        if record["id"] in ids:
            raise ValueError("duplicate evidence source")
        if record["lineage_id"] in lineages or record["dataset_id"] in datasets:
            raise ValueError("duplicate dataset lineage")
        ids.add(record["id"])
        lineages.add(record["lineage_id"])
        datasets.add(record["dataset_id"])
        claims.add((record["claim_id"], record["revision"]))
        batches.add(record.get("plan_hash"))
    if len(claims) > 1:
        raise ValueError("confirmation cannot pool different claim revisions")
    if len(batches) > 1:
        raise ValueError("confirmation cannot pool different frozen batches")
    n = len(records)
    counts = {outcome: sum(record["outcome"] == outcome for record in records) for outcome in _OUTCOMES}
    rate = counts["support"] / n if n else 0.0
    lower = max(0.0, rate - math.sqrt(math.log(max_attempts / alpha) / (2 * n))) if n else 0.0
    complete = n == expected_count
    eligible = (expected_count >= 48 and all(record["phase"] == "confirmation" and
                len(record["seed_ids"]) == 10 for record in records))
    return {"complete": complete, "passed": bool(complete and eligible and rate >= .75 and lower > .5),
            "n": n, **counts, "rate": rate, "lower": lower}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read evidence artifact {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"evidence artifact must be an object: {path}")
    return value


def _file_hash(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256") if hasattr(hashlib, "file_digest") else None
            if digest is not None:
                return digest.hexdigest()
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
            return checksum.hexdigest()
    except OSError as exc:
        raise ValueError(f"missing evidence source: {path}") from exc


def validate_sampling_envelope(envelope: dict) -> None:
    """Validate the execution domain that can be certified by confirmation."""
    fields = {"family", "model_type", "profile_hash", "budget_values", "optimizer_types", "loss_types",
              "intervention", "family_options", "controls", "pair_sampling"}
    if not isinstance(envelope, dict) or set(envelope) != fields:
        raise ValueError("confirmation requires a complete sampling envelope")
    for key in ("family", "profile_hash", "intervention"):
        _text(envelope.get(key), f"sampling envelope {key}")
    if envelope["pair_sampling"] != "uniform_applicable_pairs_from_factor_variants":
        raise ValueError("sampling envelope requires uniform selection among applicable factor-variant pairs")
    if envelope["model_type"] != "mlp":
        raise ValueError("sampling envelope model type is unsupported")
    budgets = envelope["budget_values"]
    if not isinstance(budgets, list) or not budgets or any(type(value) is not int or value < 1 for value in budgets):
        raise ValueError("sampling envelope budget_values must be positive integers")
    if budgets != sorted(set(budgets)):
        raise ValueError("sampling envelope budgets must be distinct and sorted")
    for key in ("optimizer_types", "loss_types"):
        values = envelope[key]
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"sampling envelope {key} must be a nonempty list of names")
        if values != sorted(set(values)):
            raise ValueError(f"sampling envelope {key} must be distinct and sorted")
    if not isinstance(envelope["family_options"], dict):
        raise ValueError("sampling envelope family_options must be an object")
    expected_controls = {"equal": ["opt_key", "loss_key", "budget", "batch_size"],
                         "architecture_intervention": envelope["intervention"]}
    if envelope["controls"] != expected_controls:
        raise ValueError("sampling envelope must bind the exact experiment controls")


def verify_evidence_sources(record: dict, *, claim: dict | None = None) -> dict:
    """Verify a machine-produced record against locked plans and executed GT.

    Required producer fields beyond the shared evidence contract: provenance,
    plan_path, plan_hash, pair_index, metric, predicted_winner and summary_paths.
    Source hashes are raw-file SHA256 values keyed by absolute artifact paths.
    Returns the verified frozen plan, allowing callers to enforce study history.
    """
    validate_evidence(record)
    if record.get("provenance") != "canonical_gt" or any(record.get(key) for key in ("synthetic", "mock", "fixture")):
        raise ValueError("scientific evidence requires canonical GT provenance")
    _text(record.get("plan_path"), "plan_path")
    plan_path = Path(record["plan_path"])
    hashes = record["source_hashes"]
    if not plan_path.is_absolute() or str(plan_path) not in hashes:
        raise ValueError("evidence must bind an absolute frozen plan path")
    if record.get("plan_hash") != hashes[str(plan_path)]:
        raise ValueError("frozen plan hash mismatch")
    for path, expected in hashes.items():
        source = Path(path)
        if not source.is_absolute() or _file_hash(source) != expected:
            raise ValueError(f"source hash mismatch: {path}")
    try:
        seal = plan_path.with_suffix(".sha256").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("missing immutable plan seal") from exc
    if seal != record["plan_hash"]:
        raise ValueError("immutable plan seal differs from its source hash")
    plan = _read_json(plan_path)
    if any(plan.get(key) for key in ("synthetic", "mock", "fixture")):
        raise ValueError("synthetic plans cannot supply scientific evidence")
    request = plan.get("request", {})
    if not isinstance(request, dict):
        raise ValueError("frozen plan request is malformed")
    for key in ("claim_id", "revision", "phase"):
        if request.get(key) != record[key]:
            raise ValueError(f"evidence differs from frozen request {key}")
    if claim is not None:
        if (claim["id"], claim["revision"], claim["rule"]) != (record["claim_id"], record["revision"], request.get("rule")):
            raise ValueError("evidence does not confirm the frozen claim revision and rule")
    index = record.get("pair_index")
    pairs = plan.get("pairs")
    if type(index) is not int or not isinstance(pairs, list) or not 0 <= index < len(pairs):
        raise ValueError("evidence has no matching frozen pair")
    pair = pairs[index]
    if not isinstance(pair, dict):
        raise ValueError("frozen pair is malformed")
    _positive_int(pair.get("eligible_pair_count"), "eligible pair count")
    indexes = pair.get("chosen_variant_indexes")
    if (not isinstance(indexes, list) or len(indexes) != 2
            or any(type(index) is not int or index < 0 for index in indexes)
            or indexes[0] == indexes[1]):
        raise ValueError("frozen pair selection requires two distinct nonnegative variant indexes")
    for key in ("dataset_id", "lineage_id", "candidate_ids", "metric", "predicted_winner"):
        if pair.get(key) != record.get(key):
            raise ValueError(f"evidence differs from frozen pair {key}")
    for key, identifier in (("excluded_dataset_ids", record["dataset_id"]), ("excluded_lineage_ids", record["lineage_id"])):
        excluded = request.get(key, [])
        if not isinstance(excluded, list) or any(not isinstance(value, str) for value in excluded):
            raise ValueError("frozen request exclusions must be lists of identities")
        if identifier in excluded:
            raise ValueError("evidence uses an excluded dataset or lineage")
    envelope = plan.get("sampling_envelope")
    if record["phase"] == "confirmation" or envelope is not None:
        validate_sampling_envelope(envelope)
        if (pair.get("sampling_envelope") != envelope or envelope["family"] != request.get("family")
                or envelope["intervention"] != request.get("factor")
                or envelope["family_options"] != request.get("family_options", {})):
            raise ValueError("sampling envelope differs from its frozen request or pair")
        # Reuse the adapter's distribution description, deriving it from the
        # exact hash-bound profile rather than trusting a role-supplied scope.
        from .experiments import sampling_envelope
        from architecture_iq.profile import Profile
        _text(plan.get("profile_path"), "sampling envelope profile_path")
        profile_path = Path(plan["profile_path"])
        if not profile_path.is_absolute() or str(profile_path) not in hashes:
            raise ValueError("sampling envelope must bind its effective profile")
        try:
            profile = Profile.load(profile_path)
            expected_envelope = sampling_envelope(request, profile)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid sampling envelope profile") from exc
        if envelope != expected_envelope or envelope["profile_hash"] != plan.get("profile_hash"):
            raise ValueError("sampling envelope differs from the actual frozen profile")
    if plan.get("seed_ids") != record["seed_ids"] or plan.get("n_seeds") != len(record["seed_ids"]):
        raise ValueError("evidence seed set differs from frozen plan")
    if record["phase"] == "confirmation":
        if (plan.get("complete") is not True or request.get("count") != 48 or len(pairs) != 48
                or plan.get("planned_count") != 48 or plan.get("n_seeds") != 10):
            raise ValueError("confirmation requires a complete preregistered 48-lineage, ten-seed plan")
        lineages = [item.get("lineage_id") for item in pairs]
        datasets = [item.get("dataset_id") for item in pairs]
        if len(set(lineages)) != 48 or len(set(datasets)) != 48:
            raise ValueError("confirmation plan repeats a dataset lineage")
    for bound in (plan.get("source_hashes"), pair.get("source_hashes")):
        _hashes(bound)
        if any(hashes.get(path) != digest for path, digest in bound.items()):
            raise ValueError("evidence dropped or changed frozen source hashes")
    dataset_path = Path(pair.get("dataset_path", ""))
    candidate_paths = pair.get("candidate_paths")
    if (not dataset_path.is_absolute() or not isinstance(candidate_paths, list)
            or len(candidate_paths) != 2 or any(not isinstance(p, str) or not Path(p).is_absolute() for p in candidate_paths)):
        raise ValueError("frozen pair requires absolute data and candidate paths")
    required = [dataset_path / "dataset_spec.json", dataset_path / "synthesize.py"]
    for directory in candidate_paths:
        required.extend(Path(directory) / name for name in ("candidate_spec.json", "model.py", "loss.py", "optimizer.py", "train.py", "results/summary.json", "results/curves.npz"))
    if any(str(path) not in hashes for path in required):
        raise ValueError("evidence does not bind dataset, generated code and GT artifacts")
    dataset_spec = _read_json(dataset_path / "dataset_spec.json")
    if dataset_spec.get("dataset_id") != record["dataset_id"]:
        raise ValueError("dataset identity differs from frozen source")
    if envelope is not None:
        if dataset_spec.get("family") != envelope["family"]:
            raise ValueError("dataset family differs from the sampling envelope")
        params = dataset_spec.get("params", {})
        if not isinstance(params, dict) or any(params.get(key) != value for key, value in envelope["family_options"].items()):
            raise ValueError("dataset options differ from the sampling envelope")
    materialized = dataset_spec.get("files")
    if not isinstance(materialized, dict) or not materialized:
        raise ValueError("dataset spec must declare its materialized files")
    for name in materialized.values():
        if not isinstance(name, str) or not name:
            raise ValueError("invalid materialized dataset filename")
        path = dataset_path / name
        if not path.resolve().is_relative_to(dataset_path.resolve()) or str(path) not in hashes:
            raise ValueError("evidence does not bind every materialized dataset file")
    summary_paths = [str(Path(path) / "results" / "summary.json") for path in candidate_paths]
    if record.get("summary_paths") != summary_paths:
        raise ValueError("summary paths differ from the frozen candidate pair")
    metric = record["metric"]
    _text(metric, "metric")
    if dataset_spec.get("selection_metric") != metric:
        raise ValueError("selection metric differs from dataset specification")
    values = []
    for candidate_id, directory, summary_path in zip(record["candidate_ids"], candidate_paths, summary_paths):
        candidate_spec = _read_json(Path(directory) / "candidate_spec.json")
        if candidate_spec.get("candidate_id") != candidate_id:
            raise ValueError("candidate identity differs from frozen source")
        if candidate_spec.get("dataset_id") != record["dataset_id"]:
            raise ValueError("candidate dataset differs from frozen pair")
        if envelope is not None:
            try:
                in_envelope = (candidate_spec["family"] == envelope["family"]
                               and candidate_spec["profile_hash"] == envelope["profile_hash"]
                               and candidate_spec["model"]["type"] == envelope["model_type"]
                               and candidate_spec["budget"]["total_samples_seen"] in envelope["budget_values"]
                               and candidate_spec["optimizer"]["type"] in envelope["optimizer_types"]
                               and candidate_spec["loss"]["loss_id"] in envelope["loss_types"])
            except (KeyError, TypeError) as exc:
                raise ValueError("candidate does not describe its sampling envelope") from exc
            if not in_envelope:
                raise ValueError("candidate lies outside the frozen sampling envelope")
        summary = _read_json(Path(summary_path))
        if (summary.get("candidate_id") != candidate_id or summary.get("selection_metric") != metric
                or summary.get("execution") != "candidate_py_files"):
            raise ValueError("GT must come from the matching generated candidate code")
        if summary.get("failed_seeds") != 0 or summary.get("excluded") is not False:
            raise ValueError("execution failure cannot be scientific evidence")
        rows = summary.get("seed_results")
        if (not isinstance(rows, list) or summary.get("n_seeds") != len(record["seed_ids"])
                or len(rows) != len(record["seed_ids"]) or any(not isinstance(row, dict) for row in rows)
                or [row.get("seed") for row in rows] != record["seed_ids"]):
            raise ValueError("GT seed set differs from preregistration")
        finals = []
        for row in rows:
            final = row.get(f"final_{metric}")
            if row.get("failed") is not False or isinstance(final, bool) or not isinstance(final, (int, float)) or not math.isfinite(final):
                raise ValueError("failed or nonfinite seed result cannot be evidence")
            finals.append(final)
        values.append(finals)
    higher = pair.get("higher_is_better", False)
    if type(higher) is not bool:
        raise ValueError("higher_is_better must be boolean")
    a, b = values
    winner = None
    if max(a) < min(b):
        winner = record["candidate_ids"][1 if higher else 0]
    elif max(b) < min(a):
        winner = record["candidate_ids"][0 if higher else 1]
    predicted = record["predicted_winner"]
    if predicted not in record["candidate_ids"]:
        raise ValueError("prediction must select a frozen candidate")
    outcome = "inconclusive" if winner is None else "support" if winner == predicted else "refute"
    if record["outcome"] != outcome:
        raise ValueError("claimed outcome differs from actual per-seed GT")
    return plan


def describe_evidence(record: dict) -> dict:
    """Describe verified experiment facts for the Evidence Analyst, read-only.

    All model/control values come from the frozen candidate specs; reported
    means come from their GT summaries. Seed extrema summarize the verified
    final metrics, without training or recomputing scientific outcomes. Model
    differences map field names to candidate-ID/value mappings; a missing
    field omits that candidate ID, distinguishing absence from explicit null.
    Hypothesis text and competing explanations are never used as observations.
    """
    plan = verify_evidence_sources(record)
    pair = plan["pairs"][record["pair_index"]]

    def read_bound(path: Path) -> dict:
        # Read and hash the same bytes to avoid describing a file that changed
        # between provenance verification and assembling the analyst payload.
        try:
            contents = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read evidence description source: {path}") from exc
        if record["source_hashes"].get(str(path)) != hashlib.sha256(contents).hexdigest():
            raise ValueError(f"evidence description source hash mismatch: {path}")
        try:
            value = json.loads(contents)
        except ValueError as exc:
            raise ValueError(f"invalid evidence description JSON: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"evidence description source must be an object: {path}")
        return value

    controlled_factor = plan["request"].get("factor")
    _text(controlled_factor, "controlled factor")
    metric = pair["metric"]
    candidates = []
    for candidate_id, directory in zip(pair["candidate_ids"], pair["candidate_paths"]):
        spec = read_bound(Path(directory) / "candidate_spec.json")
        summary = read_bound(Path(directory) / "results" / "summary.json")
        for field in ("model", "budget", "optimizer", "loss"):
            if not isinstance(spec.get(field), dict):
                raise ValueError(f"candidate {candidate_id} must describe its {field}")
        mean = summary.get(f"mean_{metric}")
        if type(mean) not in (int, float) or not math.isfinite(mean):
            raise ValueError(f"candidate {candidate_id} has no finite stored metric mean")
        seed_values = [row[f"final_{metric}"] for row in summary["seed_results"]]
        candidates.append({"id": candidate_id, "model": spec["model"], "budget": spec["budget"],
                           "optimizer": spec["optimizer"], "loss": spec["loss"],
                           "mean": mean, "seed_min": min(seed_values), "seed_max": max(seed_values)})
    first, second = candidates
    models = [candidate["model"] for candidate in candidates]
    differences = {}
    for field in sorted(set(models[0]) | set(models[1])):
        if field not in models[0] or field not in models[1] or models[0][field] != models[1][field]:
            differences[field] = {candidate["id"]: candidate["model"][field]
                                  for candidate in candidates if field in candidate["model"]}
    facts = {"id": record["id"], "phase": record["phase"], "dataset_id": record["dataset_id"],
             "outcome": record["outcome"], "controlled_factor": controlled_factor,
             "training_seed_ids": list(plan["seed_ids"]), "n_seeds_per_candidate": plan["n_seeds"],
             "metric": metric, "higher_is_better": pair.get("higher_is_better", False),
             "candidate_model_differences": differences,
             "fixed_sections": {key: first[key] == second[key] for key in ("optimizer", "loss", "budget")},
             "candidates": candidates}
    dataset = read_bound(Path(pair["dataset_path"]) / "dataset_spec.json")
    if isinstance(dataset.get("params"), dict):
        facts["dataset_params"] = dataset["params"]
    return facts
