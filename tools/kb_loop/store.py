"""On-disk state of one loop directory.

<root>/config.yaml           frozen copy of configs/kb_loop/loop_vN.yaml
<root>/claims.json           current version of every claim, keyed by claim id
<root>/claim_versions.jsonl  every claim version ever written (append-only)
<root>/ledger.jsonl          one verdict per (claim version, applicable question) (append-only)
<root>/records.jsonl         public evidence record of every question the loop produced (append-only)
<root>/rounds/round_NNNN/    frozen per-round artifacts and DONE_<stage> markers

A claim version registered at the end of round k is judged only on questions
from rounds > k: those questions did not exist when it was written.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator

import yaml

STATUSES = ("candidate", "verified", "flagged", "retired")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _append(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------- layout
    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    def config(self) -> dict[str, Any]:
        return yaml.safe_load(self.config_path.read_text())

    def round_dir(self, k: int) -> Path:
        d = self.root / "rounds" / f"round_{k:04d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rounds_done(self) -> list[int]:
        return sorted(int(p.parent.name.split("_")[1]) for p in (self.root / "rounds").glob("round_*/DONE_report"))

    def next_round(self) -> int:
        done = self.rounds_done()
        return (done[-1] + 1) if done else 1

    def done(self, k: int, stage: str) -> bool:
        return (self.round_dir(k) / f"DONE_{stage}").exists()

    def mark(self, k: int, stage: str) -> None:
        (self.round_dir(k) / f"DONE_{stage}").write_text("")

    # ------------------------------------------------------------- claims
    def claims(self) -> dict[str, dict[str, Any]]:
        p = self.root / "claims.json"
        return json.loads(p.read_text())["claims"] if p.exists() else {}

    def save_claims(self, claims: dict[str, dict[str, Any]]) -> None:
        _atomic_write(self.root / "claims.json", json.dumps({"claims": claims}, indent=1, sort_keys=True) + "\n")

    def write_version(self, claim: dict[str, Any]) -> None:
        _append(self.root / "claim_versions.jsonl", [claim])

    def versions(self) -> list[dict[str, Any]]:
        return list(_read_jsonl(self.root / "claim_versions.jsonl"))

    def new_claim_id(self, claims: dict[str, dict[str, Any]]) -> str:
        used = {int(c[1:]) for c in claims if c.startswith("C") and c[1:].isdigit()}
        used |= {int(v["id"][1:]) for v in self.versions() if v["id"][1:].isdigit()}
        return f"C{(max(used) + 1) if used else 1:04d}"

    # ------------------------------------------------------------- evidence
    def add_records(self, records: list[dict[str, Any]]) -> None:
        seen = {r["question_id"] for r in self.records()}
        _append(self.root / "records.jsonl", [r for r in records if r["question_id"] not in seen])

    def records(self) -> list[dict[str, Any]]:
        return list(_read_jsonl(self.root / "records.jsonl"))

    def add_ledger(self, rows: list[dict[str, Any]]) -> None:
        _append(self.root / "ledger.jsonl", rows)

    def ledger(self) -> list[dict[str, Any]]:
        return list(_read_jsonl(self.root / "ledger.jsonl"))
