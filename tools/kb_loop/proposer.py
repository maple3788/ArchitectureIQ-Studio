"""Prompts and parsing for the claim proposer (Qwen).

The model only ever sees the loop's own questions: grouped win-rate tables,
the current KB, and examples no verified claim covers. It never sees the v1.5
main500 answers. Every reply must be JSON; the caller checks every claim in
code before anything is registered.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Any

from kb_loop.checks import _leaves
from kb_loop.evidence import strong_comparisons
from kb_loop.qwen import extract_json

SHOW_FIELDS = (
    "model_type", "params", "depth", "width", "residual", "activation", "ln_count", "num_layers", "d_model",
    "d_ff", "num_heads", "layer_residual", "opt", "lr", "momentum", "beta1", "beta2", "weight_decay",
    "batch_size", "steps", "disp", "eff_lr",
)
NUMERIC = ("ln_count", "depth", "width", "params", "lr", "disp", "eff_lr", "per_step", "steps", "batch_size",
           "weight_decay", "beta2", "momentum", "num_layers", "d_model", "d_ff")
BOOLEAN = ("residual", "ln_any", "adaptive", "smooth_activation", "layer_residual")
CATEGORICAL = ("opt", "activation", "model_type")

DSL = """A claim is one or more pairwise rules. A rule compares two candidates A and B trained on the
same dataset instance for the same number of samples, and says which one reaches the better test metric.

Rule JSON:
  {"scope": PRED, "same": [field, ...], "differ": [field, ...], "max_param_ratio": number, "predict": PREDICT}
  - scope: must hold for both candidates (dataset fields such as family/task are shared by both).
  - same / differ: fields that must be equal / different between A and B (optional).
  - max_param_ratio: the rule applies only if larger params / smaller params <= this number (optional).
  PREDICT is exactly one of:
    {"higher_better": field}  or  {"lower_better": field}   (optional "min_ratio": r, both values > 0)
    {"better": PRED, "worse": PRED}        the candidate matching better beats the one matching worse
    {"dominates": [[field, "higher"|"lower"] or [field, "higher"|"lower", min_ratio], ...],
     "winner": PRED, "loser": PRED}        the Pareto-better candidate wins (winner/loser optional)
  PRED: [field, op, value] with op in eq ne lt le gt ge in nin; a list of PREDs means AND;
        {"any": [PRED, ...]}, {"all": [PRED, ...]}, {"not": PRED}.
  A rule abstains on a pair when its conditions do not hold. At most 3 rules and {max_conditions} condition leaves
  per rule.

Fields (candidate): model_type, params (trainable parameters), depth, width, residual, activation,
  smooth_activation (gelu/silu), ln_count / ln_any / ln_all (LayerNorm in hidden layers), num_layers, d_model,
  d_ff, num_heads, layer_residual (transformer), opt, adaptive (not SGD), sign_normalized (Adam/AdamW), lr,
  momentum (SGD only), beta1, beta2, weight_decay, batch_size, steps, budget (samples seen),
  eff_lr (lr/(1-momentum) for SGD, lr otherwise), disp (cumulative step: lr*steps for Adam/AdamW/RMSprop,
  2*lr*sqrt(steps) for Adagrad, null for SGD), per_step, arch_key / opt_key (whole architecture / optimizer
  identity, for same/differ only).
