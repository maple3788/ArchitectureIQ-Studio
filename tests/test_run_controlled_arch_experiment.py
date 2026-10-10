from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import kb_claim_pairwise_eval as ev  # noqa: E402
import run_controlled_arch_experiment as ctrl  # noqa: E402
from architecture_iq.profile import load_profile  # noqa: E402
from architecture_iq.registry import ensure_registries  # noqa: E402

# Fields each factor may change; everything else in the model spec must match.
ALLOWED = {
    "layernorm": {"layer_norm"},
    "activation": {"activation", "leaky_relu_slope"},
    "residual": {"residual"},
    "depth": {"depth", "layer_norm"},
    "width": {"width"},
}


@pytest.fixture(scope="module")
def profile():
    ensure_registries()
    return load_profile(ctrl.PROFILE_NAME)


@pytest.mark.parametrize("seed", range(20))
def test_factor_variants_change_only_their_factor(profile, seed):
    rng = random.Random(seed)
    base = ctrl.sample_base(profile, "synthetic_tabular_classification", {"input_dim": 4, "num_classes": 2}, rng)
    for factor in ctrl.FACTORS:
        variants = ctrl.factor_variants(factor, base["model"], profile, rng)
        assert len({json.dumps(v, sort_keys=True) for v in variants}) == len(variants) >= 2
        for a, b in itertools.combinations(variants, 2):
            changed = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
            assert changed and changed <= ALLOWED[factor], (factor, changed)
        if factor == "depth":
            assert all(len(set(v["layer_norm"])) <= 1 for v in variants)
            assert len({tuple(set(v["layer_norm"])) for v in variants}) == 1
        if factor == "layernorm":
            assert sorted(sum(v["layer_norm"]) for v in variants) == [0, base["model"]["depth"]]


def test_dataset_plan_uses_fresh_unique_seeds_and_cycles_options():
    plan = ctrl.dataset_plan(ctrl.DEFAULT_DATASETS_PER_FAMILY)
    seeds = [p["seed"] for p in plan]
    assert len(seeds) == len(set(seeds)) == sum(ctrl.DEFAULT_DATASETS_PER_FAMILY.values())
    assert min(seeds) > 20_000_000
    tab = [p["family_options"] for p in plan if p["family"] == "synthetic_tabular_classification"]
    assert {o["rule_family"] for o in tab} == set(ctrl.TAB_RULES)
    assert all("input_dim" in p["family_options"] for p in plan if p["family"] == "xor_classification")


def test_plan_writes_scoreable_controlled_sets(tmp_path, profile):
    out = tmp_path / "ctrl"
    ctrl.cmd_plan(
        argparse.Namespace(
            out_root=out,
            bases_per_dataset=1,
            datasets_per_family=1,
            families=["univariate_regression"],
            existing_datasets_root=None,
        )
    )
    plan = json.loads((out / "plan.json").read_text())
    assert plan["n_sets"] == len(ctrl.FACTORS)
    set_dirs = sorted((out / "datasets").glob("*/*/candidates/ctrl_*"))
    assert {json.loads((d / "set.json").read_text())["controlled_factor"] for d in set_dirs} == set(ctrl.FACTORS)
    for d in set_dirs:
        manifest = json.loads((d / "set.json").read_text())
        cands = sorted(d.glob("c_*"))
        assert [c.name for c in cands] == sorted(manifest["candidates"])
        for c in cands:
            assert {p.name for p in c.iterdir()} >= {"candidate_spec.json", "model.py", "train.py", "loss.py", "optimizer.py"}
            spec = json.loads((c / "candidate_spec.json").read_text())
            assert spec["optimizer"] == manifest["fixed_shared"]["optimizer"]
            assert spec["budget"]["batch_size"] == manifest["fixed_shared"]["batch_size"]
    # Without GT the evaluator sees the sets but no candidates yet.
    sets = ev.load_sets(out / "datasets")
    assert len(sets) == len(ctrl.FACTORS) and all(not s["candidates"] for s in sets)
    groups = ctrl.candidate_groups(out / "datasets")
    assert sum(len(v) for v in groups.values()) == plan["n_candidate_dirs"]
