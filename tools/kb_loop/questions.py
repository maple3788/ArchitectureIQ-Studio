"""Build v1.5 questions exactly as the main500 benchmark was built.

``build_one`` follows ``tools/build_benchmark_v15.py`` (feat/kb-learning-pipeline,
the builder of benchmarks/v1_5/main500): create_dataset -> generate_candidate_set
(which runs ground truth by executing the generated train.py) ->
generate_questions(num_choices=3, question_type) -> write_prompt, 12 candidates
per set, the v1.5 profile unchanged. The only differences are the dataset-claim
directory (so loop questions never reuse a dataset instance, nor one of the
main500 instances) and the seed block, which the planner assigns per round.

A target item (one that feeds a claim) may additionally pick, among seeds of its
own block, a dataset instance whose dataset fields satisfy the claim's scope and a
candidate set whose sampled configurations contain a pair the claim speaks to
(both checked before any training), and among the valid three-way subsets of the
trained set (each drawn by ``generate_questions`` under a different seed) one the
claim applies to. Every pick looks only at whether the claim makes a prediction,
never at whether it is right; pools, sampling and question rules are unchanged.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

if __package__ == "tools.kb_loop":
    from tools.kb_consistency_runtime import require_authorized_execution
else:
    from kb_consistency_runtime import require_authorized_execution

FAMILY_WEIGHTS = (  # main500 quota 100/100/100/100/50/50
    ("univariate_regression", 2),
    ("multivariate_regression", 2),
    ("bigram_lm", 2),
    ("synthetic_tabular_classification", 2),
    ("xor_classification", 1),
    ("spiral_classification", 1),
)
FAMILIES = tuple(f for f, _ in FAMILY_WEIGHTS)
QUESTION_TYPES = ("architecture_only", "optimizer_only", "mixed")
BUDGETS = (4096, 8192, 16384, 32768)
MV_INPUT_DIMS = (2, 3, 4, 5, 8)
TAB_INPUT_DIMS = (2, 4, 8, 16)
TAB_RULES = ("smooth_additive", "sparse_interaction", "piecewise_boundary")


def family_options(family: str, i: int) -> dict[str, Any]:
    if family == "multivariate_regression":
        return {"input_dim": MV_INPUT_DIMS[(i // 3) % len(MV_INPUT_DIMS)]}
    if family == "synthetic_tabular_classification":
        return {"input_dim": TAB_INPUT_DIMS[(i // 3) % len(TAB_INPUT_DIMS)],
                "rule_family": TAB_RULES[(i // 4) % len(TAB_RULES)]}
    if family == "xor_classification":
        return {"input_dim": TAB_INPUT_DIMS[(i // 3) % len(TAB_INPUT_DIMS)]}
    return {}


def varying_axes(question_type: str) -> frozenset[str]:
    return {"architecture_only": frozenset({"model"}), "optimizer_only": frozenset({"optimizer"}),
            "mixed": frozenset({"model", "optimizer"})}[question_type]


def build_order(item: dict[str, Any]) -> float:
    """Relative training cost of one item, so the slowest start first and the round does not wait on a late
    straggler. bigram_lm candidates are sequence models and train 3-5x slower than the rest at the same budget."""
    return item["budget"] * (4.0 if item["family"] == "bigram_lm" else 1.0)


def _set_seed_workers(n: int) -> None:
    """Opt into the ground-truth runner's parallel seeds (same train.py, same seeds, identical results)."""
    if n > 1:
        os.environ["ARCHITECTURE_IQ_SEED_WORKERS"] = str(n)
        os.environ.setdefault("ARCHITECTURE_IQ_SEED_TORCH_THREADS", "1")
    else:
        os.environ.pop("ARCHITECTURE_IQ_SEED_WORKERS", None)


def _load_attempts(path: Path | None) -> dict[tuple[int, int], str]:
    """Set attempts an item already spent before a restart: (dataset attempt, set attempt) -> note."""
    if path is None or not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[(r["ds_attempt"], r["set_attempt"])] = r["note"]
    return out


