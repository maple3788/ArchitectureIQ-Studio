"""Server-only durable workers using the existing scientific and LLM pipeline."""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import json
import os
import time
from pathlib import Path

from architecture_iq.kb.evaluation import score_evaluation
from architecture_iq.kb.orchestrator import _answer, _knowledge
from architecture_iq.kb.roles import (
    exclusive_lock,
    parse_json_response,
    read_receipt,
    role_prompt,
)
from architecture_iq.kb.store import KBStore, canonical_hash, write_json_atomic
from .jobs import JobStore
from .events import attribution
from .models import api_identity, model_config, read_credential


def _tools():
    from tools.llm_eval.llm_client import LLMClient, ModelConfig, build_request_payload

    return LLMClient, ModelConfig, build_request_payload


def _notes(config: dict, question: dict) -> list[dict]:
    if config.get("kb_condition", "clean") == "clean":
        return []
    snapshot = config.get("kb_snapshot")
    if not snapshot:
        raise ValueError("Selected KB condition requires a frozen KB snapshot")
    return _knowledge(
        question, snapshot["claims"], legacy=config["kb_condition"] == "legacy"
    )


def preview_evaluation(config: dict) -> dict:
    _, ModelConfig, builder = _tools()
    questions = config["question_set"]["questions"]
    if config["question_set"].get("pairs"):
        from architecture_iq.kb.pair_learning import validate_pair_manifest
        validate_pair_manifest(questions, config["question_set"]["pairs"], require_discovery=False)
    models = config["models"]
    if not questions or not models:
        raise ValueError("Choose a nonempty question set and model list")
    if len({q["id"] for q in questions}) != len(questions) or len(
        {m["id"] for m in models}
    ) != len(models):
        raise ValueError("Duplicate question/model selection")
    basic = config.get("method", {}).get("id") == "basic_learning"
    if basic:
        from .workflow import compile_workflow
        from architecture_iq.kb.experience import initial_experience_snapshot
        from architecture_iq.kb.orchestrator import _memory_payload, _initial_experience_payload
        practice_config = compile_workflow(config["workflow"])["config"]
        if config.get("initial_kb"):
            from architecture_iq.kb.initial_knowledge import validate_initial_knowledge
            practice_config["initial_kb"] = validate_initial_knowledge(config["initial_kb"])
    requests = []
    total_reserve = 0
    for model in models:
        for question in questions:
            notes = _notes(config, question)
            if basic and config.get("initial_kb", {}).get("kind") == "formal":
                notes = _knowledge(question, config["initial_kb"]["snapshot"]["claims"])
            payload = {"question": question, "knowledge": notes}
            if basic:
                frozen = {**practice_config, "model": model_config(model)}
                payload = _initial_experience_payload(payload, frozen)
            if basic and practice_config["use_previous_experience"]:
                frozen = {**frozen, "experience_byte_budget": max(0, frozen.get("experience_byte_budget", 6000)
                               - payload.get("initial_experience", {}).get("content_bytes", 0))}
                payload["experience"] = _memory_payload(question, initial_experience_snapshot(), frozen,
                                                         role="solver", payload=payload)
            prompt = role_prompt(
                "solver",
                payload,
                instruction=config.get("prompt") or None,
            )
            messages = [{"role": "user", "content": prompt}]
            reserve = len(prompt.encode()) + model["parameters"]["max_tokens"] + 256
            if reserve > model.get("context_size", 32768):
                raise ValueError(
                    f"题目 {question['id']} 超出模型 {model['id']} 的保守上下文预算"
                )
            total_reserve += reserve
            requests.append(
                {
                    "question_key": question["id"],
                    "model_id": model["id"],
                    "model_revision": model["revision"],
                    "url": model["base_url"] + "/chat/completions",
                    "payload": builder(messages, ModelConfig(**model_config(model)), stream=config.get("transport", {}).get("stream", False)),
                    "reserved_tokens": reserve,
                    "knowledge": notes,
                    **({"experience": payload["experience"]} if "experience" in payload else {}),
                    **({"initial_experience": payload["initial_experience"]} if "initial_experience" in payload else {}),
                }
            )
    if len(requests) > config.get("max_calls", 1000) or total_reserve > config.get(
        "max_tokens", 20_000_000
    ):
        raise ValueError(
            f"Preflight budget insufficient: {len(requests)} calls / {total_reserve} reserved tokens"
        )
    return {
        "kind": "evaluation",
        "request_count": len(requests),
        "reserved_tokens": total_reserve,
        "question_count": len(questions),
        "model_count": len(models),
        "requests": requests,
        "sent": False,
        "kb_condition": config.get("kb_condition", "clean"),
    }


