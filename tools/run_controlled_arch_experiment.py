#!/usr/bin/env python3
"""One-factor-at-a-time MLP architecture experiments on fresh dataset instances.

Benchmark candidate sets vary depth, width, activation, residual and per-layer
LayerNorm together, so an architecture claim cannot be checked on them without
confounding. This tool builds controlled candidate sets instead: for each
dataset it samples *base* configurations from the active profile exactly as
``generate-candidates`` would (model, optimizer, loss, budget, batch size), then
derives one candidate set per factor in which only that factor changes.

Everything runs through the canonical pipeline: datasets via the family's
``create_instance`` / ``materialize`` (which executes ``synthesize.py``),
candidates via ``build_candidate_spec`` / ``write_candidate``, and GT via
``run_ground_truth``. Output keeps the standard layout, so
``tools/kb_claim_pairwise_eval.py --datasets-root OUT/datasets`` scores it.

Usage (on the GT host):
  python tools/run_controlled_arch_experiment.py plan --out-root data/controlled_arch_v1
  python tools/run_controlled_arch_experiment.py run  --out-root data/controlled_arch_v1 --workers 200
  python tools/run_controlled_arch_experiment.py status --out-root data/controlled_arch_v1
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import shutil
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROFILE_NAME = "v1.5"
# Fresh seed range: v1.5 benchmark seeds start at 100_000-600_000 and the KB
# learning epochs at 11_000_000-16_000_000, so 70_000_000+ cannot collide.
CTRL_SEED_BASE = 70_000_000
MLP_FAMILIES = (
    "univariate_regression",
    "multivariate_regression",
    "spiral_classification",
    "xor_classification",
    "synthetic_tabular_classification",
)
DEFAULT_DATASETS_PER_FAMILY = {
    "univariate_regression": 4,
    "multivariate_regression": 4,
    "spiral_classification": 4,
    "xor_classification": 4,
    # Six so every tabular rule family appears twice.
    "synthetic_tabular_classification": 6,
}
# Family option cycles follow the v1.5 benchmark builder's conventions.
MV_INPUT_DIMS = (2, 3, 4, 5, 8)
TAB_INPUT_DIMS = (2, 4, 8, 16)
TAB_RULES = ("smooth_additive", "sparse_interaction", "piecewise_boundary")
FACTORS = ("layernorm", "activation", "residual", "depth", "width")


# ---------------------------------------------------------------- dataset plan


def dataset_plan(datasets_per_family: dict[str, int]) -> list[dict[str, Any]]:
    plan = []
    for f_index, family in enumerate(MLP_FAMILIES, start=1):
        for i in range(datasets_per_family.get(family, 0)):
            options: dict[str, Any] = {}
            if family == "multivariate_regression":
                options["input_dim"] = MV_INPUT_DIMS[i % len(MV_INPUT_DIMS)]
            elif family == "synthetic_tabular_classification":
                options["input_dim"] = TAB_INPUT_DIMS[i % len(TAB_INPUT_DIMS)]
                options["rule_family"] = TAB_RULES[i % len(TAB_RULES)]
            elif family == "xor_classification":
                options["input_dim"] = TAB_INPUT_DIMS[i % len(TAB_INPUT_DIMS)]
            plan.append(
                {
                    "family": family,
                    "index": i,
                    "seed": CTRL_SEED_BASE + f_index * 1_000_000 + i * 37,
                    "family_options": options,
                }
            )
    return plan


def materialize_dataset(profile: Any, item: dict[str, Any], datasets_root: Path) -> tuple[dict[str, Any], Path]:
    """Same steps as ``datasets.create_dataset`` but rooted at ``datasets_root``."""
    from architecture_iq.registry import get_dataset_family
    from architecture_iq.util import read_json

    family = get_dataset_family(item["family"])
    partial = family.create_instance(profile, item["seed"], **item["family_options"])
    spec = family.build_spec_with_id(partial)
    out = datasets_root / family.name / spec["dataset_id"]
    if not (out / "dataset_spec.json").is_file():
        family.materialize({**partial, **spec}, out)
    return read_json(out / "dataset_spec.json"), out


# ------------------------------------------------------------- factor variants


def mlp_variant(base: dict[str, Any], profile: Any, **changes: Any) -> dict[str, Any]:
    """Copy an MLP spec with only ``changes`` applied, keeping it renderable."""
    from architecture_iq.registry import get_model_type

    model = copy.deepcopy(base)
    model.update(changes)
    if "depth" in changes and "layer_norm" not in changes:
        raise ValueError("changing depth needs an explicit layer_norm list")
    if model["activation"] == "leaky_relu":
        model["leaky_relu_slope"] = float(profile.mlp["leaky_relu_slope"])
    else:
        model.pop("leaky_relu_slope", None)
    get_model_type("mlp").validate(model)
    return model


def factor_variants(
    factor: str, base: dict[str, Any], profile: Any, rng: random.Random
) -> list[dict[str, Any]]:
    """Models for one controlled set: they differ from each other only in ``factor``.

    The depth factor also fixes LayerNorm to one uniform on/off setting, since
    a per-layer list cannot keep its length across depths.
    """
    depth = int(base["depth"])
    if factor == "layernorm":
        return [mlp_variant(base, profile, layer_norm=[flag] * depth) for flag in (False, True)]
    if factor == "activation":
        return [mlp_variant(base, profile, activation=a) for a in profile.mlp["activations"]]
    if factor == "residual":
        return [mlp_variant(base, profile, residual=r) for r in (False, True)]
    if factor == "depth":
        flag = rng.choice([False, True])
        return [mlp_variant(base, profile, depth=d, layer_norm=[flag] * d) for d in profile.mlp["depth"]]
    if factor == "width":
        widths = sorted(rng.sample(list(profile.mlp["width"]), 3))
        return [mlp_variant(base, profile, width=w) for w in widths]
    raise ValueError(f"unknown factor {factor!r}")


def sample_base(profile: Any, family: str, dataset_params: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """One base configuration, drawn the way a candidate set draws its members."""
    from architecture_iq.candidates.generator import (
        _pick_batch_size,
        sample_loss,
        sample_model,
        sample_optimizer,
    )

    budget = rng.choice(profile.budget_values)
    defaults = profile.family_training_defaults(family)
    if defaults and budget == defaults["total_samples_seen"]:
        batch_size = defaults["batch_size"]
    else:
        batch_size = _pick_batch_size(profile, budget, rng)
    return {
        "budget": budget,
        "batch_size": batch_size,
        "model": sample_model(profile, rng, family=family, dataset_params=dataset_params, model_type="mlp"),
        "optimizer": sample_optimizer(profile, rng),
        "loss": sample_loss(profile, family, rng),
    }


# ------------------------------------------------------------------------ plan


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_plan(args: argparse.Namespace) -> None:
    from architecture_iq.candidates.generator import build_candidate_spec, write_candidate
    from architecture_iq.profile import load_profile
    from architecture_iq.registry import ensure_registries, get_model_type
    from architecture_iq.util import short_hash, write_json

    ensure_registries()
    profile = load_profile(PROFILE_NAME)
    mlp = get_model_type("mlp")
    datasets_root = args.out_root / "datasets"
    per_family = dict(DEFAULT_DATASETS_PER_FAMILY)
    if args.datasets_per_family is not None:
        per_family = {f: args.datasets_per_family for f in MLP_FAMILIES}
    if args.families:
        per_family = {f: n for f, n in per_family.items() if f in args.families}

    existing_ids = set()
    if args.existing_datasets_root:
        existing_ids = {p.name for p in args.existing_datasets_root.glob("*/*") if p.is_dir()}

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest_datasets = []
    n_candidates = n_sets = 0
    for item in dataset_plan(per_family):
        ds_spec, ds_path = materialize_dataset(profile, item, datasets_root)
        if ds_spec["dataset_id"] in existing_ids:
            raise SystemExit(f"dataset {ds_spec['dataset_id']} already exists under {args.existing_datasets_root}")
        params = ds_spec["params"]
        for b in range(args.bases_per_dataset):
            rng = random.Random(f"ctrl:{ds_spec['dataset_id']}:{b}")
            base = sample_base(profile, item["family"], params, rng)
            for factor in FACTORS:
                specs = [
                    build_candidate_spec(
                        profile,
                        dataset_id=ds_spec["dataset_id"],
                        family=item["family"],
                        budget=base["budget"],
                        batch_size=base["batch_size"],
                        model=model,
                        optimizer=base["optimizer"],
                        loss=base["loss"],
                    )
                    for model in factor_variants(factor, base["model"], profile, rng)
                ]
                ids = [s["candidate_id"] for s in specs]
                if len(set(ids)) != len(ids):
                    raise RuntimeError(f"duplicate variants in {factor} set for {ds_spec['dataset_id']} base {b}")
                set_id = f"ctrl_{base['budget']}_{factor}_b{b:02d}_{short_hash(ids)}"
                set_dir = ds_path / "candidates" / set_id
                for spec in specs:
                    write_candidate(spec, set_dir / spec["candidate_id"], mlp)
                write_json(
                    set_dir / "set.json",
                    {
                        "schema_version": profile.schema_version,
                        "set_id": set_id,
                        "dataset_id": ds_spec["dataset_id"],
                        "family": item["family"],
                        "budget": {"total_samples_seen": base["budget"]},
                        "count": len(specs),
                        "varying_axes": ["model"],
                        "invariant_axes": ["loss", "optimizer"],
                        "controlled_factor": factor,
                        "base_index": b,
                        "base_model": base["model"],
                        "fixed_shared": {
                            "batch_size": base["batch_size"],
                            "optimizer": base["optimizer"],
                            "loss": base["loss"],
                        },
                        "candidates": ids,
                        "profile": profile.name,
                        "profile_hash": profile.profile_hash,
                        "created_at": created,
                    },
                )
                n_candidates += len(specs)
                n_sets += 1
        manifest_datasets.append({**item, "dataset_id": ds_spec["dataset_id"], "path": str(ds_path)})

    write_json(
        args.out_root / "plan.json",
        {
            "created_at": created,
            "profile": profile.name,
            "profile_hash": profile.profile_hash,
            "tool_sha256": _file_sha256(Path(__file__)),
            "factors": list(FACTORS),
            "bases_per_dataset": args.bases_per_dataset,
            "datasets": manifest_datasets,
            "n_sets": n_sets,
            "n_candidate_dirs": n_candidates,
        },
    )
    groups = candidate_groups(datasets_root)
    print(f"datasets={len(manifest_datasets)} sets={n_sets} candidate_dirs={n_candidates} unique_candidates={len(groups)}")


# ------------------------------------------------------------------------- run


def candidate_groups(datasets_root: Path) -> dict[tuple[str, str], list[Path]]:
    """Candidate dirs keyed by (dataset path, candidate_id); one GT run serves a group."""
    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for spec_path in sorted(datasets_root.glob("*/*/candidates/*/c_*/candidate_spec.json")):
        ds_path = spec_path.parents[3]
        groups[(str(ds_path), spec_path.parent.name)].append(spec_path.parent)
    return groups


def _has_results(cand: Path) -> bool:
    return (cand / "results" / "summary.json").is_file()


def _fan_out(dirs: list[Path]) -> None:
    """Copy the primary candidate's results to identical candidates in other sets."""
    primary = dirs[0]
    for other in dirs[1:]:
        if not _has_results(other):
            shutil.copytree(primary / "results", other / "results", dirs_exist_ok=True)


