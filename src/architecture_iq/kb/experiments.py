"""Frozen public-only pair plans executed through the canonical GT pipeline.

The supported interventions come from the existing controlled architecture tool.
Planning may synthesize data and render candidates, but never computes GT.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import random

from .rules import _legacy_module, match_rule, public_views, validate_rule
from .store import canonical_hash, write_json_atomic

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_FILES = ("candidate_spec.json", "model.py", "loss.py", "optimizer.py", "train.py")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hashes(paths) -> dict[str, str]:
    return {str(path.resolve()): _hash(path) for path in sorted(set(paths))}


def _verify(hashes: dict[str, str]) -> None:
    for name, digest in hashes.items():
        path = Path(name)
        if not path.is_absolute() or not path.is_file() or _hash(path) != digest:
            raise ValueError(f"Frozen artifact hash changed: {name}")


@contextmanager
def _lock(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".experiment.lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _request(value: dict) -> dict:
    required = {"family", "factor", "seed_start", "count", "phase", "rule", "claim_id", "revision"}
    optional = {"profile", "planning_limit", "n_seeds", "family_options",
                "excluded_dataset_ids", "excluded_lineage_ids"}
    if not isinstance(value, dict) or not required <= set(value) or not set(value) <= required | optional:
        raise ValueError("Experiment request has missing or unknown fields")
    request = copy.deepcopy(value)
    for field in ("count", "revision", "seed_start", "planning_limit", "n_seeds"):
        if field in request and (type(request[field]) is not int or request[field] < (0 if field == "seed_start" else 1)):
            raise ValueError(f"Invalid experiment {field}")
    if request["count"] > 48 or request.get("n_seeds", 10) > 10:
        raise ValueError("Experiment exceeds supported dataset/seed count")
    request.setdefault("profile", "v1.5")
    request.setdefault("planning_limit", request["count"] * 20)
    request.setdefault("family_options", {})
    for key in ("excluded_dataset_ids", "excluded_lineage_ids"):
        identities = request.setdefault(key, [])
        if (not isinstance(identities, list) or len(identities) > 10000
                or any(not isinstance(identity, str) or not identity.strip() or len(identity) > 256
                       for identity in identities)):
            raise ValueError(f"{key} must be a bounded list of nonempty identity strings")
        request[key] = sorted(set(identities))
    if request["planning_limit"] > 5000 or request["planning_limit"] < request["count"]:
        raise ValueError("planning_limit must cover count and be at most 5000")
    for key in ("family", "profile", "claim_id"):
        if not isinstance(request[key], str) or not request[key] or len(request[key]) > 128:
            raise ValueError(f"Invalid experiment {key}")
    if not request["profile"].replace(".", "").replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid profile name")
    if request["phase"] not in ("exploration", "confirmation"):
        raise ValueError("Invalid experiment phase")
    controlled = _legacy_module("run_controlled_arch_experiment")
    if request["factor"] not in controlled.FACTORS or request["family"] not in controlled.MLP_FAMILIES:
        raise ValueError("Unsupported controlled family/factor")
    options = request["family_options"]
    if not isinstance(options, dict) or not set(options) <= {"input_dim", "rule_family"}:
        raise ValueError("Unsupported family_options")
    if "input_dim" in options and (type(options["input_dim"]) is not int or not 1 <= options["input_dim"] <= 128):
        raise ValueError("Invalid family input dimension")
    if "rule_family" in options and options["rule_family"] not in controlled.TAB_RULES:
        raise ValueError("Invalid family rule")
    validate_rule(request["rule"])
    # JSON is the boundary: NaN/Infinity or unserializable extensions are invalid.
    try:
        json.dumps(request, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Experiment request must be finite JSON") from exc
    return request


def _source_paths(profile: str) -> list[Path]:
    # Bind every potential canonical generation/runtime dependency, including
    # family plugins. Only the unrelated coordinator/store files are excluded.
    package = ROOT / "src" / "architecture_iq"
    paths = [p for p in package.rglob("*.py") if "kb" not in p.relative_to(package).parts]
    paths += [Path(__file__).resolve(), ROOT / "src/architecture_iq/kb/rules.py",
              ROOT / "tools/run_controlled_arch_experiment.py", ROOT / "tools/kb_claim_pairwise_eval.py",
              ROOT / "profiles" / f"{profile}.yaml"]
    return paths


def _dataset_paths(spec: dict, root: Path) -> list[Path]:
    paths = [root / "dataset_spec.json"]
    files = spec.get("files")
    if not isinstance(files, dict) or "synthesize" not in files:
        raise ValueError("Dataset spec must declare synthesis/materialized files")
    for relative in files.values():
        if not isinstance(relative, str):
            raise ValueError("Dataset file paths must be strings")
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("Dataset artifact is missing or outside its directory")
        paths.append(path)
    return paths


def _is_excluded(request: dict, dataset_id: str, lineage_id: str) -> bool:
    return (dataset_id in request["excluded_dataset_ids"]
            or lineage_id in request["excluded_lineage_ids"])


def sampling_envelope(request: dict, profile) -> dict:
    """The distribution sampled by this adapter, restricted to its actual family."""
    return {"family": request["family"], "model_type": "mlp", "profile_hash": profile.profile_hash,
            "budget_values": sorted(set(profile.budget_values)),
            "optimizer_types": sorted(set(profile.pools["optimizers"])),
            "loss_types": sorted(set(profile.pools["losses"][request["family"]])),
            "intervention": request["factor"], "family_options": copy.deepcopy(request["family_options"]),
            "pair_sampling": "uniform_applicable_pairs_from_factor_variants",
            "controls": {"equal": ["opt_key", "loss_key", "budget", "batch_size"],
                         "architecture_intervention": request["factor"]}}


def _load_plan(path: Path) -> dict:
    seal = path.with_suffix(".sha256")
    if not seal.is_file() or seal.read_text().strip() != _hash(path):
        raise ValueError("Immutable plan hash is missing or changed")
    plan = _read(path)
    if _request(plan["request"]) != plan["request"]:
        raise ValueError("Frozen request is not normalized")
    _verify(plan["source_hashes"])
    for pair in plan["pairs"]:
        if _is_excluded(plan["request"], pair["dataset_id"], pair["lineage_id"]):
            raise ValueError("Frozen plan contains an excluded dataset or lineage")
        _verify(pair["source_hashes"])
    return plan


def plan_experiment(request: dict, out: Path) -> dict:
    """Freeze at most one applicable pair per dataset within a fixed sample limit."""
    from architecture_iq.candidates.generator import build_candidate_spec, write_candidate
    from architecture_iq.profile import load_profile
    from architecture_iq.registry import ensure_registries, get_model_type
    import yaml

    request = _request(request)
    out = Path(out).resolve()
    with _lock(out):
        plan_path = out / "plan.json"
        if plan_path.exists():
            existing = _load_plan(plan_path)
            if existing["request"] != request:
                raise ValueError("Immutable plan already exists for a different request")
            return existing
        ensure_registries()
        profile = load_profile(request["profile"])
        if "n_seeds" in request:
            profile.ground_truth["n_seeds"] = request["n_seeds"]
        profile_path = out / "profile.yaml"
        profile_path.write_text(yaml.safe_dump(profile.raw, sort_keys=True), encoding="utf-8")
        source_hashes = _hashes([*_source_paths(request["profile"]), profile_path])
        envelope = sampling_envelope(request, profile)
        controlled = _legacy_module("run_controlled_arch_experiment")
        pairs = []
        seen = set()
        attempts = 0
        for attempt in range(request["planning_limit"]):
            attempts += 1
            item = {"family": request["family"], "seed": request["seed_start"] + attempt,
                    "family_options": request["family_options"]}
            dataset, dataset_path = controlled.materialize_dataset(profile, item, out / "datasets")
            lineage_id = f"{dataset['family']}:{dataset['dataset_id']}"
            if _is_excluded(request, dataset["dataset_id"], lineage_id):
                continue
            if dataset["family"] != request["family"]:
                raise ValueError("Generated dataset differs from requested family")
            if dataset["dataset_id"] in seen:
                continue
            seen.add(dataset["dataset_id"])
            metric = dataset["selection_metric"]
            if metric not in _legacy_module("kb_claim_pairwise_eval").LOWER_IS_BETTER:
                raise ValueError("No verified metric direction for controlled family")
            rng = random.Random(f"kb:{dataset['dataset_id']}:{request['factor']}")
            base = controlled.sample_base(profile, request["family"], dataset["params"], rng)
            specs = [build_candidate_spec(profile, dataset_id=dataset["dataset_id"], family=request["family"],
                                          budget=base["budget"], batch_size=base["batch_size"],
                                          model=model, optimizer=base["optimizer"], loss=base["loss"])
                     for model in controlled.factor_variants(request["factor"], base["model"], profile, rng)]
            views = public_views(dataset, specs)
            applicable = []
            for a, b in itertools.combinations(range(len(specs)), 2):
                prediction = match_rule(request["rule"], views[a], views[b])
                if prediction is not None:
                    applicable.append((a, b, prediction))
            if not applicable:
                continue
            # This independent, preregistered seed stream selects uniformly from
            # every public-applicable pair. No result exists at this stage.
            pair_rng = random.Random(f"kb-pair:{item['seed']}:{dataset['dataset_id']}:{request['factor']}")
            a_index, b_index, prediction = pair_rng.choice(applicable)
            candidates = [specs[a_index], specs[b_index]]
            candidate_paths = []
            for candidate in candidates:
                path = dataset_path / "candidates" / "kb_pair" / candidate["candidate_id"]
                write_candidate(candidate, path, get_model_type(candidate["model"]["type"]))
                candidate_paths.append(path.resolve())
            candidate_ids = [s["candidate_id"] for s in candidates]
            if len(set(candidate_ids)) != 2:
                raise ValueError("Controlled pair contains duplicate candidates")
            hashes = _hashes([*_dataset_paths(dataset, dataset_path),
                              *(p / name for p in candidate_paths for name in CANDIDATE_FILES)])
            pairs.append({"dataset_id": dataset["dataset_id"],
                          "lineage_id": lineage_id, "sampling_envelope": envelope,
                          "eligible_pair_count": len(applicable),
                          "chosen_variant_indexes": [a_index, b_index],
                          "dataset_path": str(dataset_path.resolve()), "candidate_ids": candidate_ids,
                          "candidate_paths": list(map(str, candidate_paths)), "metric": metric,
                          "higher_is_better": not _legacy_module("kb_claim_pairwise_eval").LOWER_IS_BETTER[metric],
                          "predicted_winner": candidate_ids[prediction], "source_hashes": hashes})
            if len(pairs) == request["count"]:
                break
        plan = {"schema_version": 1, "request": request, "complete": len(pairs) == request["count"],
                "planned_count": len(pairs), "planning_attempts": attempts, "pairs": pairs,
                "n_seeds": profile.n_seeds, "seed_ids": list(range(profile.base_seed, profile.base_seed + profile.n_seeds)),
                "profile_hash": profile.profile_hash, "profile_path": str(profile_path),
                "sampling_envelope": envelope,
                "source_hashes": source_hashes, "required_candidate_seed_runs": len(pairs) * 2 * profile.n_seeds}
        # Recheck dependencies in case another worker changed code during planning.
        _verify(source_hashes)
        write_json_atomic(plan_path, plan)
        with plan_path.with_suffix(".sha256").open("x", encoding="utf-8") as handle:
            handle.write(_hash(plan_path) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return plan


def _require_execution_host() -> None:
    from .execution_host import execution_host_enabled

    if not execution_host_enabled():
        raise RuntimeError("Scientific GT requires the privately configured authorized Linux execution host")


def _summary(path: Path, candidate_id: str, metric: str, seed_ids: list[int]) -> dict:
    value = _read(path)
    if value.get("execution") != "candidate_py_files" or value.get("candidate_id") != candidate_id or value.get("selection_metric") != metric:
        raise ValueError("GT summary provenance does not match the frozen candidate")
    rows = value.get("seed_results", [])
    if value.get("n_seeds") != len(seed_ids) or [r.get("seed") for r in rows] != seed_ids:
        raise ValueError("GT summary seed provenance does not match the frozen plan")
    for row in rows:
        metric_value = row.get(f"final_{metric}")
        if type(metric_value) not in (int, float) or type(row.get("failed")) is not bool:
            raise ValueError("GT summary has invalid seed results")
        if not row["failed"] and not math.isfinite(metric_value):
            raise ValueError("Successful GT seed has nonfinite metric")
    return value


def _outcome(summaries: list[dict], pair: dict) -> str:
    if any(s.get("excluded") or s.get("failed_seeds") or any(r["failed"] for r in s["seed_results"]) for s in summaries):
        return "inconclusive"
    candidates = [{"mean": s[f"mean_{pair['metric']}"],
                   "seeds": [r[f"final_{pair['metric']}"] for r in s["seed_results"]],
                   "seed_ids": [r["seed"] for r in s["seed_results"]]} for s in summaries]
    relation = _legacy_module("kb_claim_pairwise_eval").pair_outcome(*candidates, pair["metric"])
    winner = relation["separated_winner"]
    if winner is None:
        return "inconclusive"
    return "support" if pair["candidate_ids"][winner] == pair["predicted_winner"] else "refute"


def execute_experiment(plan_path: Path, *, max_candidate_seed_runs: int,
                       safe_boundary=None) -> list[dict]:
    """Run a sealed plan once, preserving uncertain reservations on interruption.

    The limit is a ceiling for this entire plan, including completed receipts.
    A directory with GT but no matching receipt is never adopted as a cache hit.
    The optional control callback may block before a new candidate reservation
    and after its complete receipt is durable. It never runs during GT execution.
    """
    from architecture_iq.ground_truth.runner import run_ground_truth
    from architecture_iq.profile import Profile
    from architecture_iq.registry import ensure_registries
    from .evidence import evidence_id

    plan_path = Path(plan_path).resolve()
    with _lock(plan_path.parent):
        plan = _load_plan(plan_path)
        if type(max_candidate_seed_runs) is not int or max_candidate_seed_runs < plan["required_candidate_seed_runs"]:
            raise ValueError("Candidate-seed budget is insufficient for the frozen plan")
        plan_hash = _hash(plan_path)
        profile = Profile.load(Path(plan["profile_path"]))
        if profile.profile_hash != plan["profile_hash"] or profile.n_seeds != plan["n_seeds"]:
            raise ValueError("Frozen profile hash changed")
        envelope = sampling_envelope(plan["request"], profile)
        if plan.get("sampling_envelope") != envelope:
            raise ValueError("Frozen sampling envelope differs from the profile/request")
        ensure_registries()
        jobs = []
        for pair in plan["pairs"]:
            dataset = _read(Path(pair["dataset_path"]) / "dataset_spec.json")
            lineage_id = f"{dataset['family']}:{dataset['dataset_id']}"
            if _is_excluded(plan["request"], dataset["dataset_id"], lineage_id):
                raise ValueError("Dataset content identity is excluded by the frozen request")
            if (dataset["family"] != envelope["family"] or dataset["dataset_id"] != pair["dataset_id"]
                    or lineage_id != pair["lineage_id"] or pair.get("sampling_envelope") != envelope):
                raise ValueError("Frozen pair identity/sampling envelope differs from the dataset")
            specs = [_read(Path(p) / "candidate_spec.json") for p in pair["candidate_paths"]]
            for candidate_id, spec in zip(pair["candidate_ids"], specs):
                if (spec["candidate_id"] != candidate_id or spec["dataset_id"] != dataset["dataset_id"]
                        or spec["family"] != envelope["family"] or spec["model"]["type"] != "mlp"
                        or spec["profile_hash"] != envelope["profile_hash"]
                        or spec["budget"]["total_samples_seen"] not in envelope["budget_values"]
                        or spec["optimizer"]["type"] not in envelope["optimizer_types"]
                        or spec["loss"]["loss_id"] not in envelope["loss_types"]):
                    raise ValueError("Candidate differs from the frozen sampling envelope")
            views = public_views(dataset, specs)
            predicted = match_rule(plan["request"]["rule"], *views)
            if predicted is None or pair["candidate_ids"][predicted] != pair["predicted_winner"]:
                raise ValueError("Frozen public pair prediction changed")
            for candidate_id, name in zip(pair["candidate_ids"], pair["candidate_paths"]):
                candidate = Path(name)
                receipt = plan_path.parent / "receipts" / f"{canonical_hash(str(candidate))}.json"
                result_paths = [candidate / "results" / name for name in ("summary.json", "curves.npz")]
                if receipt.exists():
                    saved = _read(receipt)
                    if saved.get("plan_hash") != plan_hash or saved.get("candidate_id") != candidate_id:
                        raise ValueError("GT receipt does not match the frozen plan")
                    if saved.get("state") != "complete":
                        raise RuntimeError("GT reservation is pending; execution is uncertain and cannot be retried")
                    _verify(saved["source_hashes"])
                    if set(saved["source_hashes"]) != {str(p) for p in result_paths}:
                        raise ValueError("GT receipt is missing result source hashes")
                elif any(p.exists() for p in result_paths):
                    raise ValueError("Unreceipted GT cannot be reused")
                jobs.append((pair, candidate_id, candidate, receipt, result_paths))
        if any(not receipt.exists() for _, _, _, receipt, _ in jobs):
            _require_execution_host()
        for pair, candidate_id, candidate, receipt, result_paths in jobs:
            if receipt.exists():
                continue
            def boundary(state):
                if safe_boundary is not None:
                    safe_boundary({
                        "node_id": "confirmation" if plan["request"]["phase"] == "confirmation" else "experiment",
                        "state": state, "safe_boundary": True,
                        "candidate_id": candidate_id, "dataset_id": pair["dataset_id"],
                        "candidate_seed_runs": profile.n_seeds,
                        "receipt_path": str(receipt),
                    })
            boundary("ready")
            # Reservation is durably persisted before the external execution.
            write_json_atomic(receipt, {"state": "pending", "plan_hash": plan_hash,
                                       "candidate_id": candidate_id, "candidate_seed_runs": profile.n_seeds})
            run_ground_truth(candidate, profile, dataset_path=Path(pair["dataset_path"]))
            _verify(plan["source_hashes"])
            _verify(pair["source_hashes"])
            _summary(result_paths[0], candidate_id, pair["metric"], plan["seed_ids"])
            write_json_atomic(receipt, {"state": "complete", "plan_hash": plan_hash,
                                       "candidate_id": candidate_id, "candidate_seed_runs": profile.n_seeds,
                                       "source_hashes": _hashes(result_paths)})
            boundary("complete")
        records = []
        failures = []
        for index, pair in enumerate(plan["pairs"]):
            summary_paths = [Path(p) / "results/summary.json" for p in pair["candidate_paths"]]
            summaries = [_summary(path, candidate_id, pair["metric"], plan["seed_ids"])
                         for path, candidate_id in zip(summary_paths, pair["candidate_ids"])]
            if any(s.get("excluded") or s.get("failed_seeds") or any(r["failed"] for r in s["seed_results"]) for s in summaries):
                failures.append({"pair_index": index, "dataset_id": pair["dataset_id"],
                                 "reason": "failed_or_excluded_seeds",
                                 "summary_paths": list(map(str, summary_paths))})
                continue
            sources = {**plan["source_hashes"], **pair["source_hashes"], str(plan_path): plan_hash,
                       **_hashes([p for candidate in pair["candidate_paths"]
                                  for p in (Path(candidate) / "results/summary.json", Path(candidate) / "results/curves.npz")])}
            record = {"claim_id": plan["request"]["claim_id"], "revision": plan["request"]["revision"],
                      "phase": plan["request"]["phase"], "lineage_id": pair["lineage_id"],
                      "dataset_id": pair["dataset_id"], "candidate_ids": pair["candidate_ids"],
                      "seed_ids": plan["seed_ids"], "outcome": _outcome(summaries, pair),
                      "provenance": "canonical_gt", "plan_path": str(plan_path), "plan_hash": plan_hash,
                      "pair_index": index, "metric": pair["metric"], "predicted_winner": pair["predicted_winner"],
                      "summary_paths": list(map(str, summary_paths)), "source_hashes": sources}
            record["id"] = evidence_id(record)
            records.append(record)
        write_json_atomic(plan_path.parent / "execution_failures.json", failures)
        write_json_atomic(plan_path.parent / "evidence.json", records)
        return records