def create_client(profile: dict, observer, *, stream: bool = False, chunk_observer=None, credential_root: Path | None = None):
    LLMClient, _, _ = _tools()
    credential = read_credential(profile, credential_root)
    client = LLMClient(
        base_url=profile["base_url"],
        api_key=credential,
        timeout_s=900,
        max_retries=0,
        request_observer=observer,
        stream=stream,
        chunk_observer=chunk_observer,
        allow_model_alias=profile.get("connection_type") == "api",
    )
    # Providers can echo authorization values in error bodies; never journal them.
    original_conversation = client.complete_conversation
    def redact(value):
        if isinstance(value, str):
            return value.replace(credential, "[redacted]").replace(json.dumps(credential)[1:-1], "[redacted]")
        if isinstance(value, dict):
            return {redact(key): redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    def safe_conversation(*args, **kwargs):
        # Wrap the current observers at the call boundary, including callbacks
        # attached by evaluation after client construction.
        request_observer, chunk_observer = client.request_observer, client.chunk_observer
        client.request_observer = (lambda wire: request_observer(redact(wire))) if request_observer else None
        pending = {}
        def safe_frame(frame):
            value = redact(frame)
            chunk = value.get("chunk")
            if isinstance(chunk, dict) and isinstance(chunk.get("choices"), list):
                for choice in chunk["choices"]:
                    if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                        continue
                    delta = choice.setdefault("delta", {})
                    for field in ("content", "reasoning_content", "reasoning", "thought", "thinking"):
                        key = (choice.get("index", 0), field)
                        text = delta.get(field, "")
                        if not isinstance(text, str):
                            continue
                        buffered = redact(pending.pop(key, "") + text)
                        held = 0
                        if choice.get("finish_reason") is None:
                            # Delay only a suffix which could complete the key in
                            # the next delta; a finished response flushes safe text.
                            for token in {credential, json.dumps(credential)[1:-1]}:
                                for size in range(min(len(buffered), len(token) - 1), 0, -1):
                                    if buffered.endswith(token[:size]):
                                        held = max(held, size)
                                        break
                        if held:
                            pending[key] = buffered[-held:]
                        if field in delta or buffered:
                            delta[field] = buffered[:-held] if held else buffered
                # Do not persist the unsanitized serialized copy of a delta.
                value["data"] = json.dumps(chunk, ensure_ascii=False)
            chunk_observer(value)
        client.chunk_observer = safe_frame if chunk_observer else None
        try:
            response = original_conversation(*args, **kwargs)
            return replace(response, content=redact(response.content), raw=redact(response.raw))
        except Exception as exc:
            raise RuntimeError(redact(str(exc))) from None
        finally:
            client.request_observer, client.chunk_observer = request_observer, chunk_observer
    client.complete_conversation = safe_conversation
    if profile.get("runtime_lock_path"):
        from architecture_iq.kb.cli import verify_live_runtime

        lock = json.loads(Path(profile["runtime_lock_path"]).read_text())
        if canonical_hash(lock) != profile.get("runtime_fingerprint"):
            raise ValueError("Frozen runtime lock fingerprint changed or is missing")
        frozen = {
            "model": lock["model_parameters"],
            "runtime_fingerprint": profile["runtime_fingerprint"],
        }
        if lock["model_id"] != profile["model"]:
            raise ValueError("Model identity differs from selected runtime lock")
        client.verify_runtime = lambda: verify_live_runtime(
            Path(profile["runtime_lock_path"]), frozen, profile["base_url"]
        )
    return client


def execute_evaluation(
    store: JobStore, identifier: str, config: dict, *, client_factory=create_client
) -> dict:
    preview = preview_evaluation(config)
    _, ModelConfig, _ = _tools()
    questions = config["question_set"]["questions"]
    private = config["question_set"]["feedback"]
    lookup = {q["id"]: q for q in questions}
    profiles = {m["id"]: m for m in config["models"]}
    outputs = {m["id"]: {} for m in config["models"]}
    started = time.time()
    total_tokens = 0
    for index, request in enumerate(preview["requests"]):
        qid, mid = request["question_key"], request["model_id"]
        key = qid + ":" + mid
        store.boundary(
            identifier,
            {
                "node_id": "solver",
                "completed": index,
                "total": preview["request_count"],
                "question_key": qid,
                "model_id": mid,
            },
        )
        existing = store.reserve(identifier, key, request)
        if existing:
            outputs[mid][qid] = existing["answer"]
            total_tokens += existing.get("charged_tokens", 0)
            continue
        call_started = time.time()
        try:
            client = client_factory(
                profiles[mid],
                lambda wire: store.update_record(
                    identifier, key, {"actual_request": wire, "sent_at": time.time()}
                ),
                **({"credential_root": store.state_root / "credentials"}
                   if profiles[mid].get("connection_type") == "api" else {}),
            )
            client.stream = config.get("transport", {}).get("stream", False)
            client.chunk_observer = lambda value: store.append_stream(
                identifier, key,
                {"node_id": "solver", "round_index": 0, "operation_key": qid,
                 "question_key": qid, "model_id": mid}, value,
            )
            verifier = getattr(client, "verify_runtime", None)
            if verifier:
                verifier()
            response = client.complete_conversation(
                request["payload"]["messages"],
                ModelConfig(**model_config(profiles[mid])),
            )
            store.update_record(
                identifier,
                key,
                {
                    "raw": response.raw,
                    "finish_reason": response.finish_reason,
                    "usage": response.usage,
                    "response_received_at": time.time(),
                },
            )
            if verifier:
                verifier()
            if response.raw.get("model") != profiles[mid]["model"]:
                raise RuntimeError(
                    "Returned model identity differs from frozen request"
                )
            try:
                if response.finish_reason != "stop":
                    raise ValueError(f"Incomplete response: {response.finish_reason}")
                parsed = parse_json_response(
                    response.raw["choices"][0]["message"].get("content") or ""
                )
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                parsed = {"_invalid": True, "error": str(exc)}
            answer = _answer(parsed, lookup[qid], request["knowledge"])
            answer["knowledge_count"] = len(request["knowledge"])
            usage = response.usage or {}
            tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            if type(tokens) is not int or tokens <= 0:
                tokens = request["reserved_tokens"]
            if tokens > request["reserved_tokens"]:
                raise RuntimeError("Actual usage exceeds reserved token budget")
            total_tokens += tokens
            correct = bool(
                answer["valid"]
                and answer["ranking"][0] == private[qid]["correct_letter"]
            )
            store.finish(
                identifier,
                key,
                {
                    "status": "complete" if answer["valid"] else "invalid",
                    "answer": answer,
                    "correct": correct,
                    "feedback": private[qid],
                    "charged_tokens": tokens,
                    "elapsed_seconds": time.time() - call_started,
                },
            )
            outputs[mid][qid] = answer
            store.event(
                identifier,
                {
                    "type": "answer_committed",
                    "question_key": qid,
                    "model_id": mid,
                    "correct": correct,
                },
            )
            store.update(
                identifier,
                progress={
                    "node_id": "solver",
                    "completed": index + 1,
                    "total": preview["request_count"],
                    "question_key": qid,
                    "model_id": mid,
                },
            )
        except Exception as exc:
            record = json.loads(store.record_path(identifier, key).read_text())
            uncertain = "actual_request" in record and "raw" not in record
            usage = record.get("usage") or {}
            components = [
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            ]
            charged = (
                sum(components)
                if all(type(x) is int and x >= 0 for x in components)
                else 0
            )
            if not charged and "actual_request" in record:
                charged = request["reserved_tokens"]
            store.finish(
                identifier,
                key,
                {
                    "status": "uncertain" if uncertain else "failed",
                    "error": str(exc),
                    "charged_tokens": charged,
                    "elapsed_seconds": time.time() - call_started,
                },
            )
            raise
    return {
        "scores": score_evaluation(questions, outputs, private, **({"pair_manifest": config["question_set"]["pairs"]} if config["question_set"].get("pairs") else {})),
        "outputs": outputs,
        "calls": preview["request_count"],
        "charged_tokens": total_tokens,
        "elapsed_seconds": time.time() - started,
        "question_set_id": config["question_set"]["id"],
    }


def execute_workflow(store: JobStore, identifier: str, config: dict) -> dict:
    from architecture_iq.kb.orchestrator import prepare_run, run_round, evaluate_run
    from architecture_iq.kb.cli import read_runtime_lock, verify_live_runtime
    from .workflow import compile_workflow

    compiled = compile_workflow(config["workflow"])
    if config.get("method") is not None and config["method"] != compiled.get("method"):
        raise ValueError("Frozen method recipe differs from compiled workflow")
    profile = config["models"][0]
    coordinator = {
        **compiled["config"],
        "model": model_config(profile),
        "runtime_fingerprint": profile["runtime_fingerprint"],
    }
    if config.get("initial_kb"):
        coordinator["initial_kb"] = copy.deepcopy(config["initial_kb"])
    if profile.get("connection_type") == "api":
        if compiled.get("method", {}).get("id") != "basic_learning":
            raise ValueError("API models require basic_learning; scientific methods require a runtime lock")
        identity = api_identity(profile)
        if (profile.get("runtime_lock_path") or profile.get("service_identity") != identity
                or profile.get("runtime_fingerprint") != canonical_hash(identity)):
            raise ValueError("Frozen API configuration identity changed or is missing")
        coordinator["runtime_identity"] = identity
    else:
        lock_path = Path(profile["runtime_lock_path"])
        lock = json.loads(lock_path.read_text())
        if canonical_hash(lock) != profile.get("runtime_fingerprint"):
            raise ValueError("Frozen runtime lock fingerprint changed or is missing")
        read_runtime_lock(lock_path, coordinator, verify_files=True)
        verify_live_runtime(lock_path, coordinator, profile["base_url"])
    output = (
        Path(config["output_root"]) / identifier / "workflow"
        if config.get("output_root")
        else store.directory(identifier) / "workflow"
    )
    from .task_inputs import workflow_inputs, workflow_pairs

    public, private = workflow_inputs(
        config["question_set"], config.get("task_question_set"), phase=compiled["evaluate_phase"]
    )
    pairs = workflow_pairs(config["question_set"], config.get("task_question_set"), phase=compiled["evaluate_phase"])
    if pairs:
        coordinator["pair_manifest"] = pairs
    manifest = prepare_run(output, coordinator, public, private, config.get("legacy_claims", []))
    store.event(identifier, {"type": "material_prepared", "node_id": "input",
                            "item_id": "frozen-inputs", "question_count": len(public),
                            "artifact_refs": [str(output / "manifest.json"), str(output / "public_questions.json")]})
    active = {"key": None, "node_id": "agent", "stage": {}}

    def stage(event):
        if event.get("state") == "running":
            active["stage"] = copy.deepcopy(event)
        store.event(identifier, {"type": "stage", **event})
        store.update(identifier, progress=event)
        if event.get("state") == "complete" and event.get("key") and event.get("node_id") in {"solver", "discoverer", "skeptic", "analyst", "curator", "evaluate", "experience_curator"}:
            role = event.get("role") or ("solver" if event["node_id"] == "evaluate" else event["node_id"])
            receipt_path = output / "calls" / (canonical_hash({"role": role, "key": event["key"], "round": event["round_index"]}) + ".json")
            receipt = read_receipt(receipt_path)
            if receipt["status"] != "complete":
                raise ValueError("Completed stage has no sealed role result")
            wire_key = active["key"] if active["stage"].get("key") == event["key"] and active["stage"].get("round_index") == event["round_index"] else None
            if wire_key:
                store.finish(identifier, wire_key, {"status": "invalid" if receipt["result"].get("_invalid") else "complete"})
            store.event(identifier, {"type": "output_sealed", **event, "attempt_id": wire_key or event["key"],
                                    "valid": not receipt["result"].get("_invalid", False),
                                    "artifact_refs": [str(receipt_path)]})
        if event.get("node_id") == "publish" and event.get("state") == "ready":
            patch_path = output / "rounds" / str(event["round_index"]) / "patch.json"
            patch = read_receipt(patch_path)["result"]
            store.event(identifier, {"type": "kb_patch_proposed", "node_id": "publish", "round_index": event["round_index"],
                                    "parent_version": patch["parent_version"], "operation_count": len(patch["operations"]),
                                    "artifact_refs": [str(patch_path)]})
        if event.get("node_id") == "input" and event.get("state") == "complete":
            index = event["round_index"]
            store.event(identifier, {"type": "material_prepared", "node_id": "input", "round_index": index,
                                    "item_id": f"batch-{index}", "question_ids": manifest["round_questions"][str(index)],
                                    "artifact_refs": [str(output / "manifest.json")]})
        if event.get("node_id") == "publish" and event.get("state") == "complete":
            index = event["round_index"]
            result_path = output / "rounds" / str(index) / "result.json"
            sealed = read_receipt(result_path)["result"]
            store.event(identifier, {"type": "kb_snapshot_saved", "node_id": "publish", "round_index": index,
                                    "kb_before": sealed["kb_before"], "kb_after": sealed["kb_after"],
                                    "operation_count": len(sealed["patch"]["operations"]),
                                    "artifact_refs": [str(result_path), str(output / "kb")]})

        if event.get("node_id") == "experience_save" and event.get("state") == "complete":
            index = event["round_index"]
            result_path = output / "rounds" / str(index) / "result.json"
            empirical = read_receipt(result_path)["result"]["experience"]
            store.event(identifier, {"type": "experience_snapshot_saved", "node_id": "experience_save", "round_index": index,
                                    "experience_before": empirical["before"], "experience_after": empirical["after"],
                                    "operation_count": len(empirical["operations"]), "scientific_status": "unverified",
                                    "artifact_refs": [str(result_path), str(output / "experience" / "snapshots" / (empirical["after"] + ".json"))]})

    def boundary(event):
        store.boundary(identifier)

    def wire_observer(wire):
        key = "wire-" + str(
            len(list((store.directory(identifier) / "records").glob("*.json")))
        )
        active["key"] = key
        store.reserve(
            identifier,
            key,
            {
                "node_id": active["stage"].get("node_id", active["node_id"]),
                "round_index": active["stage"].get("round_index", 0),
                "operation_key": active["stage"].get("key"),
                "model_id": profile["id"],
                **attribution(identifier, active["stage"], attempt_id=key),
                "role": active["stage"].get("role", active["node_id"]),
                "body_sha256": wire["body_sha256"],
            },
        )
        store.update_record(
            identifier, key, {"actual_request": wire, "sent_at": time.time()}
        )
        store.event(identifier, {"type": "request_sent", **active["stage"], "attempt_id": key,
                                "artifact_refs": [str(store.record_path(identifier, key))]})

    def chunk_observer(value):
        current = active["stage"]
        store.append_stream(
            identifier, active["key"],
            {"node_id": current.get("node_id", active["node_id"]),
             "round_index": current.get("round_index", 0),
             "operation_key": current.get("key"), "arm": current.get("arm"),
             "question_key": current.get("question_id"), "model_id": profile["id"],
             "step_id": current.get("step_id"), "stage_id": current.get("stage_id"), "role": current.get("role") }, value,
        )

    credential_options = ({"credential_root": store.state_root / "credentials"}
                          if profile.get("connection_type") == "api" else {})
    if config.get("transport", {}).get("stream", False):
        client = create_client(profile, wire_observer, stream=True, chunk_observer=chunk_observer, **credential_options)
    else:
        client = create_client(profile, wire_observer, **credential_options)
    original_complete = client.complete

    def complete(prompt, model):
        from architecture_iq.kb.roles import INSTRUCTIONS

        active["node_id"] = next(
            (
                role
                for role in INSTRUCTIONS
                if prompt.startswith(f"You are the {role} ")
            ),
            "agent",
        )
        active["key"] = None
        response = original_complete(prompt, model)
        if active["key"]:
            store.update_record(
                identifier,
                active["key"],
                {
                    "response_received_at": time.time(),
                    "raw": response.raw,
                    "finish_reason": response.finish_reason,
                    "usage": response.usage,
                },
            )
        return response

    client.complete = complete
    from architecture_iq.kb.completion import seal_learning_complete, require_learning_complete
    from architecture_iq.kb.experience import ExperienceStore

    rounds = []
    no_change = 0
    learning_completion = None
    evaluate_requested = False
    manual = coordinator.get("loop_mode", "automatic") == "manual"
    for index in range(1, coordinator["max_rounds"] + 1):
        if not manifest["round_questions"].get(str(index)):
            if not rounds:
                raise ValueError("No frozen discovery batch available")
            learning_completion = seal_learning_complete(output, manifest, len(rounds), reason="no_next_batch")
            break
        store.boundary(identifier, {"node_id": "input", "round_index": index})
        result = run_round(output, client, None, round_index=index, stage_observer=stage, control_callback=boundary)
        # Waiting and terminal decisions happen only after this durable seal.
        sealed = read_receipt(output / "rounds" / str(index) / "result.json")["result"]
        if sealed != result:
            raise ValueError("Coordinator result differs from sealed round")
        rounds.append(result)
        changed = bool(result["patch"]["operations"] or result.get("experience", {}).get("operations"))
        no_change = 0 if changed else no_change + 1
        next_index = index + 1 if index < coordinator["max_rounds"] else None
        next_ids = manifest["round_questions"].get(str(next_index), []) if next_index else []
        threshold = coordinator.get("stop_after_no_change_rounds")
        reason = ("round_cap" if next_index is None else "no_next_batch" if not next_ids
                  else "no_change" if not manual and threshold is not None and no_change >= threshold else None)
        if manual:
            evaluate_available = bool(compiled["evaluate_phase"] and any(q.get("split") == compiled["evaluate_phase"] for q in public))
            decision = store.offer_round_decision(identifier, round_index=index, kb_version=result["kb_after"],
                        next_round_index=next_index, next_question_ids=next_ids,
                        next_round_reason=reason, evaluate_available=evaluate_available)
            if decision["status"] == "consumed":
                action = decision["action"]  # Durable replay; run_round itself never repeats sealed work.
            else:
                selected = None
                while selected is None:
                    store.boundary(identifier)
                    selected = store.wait_round_decision(identifier, round_index=index, timeout=0.5)
                action = selected["action"]
            if action == "continue":
                continue
            evaluate_requested = action == "evaluate"
            learning_completion = seal_learning_complete(output, manifest, index, reason=action)
            break
        if reason:
            learning_completion = seal_learning_complete(output, manifest, index, reason=reason)
            break
    evaluation = None
    if compiled["evaluate_phase"] and (not manual or evaluate_requested):
        require_learning_complete(output, manifest, len(rounds))
        store.boundary(identifier, {"node_id": "evaluate"})
        evaluation = evaluate_run(output, client, phase=compiled["evaluate_phase"],
                                  stage_observer=stage, control_callback=boundary)
    calls = [read_receipt(p) for p in sorted((output / "calls").glob("*.json"))]
    return {
        "workflow_output": str(output),
        "workflow_hash": compiled["workflow_hash"],
        "execution_hash": compiled["execution_hash"],
        "rounds": rounds,
        "learning_completion": learning_completion,
        "evaluation": evaluation,
        "kb": KBStore(output / "kb").current(),
        "calls": calls,
        **({"model_identity": coordinator["runtime_identity"]} if "runtime_identity" in coordinator else {}),
        **({"experience": ExperienceStore(output / "experience").current(),
            "practice": manifest["practice"]} if manifest.get("practice") else {}),
    }


def public_job(job: dict) -> dict:
    """Hide uncommitted private inputs; completed records reveal their own feedback."""
    result = copy.deepcopy(job)
    config = result.get("config", {})
    enabled = config.get("transport", {}).get("stream", False)
    result["transport"] = {
        "stream": enabled, "legacy": "transport" not in config,
        "stage_events": "polling", "text_events": "sse" if enabled else "unavailable",
        "separate_cursors": True, "stage_cursor": "sequence", "text_cursor": "seq",
        "notice": ("实时文本在节点完成校验前仅为部分输出" if enabled
                   else "此任务以非流式方式发送请求，只有最终收据；无法补录历史增量"),
    }
    events = result.get("events")
    result["sync"] = {"stage": {"transport": "polling", "status": "snapshot", "snapshot_at": time.time(),
                                "last_sequence": max((event.get("sequence", 0) for event in events), default=0) if events is not None else None},
                      "text": {"transport": "sse" if enabled else "unavailable", "cursor": "seq",
                               "status": "subscription_available" if enabled else "unavailable"}}
    for name in ("question_set", "task_question_set"):
        if name in config:
            original = config[name]
            config[name] = {
                k: v for k, v in original.items() if k not in {"feedback", "questions"}
            }
            config[name]["question_count"] = len(original.get("questions", []))
    # Legacy research text is available through the KB panel; avoid duplicating
    # a large initial corpus in each queued job's response.
    if "legacy_claims" in config:
        config["legacy_claim_count"] = len(config.pop("legacy_claims"))
    return result


def worker(state: Path, identifier: str) -> None:
    from architecture_iq.kb.cli import require_execution_host
    from .catalog import Catalog

    require_execution_host(True)
    store = JobStore(state)
    directory = store.directory(identifier)
    with exclusive_lock(directory / ".worker.lock"):
        job = store.get(identifier, full=False)
        if job["status"] == "complete":
            return
        from .jobs import process_stamp

        store.update(
            identifier,
            status="running",
            pid=os.getpid(),
            process_stamp=process_stamp(os.getpid()),
        )
        try:
            from .jobs import source_fingerprint

            if job.get("source_fingerprint") != source_fingerprint():
                raise ValueError(
                    "Source fingerprint differs from the frozen job; automatic execution blocked"
                )
            if job["kind"] == "evaluation":
                result = execute_evaluation(store, identifier, job["config"])
            elif job["kind"] == "workflow":
                result = execute_workflow(store, identifier, job["config"])
            elif job["kind"] == "rag":
                from .rag import execute_rag

                result = execute_rag(store, identifier, job["config"])
            elif job["kind"] == "generation":
                from .generation import execute_generation

                result = execute_generation(
                    store, identifier, job["config"], Catalog(state)
                )
            else:
                raise ValueError("Archived runs cannot execute")
            write_json_atomic(directory / "result.json", result)
            store.update(identifier, status="complete", error=None)
            store.event(identifier, {"type": "complete"})
        except Exception as exc:
            pending = [
                r
                for r in store.get(identifier)["records"]
                if r["status"] in {"pending", "uncertain"}
            ]
            store.update(
                identifier, status="uncertain" if pending else "failed", error=str(exc)
            )
            store.event(identifier, {"type": "error", "message": str(exc)})
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--run", required=True)
    options = parser.parse_args()
    worker(options.state, options.run)