def _worker_init() -> None:
    import torch

    torch.set_num_threads(1)


def _run_one(candidate: str, dataset: str) -> tuple[str, float, str | None]:
    from architecture_iq.profile import load_profile
    from architecture_iq.registry import ensure_registries
    from architecture_iq.ground_truth.runner import run_ground_truth

    start = time.time()
    try:
        ensure_registries()
        run_ground_truth(Path(candidate), load_profile(PROFILE_NAME), Path(dataset))
        return candidate, time.time() - start, None
    except Exception:  # noqa: BLE001 - logged and retried on the next run
        return candidate, time.time() - start, traceback.format_exc()


def cmd_run(args: argparse.Namespace) -> None:
    # One Torch thread per candidate process; parallelism comes from workers.
    os.environ["ARCHITECTURE_IQ_TORCH_THREADS"] = "1"
    os.environ.pop("ARCHITECTURE_IQ_SEED_WORKERS", None)
    datasets_root = args.out_root / "datasets"
    groups = candidate_groups(datasets_root)
    pending = []
    for (ds_path, _cid), dirs in groups.items():
        if _has_results(dirs[0]):
            _fan_out(dirs)
            continue
        steps = json.loads((dirs[0] / "candidate_spec.json").read_text())["budget"]["training_steps"]
        pending.append((steps, ds_path, dirs))
    pending.sort(key=lambda t: -t[0])  # longest first for load balance
    log = (args.out_root / "run.log").open("a")
    failures = (args.out_root / "run_failures.jsonl").open("a")

    def emit(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    total = len(pending)
    emit(f"start pending={total} of unique={len(groups)} workers={args.workers}")
    by_candidate = {str(dirs[0]): dirs for _s, _d, dirs in pending}
    t0 = time.time()
    done = failed = 0
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init) as pool:
        futures = [pool.submit(_run_one, str(dirs[0]), ds) for _s, ds, dirs in pending]
        for fut in as_completed(futures):
            cand, secs, err = fut.result()
            if err is None:
                _fan_out(by_candidate[cand])
                done += 1
            else:
                failed += 1
                failures.write(json.dumps({"candidate": cand, "error": err}) + "\n")
                failures.flush()
            n = done + failed
            if n % args.log_every == 0 or n == total:
                rate = n / max(time.time() - t0, 1e-9)
                eta = (total - n) / rate if rate else float("inf")
                emit(f"progress {n}/{total} ok={done} failed={failed} last={secs:.1f}s eta={eta / 60:.1f}min")
    emit(f"finished ok={done} failed={failed} minutes={(time.time() - t0) / 60:.1f}")


def cmd_status(args: argparse.Namespace) -> None:
    groups = candidate_groups(args.out_root / "datasets")
    done = sum(_has_results(dirs[0]) for dirs in groups.values())
    print(f"unique_candidates={len(groups)} with_results={done} pending={len(groups) - done}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="materialize datasets and write controlled candidate sets")
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--bases-per-dataset", type=int, default=8)
    p.add_argument("--datasets-per-family", type=int, default=None, help="override the per-family defaults")
    p.add_argument("--families", nargs="*", default=None, choices=MLP_FAMILIES)
    p.add_argument("--existing-datasets-root", type=Path, default=None, help="refuse dataset ids already present here")
    r = sub.add_parser("run", help="run GT for every candidate without results")
    r.add_argument("--out-root", type=Path, required=True)
    r.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 8))
    r.add_argument("--log-every", type=int, default=25)
    s = sub.add_parser("status")
    s.add_argument("--out-root", type=Path, required=True)
    args = ap.parse_args(argv)
    commands: dict[str, Callable[[argparse.Namespace], None]] = {"plan": cmd_plan, "run": cmd_run, "status": cmd_status}
    commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
