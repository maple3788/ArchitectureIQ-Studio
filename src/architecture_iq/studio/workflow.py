"""Typed v1 graph compilation into the existing scientific coordinator.

The graph encodes a fixed data-boundary protocol and two optional routes, rather
than claiming arbitrary directed graphs can be executed by ``run_round``.
Layout, labels, and edge IDs are presentation metadata only.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from architecture_iq.kb.orchestrator import DEFAULTS
from architecture_iq.kb.roles import INSTRUCTIONS
from architecture_iq.kb.store import canonical_hash
from .methods import METHOD_SETTINGS, resolve_method

NODE_TYPES = {
    "input": "question_input", "solver": "agent", "commit": "answer_commit",
    "reveal": "feedback_reveal", "discoverer": "agent", "skeptic": "agent",
    "experiment": "experiment", "confirmation": "confirmation", "analyst": "agent",
    "curator": "agent", "publish": "publish", "loop": "loop",
    "evaluate": "evaluation", "end": "end",
    "experience_curator": "agent", "experience_save": "experience_save",
}
LABELS = {
    "input": "题目与知识检索", "solver": "Solver", "commit": "保存答案", "reveal": "揭示发现反馈",
    "discoverer": "Discoverer", "skeptic": "Skeptic", "experiment": "探索实验",
    "confirmation": "独立确认", "analyst": "Analyst", "curator": "Curator", "publish": "验证并发布 KB",
    "loop": "有界轮次", "evaluate": "盲测评估", "end": "结束",
    "experience_curator": "提炼经验", "experience_save": "保存未验证经验",
}
BASIC = ["input", "solver", "commit", "reveal", "experience_curator", "experience_save", "loop"]
BASIC_ONLY = {"experience_curator", "experience_save"}
CORE = ["input", "solver", "commit", "reveal", "discoverer", "skeptic", "experiment"]
TAIL = ["analyst", "curator", "publish", "loop"]
REFERENCES = {"initial_kb", "model_id", "question_set_id", "task_question_set_id", "output_root", "runtime_lock_path", "kb_path", "rules_path"}


def _edge(source: str, target: str, condition: str = "always") -> dict:
    return {"id": f"{source}-{target}", "source": source, "target": target,
            "source_handle": "out", "target_handle": "in", "mapping": {}, "condition": condition}


def default_workflow(method_id: str = "basic_learning") -> dict:
    """Return a new editable template; no runtime identity is invented here."""
    method = resolve_method({"method_id": method_id})
    basic = method_id == "basic_learning"
    nodes = []
    for index, (identifier, kind) in enumerate(NODE_TYPES.items()):
        if identifier in BASIC_ONLY and not basic:
            continue
        config = {"role": identifier, "prompt": ""} if kind == "agent" else {}
        if identifier == "evaluate":
            config = {"phase": "final"}
        nodes.append({"id": identifier, "type": kind, "label": LABELS[identifier],
                      "position": {"x": (index % 7) * 230, "y": (index // 7) * 190}, "config": config})
    sequence = BASIC if basic else CORE + TAIL
    edges = [_edge(a, b) for a, b in zip(sequence, sequence[1:])]
    edges += [_edge("loop", "input", "continue"), _edge("loop", "end", "done")]
    settings = copy.deepcopy(DEFAULTS)
    settings.update(max_rounds=1, discovery_per_round=1, packet_size=1,
                    exploration_count=1, n_seeds=2, enable_confirmation=False,
                    max_calls_per_round=30, max_tokens_per_round=250000,
                    max_candidate_seed_runs=40, wall_time_seconds=3600,
                    seed_start=101000000, profile="v1.5", method_id=method_id,
                    method_version="1", loop_mode="manual", stop_after_no_change_rounds=1)
    if basic:
        settings.update(max_rounds=2, max_calls_per_round=2, use_previous_experience=True,
                        record_conditions=True, enable_evaluation=False)
    elif method["learning_protocol"] != "single":
        settings.update(discovery_per_round=2, packet_size=2)
    return {"schema_version": 1, "name": "单题学习" if basic else "KB 科学研究工作流", "nodes": nodes,
            "edges": edges, "settings": settings}


def _inspect(spec: Any) -> tuple[list[str], dict, set[tuple[str, str, str]]]:
    errors, nodes, routes = [], {}, set()
    if not isinstance(spec, dict):
        return ["Workflow must be an object"], nodes, routes
    if set(spec) - {"schema_version", "name", "nodes", "edges", "settings"}:
        errors.append("Unsupported workflow fields")
    if type(spec.get("schema_version")) is not int or spec.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        errors.append("Workflow name is required")
    settings = spec.get("settings")
    if not isinstance(settings, dict):
        errors.append("settings must be an object")
        settings = {}
    basic = settings.get("method_id") == "basic_learning"
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list):
        errors.append("nodes must be a list")
        raw_nodes = []
    for node in raw_nodes:
        if not isinstance(node, dict):
            errors.append("Each node must be an object")
            continue
        identifier = node.get("id")
        if not isinstance(identifier, str) or identifier not in NODE_TYPES:
            errors.append(f"Unsupported node ID: {identifier!r}")
            continue
        if identifier in nodes:
            errors.append(f"Duplicate node: {identifier}")
        nodes[identifier] = node
        if set(node) - {"id", "type", "label", "position", "config"}:
            errors.append(f"Unsupported node fields: {identifier}")
        if node.get("type") != NODE_TYPES[identifier]:
            errors.append(f"Invalid node type: {identifier}")
        if not isinstance(node.get("label", ""), str):
            errors.append(f"Invalid node label: {identifier}")
        position = node.get("position", {})
        if (not isinstance(position, dict) or set(position) != {"x", "y"}
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in position.values())):
            errors.append(f"Invalid node position: {identifier}")
        config = node.get("config", {})
        if not isinstance(config, dict):
            errors.append(f"Invalid node config: {identifier}")
            continue
        if NODE_TYPES[identifier] == "agent":
            if set(config) != {"role", "prompt"} or config.get("role") != identifier:
                errors.append(f"Agent role is fixed by node type: {identifier}")
            if not isinstance(config.get("prompt"), str) or len(config.get("prompt", "")) > 32000:
                errors.append(f"Agent prompt must be a string of at most 32000 characters: {identifier}")
        elif identifier == "evaluate":
            if set(config) != {"phase"} or config.get("phase") not in ("development", "final"):
                errors.append("Evaluation phase must be development or final")
        elif config:
            errors.append(f"Unsupported configuration for fixed program node: {identifier}")
    missing = (set(NODE_TYPES) if basic else set(NODE_TYPES) - BASIC_ONLY) - nodes.keys()
    if missing:
        errors.append(f"Required stages missing: {', '.join(sorted(missing))}")
    raw_edges = spec.get("edges")
    if not isinstance(raw_edges, list):
        errors.append("edges must be a list")
        raw_edges = []
    identifiers = set()
    for edge in raw_edges:
        if not isinstance(edge, dict):
            errors.append("Each edge must be an object")
            continue
        if set(edge) - {"id", "source", "target", "source_handle", "target_handle", "mapping", "condition"}:
            errors.append("Unsupported edge fields")
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            errors.append("Each edge requires a distinct ID")
        else:
            identifiers.add(identifier)
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or source not in nodes or not isinstance(target, str) or target not in nodes:
            errors.append("Edge references an unknown node")
            continue
        if edge.get("source_handle") != "out" or edge.get("target_handle") != "in":
            errors.append("Only typed out → in handles are supported in v1")
        if edge.get("mapping", {}) != {}:
            errors.append("Custom field mappings are unsupported in v1; data permissions are fixed")
        condition = edge.get("condition", "always")
        if condition not in ("always", "continue", "done"):
            errors.append("Unsupported edge condition")
            continue
        route = (source, target, condition)
        if route in routes:
            errors.append("Duplicate execution edge")
        routes.add(route)
    core_routes = {(a, b, "always") for chain in (CORE, TAIL) for a, b in zip(chain, chain[1:])}
    core_routes.add(("loop", "input", "continue"))
    confirmation_routes = {("experiment", "confirmation", "always"), ("confirmation", "analyst", "always")}
    evaluation_routes = {("loop", "evaluate", "done"), ("evaluate", "end", "always")}
    confirmation = ("experiment", "confirmation", "always") in routes
    evaluation = ("loop", "evaluate", "done") in routes
    expected = core_routes | (confirmation_routes if confirmation else {("experiment", "analyst", "always")})
    expected |= evaluation_routes if evaluation else {("loop", "end", "done")}
    if basic:
        expected = {(a, b, "always") for a, b in zip(BASIC, BASIC[1:])}
        expected |= {("loop", "input", "continue"), ("loop", "end", "done")}
    if routes != expected:
        errors.append("Unsupported routing: core stages cannot be bypassed, reordered, or receive private feedback early")
    settings = spec.get("settings")
    if not isinstance(settings, dict):
        errors.append("settings must be an object")
        settings = {}
    if set(settings) - (set(DEFAULTS) | REFERENCES | METHOD_SETTINGS | {"enable_evaluation", "learning_protocol"}):
        errors.append("Unsupported workflow setting")
    try:
        method = resolve_method(settings)
    except ValueError as exc:
        method = None
        errors.append(str(exc))
    if basic:
        for key, value in {"discovery_per_round": 1, "packet_size": 1, "max_calls_per_round": 2,
                           "loop_mode": "manual"}.items():
            if settings.get(key, value) != value:
                errors.append(f"basic_learning requires {key}={value!r}")
        for key in ("use_previous_experience", "record_conditions"):
            if type(settings.get(key, True)) is not bool:
                errors.append(f"{key} must be boolean")
        if any(settings.get(key) for key in ("kb_path", "rules_path", "task_question_set_id")):
            errors.append("单题学习不支持 Task 或任意 KB 文件路径；请从 KB 库中选择")
    selection = settings.get("initial_kb")
    if selection not in (None, {}):
        if (not isinstance(selection, dict) or set(selection) != {"id", "version"}
                or not isinstance(selection.get("id"), str) or not selection["id"]
                or not isinstance(selection.get("version"), str) or len(selection["version"]) != 64
                or any(c not in "0123456789abcdef" for c in selection["version"])):
            errors.append("初始 KB 必须是知识库中的固定版本，请重新选择")
        if not basic:
            errors.append("初始 KB 选择目前仅用于单题学习")
    protocol = method["learning_protocol"] if method else settings.get("learning_protocol", "single")
    if protocol not in ("single", "paired_contrastive", "paired_progressive"):
        errors.append("Unknown learning protocol")
    if settings.get("loop_mode", "automatic") not in ("manual", "automatic"):
        errors.append("loop_mode must be manual or automatic")
    no_change = settings.get("stop_after_no_change_rounds", 2)
    if type(no_change) is not int or not 1 <= no_change <= 3:
        errors.append("stop_after_no_change_rounds must be an integer from 1 to 3")
    if protocol != "single":
        for key in ("discovery_per_round", "packet_size"):
            value = settings.get(key, DEFAULTS[key])
            if type(value) is int and value % 2:
                errors.append(f"{key} must be even to keep complete pairs")
    effective = {**DEFAULTS, **settings}
    for key, default in DEFAULTS.items():
        if type(default) is int and (type(effective[key]) is not int or effective[key] <= 0):
            errors.append(f"{key} must be a positive integer")
    if type(effective["max_rounds"]) is int and effective["max_rounds"] > 3:
        errors.append("At most three rounds/confirmation attempts")
    if not isinstance(effective["profile"], str) or not effective["profile"]:
        errors.append("Profile is required")
    for key, enabled in (("enable_confirmation", confirmation), ("enable_evaluation", evaluation)):
        if key in settings and (type(settings[key]) is not bool or settings[key] != enabled):
            errors.append(f"{key} contradicts graph routing")
    if confirmation and (effective["n_seeds"] != 10 or effective["confirmation_count"] != 48):
        errors.append("Confirmation requires 48 independent datasets and ten seeds")
    reference_ids = {"model_id", "question_set_id", "task_question_set_id"}
    for key in reference_ids:
        if key in settings and (not isinstance(settings[key], str) or not settings[key]):
            errors.append(f"{key} must be a nonempty server reference")
    for key in REFERENCES - reference_ids - {"initial_kb"}:
        if key in settings and not isinstance(settings[key], str):
            errors.append(f"{key} must be a server path reference")
    return errors, nodes, routes


def validate_workflow(spec: dict) -> dict:
    errors, _, _ = _inspect(spec)
    return {"valid": not errors, "errors": errors}


def compile_workflow(spec: dict) -> dict:
    """Freeze a valid graph's execution semantics without mutating the draft."""
    errors, nodes, routes = _inspect(spec)
    if errors:
        raise ValueError("Invalid workflow: " + "; ".join(errors))
    workflow = copy.deepcopy(spec)
    method = resolve_method(spec["settings"])
    protocol = method["learning_protocol"] if method else spec["settings"].get("learning_protocol", "single")
    instructions = {role: nodes[role]["config"]["prompt"] for role in INSTRUCTIONS
                    if role in nodes and nodes[role]["config"]["prompt"].strip()}
    if protocol != "single" and "discoverer" in instructions:
        instructions["pair_researcher"] = instructions["discoverer"]
    confirmation = ("experiment", "confirmation", "always") in routes
    evaluation = ("loop", "evaluate", "done") in routes
    config = {**copy.deepcopy(DEFAULTS), **{k: copy.deepcopy(v) for k, v in spec["settings"].items() if k not in REFERENCES}}
    config.update(enable_confirmation=confirmation, enable_evaluation=evaluation, role_instructions=instructions)
    if method and method["id"] == "basic_learning":
        config.update(discovery_per_round=1, packet_size=1, max_calls_per_round=2, loop_mode="manual",
                      use_previous_experience=spec["settings"].get("use_previous_experience", True),
                      record_conditions=spec["settings"].get("record_conditions", True))
    if method:
        config.update(method=copy.deepcopy(method), learning_protocol=method["learning_protocol"],
                      experience_mode=method["experience_mode"])
    phase = nodes["evaluate"]["config"]["phase"] if evaluation else None
    order = CORE + (["confirmation"] if confirmation else []) + TAIL + (["evaluate"] if evaluation else []) + ["end"]
    if method and method["id"] == "basic_learning":
        order = BASIC + ["end"]
    semantic = {"schema_version": 1, "config": config,
                "routes": sorted(routes), "evaluate_phase": phase,
                "references": {k: v for k, v in spec["settings"].items() if k in REFERENCES}}
    return {"workflow": workflow, "config": config, "role_instructions": copy.deepcopy(instructions),
            "workflow_hash": canonical_hash(workflow), "execution_hash": canonical_hash(semantic),
            "evaluate_phase": phase, "execution_order": order,
            **({"method": method} if method else {})}