Fields (dataset): family, task (regression/classification/lm), metric, input_dim, rule_family,
  n_active_features, spiral_turns, vocab_size, context_length, train_size, target_abs_mean, target_std,
  target_oscillatory, n_used_inputs (input variables the regression target actually uses), transition_alpha
  (bigram transition-table concentration: lower is peakier, more predictable)."""

QUALITY = """Good claims are leaves of a knowledge tree: narrow and almost never wrong. Add as many explicit
conditions as needed (training setup and dataset fields alike) so that the claim holds on nearly every question
it applies to; a narrow claim that is always right beats a broad one that is often right. Leaves that agree
are merged into broader claims later, so do not stretch a claim beyond where the evidence supports it.
Each claim must still be falsifiable and must not restate an existing claim.
Text: one or two plain English sentences that say exactly what the rule says, no dataset or question ids.
Every question already uses a short budget (256-2048 steps), so do not write "under short budgets" unless the
rule itself constrains steps or budget; do not add causal explanations the rule does not encode."""

DATASET_SPLIT = ("input_dim", "n_used_inputs", "rule_family", "n_active_features", "spiral_turns", "vocab_size",
                 "context_length", "transition_alpha", "target_oscillatory")


def dsl(max_conditions: int = 6) -> str:
    return DSL.replace("{max_conditions}", str(max_conditions))


def compact(view: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k in SHOW_FIELDS:
        v = view.get(k)
        if v is None:
            continue
        out[k] = round(v, 6) if isinstance(v, float) else v
    return out


def win_tables(records: list[dict[str, Any]], min_n: int = 5, min_gap: float = 0.0,
               winner_only: bool = False) -> dict[tuple[str, str], list[str]]:
    """Per (family, question type): how often the candidate with more/less of each field wins."""
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for rec in records:
        views = rec["candidates"]
        for cell in ((rec["family"], rec["type"]), ("*", rec["type"])):  # per family, and pooled over families
            for better, worse in strong_comparisons(rec, min_gap, winner_only):
                b, w = views[better], views[worse]
                for f in NUMERIC + BOOLEAN:
                    vb, vw = b.get(f), w.get(f)
                    if vb is None or vw is None or vb == vw:
                        continue
                    counts[cell][(f, "n")] += 1
                    counts[cell][(f, "higher")] += int(vb > vw)
                for f in CATEGORICAL:
                    vb, vw = b.get(f), w.get(f)
                    if vb is not None and vw is not None and vb != vw:
                        counts[cell][(f, f"{vb}>{vw}")] += 1
    tables = {}
    for cell, c in counts.items():
        lines = []
        for f in NUMERIC + BOOLEAN:
            n = c[(f, "n")]
            if n >= min_n:
                lines.append((abs(c[(f, "higher")] / n - 0.5) * n, f"{f}: higher wins {c[(f, 'higher')]}/{n}"))
        for (f, key), k in c.items():
            if f in CATEGORICAL and ">" in str(key) and k >= min_n:
                lines.append((k, f"{f}: {key} {k} times"))
        tables[cell] = [t for _, t in sorted(lines, reverse=True)[:14]]
    return tables


def dataset_tables(records: list[dict[str, Any]], min_n: int = 8, min_spread: float = 0.2,
                   min_gap: float = 0.0, top: int = 12, winner_only: bool = False) -> dict[tuple[str, str], list[str]]:
    """Per (family, question type): factors whose win rate changes with a dataset field, one line each.

    "lr: higher wins 41/45 (91%) at input_dim=2 | 9/20 (45%) at input_dim=16" says where a leaf's dataset
    condition belongs. Only factors whose rate differs by >= ``min_spread`` between dataset values are shown."""
    counts: dict[tuple, Counter] = defaultdict(Counter)
    for rec in records:
        cell = (rec["family"], rec["type"])
        views = rec["candidates"]
        for better, worse in strong_comparisons(rec, min_gap, winner_only):
            b, w = views[better], views[worse]
            for f in NUMERIC + BOOLEAN:
                vb, vw = b.get(f), w.get(f)
                if vb is None or vw is None or vb == vw:
                    continue
                for d in DATASET_SPLIT:
                    dv = b.get(d)
                    if dv is None:
                        continue
                    counts[(cell, f, d)][(dv, "n")] += 1
                    counts[(cell, f, d)][(dv, "higher")] += int(vb > vw)
    out: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for (cell, f, d), c in counts.items():
        vals = sorted({dv for dv, _ in c}, key=lambda v: (str(type(v)), v))
        rows = [(dv, c[(dv, "higher")], c[(dv, "n")]) for dv in vals if c[(dv, "n")] >= min_n]
        if len(rows) < 2:
            continue
        rates = [k / n for _, k, n in rows]
        spread = max(rates) - min(rates)
        if spread < min_spread:
            continue
        text = " | ".join(f"{k}/{n} ({k / n:.0%}) at {d}={dv}" for dv, k, n in rows)
        out[cell].append((spread * math.sqrt(sum(n for *_, n in rows)), f"{f}: higher wins {text}"))
    return {cell: [t for _, t in sorted(lines, reverse=True)[:top]] for cell, lines in out.items()}


def claim_families(rules: list[dict[str, Any]]) -> set[str] | None:
    """Families the claim's scopes pin it to (family eq / in); None when some rule may apply to any family."""
    fams: set[str] = set()
    for rule in rules:
        named = None
        for field, op, value in _leaves(rule.get("scope")):
            if field == "family" and op == "eq":
                named = {value}
            elif field == "family" and op == "in" and isinstance(value, list):
                named = set(value)
        if named is None:
            return None
        fams |= named
    return fams


