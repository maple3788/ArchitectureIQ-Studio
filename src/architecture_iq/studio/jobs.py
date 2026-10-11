"""Immutable job definitions, durable events and at-most-once attempt records."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from architecture_iq.kb.roles import exclusive_lock
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from .models import IDENTIFIER
from .events import attribution, stage_event


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def source_fingerprint() -> str:
    repo = Path(__file__).resolve().parents[3]
    files = [
        *repo.joinpath("src").rglob("*.py"),
        *repo.joinpath("prompts/templates").rglob("*.md"),
        *repo.joinpath("profiles").glob("*.yaml"),
        *repo.joinpath("tools").rglob("*.py"),
        *repo.joinpath("services/kb_workflow_api").rglob("*.py"),
    ]
    return canonical_hash(
        {
            str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)
            if p.is_file()
        }
    )


def process_stamp(pid: int) -> str | None:
    try:
        os.kill(pid, 0)
        if sys.platform.startswith("linux"):
            fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
            return None if fields[0] == "Z" else fields[19]
        return str(pid)
    except (OSError, IndexError):
        return None


class JobStore:
    def __init__(self, root: Path):
        self.state_root = Path(root).resolve()
        self.root = self.state_root / "runs"
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, identifier: str) -> Path:
        if not IDENTIFIER.fullmatch(identifier):
            raise ValueError("无效运行 ID")
        return self.root / identifier

    def create(
        self, kind: str, config: dict, *, idempotency_key: str | None = None
    ) -> dict:
        if kind not in {"evaluation", "workflow", "generation", "archive", "rag", "rule_refinement", "rule_evaluation"}:
            raise ValueError("未知任务类型")
        fingerprint = canonical_hash({"kind": kind, "config": config})
        with exclusive_lock(self.root / ".create.lock"):
            index = (
                self.root / "idempotency" / (canonical_hash(idempotency_key) + ".json")
                if idempotency_key
                else None
            )
            if index and index.exists():
                saved = read(index)
                if saved["fingerprint"] != fingerprint:
                    raise ValueError("相同请求标识对应不同配置")
                return self.get(saved["id"])
            identifier = "run_" + uuid.uuid4().hex[:16]
            directory = self.directory(identifier)
            definition = {
                "id": identifier,
                "kind": kind,
                "config": config,
                "created_at": time.time(),
                "source_fingerprint": source_fingerprint(),
            }
            definition["definition_hash"] = canonical_hash(definition)
            write_json_atomic(directory / "definition.json", definition)
            write_json_atomic(
                directory / "state.json",
                {
                    "status": "queued",
                    "updated_at": time.time(),
                    "progress": {},
                    "error": None,
                },
            )
            if index:
                write_json_atomic(index, {"id": identifier, "fingerprint": fingerprint})
        self.event(identifier, {"type": "queued", "message": "配置已冻结，等待执行"})
        return self.get(identifier)

    def definition(self, identifier: str) -> dict:
        definition = read(self.directory(identifier) / "definition.json")
        if definition["definition_hash"] != canonical_hash(
            {k: v for k, v in definition.items() if k != "definition_hash"}
        ):
            raise ValueError("Job definition integrity failure")
        return definition

    def get(self, identifier: str, *, full: bool = True) -> dict:
        directory = self.directory(identifier)
        result = {**self.definition(identifier), **read(directory / "state.json")}
        if result["status"] in {"starting", "running", "paused", "waiting_round"} and result.get("pid"):
            stamp = process_stamp(result["pid"])
            if stamp is None or (
                result.get("process_stamp") and stamp != result["process_stamp"]
            ):
                with exclusive_lock(directory / ".state.lock"):
                    current = read(directory / "state.json")
                    if (
                        current["status"] in {"starting", "running", "paused", "waiting_round"}
                        and current.get("pid") == result["pid"]
                    ):
                        pending = any(
                            read(p)["status"] in {"pending", "uncertain"}
                            for p in (directory / "records").glob("*.json")
                        )
                        current.update(
                            status="uncertain" if pending else "interrupted",
                            error="工作进程已退出；保留原始收据，禁止自动重试",
                            updated_at=time.time(),
                        )
                        write_json_atomic(directory / "state.json", current)
                    result.update(current)
        if (directory / "control.json").exists():
            result["control"] = read(directory / "control.json")
        if result.get("round_decision_index") is not None:
            path = directory / "round_decisions" / f"{result['round_decision_index']}.json"
            if path.exists():
                result["round_decision"] = read(path)
        if full:
            result["events"] = self.events(identifier)
            result["records"] = [
                read(path) for path in sorted((directory / "records").glob("*.json"))
            ]
            if (directory / "result.json").exists():
                result["result"] = read(directory / "result.json")
        return result

    def list(self) -> list[dict]:
        result = [
            self.get(path.parent.name, full=False)
            for path in self.root.glob("*/definition.json")
        ]
        return sorted(result, key=lambda value: value["created_at"], reverse=True)

    def update(self, identifier: str, **values) -> None:
        directory = self.directory(identifier)
        with exclusive_lock(directory / ".state.lock"):
            old = read(directory / "state.json")
            write_json_atomic(
                directory / "state.json", {**old, **values, "updated_at": time.time()}
            )

    def event(self, identifier: str, value: dict) -> None:
        directory = self.directory(identifier)
        with exclusive_lock(directory / ".events.lock"):
            path = directory / "events.jsonl"
            previous = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
            sequence = max([len(previous), *(event.get("sequence", 0) for event in previous)]) + 1
            value = stage_event(identifier, sequence, value)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {"time": time.time(), **value},
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())

    def events(self, identifier: str) -> list[dict]:
        path = self.directory(identifier) / "events.jsonl"
        if not path.exists():
            return []
        with exclusive_lock(self.directory(identifier) / ".events.lock"):
            return [
                json.loads(line)
                for line in path.read_text().splitlines()
                if line.strip()
            ]

    def append_stream(self, identifier: str, key: str, metadata: dict, value: dict) -> dict:
        """Publish a provider frame only after its independent journal is durable.

        This never seals a call or an answer. A transport [DONE] event is still
        provisional until the existing role/evaluation completion checks pass.
        """
        directory = self.directory(identifier)
        with exclusive_lock(directory / ".stream.lock"):
            record = read(self.record_path(identifier, key))
            if record["status"] != "pending":
                raise ValueError("Only a reserved pending call can append stream frames")
            path = directory / "stream.jsonl"
            previous = 0
            if path.exists() and path.stat().st_size:
                with path.open("rb") as stream:
                    end = stream.seek(0, os.SEEK_END)
                    size = min(8192, end)
                    while True:
                        stream.seek(end - size)
                        tail = stream.read(size)
                        if not tail.endswith(b"\n"):
                            raise ValueError("Incomplete stream journal; do not retry the call")
                        if b"\n" in tail[:-1] or size == end:
                            previous = json.loads(tail[:-1].rsplit(b"\n", 1)[-1])["seq"]
                            break
                        size = min(end, size * 2)
            allowed = {"node_id", "round_index", "operation_key", "arm", "model_id", "question_key", "stage_id", "step_id", "item_id", "attempt_id", "role"}
            event = {**{k: v for k, v in metadata.items() if k in allowed},
                     **{k: v for k, v in value.items() if k in {"kind", "chunk", "data"}},
                     "seq": previous + 1, "stream_sequence": previous + 1, "time": time.time(), "wire_key": key,
                     **attribution(identifier, metadata, attempt_id=key)}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            # A newly created journal must also have a durable directory entry.
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def stream_events(self, identifier: str, *, after: int = 0, limit: int = 200) -> list[dict]:
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid stream cursor or page size")
        path = self.directory(identifier) / "stream.jsonl"
        if not path.exists():
            return []
        events = []
        with exclusive_lock(path.parent / ".stream.lock"):
            with path.open("rb") as stream:
                for line in stream:
                    if not line.endswith(b"\n"):
                        break  # A crash tail is not a complete durable event.
                    value = json.loads(line)
                    if value["seq"] > after:
                        events.append(value)
                        if len(events) == limit:
                            break
        return events

    def control(self, identifier: str, action: str) -> None:
        if action not in {"pause", "resume"}:
            raise ValueError("未知控制操作")
        state = self.get(identifier, full=False)
        if state["status"] in {"complete", "failed", "uncertain", "interrupted"}:
            raise ValueError("已结束或状态不确定的任务不能自动恢复；请查看原始记录")
        write_json_atomic(
            self.directory(identifier) / "control.json",
            {"action": action, "time": time.time()},
        )
        self.event(identifier, {"type": "control", "action": action})

    def boundary(self, identifier: str, event: dict | None = None) -> None:
        directory = self.directory(identifier)
        control = directory / "control.json"
        if event:
            self.event(identifier, {"type": "stage", **event})
            self.update(identifier, progress=event)
        announced = False
        while control.exists() and read(control)["action"] == "pause":
            if not announced:
                self.update(identifier, status="paused")
                self.event(
                    identifier, {"type": "paused", "message": "已在安全边界暂停"}
                )
                announced = True
            time.sleep(0.25)
        if announced:
            decision = self.get(identifier, full=False).get("round_decision", {})
            self.update(identifier, status="waiting_round" if decision.get("status") in {"waiting", "decided"} else "running")
            self.event(identifier, {"type": "resumed"})

    def offer_round_decision(self, identifier: str, *, round_index: int, kb_version: str,
                             next_round_index: int | None, next_question_ids: list[str],
                             next_round_reason: str | None, evaluate_available: bool) -> dict:
        """Called by the worker only after the coordinator seals its result."""
        directory = self.directory(identifier)
        path = directory / "round_decisions" / f"{round_index}.json"
        available = ["finish"]
        if next_round_index is not None and next_question_ids and next_round_reason is None:
            available.insert(0, "continue")
        if evaluate_available:
            available.append("evaluate")
        offer = {"round_index": round_index, "kb_version": kb_version,
                 "available_actions": available, "next_round_available": "continue" in available,
                 "next_round_index": next_round_index, "next_question_ids": next_question_ids,
                 "next_round_reason": next_round_reason, "status": "waiting"}
        with exclusive_lock(directory / ".round_decisions.lock"):
            if path.exists():
                saved = read(path)
                if any(saved.get(key) != value for key, value in offer.items() if key != "status"):
                    raise RuntimeError("Round decision inputs changed")
                if saved["status"] in {"waiting", "decided"}:
                    self.update(identifier, status="waiting_round", round_decision_index=round_index)
                return saved
            write_json_atomic(path, offer)
            self.update(identifier, status="waiting_round", round_decision_index=round_index)
            self.event(identifier, {"type": "round_waiting", "node_id": "loop", **offer})
        return offer

    def decide_round(self, identifier: str, *, round_index: int, action: str) -> dict:
        if type(round_index) is not int or round_index < 1 or not isinstance(action, str) or action not in {"continue", "finish", "evaluate"}:
            raise ValueError("Invalid round decision")
        directory = self.directory(identifier)
        with exclusive_lock(directory / ".round_decisions.lock"):
            state = self.get(identifier, full=False)
            if state.get("round_decision_index") != round_index:
                raise RuntimeError("Round decision is stale")
            path = directory / "round_decisions" / f"{round_index}.json"
            decision = read(path)
            if decision.get("action"):
                if decision["action"] != action:
                    raise RuntimeError("Round decision conflict")
                return decision
            if state["status"] not in {"waiting_round", "paused"}:
                raise RuntimeError("Run is not waiting for a round decision")
            if action not in decision["available_actions"]:
                raise RuntimeError("Round action is not available")
            decision.update(action=action, status="decided", decided_at=time.time())
            write_json_atomic(path, decision)
            self.event(identifier, {"type": "round_decided", "node_id": "loop", "round_index": round_index,
                                    "action": action, "kb_version": decision["kb_version"]})
            return decision

    def consume_round_decision(self, identifier: str, *, round_index: int) -> dict | None:
        directory = self.directory(identifier)
        with exclusive_lock(directory / ".round_decisions.lock"):
            path = directory / "round_decisions" / f"{round_index}.json"
            decision = read(path)
            if decision["status"] != "decided":
                return None
            control = directory / "control.json"
            if control.exists() and read(control)["action"] == "pause":
                return None
            decision.update(status="consumed", consumed_at=time.time())
            write_json_atomic(path, decision)
            self.update(identifier, status="running")
            return decision

    def wait_round_decision(self, identifier: str, *, round_index: int, timeout: float = 1.0) -> dict | None:
        """A bounded poll, outside run_round and its wall-time budget."""
        if not 0 <= timeout <= 60:
            raise ValueError("Round decision poll must be finite (0..60 seconds)")
        deadline = time.monotonic() + timeout
        while True:
            decision = self.consume_round_decision(identifier, round_index=round_index)
            if decision is not None:
                return decision
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.25, remaining))

    def record_path(self, identifier: str, key: str) -> Path:
        return self.directory(identifier) / "records" / (canonical_hash(key) + ".json")

    def reserve(self, identifier: str, key: str, inputs: dict) -> dict | None:
        path = self.record_path(identifier, key)
        with exclusive_lock(self.directory(identifier) / ".records.lock"):
            if path.exists():
                existing = read(path)
                if existing["input_hash"] != canonical_hash(inputs):
                    raise ValueError("Attempt inputs changed")
                if existing["status"] not in {"complete", "invalid"}:
                    raise RuntimeError(
                        "Attempt pending/uncertain; never repeat automatically"
                    )
                return existing
            write_json_atomic(
                path,
                {
                    "key": key,
                    "input_hash": canonical_hash(inputs),
                    "inputs": inputs,
                    "status": "pending",
                    "created_at": time.time(),
                },
            )
        return None

    def update_record(self, identifier: str, key: str, values: dict) -> None:
        path = self.record_path(identifier, key)
        with exclusive_lock(self.directory(identifier) / ".records.lock"):
            write_json_atomic(path, {**read(path), **values})

    def finish(self, identifier: str, key: str, values: dict) -> None:
        self.update_record(identifier, key, {**values, "completed_at": time.time()})

    def launch(self, identifier: str) -> int:
        self.definition(identifier)
        directory = self.directory(identifier)
        with exclusive_lock(directory / ".launch.lock"):
            state = read(directory / "state.json")
            if state["status"] != "queued":
                raise ValueError("任务已经启动；不能重复提交")
            repo = Path(__file__).resolve().parents[3]
            env = {
                **os.environ,
                "PYTHONPATH": str(repo / "src") + os.pathsep + str(repo),
            }
            self.update(identifier, status="starting")
            try:
                with (directory / "worker.log").open("ab") as log:
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "architecture_iq.studio.execution",
                            "--state",
                            str(self.state_root),
                            "--run",
                            identifier,
                        ],
                        cwd=repo,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                self.update(identifier, pid=proc.pid)
            except Exception as exc:
                self.update(identifier, status="failed", error=str(exc))
                raise
        return proc.pid