def _record_attempt(path: Path | None, ds_attempt: int, set_attempt: int, note: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"ds_attempt": ds_attempt, "set_attempt": set_attempt, "note": note}) + "\n")


def _reset_partial(dataset_path: Path, candidates_root: Path, questions_root: Path) -> None:
    """Drop an interrupted item's half-built candidate sets and question runs. Their folder names are seed
    determined and the pipeline never overwrites a folder, so a leftover would waste the retried attempt."""
    import shutil

    for root in (candidates_root, questions_root):
        if root.resolve().parent == dataset_path.resolve() and root.exists():
            shutil.rmtree(root)


def dataset_fits(spec: dict[str, Any], target_rules: list[list[dict[str, Any]]]) -> bool:
    """Some target rule's required dataset conditions hold on this dataset instance."""
    from kb_claim_pairwise_eval import dataset_view, holds
    from kb_loop.checks import DATASET_FIELDS
    from kb_loop.planner import required_leaves

    try:
        ds = dataset_view(spec)
        return any(all(holds(leaf, ds) for leaf in required_leaves(rule.get("scope")) if leaf[0] in DATASET_FIELDS)
                   for rules in target_rules for rule in rules)
    except Exception:  # noqa: BLE001 -- a malformed scope never blocks a build
        return True


def set_speaks_to(specs: list[dict[str, Any]], dataset_spec: dict[str, Any],
                  target_rules: list[list[dict[str, Any]]]) -> bool:
    """Some pair of the sampled (untrained) candidate configurations is one a target rule predicts on."""
    from kb_claim_pairwise_eval import candidate_view, dataset_view
    from kb_loop.ensemble import pair_vote

    try:
        ds = dataset_view(dataset_spec)
        views = [candidate_view(spec, ds) for spec in specs]
        return any(pair_vote(rules, a, b) is not None
                   for a, b in itertools.combinations(views, 2) for rules in target_rules)
    except Exception:  # noqa: BLE001
        return True


def target_applies(question: dict[str, Any], data_root: Path, target_rules: list[list[dict[str, Any]]],
                   min_gap: float, winner_only: bool = False) -> bool:
    """Some target claim makes a prediction on one of the question's counted comparisons (right or wrong)."""
    from kb_loop.evidence import claim_outcome, question_record

    try:
        rec = question_record(question, data_root, 0, "target")
        return any(claim_outcome(rules, rec, min_gap, winner_only) is not None for rules in target_rules)
    except Exception:  # noqa: BLE001
        return False


def _claim(claims_dir: Path, dataset_id: str, reserved: frozenset[str], item_id: str = "") -> bool:
    """Atomically claim a dataset instance for one item; the same item may reclaim it after a restart."""
    if dataset_id in reserved:
        return False
    claims_dir.mkdir(parents=True, exist_ok=True)
    path = claims_dir / dataset_id
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return bool(item_id) and path.read_text().strip() == item_id
    os.write(fd, item_id.encode())
    os.close(fd)
    return True