def listing_for(claims: dict[str, dict[str, Any]], family: str, evidence: dict[str, int],
                cap: int = 60) -> dict[str, dict[str, Any]]:
    """Claims shown to the proposer for one family: every verified or flagged claim, plus up to ``cap``
    candidates that can apply to the family, most historical evidence first (the full list stops fitting
    in a prompt once candidates pile up)."""
    keep = {cid: c for cid, c in claims.items() if c["status"] in ("verified", "flagged")}
    cands = []
    for cid, c in claims.items():
        if c["status"] != "candidate":
            continue
        try:
            fams = claim_families(c["rules"])
        except Exception:  # noqa: BLE001 -- a malformed scope just stays visible
            fams = None
        if fams is None or family in fams:
            cands.append(cid)
    cands.sort(key=lambda cid: (-evidence.get(cid, 0), cid))
    keep.update({cid: claims[cid] for cid in cands[:cap]})
    return keep


def kb_listing(claims: dict[str, dict[str, Any]]) -> str:
    rows = []
    for cid, c in sorted(claims.items()):
        if c["status"] == "retired":
            continue
        st = c.get("stats") or {}
        rows.append(f"{cid} [{c['status']}, support {st.get('support', '-')}/{st.get('applicable', '-')}] "
                    f"{c['text']}\n  rules: {json.dumps(c['rules'], separators=(',', ':'))}")
    return "\n".join(rows) or "(empty)"


DATASET_FIELDS = ("family", "task", "metric", "input_dim", "rule_family", "n_active_features", "spiral_turns",
                  "vocab_size", "context_length", "train_size", "target_abs_mean", "target_std", "target_oscillatory")


def dataset_line(view: dict[str, Any]) -> str:
    shown = {}
    for k in DATASET_FIELDS:
        v = view.get(k)
        if v is not None:
            shown[k] = round(v, 4) if isinstance(v, float) else v
    return json.dumps(shown, separators=(",", ":"))


def comparison_line(rec: dict[str, Any]) -> str:
    gaps = rec.get("gaps") or [None] * len(rec["comparisons"])
    def fmt(g: float | None) -> str:
        if g is None:
            return ""
        return f" by {g:.0%}" if g < 1 else f" (loser's loss {1 + g:.1f}x the winner's)"

    return "; ".join(f"{b} beats {w}{fmt(g)}" for (b, w), g in zip(rec["comparisons"], gaps))


def question_example(rec: dict[str, Any]) -> str:
    views = rec["candidates"]
    ids = sorted(views)
    lines = [f"type={rec['type']} winner={rec['winner']} dataset={dataset_line(views[ids[0]])}"]
    for cid in ids:
        lines.append(f"  {cid}: {json.dumps(compact(views[cid]), separators=(',', ':'))}")
    lines.append(f"  results (seed-separated, gap = relative loss difference): {comparison_line(rec)}")
    return "\n".join(lines)


