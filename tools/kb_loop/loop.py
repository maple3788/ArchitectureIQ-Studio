#!/usr/bin/env python3
"""KB self-iteration loop: build v1.5 questions, score claims, judge, propose, register, report.

  python tools/kb_loop/loop.py init --root LOOP --config configs/kb_loop/loop.example.yaml \\
      --seed-claims configs/kb_claim_rules/kb_v10_revision.json --reference data/kb_0008.json
  python tools/kb_loop/loop.py round --root LOOP [--pilot] [--round K]
  python tools/kb_loop/loop.py run-forever --root LOOP [--max-rounds N]
  python tools/kb_loop/loop.py status --root LOOP

Each round runs the stages plan -> build -> score -> judge -> propose -> register -> report;
a DONE_<stage> marker is written after each, and a rerun resumes at the first missing one.
Touch <root>/STOP to stop after the current round. Design:
docs/superpowers/specs/2026-10-11-kb-self-iteration-loop-design.md
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
# The GT runner defaults to 8 Torch threads per process; with ~200 build workers that oversubscribes the host
# (load ~1600 on 232 cores, round 2 built 2 questions in 9 h). One thread per worker; results are unaffected.
os.environ.setdefault("ARCHITECTURE_IQ_TORCH_THREADS", "1")

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from kb_loop import checks, diagnostics, ensemble, judge, planner, proposer, questions, report  # noqa: E402
from kb_loop.evidence import question_record, score_records  # noqa: E402
from kb_loop.qwen import ReplicaPool, read_api_key  # noqa: E402
from kb_loop.store import Store, sha256_file  # noqa: E402
from kb_consistency_runtime import MANIFEST, RUN_MARKER, _digest, require_authorized_execution  # noqa: E402

STAGES = ("plan", "build", "score", "judge", "propose", "register", "report")
MAIN500_IDS = TOOLS.parent / "configs" / "kb_loop" / "main500_dataset_ids.json"


def _require_prepared_runtime(run_root: Path | None = None) -> None:
    """Require installed gates and the run binding before mutating loop state."""
    manifest_path = TOOLS.parent / MANIFEST
    if not globals().get("_semantic_gate_installed", False) or not manifest_path.is_file():
        raise RuntimeError("KB mutations require a prepared runtime; use tools/kb_consistency_runtime.py")
    require_authorized_execution()
    if run_root is not None:
        marker = Path(run_root) / RUN_MARKER
        manifest = json.loads(manifest_path.read_text())
        if not marker.is_file() or json.loads(marker.read_text()).get("runtime_manifest_hash") != _digest(manifest):
            raise ValueError("run is not bound to this prepared runtime; never resume frozen runs with new source")


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True, default=list) + "\n")


def _data_root() -> Path:
    from architecture_iq.paths import DATA_DIR
    return Path(DATA_DIR)


# ------------------------------------------------------------------ init


def seed_claims(path: Path) -> list[dict[str, Any]]:
    """KB v10 claims as candidates; ``same`` is replaced by ``inject_same`` where given (the injected form)."""
    out = []
    for c in _json(path)["claims"]:
        rules = c["rules"]
        if "inject_same" in c:
            rules = [{**r, "same": list(c["inject_same"])} for r in rules]
            rules = [{k: v for k, v in r.items() if k != "same" or v} for r in rules]
        out.append({"text": c["text"], "rules": rules, "origin": f"seed:{path.stem}/{c['id']}"})
    return out


def cmd_init(args: argparse.Namespace) -> None:
    _require_prepared_runtime()
    if args.root.exists():
        raise ValueError("initialize requires a new run directory; historical runs cannot be rebound")
    store = Store(args.root)
    store.root.mkdir(parents=True, exist_ok=True)
    if store.config_path.exists():
        raise SystemExit(f"{store.root} is already initialised")
    shutil.copy(args.config, store.config_path)
    claims: dict[str, dict[str, Any]] = {}
    for s in seed_claims(Path(args.seed_claims)):
        cid = store.new_claim_id(claims)
        claims[cid] = {"id": cid, "version": 1, "status": "candidate", "text": s["text"], "rules": s["rules"],
                       "origin": s["origin"], "parent": None, "registered_round": 0, "revisions": 0,
                       "needs_revision": False, "stats": None}
        store.write_version(claims[cid])
    store.save_claims(claims)
    ref = []
    if args.reference:
        snap = _json(Path(args.reference))
        ref = [f"- {c['text']}" for c in snap["claims"] if c.get("support_count", 0) + c.get("failure_count", 0) >= 1]
    _dump(store.root / "reference.json", ref)
    _dump(store.root / "rounds_reference_used.json", {"rounds": [1]})
    log(f"initialised {store.root}: {len(claims)} seed claims, {len(ref)} reference propositions")


# ------------------------------------------------------------------ stages


def stage_plan(store: Store, k: int, n_total: int, cfg: dict[str, Any]) -> None:
    _require_prepared_runtime(store.root)
    items = planner.plan_round(k, store.claims(), store.ledger(), store.records(), n_total,
                               {**cfg["questions"], **cfg["judge"]})
    _dump(store.round_dir(k) / "plan.json", items)
    log(f"round {k}: planned {len(items)} questions "
        f"({sum(i['purpose'] == 'target' for i in items)} targeted)")


def _reserved() -> frozenset[str]:
    if not MAIN500_IDS.exists():
        raise SystemExit(f"missing {MAIN500_IDS}: needed so loop questions never reuse a main500 dataset")
    return frozenset(_json(MAIN500_IDS)["dataset_ids"])


def stage_build(store: Store, k: int, cfg: dict[str, Any]) -> None:
    _require_prepared_runtime(store.root)
    q = cfg["questions"]
    items = _json(store.round_dir(k) / "plan.json")
    done = Counter()

    def progress(r: dict[str, Any]) -> None:
        done[r["status"]] += 1
        if sum(done.values()) % 10 == 0 or sum(done.values()) == len(items):
            log(f"round {k}: built {sum(done.values())}/{len(items)} ({dict(done)})")

    questions.build_items(items, profile=cfg["profile"], count=q["candidates_per_set"], ds_attempts=q["dataset_attempts"],
                          set_attempts=q["set_attempts"], workers=q["workers"], claims_dir=store.root / "dataset_claims",
                          reserved=_reserved(), log_path=store.round_dir(k) / "build.jsonl", on_result=progress,
                          seed_workers=q.get("seed_workers") or {}, attempts_dir=store.round_dir(k) / "attempts",
                          target_rules={cid: c["rules"] for cid, c in store.claims().items()},
                          targeting={"probe_tries": q.get("target_probe_tries", 1), "draws": q.get("target_draws", 1),
                                     "set_probe_tries": q.get("target_set_probe_tries", 1), "min_gap": _min_gap(cfg),
                                     "winner_only": _winner_only(cfg)})


def _built(store: Store, k: int) -> list[dict[str, Any]]:
    rows = {}
    p = store.round_dir(k) / "build.jsonl"
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["status"] == "ok" or r["item_id"] not in rows:
                rows[r["item_id"]] = r
    return list(rows.values())


def stage_score(store: Store, k: int, cfg: dict[str, Any]) -> None:
    _require_prepared_runtime(store.root)
    data_root = _data_root()
    recs = []
    for r in _built(store, k):
        if r["status"] != "ok":
            continue
        q = _json(Path(r["question_path"]))
        recs.append(question_record(q, data_root, k, r["purpose"], r.get("targets")))
    store.add_records(recs)
    this_round = [r for r in store.records() if r["round"] == k]
    have = {(r["claim_id"], r["version"], r["question_id"]) for r in store.ledger()}
    rows = []
    for cid, c in store.claims().items():
        if c["status"] == "retired":
            continue
        for qid, v in score_records(c["rules"], this_round, _min_gap(cfg), _winner_only(cfg)).items():
            if (cid, c["version"], qid) not in have:
                rows.append({"claim_id": cid, "version": c["version"], "question_id": qid, "round": k, **v})
    store.add_ledger(rows)
    _dump(store.round_dir(k) / "score.json", {"questions": len(this_round), "verdicts": len(rows)})
    log(f"round {k}: scored {len(this_round)} questions, {len(rows)} verdicts")


def stage_judge(store: Store, k: int, cfg: dict[str, Any]) -> None:
    _require_prepared_runtime(store.root)
    path = store.round_dir(k) / "judge.json"
    if not path.exists():
        claims, events = judge.judge_round(store.claims(), store.ledger(), k, cfg["judge"])
        _dump(path, {"claims": claims, "events": events})
    data = _json(path)
    store.save_claims(data["claims"])
    log(f"round {k}: {len(data['events'])} status events")


def _min_gap(cfg: dict[str, Any]) -> float:
    """Relative gap two options need before their comparison counts as evidence (0 = every separated pair)."""
    return float(cfg.get("evidence", {}).get("min_relative_gap", 0.0))


def _winner_only(cfg: dict[str, Any]) -> bool:
    """Only comparisons of the correct answer against a rival count (a misordered pair of losers is not evidence)."""
    return bool(cfg.get("evidence", {}).get("winner_only", False))


def _proposer_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """The model that proposes and revises claims: ``proposer`` when configured, else the local Qwen block."""
    return cfg.get("proposer") or cfg["qwen"]


def _pool(store: Store, cfg: dict[str, Any]) -> ReplicaPool:
    _require_prepared_runtime(store.root)
    q = _proposer_cfg(cfg)
    return ReplicaPool(q["base_urls"], q["model"], store.root / "qwen_cache", timeout_s=q["timeout_s"],
                       max_tokens=q.get("max_tokens", 0), concurrency=q["concurrency"],
                       api_key=read_api_key(q.get("api_key_file")), extra_params=q.get("extra_params"),
                       send_temperature=q.get("send_temperature", True), thinking_toggle=q.get("thinking_toggle", True),
                       stream=q.get("stream", False))


def split_targets(active: dict[str, dict[str, Any]], verdicts: dict[str, dict[str, Any]], min_new_errors: int,
                  cap: int) -> dict[str, int]:
    """Claims to try splitting because they were wrong again: {claim id: its wrong answers now}.

    A claim qualifies with at least ``min_new_errors`` more wrong answers than at its last split attempt; the
    most new errors go first, up to ``cap`` claims. Claims judged in need of revision are split anyway."""
    if min_new_errors <= 0:
        return {}
    rows = []
    for cid, c in active.items():
        if c.get("needs_revision"):
            continue
        wrong = sum(x["outcome"] == "refute" for x in verdicts[cid].values())
        if wrong - c.get("split_seen_wrong", 0) >= min_new_errors:
            rows.append((-(wrong - c.get("split_seen_wrong", 0)), cid, wrong))
    return {cid: wrong for _, cid, wrong in sorted(rows)[:cap]}


def stage_propose(store: Store, k: int, cfg: dict[str, Any]) -> dict[str, Any]:
    _require_prepared_runtime(store.root)
    path = store.round_dir(k) / "proposals.json"
    if path.exists():
        return _json(path)
    q, ck, jd = _proposer_cfg(cfg), cfg["checks"], cfg["judge"]
    pool = _pool(store, cfg)
    rng = random.Random(k)
    claims = store.claims()
    records = store.records()
    by_qid = {r["question_id"]: r for r in records}
    active = {cid: c for cid, c in claims.items() if c["status"] != "retired"}
    gap, wo = _min_gap(cfg), _winner_only(cfg)
    verdicts = {cid: score_records(c["rules"], records, gap, wo) for cid, c in active.items()}
    rejections: Counter = Counter()

    new_rate = ck.get("new_min_rate", jd["flag_rate"])
    split_rate = ck.get("revision_min_rate", new_rate)

    # Splits: claims that failed judgement, and any claim with new wrong answers since its last split attempt.
    split_attempts = split_targets(active, verdicts, q.get("split_new_errors", 0), q.get("split_max_claims", 30))
    rev_jobs, rev_meta = [], []
    for cid in [c for c in active if active[c].get("needs_revision")] + sorted(split_attempts):
        c = active[cid]
        v = verdicts[cid]
        refuted = diagnostics.stratified([by_qid[qid] for qid, x in v.items() if x["outcome"] == "refute"], 8, rng)
        supported = diagnostics.stratified([by_qid[qid] for qid, x in v.items() if x["outcome"] == "support"], 6, rng)
        table = diagnostics.condition_table(diagnostics.claim_pairs(v, by_qid))
        msgs = proposer.revision_messages(c, refuted, supported, v, table, ck["min_history_applicable"], split_rate,
                                          ck["max_conditions"])
        for j in range(q["revisions_per_claim"]):
            rev_jobs.append((msgs, q["propose_temperature"], f"rev:{cid}:v{c['version']}:{j}"))
            rev_meta.append(cid)

    # New claims per (family, question type) cell.
    verified_rules = [c["rules"] for c in active.values() if c["status"] == "verified"]
    tables = proposer.win_tables(records, min_gap=gap, winner_only=wo)
    by_dataset = proposer.dataset_tables(records, min_gap=gap, winner_only=wo)
    use_ref = k in _json(store.root / "rounds_reference_used.json")["rounds"]
    reference = _json(store.root / "reference.json") if use_ref else []
    new_jobs = []
    evidence_n = {cid: len(v) for cid, v in verdicts.items()}
    for family in questions.FAMILIES:
        listing = proposer.listing_for(active, family, evidence_n, q.get("listing_cap", 60))
        for qtype in questions.QUESTION_TYPES:
            cell = [r for r in records if r["family"] == family and r["type"] == qtype]
            uncovered = [r for r in cell if not any(score_records(rules, [r], gap, wo) for rules in verified_rules)]
            rng.shuffle(uncovered)
            msgs = proposer.proposal_messages((family, qtype), tables.get((family, qtype), []), listing,
                                              uncovered[:8], reference, pooled=tables.get(("*", qtype), []),
                                              by_dataset=by_dataset.get((family, qtype), []),
                                              max_conditions=ck["max_conditions"])
            for j in range(q["proposals_per_cell"]):
                new_jobs.append((msgs, q["propose_temperature"], f"new:{family}:{qtype}:{j}"))

    log(f"round {k}: asking the proposer for {len(rev_jobs)} split drafts and {len(new_jobs)} proposal batches")
    replies = pool.map(rev_jobs + new_jobs)
    rev_replies, new_replies = replies[:len(rev_jobs)], replies[len(rev_jobs):]
    # Novelty is judged against claims that already hold up (verified) and against what this round accepts;
    # a narrower, more accurate claim inside a weak broad one is exactly what we want to keep.
    strong = {cid: v for cid, v in verdicts.items() if active[cid]["status"] == "verified"}
    splits: dict[str, list[dict[str, Any]]] = {}
    split_verdicts: dict[str, Any] = {}
    for cid, reply in zip(rev_meta, rev_replies):
        if isinstance(reply, Exception):
            rejections["qwen error"] += 1
            continue
        try:
            drafts = proposer.parse_proposals(reply)
        except Exception as exc:  # noqa: BLE001
            rejections[f"split unparseable: {str(exc)[:60]}"] += 1
            continue
        for d in drafts:
            if len(splits.get(cid, [])) >= q.get("splits_per_claim", 3):
                rejections["split cap reached"] += 1
                continue
            try:
                stats = checks.check_claim(d["rules"], records, {**strong, **split_verdicts}, ck, split_rate,
                                           min_gap=gap, winner_only=wo)
            except Exception as exc:  # noqa: BLE001 -- one bad draft must never stop the stage
                rejections[f"split: {str(exc)[:80]}"] += 1
                continue
            split_verdicts[f"split:{cid}:{len(splits.get(cid, []))}"] = score_records(d["rules"], records, gap, wo)
            splits.setdefault(cid, []).append({**d, **stats})

    accepted: list[dict[str, Any]] = []
    accepted_verdicts: dict[str, Any] = {}
    candidates = []
    for reply in new_replies:
        if isinstance(reply, Exception):
            rejections["qwen error"] += 1
            continue
        try:
            candidates.extend(proposer.parse_proposals(reply))
        except Exception as exc:  # noqa: BLE001
            rejections[f"unparseable: {str(exc)[:60]}"] += 1
    rng.shuffle(candidates)
    for cand in candidates:
        if len(accepted) >= q.get("max_new_per_round", 40):
            rejections["round cap reached"] += 1
            continue
        try:
            stats = checks.check_claim(cand["rules"], records, {**strong, **split_verdicts, **accepted_verdicts}, ck,
                                       new_rate, min_gap=gap, winner_only=wo)
        except Exception as exc:  # noqa: BLE001 -- one bad proposal must never stop the stage
            rejections[f"new: {str(exc)[:80]}"] += 1
            continue
        tag = f"new{len(accepted)}"
        accepted_verdicts[tag] = score_records(cand["rules"], records, gap, wo)
        accepted.append({**cand, **stats})

    # Text-vs-rule consistency check on everything that will be registered.
    to_check = [(f"{cid}#{i}", d) for cid, ds in splits.items() for i, d in enumerate(ds)] + \
        [(f"new{i}", a) for i, a in enumerate(accepted)]
    cons = pool.map([(proposer.consistency_messages(a["text"], a["rules"]), q["check_temperature"], f"cons:{k}:{key}")
                     for key, a in to_check])
    consistency = {}
    for (key, _a), reply in zip(to_check, cons):
        try:
            consistency[key] = proposer.parse_consistency(reply) if not isinstance(reply, Exception) else {"consistent": None, "issue": "check failed"}
        except ValueError:
            consistency[key] = {"consistent": None, "issue": "unparseable"}
    data = {"revisions": {}, "splits": splits, "new": accepted, "consistency": consistency, "rejections": dict(rejections),
            "needs_revision": [cid for cid, c in active.items() if c.get("needs_revision")],
            "split_attempts": split_attempts,
            "split_seen": {cid: sum(x["outcome"] == "refute" for x in verdicts[cid].values())
                           for cid in set(rev_meta)},
            "qwen": pool.stats, "model": q["model"]}
    _dump(path, data)
    log(f"round {k}: {sum(map(len, splits.values()))} split claims (from {len(splits)} parents) and "
        f"{len(accepted)} new claims passed the checks")
    return data


def stage_register(store: Store, k: int, props: dict[str, Any]) -> list[dict[str, Any]]:
    _require_prepared_runtime(store.root)
    path = store.round_dir(k) / "preregistered.json"
    if path.exists():
        return _json(path)["claims"]
    claims = store.claims()
    registered = []
    for cid, wrong in props.get("split_seen", {}).items():
        claims[cid]["split_seen_wrong"] = wrong  # next error-triggered split waits for new wrong answers
    for cid in list(props["needs_revision"]) + [c for c in props.get("split_attempts", {}) if c not in props["needs_revision"]]:
        c = claims[cid]
        if cid in props["needs_revision"]:
            c["revisions"] = c.get("revisions", 0) + 1
        for i, d in enumerate(props.get("splits", {}).get(cid, [])):
            nid = store.new_claim_id(claims)
            new = {"id": nid, "version": 1, "status": "candidate", "text": d["text"], "rules": d["rules"],
                   "origin": f"split:{cid}:round_{k}", "parent": {"id": cid, "version": c["version"]},
                   "registered_round": k, "revisions": 0, "needs_revision": False, "stats": None,
                   "rationale": d.get("rationale", ""), "consistency": props["consistency"].get(f"{cid}#{i}")}
            claims[nid] = new
            store.write_version(new)
            registered.append(new)
        draft = props.get("revisions", {}).get(cid)  # proposals written before splits existed
        if draft:
            new = {**c, "version": c["version"] + 1, "status": "candidate", "text": draft["text"], "rules": draft["rules"],
                   "origin": f"revision:round_{k}", "parent": {"id": cid, "version": c["version"]},
                   "registered_round": k, "needs_revision": False, "stats": None,
                   "consistency": props["consistency"].get(cid)}
            claims[cid] = new
            store.write_version(new)
            registered.append(new)
    for i, a in enumerate(props["new"]):
        cid = store.new_claim_id(claims)
        new = {"id": cid, "version": 1, "status": "candidate", "text": a["text"], "rules": a["rules"],
               "origin": f"qwen:round_{k}", "parent": None, "registered_round": k, "revisions": 0,
               "needs_revision": False, "stats": None, "rationale": a.get("rationale", ""),
               "consistency": props["consistency"].get(f"new{i}")}
        claims[cid] = new
        store.write_version(new)
        registered.append(new)
    _dump(path, {"round": k, "claims": registered})
    (store.round_dir(k) / "preregistered.sha256").write_text(sha256_file(path) + "\n")
    store.save_claims(claims)
    log(f"round {k}: registered {len(registered)} claim versions (sha256 {sha256_file(path)[:12]})")
    return registered


def stage_report(store: Store, k: int) -> None:
    _require_prepared_runtime(store.root)
    d = store.round_dir(k)
    built = _built(store, k)
    props = _json(d / "proposals.json")
    reg = _json(d / "preregistered.json")["claims"]
    verified = [c for c in _json(d / "judge.json")["claims"].values() if c["status"] == "verified"]
    info = {
        "build": {"items": len(_json(d / "plan.json")), "ok": sum(r["status"] == "ok" for r in built),
                  "failed": sum(r["status"] != "ok" for r in built),
                  "target": sum(r["status"] == "ok" and r["purpose"] == "target" for r in built),
                  "explore": sum(r["status"] == "ok" and r["purpose"] == "explore" for r in built),
                  "steered": sum(r["status"] == "ok" and r.get("target_hit") is not None for r in built),
                  "target_hit": sum(r["status"] == "ok" and bool(r.get("target_hit")) for r in built)},
        "splits": {"parents": len(set(props.get("needs_revision", [])) | set(props.get("split_attempts", {}))),
                   "registered": sum(str(c["origin"]).startswith("split:") for c in reg)},
        "events": _json(d / "judge.json")["events"],
        "registered": [{"id": c["id"], "version": c["version"], "origin": c["origin"], "text": c["text"],
                        "consistent": (c.get("consistency") or {}).get("consistent", True),
                        "issue": (c.get("consistency") or {}).get("issue", "")} for c in reg],
        "rejections": props["rejections"], "qwen": props["qwen"], "model": props.get("model", "qwen3.5-27b"),
        "preregistered_sha256": (d / "preregistered.sha256").read_text().strip(),
        "ensemble": ensemble.evaluate([r for r in store.records() if r["round"] == k], verified),
        # Target questions are picked so that some claim applies; the random ones show coverage on the main500 mix.
        "ensemble_explore": ensemble.evaluate([r for r in store.records() if r["round"] == k and r["purpose"] == "explore"],
                                              verified),
    }
    report.write_report(d, k, info, store.claims())
    log(f"round {k}: report written ({report.kb_summary(store.claims())})")


def run_round(store: Store, k: int, n_total: int) -> None:
    _require_prepared_runtime(store.root)
    cfg = store.config()
    props = None
    for stage in STAGES:
        if store.done(k, stage):
            continue
        log(f"round {k}: stage {stage}")
        if stage == "plan":
            stage_plan(store, k, n_total, cfg)
        elif stage == "build":
            stage_build(store, k, cfg)
        elif stage == "score":
            stage_score(store, k, cfg)
        elif stage == "judge":
            stage_judge(store, k, cfg)
        elif stage == "propose":
            props = stage_propose(store, k, cfg)
        elif stage == "register":
            stage_register(store, k, props or _json(store.round_dir(k) / "proposals.json"))
        elif stage == "report":
            stage_report(store, k)
        store.mark(k, stage)


def _current_round(store: Store) -> int:
    partial = sorted(int(p.name.split("_")[1]) for p in (store.root / "rounds").glob("round_*")
                     if not (p / "DONE_report").exists()) if (store.root / "rounds").exists() else []
    return partial[0] if partial else store.next_round()


def _round_size(store: Store, k: int, pilot: bool) -> int:
    q = store.config()["questions"]
    return q["pilot_per_round"] if pilot or k == 1 else q["per_round"]


def cmd_round(args: argparse.Namespace) -> None:
    _require_prepared_runtime(args.root)
    store = Store(args.root)
    k = args.round or _current_round(store)
    run_round(store, k, _round_size(store, k, args.pilot))


def cmd_forever(args: argparse.Namespace) -> None:
    _require_prepared_runtime(args.root)
    store = Store(args.root)
    rounds = 0
    failures: Counter = Counter()
    while not (store.root / "STOP").exists() and (args.max_rounds is None or rounds < args.max_rounds):
        k = _current_round(store)
        if args.until_round is not None and k > args.until_round:
            log(f"reached --until-round {args.until_round}")
            break
        try:
            run_round(store, k, _round_size(store, k, False))
            rounds += 1
            failures.clear()
            if args.max_rounds is None:
                # Reload the code between rounds, so a fix deployed mid-round applies from the next one.
                log("re-executing to pick up code changes")
                os.execv(sys.executable, [sys.executable, *sys.argv])
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            stage = next((s for s in STAGES if not store.done(k, s)), "?")
            failures[stage] += 1
            log(f"round {k}: stage {stage} failed ({failures[stage]}/3)\n{tb}")
            if failures[stage] >= 3:
                (store.root / "ALERT").write_text(f"round {k} stage {stage} failed 3 times\n{tb}")
                log("stopping: wrote ALERT")
                return
            if stage == "propose" and args.qwen_restart:
                subprocess.run(args.qwen_restart, shell=True, check=False)
            time.sleep(60)
    log("stopped")


def cmd_status(args: argparse.Namespace) -> None:
    store = Store(args.root)
    claims = store.claims()
    k = _current_round(store)
    stages = [s for s in STAGES if (store.root / "rounds" / f"round_{k:04d}" / f"DONE_{s}").exists()]
    print(json.dumps({"round": k, "stages_done": stages, "kb": report.kb_summary(claims),
                      "questions": len(store.records()), "verdicts": len(store.ledger()),
                      "alert": (store.root / "ALERT").exists()}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--seed-claims", type=Path, required=True)
    p.add_argument("--reference", type=Path, default=None)
    p = sub.add_parser("round")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--round", type=int, default=None)
    p.add_argument("--pilot", action="store_true")
    p = sub.add_parser("run-forever")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--max-rounds", type=int, default=None)
    p.add_argument("--until-round", type=int, default=None, help="stop after this round completes (re-exec still on)")
    p.add_argument("--qwen-restart", default=None, help="shell command that (re)starts the Qwen replicas")
    p = sub.add_parser("status")
    p.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    {"init": cmd_init, "round": cmd_round, "run-forever": cmd_forever, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