def build_one(item: dict[str, Any], profile_name: str, count: int, ds_attempts: int, set_attempts: int,
              claims_dir: str, reserved: frozenset[str], seed_workers: int = 1,
              attempts_dir: str | None = None, targeting: dict[str, Any] | None = None) -> dict[str, Any]:
    require_authorized_execution()
    import shutil

    import torch

    torch.set_num_threads(1)
    _set_seed_workers(seed_workers)
    from architecture_iq.candidates.sets import generate_candidate_set, sample_candidate_set_pool
    from architecture_iq.datasets import create_dataset
    from architecture_iq.paths import DATA_DIR, candidate_set_dir
    from architecture_iq.profile import load_profile
    from architecture_iq.prompts.renderer import write_prompt
    from architecture_iq.questions.generator import generate_questions
    from architecture_iq.questions.runs import question_run_dir
    from architecture_iq.registry import ensure_registries, get_dataset_family

    ensure_registries()
    profile = load_profile(profile_name)
    family_name = item["family"]
    family = get_dataset_family(family_name)
    qtype = item["question_type"]
    started = time.time()
    notes: list[str] = []
    attempts_path = Path(attempts_dir) / f"{item['item_id']}.jsonl" if attempts_dir else None
    tried = _load_attempts(attempts_path)
    target_rules = (targeting or {}).get("rules") or []
    probe_tries = int((targeting or {}).get("probe_tries", 1)) if target_rules else 1
    draws = int((targeting or {}).get("draws", 1)) if target_rules else 1
    set_probe_tries = int((targeting or {}).get("set_probe_tries", 1)) if target_rules else 1
    min_gap = float((targeting or {}).get("min_gap", 0.0))
    winner_only = bool((targeting or {}).get("winner_only", False))
    for ds_attempt in range(ds_attempts):
        ds_seed = item["seed_base"] + 1_009 * ds_attempt
        if all((ds_attempt, s) in tried for s in range(set_attempts)):
            notes += [f"{tried[(ds_attempt, s)]} (before restart)" for s in range(set_attempts)]
            continue
        try:
            probe = family.build_spec_with_id(family.create_instance(profile, ds_seed, **item["family_options"]))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"ds_seed={ds_seed} create_instance failed: {exc!r}")
            continue
        if probe_tries > 1 and not dataset_fits(probe, target_rules):
            for t in range(1, probe_tries):  # other seeds of this item's block; first fit wins
                seed_t = ds_seed + 104_729 * t
                try:
                    probe_t = family.build_spec_with_id(family.create_instance(profile, seed_t, **item["family_options"]))
                except Exception:  # noqa: BLE001
                    continue
                if dataset_fits(probe_t, target_rules):
                    ds_seed, probe = seed_t, probe_t
                    break
        dataset_id = probe["dataset_id"]
        reclaimed = (Path(claims_dir) / dataset_id).exists()
        if not _claim(Path(claims_dir), dataset_id, reserved, item["item_id"]):
            notes.append(f"ds_seed={ds_seed} dataset_id {dataset_id} already used")
            continue
        try:
            _spec, dataset_path = create_dataset(profile, ds_seed, family_name=family_name,
                                                 family_options=item["family_options"] or None)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"ds_seed={ds_seed} create_dataset failed: {exc!r}")
            continue
        if reclaimed:
            _reset_partial(Path(dataset_path), candidate_set_dir(Path(dataset_path), "_").parent,
                           question_run_dir(Path(dataset_path).resolve(), "_").parent)
        for set_attempt in range(set_attempts):
            set_seed = item["seed_base"] * 3 + 7_919 * set_attempt + 101 * ds_attempt
            set_count = count if set_attempt == 0 else max(6, count - 2 * set_attempt)
            if (ds_attempt, set_attempt) in tried:
                notes.append(f"{tried[(ds_attempt, set_attempt)]} (before restart)")
                continue
            if set_probe_tries > 1:  # untrained draws of the official sampler; first one the claim speaks to wins
                ds_spec = json.loads((Path(dataset_path) / "dataset_spec.json").read_text())
                for t in range(set_probe_tries):
                    seed_t = set_seed + 104_729 * t
                    try:
                        specs = sample_candidate_set_pool(profile, dataset_id=dataset_id, family=family_name,
                                                          budget=item["budget"], count=set_count,
                                                          varying_axes=varying_axes(qtype), rng=random.Random(seed_t),
                                                          fixed_shared={}, dataset_params=ds_spec["params"])
                    except Exception:  # noqa: BLE001
                        continue
                    if set_speaks_to(specs, ds_spec, target_rules):
                        set_seed = seed_t
                        break
            try:
                set_path = generate_candidate_set(profile, dataset_path=dataset_path, budget=item["budget"],
                                                  count=set_count, varying_axes=varying_axes(qtype),
                                                  rng=random.Random(set_seed), seed=set_seed)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"set_seed={set_seed} candidate set failed: {exc!r}")
                _record_attempt(attempts_path, ds_attempt, set_attempt, notes[-1])
                continue
            made: list[tuple[Path, dict[str, Any], Path, bool]] = []
            failure: Exception | None = None
            for j in range(draws):  # draw 0 is the untargeted question; later draws only for target items
                q_seed = set_seed + 1 + 104_729 * j
                try:
                    run_path, results = generate_questions(profile, dataset_path=dataset_path,
                                                           candidate_set_paths=[set_path], rng=random.Random(q_seed),
                                                           num_questions=1, num_choices=3, seed=q_seed,
                                                           question_type=qtype)
                except Exception as exc:  # noqa: BLE001
                    failure = failure or exc
                    break
                record, out = results[0]
                hit = bool(target_rules) and target_applies(json.loads((Path(out) / "question.json").read_text()),
                                                            Path(DATA_DIR), target_rules, min_gap, winner_only)
                made.append((Path(run_path), record, Path(out), hit))
                if hit or not target_rules:
                    break
            if not made:
                notes.append(f"set_seed={set_seed} question assembly failed: {failure!r}")
                _record_attempt(attempts_path, ds_attempt, set_attempt, notes[-1])
                continue
            chosen = next((m for m in made if m[3]), made[0])
            for m in made:  # one question per dataset: drop the draws not kept
                if m[0] != chosen[0]:
                    shutil.rmtree(m[0], ignore_errors=True)
            _run, record, out, hit = chosen
            write_prompt(out)
            return {**item, "status": "ok", "dataset_id": dataset_id, "question_id": record["question_id"],
                    "question_path": str(out / "question.json"), "question_type": record["type"],
                    "target_hit": hit if target_rules else None, "draws": len(made),
                    "seconds": round(time.time() - started, 1), "notes": notes}
    return {**item, "status": "failed", "seconds": round(time.time() - started, 1), "notes": notes}