def proposal_messages(cell: tuple[str, str], table: list[str], claims: dict[str, dict[str, Any]],
                      uncovered: list[dict[str, Any]], reference: list[str],
                      pooled: list[str] | None = None, by_dataset: list[str] | None = None,
                      max_conditions: int = 6) -> list[dict[str, str]]:
    family, qtype = cell
    parts = [
        "You study which neural-network training setups win under short, fixed training budgets.",
        f"Focus: dataset family {family}, question type {qtype}.",
        dsl(max_conditions), QUALITY,
        "Win rates on this focus (winner vs loser; only comparisons whose 10-seed ranges fully separate and whose options differ widely; "
        "a claim is judged on all counted comparisons; each counted prediction must be correct):",
        "\n".join(table) or "(not enough data yet)",
        f"Win rates for {qtype} questions pooled over all families:",
        "\n".join(pooled or []) or "(not enough data yet)",
        "Where a dataset field changes the picture on this focus (same comparisons, split by dataset value):",
        "\n".join(by_dataset or []) or "(no clear dataset dependence yet)",
        "Current knowledge base (do not repeat these):", kb_listing(claims),
        "Questions no verified claim covers yet:", "\n\n".join(question_example(r) for r in uncovered) or "(none)",
    ]
    if reference:
        parts += ["Earlier unverified propositions you may draw on (they can be wrong):", "\n".join(reference)]
    parts.append('Propose up to 3 new claims. Reply with JSON only: '
                 '{"claims": [{"text": "...", "rules": [...], "rationale": "..."}]}')
    return [{"role": "user", "content": "\n\n".join(parts)}]


def revision_messages(claim: dict[str, Any], refuted: list[dict[str, Any]], supported: list[dict[str, Any]],
                      verdicts: dict[str, dict[str, Any]], conditions: list[str] | None = None,
                      min_applicable: int = 20, min_rate: float = 0.85,
                      max_conditions: int = 6) -> list[dict[str, str]]:
    def show(rec: dict[str, Any]) -> str:
        pairs = verdicts.get(rec["question_id"], {}).get("pairs", [])
        marks = "; ".join(f"predicted {'right' if ok else 'WRONG'} on {b} beats {w}" for b, w, ok in pairs)
        return question_example(rec) + f"\n  claim: {marks}"

    parts = [
        "You maintain a structured claim about neural-network training under short, fixed budgets.",
        dsl(max_conditions), QUALITY,
        f"Claim {claim['id']} v{claim['version']}: {claim['text']}",
        f"Rules: {json.dumps(claim['rules'])}",
        f"Over ALL {len(verdicts)} historical questions it applies to "
        f"({sum(v['outcome'] == 'support' for v in verdicts.values())} right, "
        f"{sum(v['outcome'] == 'refute' for v in verdicts.values())} wrong), how often its pairwise predictions were "
        "right under simple conditions on the compared pair (your revision is checked against all of them):",
        "\n".join(conditions or []) or "(not computed)",
        "Examples where it was WRONG (sampled across dataset families and question types):",
        "\n\n".join(show(r) for r in refuted),
        "Examples where it was right:",
        "\n\n".join(show(r) for r in supported) or "(none)",
        "Split it into narrower claims. Propose up to 3 claims, each covering a part of the space where this "
        "mechanism really holds (use the condition table to find those parts). Each is accepted on its own if, on all "
        f"historical questions it applies to, its support rate is at least {min_rate:.0%} and it applies to at least {min_applicable} "
        "of them; they must not restate each other. Do not add conditions that only carve out the listed examples. "
        'Reply with JSON only: {"claims": [{"text": "...", "rules": [...], "rationale": "..."}]}',
    ]
    return [{"role": "user", "content": "\n\n".join(parts)}]


def consistency_messages(text: str, rules: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"role": "user", "content": "\n\n".join([
        dsl(10),
        f"Claim text: {text}", f"Rules: {json.dumps(rules)}",
        "Does the text say exactly what the rules say, no more and no less? "
        'Reply with JSON only: {"consistent": true|false, "issue": "..."}',
    ])}]


def parse_proposals(reply: str) -> list[dict[str, Any]]:
    data = extract_json(reply)
    items = data.get("claims", []) if isinstance(data, dict) else data
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("text"), str) and isinstance(it.get("rules"), list):
            out.append({"text": it["text"].strip(), "rules": it["rules"], "rationale": str(it.get("rationale", ""))})
    return out


def parse_revision(reply: str) -> dict[str, Any]:
    data = extract_json(reply)
    if not (isinstance(data, dict) and isinstance(data.get("text"), str) and isinstance(data.get("rules"), list)):
        raise ValueError("revision reply needs text and rules")
    return {"text": data["text"].strip(), "rules": data["rules"], "rationale": str(data.get("rationale", ""))}


def parse_consistency(reply: str) -> dict[str, Any]:
    data = extract_json(reply)
    return {"consistent": bool(data.get("consistent")), "issue": str(data.get("issue", ""))}
