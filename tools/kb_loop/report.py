"""Per-round report (Markdown + JSON) and the running KB summary."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def kb_summary(claims: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter(c["status"] for c in claims.values())
    return {"claims": len(claims), **{s: by_status.get(s, 0) for s in ("candidate", "verified", "flagged", "retired")}}


def ensemble_line(e: dict[str, Any] | None, what: str = "this round's questions") -> str:
    if not e or not e.get("questions"):
        return "(no questions)"
    acc = f"{e['accuracy']:.0%}" if e["accuracy"] is not None else "-"
    return (f"{e['claims']} verified claims answered {e['answered']}/{e['questions']} of {what} "
            f"({e['coverage']:.0%}); right on {e['correct']} ({acc} of answered, {e['overall']:.0%} of all).")


def write_report(round_dir: Path, round_no: int, info: dict[str, Any], claims: dict[str, dict[str, Any]]) -> None:
    summary = kb_summary(claims)
    data = {"round": round_no, "kb": summary, **info}
    (round_dir / "report.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    b = info.get("build", {})
    lines = [
        f"# KB loop round {round_no}",
        "",
        f"Questions: {b.get('ok', 0)} built of {b.get('items', 0)} planned "
        f"({b.get('target', 0)} targeted, {b.get('explore', 0)} explore; {b.get('failed', 0)} datasets without a valid question).",
        f"KB: {summary['verified']} verified, {summary['candidate']} candidate, {summary['flagged']} flagged, "
        f"{summary['retired']} retired.",
        *([f"Targeted questions the target claim applies to: {b['target_hit']}/{b['steered']}."] if b.get("steered") else []),
        *([f"Split attempts: {info['splits']['parents']} claims, {info['splits']['registered']} narrower claims registered."]
          if info.get("splits") else []),
        "",
        "## KB answering together (verified claims vote on every pair; most pairwise wins answers; ties abstain)",
        "",
        ensemble_line(info.get("ensemble")),
        *([ensemble_line(info["ensemble_explore"], "the random (explore) questions")] if info.get("ensemble_explore") else []),
        "",
        "## Status changes",
        "",
        "| claim | version | from | to | support / applicable | lower bound |",
        "|---|---|---|---|---|---|",
    ]
    for e in info.get("events", []):
        lines.append(f"| {e['claim_id']} | {e['version']} | {e['from']} | {e['to']}"
                     f"{' (revise)' if e.get('needs_revision') else ''} | {e['support']}/{e['applicable']} | "
                     f"{e['lower_bound']:.2f} |")
    lines += ["", "## Registered this round", ""]
    for r in info.get("registered", []):
        flag = "" if r.get("consistent", True) else f"  [text check: {r.get('issue', '')}]"
        lines.append(f"- {r['id']} v{r['version']} ({r['origin']}): {r['text']}{flag}")
    rej = info.get("rejections", Counter())
    lines += ["", "## Rejected by checks", ""]
    for reason, n in sorted(dict(rej).items(), key=lambda x: -x[1])[:20]:
        lines.append(f"- {n} x {reason}")
    q = info.get("qwen", {})
    lines += ["", f"Proposer {info.get('model', 'qwen3.5-27b')}: {q.get('calls', 0)} calls, {q.get('cached', 0)} cached, "
              f"{q.get('errors', 0)} errors, {q.get('failovers', 0)} failovers."]
    (round_dir / "report.md").write_text("\n".join(lines) + "\n")