def _worker(payload: tuple) -> dict[str, Any]:
    item = payload[0]
    try:
        return build_one(*payload)
    except Exception:  # noqa: BLE001
        return {**item, "status": "crashed", "traceback": traceback.format_exc()[-2000:]}


def build_items(items: list[dict[str, Any]], *, profile: str, count: int, ds_attempts: int, set_attempts: int,
                workers: int, claims_dir: Path, reserved: frozenset[str], log_path: Path,
                on_result: Callable[[dict[str, Any]], None] | None = None,
                seed_workers: dict[str, int] | None = None, attempts_dir: Path | None = None,
                target_rules: dict[str, list[dict[str, Any]]] | None = None,
                targeting: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build every item not already ``ok`` in ``log_path``, slowest first; append each result to it.

    ``seed_workers`` maps a dataset family to parallel ground-truth seeds per candidate; ``attempts_dir``
    keeps each item's spent set attempts so a restart resumes instead of repeating them. ``target_rules`` (claim
    id -> rules) and ``targeting`` (probe_tries, draws, min_gap) steer target items toward their claims."""
    require_authorized_execution()
    done = {}
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r["status"] == "ok" or r["item_id"] not in done:
                    done[r["item_id"]] = r
    todo = [it for it in items if done.get(it["item_id"], {}).get("status") != "ok"]
    todo.sort(key=build_order, reverse=True)
    def steer(it: dict[str, Any]) -> dict[str, Any] | None:
        rules = [target_rules[c] for c in it.get("targets") or [] if target_rules and c in target_rules]
        return {**targeting, "rules": rules} if targeting and rules else None

    payloads = [(it, profile, count, ds_attempts, set_attempts, str(claims_dir), reserved,
                 (seed_workers or {}).get(it["family"], 1), str(attempts_dir) if attempts_dir else None, steer(it))
                for it in todo]
    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(payloads) or 1))) as ex:
        futures = [ex.submit(_worker, p) for p in payloads]
        for fut in as_completed(futures):
            r = fut.result()
            with log_path.open("a") as f:
                f.write(json.dumps(r, sort_keys=True) + "\n")
            done[r["item_id"]] = r
            if on_result:
                on_result(r)
    return [done[it["item_id"]] for it in items if it["item_id"] in done]
