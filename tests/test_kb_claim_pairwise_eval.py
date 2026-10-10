from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import kb_claim_pairwise_eval as ev  # noqa: E402

DS = {
    "family": "xor_classification",
    "params": {"input_dim": 2, "rule_family": "xor", "active_features": [0, 1], "train_size": 1024},
    "selection_metric": "test_ce",
}


def _spec(opt: str, lr: float, *, depth: int = 2, width: int = 64, residual: bool = False,
          batch: int = 16, steps: int = 256, **opt_extra) -> dict:
    return {
        "family": DS["family"],
        "budget": {"training_steps": steps, "batch_size": batch, "total_samples_seen": steps * batch},
        "model": {
            "type": "mlp", "depth": depth, "width": width, "residual": residual,
            "activation": "relu", "layer_norm": [False] * depth, "input_dim": 2, "output_dim": 2,
        },
        "optimizer": {"type": opt, "lr": lr, "weight_decay": 0.0, **opt_extra},
        "loss": {"loss_id": "cross_entropy"},
    }


def _view(spec: dict) -> dict:
    return ev.candidate_view(spec, ev.dataset_view(DS))


def test_leaf_and_conjunction_predicates():
    v = _view(_spec("Adam", 1e-3, betas=[0.9, 0.95]))
    assert ev.holds(["lr", "eq", 0.001], v)
    assert ev.holds(["lr", "le", 0.001], v)  # tolerant equality on grid floats
    assert ev.holds([["opt", "eq", "Adam"], ["beta2", "eq", 0.95]], v)
    assert not ev.holds({"any": [["opt", "eq", "SGD"], ["lr", "lt", 1e-4]]}, v)
    assert ev.holds({"not": ["opt", "eq", "SGD"]}, v)
    # A field the candidate does not have (momentum for Adam) never satisfies a leaf.
    assert not ev.holds(["momentum", "eq", 0], v)


def test_displacement_proxy_matches_claim_formulas():
    assert _view(_spec("Adam", 1e-3, betas=[0.9, 0.999]))["disp"] == 1e-3 * 256
    assert abs(_view(_spec("Adagrad", 1e-3))["disp"] - 2 * 1e-3 * 16) < 1e-12
    sgd = _view(_spec("SGD", 1e-3, momentum=0.9))
    assert sgd["disp"] is None
    assert abs(sgd["eff_lr"] - 1e-2) < 1e-12


def test_better_worse_rule_orients_and_respects_same():
    rule = {
        "same": ["arch_key"],
        "predict": {"better": [["lr", "ge", 1e-3]], "worse": [["lr", "le", 1e-4]]},
    }
    hi = _view(_spec("Adam", 1e-3, betas=[0.9, 0.999]))
    lo = _view(_spec("Adam", 1e-4, betas=[0.9, 0.999]))
    assert ev.predicted_winner(rule, hi, lo) == 0
    assert ev.predicted_winner(rule, lo, hi) == 1
    other_arch = _view(_spec("Adam", 1e-4, depth=3, betas=[0.9, 0.999]))
    assert ev.predicted_winner(rule, hi, other_arch) is None


def test_dominates_needs_strict_gain_and_min_ratio():
    rule = {"predict": {"dominates": [["width", "higher"], ["depth", "lower"]]}}
    wide_shallow = _view(_spec("Adam", 1e-3, depth=1, width=128, betas=[0.9, 0.999]))
    narrow_deep = _view(_spec("Adam", 1e-3, depth=4, width=32, betas=[0.9, 0.999]))
    wide_deep = _view(_spec("Adam", 1e-3, depth=4, width=128, betas=[0.9, 0.999]))
    assert ev.predicted_winner(rule, narrow_deep, wide_shallow) == 1
    assert ev.predicted_winner(rule, wide_shallow, wide_deep) == 0
    # Trade-off pairs are not covered by a Pareto claim.
    assert ev.predicted_winner(rule, wide_deep, _view(_spec("Adam", 1e-3, depth=1, width=32, betas=[0.9, 0.999]))) is None

    ratio = {
        "predict": {
            "dominates": [["per_step", "higher", 10]],
            "winner": [["opt", "eq", "SGD"]],
            "loser": [["opt", "eq", "Adagrad"]],
        }
    }
    sgd = _view(_spec("SGD", 3e-3, momentum=0.9))  # per_step 0.03
    adagrad_small = _view(_spec("Adagrad", 1e-3))  # per_step 2e-3/16 = 1.25e-4
    adagrad_big = _view(_spec("Adagrad", 0.1))  # per_step 0.0125, under 10x
    assert ev.predicted_winner(ratio, sgd, adagrad_small) == 0
    assert ev.predicted_winner(ratio, sgd, adagrad_big) is None


def test_pair_outcome_uses_full_separation():
    a = {"mean": 0.1, "seeds": [0.09, 0.1, 0.11], "seed_ids": [0, 1, 2]}
    b = {"mean": 0.3, "seeds": [0.2, 0.3, 0.4], "seed_ids": [0, 1, 2]}
    overlap = {"mean": 0.2, "seeds": [0.105, 0.2, 0.3], "seed_ids": [0, 1, 2]}
    assert ev.pair_outcome(a, b, "test_ce") == {"mean_winner": 0, "separated_winner": 0}
    assert ev.pair_outcome(a, overlap, "test_ce") == {"mean_winner": 0, "separated_winner": None}
    failed = {"mean": 0.05, "seeds": [0.01, float("inf"), 0.02], "seed_ids": [0, 1, 2]}
    assert ev.pair_outcome(failed, b, "test_ce")["separated_winner"] is None


def test_end_to_end_on_tiny_candidate_set(tmp_path: Path):
    ds_dir = tmp_path / "datasets" / "xor_classification" / "xorcls_t"
    set_dir = ds_dir / "candidates" / "set_4096_fix_var_fix_t"
    set_dir.mkdir(parents=True)
    (ds_dir / "dataset_spec.json").write_text(json.dumps({**DS, "dataset_id": "xorcls_t"}))
    (set_dir / "set.json").write_text(json.dumps(
        {"set_id": set_dir.name, "dataset_id": "xorcls_t", "family": DS["family"], "varying_axes": ["optimizer"]}
    ))
    for cid, lr, seeds in [("c_hi", 1e-3, [0.2, 0.21]), ("c_lo", 1e-4, [0.6, 0.65]), ("c_mid", 3e-4, [0.5, 0.7])]:
        c = set_dir / cid
        (c / "results").mkdir(parents=True)
        (c / "candidate_spec.json").write_text(json.dumps({**_spec("Adam", lr, betas=[0.9, 0.999]), "candidate_id": cid}))
        (c / "results" / "summary.json").write_text(json.dumps({
            "mean_test_ce": sum(seeds) / 2,
            "seed_results": [{"seed": i, "failed": False, "final_test_ce": s} for i, s in enumerate(seeds)],
        }))
    sets = ev.load_sets(tmp_path / "datasets")
    claim = {"rules": [{"scope": [["adaptive", "eq", True]], "same": ["arch_key"], "predict": {"higher_better": "lr"}}]}
    scored = ev.score_claim(claim, sets)
    # hi>lo (separated), hi>mid (separated), mid vs lo overlaps -> not decisive.
    assert scored["n_applicable"] == 3
    assert scored["n_decisive"] == 2
    assert scored["precision"] == 1.0
    assert scored["mean_order_precision"] == 1.0
