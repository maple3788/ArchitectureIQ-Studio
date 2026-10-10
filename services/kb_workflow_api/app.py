"""Browser API for a transparent, server-executed scientific workflow studio."""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.kb.execution_host import execution_host_enabled
from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.drafts import DraftConflict, DraftStore, MAX_DRAFT_BYTES, parse_draft_json
from architecture_iq.studio.execution import preview_evaluation, public_job
from architecture_iq.studio.jobs import JobStore, source_fingerprint
from architecture_iq.studio.observations import node_observations
from architecture_iq.studio.models import ModelRegistry, api_identity, model_config, resolve_path
from architecture_iq.studio.workflow import (
    compile_workflow,
    default_workflow,
    validate_workflow,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path):
    return json.loads(
        path.read_text(),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def create_app(
    *,
    state_root: Path | None = None,
    allowed_roots: list[Path] | None = None,
    execution_enabled: bool | None = None,
    dist_dir: Path | None = None,
) -> FastAPI:
    state = (
        state_root
        or Path(os.environ.get("STUDIO_STATE_ROOT", ROOT / "data/kb_workflow_studio"))
    ).resolve()
    sources = allowed_roots or [
        Path(x)
        for x in os.environ.get("STUDIO_SOURCE_ROOTS", str(ROOT / "data")).split(
            os.pathsep
        )
        if x
    ]
    sources = [p.resolve() for p in [*sources, state]]
    enabled = (
        execution_enabled
        if execution_enabled is not None
        else execution_host_enabled()
    )
    catalog, models, jobs = Catalog(state), ModelRegistry(state), JobStore(state)
    drafts = DraftStore(state)
    api = FastAPI(title="ArchitectureIQ · KB Workflow Studio", version="0.1.0")
    api.state.catalog, api.state.models, api.state.jobs = catalog, models, jobs
    prefix = "/api/studio"

    @api.exception_handler(ValueError)
    async def value_error(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(FileNotFoundError)
    @api.exception_handler(KeyError)
    async def not_found(_request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @api.exception_handler(RuntimeError)
    async def runtime_error(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def require_execution():
        if not enabled:
            raise HTTPException(
                409, "当前为只读/编辑模式；模型和训练任务只能在指定服务器执行"
            )
        from architecture_iq.kb.cli import require_execution_host

        require_execution_host(True)

    def all_models():
        return models.describe()

    def archive_roots():
        return [
            Path(p)
            for p in os.environ.get("STUDIO_ARCHIVES", "").split(os.pathsep)
            if p
        ]

    def archives(full=False):
        result = []
        for directory in archive_roots():
            if not (directory / "manifest.json").is_file():
                continue
            manifest = _load(directory / "manifest.json")
            identifier = "archive_" + canonical_hash(str(directory))[:16]
            rounds = [
                _load(p) for p in sorted((directory / "rounds").glob("*/result.json"))
            ]
            item = {
                "id": identifier,
                "kind": "archive",
                "status": "complete" if rounds else "incomplete",
                "created_at": (directory / "manifest.json").stat().st_mtime,
                "updated_at": max(
                    [p.stat().st_mtime for p in directory.glob("rounds/*/result.json")]
                    or [0]
                ),
                "config": {
                    "source_path": str(directory),
                    "name": directory.parent.name,
                    "manifest": manifest,
                },
                "progress": {"rounds": len(rounds)},
            }
            if full:
                item["records"] = [
                    _load(p) for p in sorted((directory / "calls").glob("*.json"))
                ]
                item["result"] = {"rounds": rounds}
                pointer = directory / "kb/CURRENT"
                if pointer.is_file():
                    from architecture_iq.kb.store import KBStore

                    item["result"]["kb"] = KBStore(directory / "kb").current()
                item["events"] = []
            result.append(item)
        return result

    @api.get(prefix + "/bootstrap")
    def bootstrap():
        from architecture_iq.studio.generation import capabilities
        from architecture_iq.kb.roles import INSTRUCTIONS, role_prompt

        return {
            "service": {
                "execution_enabled": enabled,
                "host": "authorized execution host" if enabled else "local editor",
                "state_root": str(state),
                "source_roots": [str(p) for p in sources],
            },
            "stats": catalog.stats(),
            "capabilities": capabilities(),
            "workflow": default_workflow(),
            "role_prompts": {
                role: role_prompt(
                    role,
                    {
                        "_template": "Actual per-node data is substituted at run time; this is not a sent request."
                    },
                )
                for role in INSTRUCTIONS
            },
            "models": all_models(),
        }

    @api.get(prefix + "/questions")
    def questions(
        search: str = "",
        family: str = "",
        type: str = "",
        source_id: str = "",
        split: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        return catalog.list_questions(
            search=search,
            family=family,
            question_type=type,
            source_id=source_id,
            split=split,
            offset=offset,
            limit=limit,
        )

    @api.get(prefix + "/questions/{key}")
    def question(key: str):
        return catalog.get_question(key)

    @api.get(prefix + "/question-pairs")
    def question_pairs(search: str = "", family: str = "", type: str = "", split: str = "",
                       offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=200)):
        return catalog.list_question_pairs(search=search, family=family, question_type=type,
                                           split=split, offset=offset, limit=limit)

    @api.get(prefix + "/question-pairs/{key}")
    def question_pair(key: str):
        return catalog.get_question_pair(key)

    @api.get(prefix + "/sources")
    def source_list():
        values = catalog.list_sources()
        return {
            "items": values,
            "total": len(values),
            "allowed_roots": [str(p) for p in sources],
        }

    @api.post(prefix + "/sources/import")
    def import_source(body: dict = Body(...)):
        path = resolve_path(body["path"], sources)
        pairmap = (
            resolve_path(body["pairmap_path"], sources)
            if body.get("pairmap_path")
            else None
        )
        return catalog.import_source(path, name=body.get("name"), pairmap_path=pairmap)

    @api.post(prefix + "/sources/upload")
    async def upload_source(request: Request, name: str = "题包上传"):
        body = await request.body()
        if len(body) > 200 * 1024 * 1024:
            raise HTTPException(413, "题包上限为200 MiB")
        value = json.loads(body)
        path = state / "uploads" / (canonical_hash(value) + ".json")
        if not path.exists():
            write_json_atomic(path, value)
        return catalog.import_source(path, name=name)

    @api.get(prefix + "/question-sets")
    def question_sets():
        values = catalog.list_question_sets()
        return {"items": values, "total": len(values)}

    @api.get(prefix + "/question-sets/{identifier}")
    def question_set(identifier: str):
        return catalog.get_question_set(identifier)

    @api.post(prefix + "/question-sets")
    def save_question_set(body: dict = Body(...)):
        if "pair_keys" in body:
            if any(k in body for k in ("keys", "filters", "limit", "seed")):
                raise ValueError("题目对选择不能同时指定单题 keys 或筛选抽样")
            return catalog.save_question_pair_set(body["pair_keys"], name=body.get("name", "未命名题对集"))
        keys = body.get("keys")
        if keys is None:
            filters = body.get("filters", {})
            accepted = {
                k: v
                for k, v in filters.items()
                if k in {"search", "family", "source_id", "split"}
            }
            accepted["question_type"] = filters.get(
                "type", filters.get("question_type", "")
            )
            rows = []
            offset = 0
            while True:
                batch = catalog.list_questions(**accepted, offset=offset, limit=200)
                rows.extend(batch["items"])
                offset += len(batch["items"])
                if offset >= batch["total"] or not batch["items"]:
                    break
            keys = [row["key"] for row in rows if row["ready"]]
            if body.get("seed") is not None:
                random.Random(int(body["seed"])).shuffle(keys)
            if body.get("limit") is not None:
                if type(body["limit"]) is not int or body["limit"] <= 0:
                    raise ValueError("题集上限必须为正整数")
                keys = keys[: body["limit"]]
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ValueError("keys必须为题目版本ID列表")
        return catalog.create_question_set(body.get("name", "未命名题集"), keys)

    @api.get(prefix + "/methods")
    def method_list():
        from architecture_iq.studio.methods import list_methods
        return {"items": list_methods()}

    @api.get(prefix + "/models")
    def model_list():
        values = all_models()
        return {"items": values, "total": len(values)}

    @api.post(prefix + "/models")
    def save_model(body: dict = Body(...)):
        body = dict(body)
        api_key = body.pop("api_key", None)
        if body.get("runtime_lock_path"):
            resolve_path(body["runtime_lock_path"], sources)
        return models.save(body, api_key=api_key)

    @api.post(prefix + "/models/{identifier}/check")
    def check_model(identifier: str):
        return models.check(identifier)

    @api.get(prefix + "/workflow/default")
    def workflow_default(method_id: str = "basic_learning"):
        return default_workflow(method_id)

    def draft_response(value):
        return JSONResponse(content=value, headers={"Cache-Control": "no-store"})

    async def draft_body(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_DRAFT_BYTES:
                raise HTTPException(413, "草稿上限为 1 MiB")
            raw.extend(chunk)
        value = parse_draft_json(raw)
        if not isinstance(value, dict):
            raise ValueError("草稿请求必须是对象")
        return value

    @api.get(prefix + "/workflow/draft")
    def workflow_draft():
        return draft_response(drafts.get())

    @api.put(prefix + "/workflow/draft")
    async def update_workflow_draft(request: Request):
        body = await draft_body(request)
        if set(body) != {"expected_revision", "workflow", "advanced_backup"}:
            raise ValueError("需要 expected_revision、workflow、advanced_backup")
        try:
            saved = drafts.save(**body)
        except DraftConflict as exc:
            return JSONResponse(status_code=409,
                                content={"detail": str(exc), "revision": exc.revision},
                                headers={"Cache-Control": "no-store"})
        return draft_response(saved)

    @api.get(prefix + "/workflow/draft/backups")
    def workflow_draft_backups():
        return draft_response(drafts.backups())

    @api.post(prefix + "/workflow/draft/backups")
    async def backup_workflow_draft(request: Request):
        body = await draft_body(request)
        if set(body) != {"workflow", "source"}:
            raise ValueError("恢复副本需要 workflow 和 source")
        return draft_response(drafts.backup(**body))

    @api.post(prefix + "/workflows/validate")
    def workflow_validate(body: dict = Body(...)):
        result = validate_workflow(body)
        if result["valid"]:
            result["compiled"] = compile_workflow(body)
        return result

    @api.get(prefix + "/workflows")
    def workflows():
        values = [
            _load(p)
            for p in sorted(
                (state / "workflows").glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        ]
        return {"items": values, "total": len(values)}

    @api.post(prefix + "/workflows")
    def save_workflow(body: dict = Body(...)):
        compiled = compile_workflow(body)
        identifier = "wf_" + compiled["workflow_hash"][:16]
        result = {
            "id": identifier,
            "revision": compiled["workflow_hash"],
            "workflow": body,
            "created_at": time.time(),
        }
        path = state / "workflows" / (identifier + ".json")
        if path.exists():
            return _load(path)
        write_json_atomic(path, result)
        return result

    def freeze_run(body: dict) -> dict:
        kind = body.get("kind", "evaluation")
        if kind not in {"workflow", "evaluation"}:
            raise ValueError("Unsupported run kind")
        workflow = body.get("workflow")
        settings = workflow.get("settings", {}) if workflow else {}
        selected = body.get("question_set_id") or settings.get("question_set_id")
        if not selected:
            raise ValueError("请先保存并选择题集")
        if settings.get("question_set_id") and settings["question_set_id"] != selected:
            raise ValueError("画布与运行面板选择了不同题集")
        question_set = catalog.get_question_set(selected, include_private=True)
        selected_models = body.get("model_ids") or (
            [settings["model_id"]] if settings.get("model_id") else []
        )
        if not selected_models:
            raise ValueError("请选择被测LLM")
        chosen = [models.get(mid) for mid in selected_models]
        if any(not model["enabled"] for model in chosen):
            raise ValueError("已停用的模型不能执行")
        requested_transport = body.get("transport", {"stream": True})
        if not isinstance(requested_transport, dict) or set(requested_transport) != {"stream"} or requested_transport["stream"] is not True:
            raise ValueError("新 Studio 任务的 transport 必须为 {stream: true}")
        config = {
            "transport": {"stream": True},
            "name": body.get("name"),
            "question_set": question_set,
            "models": chosen,
            "prompt": body.get("prompt", ""),
            "max_calls": body.get("max_calls", 1000),
            "max_tokens": body.get("max_tokens", 20_000_000),
            "kb_condition": body.get("kb_condition", "clean"),
        }
        if config["kb_condition"] not in {"clean", "current", "legacy"}:
            raise ValueError("未知KB评测条件")
        for key in ("max_calls", "max_tokens"):
            if type(config[key]) is not int or config[key] <= 0:
                raise ValueError(f"{key}必须为正整数")
        if config["kb_condition"] != "clean":
            path = resolve_path(body["kb_path"], sources)
            snapshot = _load(path)
            if isinstance(snapshot, list):
                snapshot = {"claims": snapshot, "version": canonical_hash(snapshot)}
            config["kb_snapshot"] = snapshot
        if kind == "workflow":
            if len(chosen) != 1:
                raise ValueError("一次KB研究固定一个模型；多模型请使用评测模式")
            if settings.get("model_id") and settings["model_id"] != chosen[0]["id"]:
                raise ValueError("画布与运行面板选择了不同模型")
            compiled = compile_workflow(workflow)
            if compiled.get("method", {}).get("id") == "basic_learning" and config["kb_condition"] != "clean":
                raise ValueError("单题学习请在作答节点选择初始 KB，不使用评测模式的 KB 路径")
            config["workflow"] = workflow
            if compiled.get("method") is not None:
                config["method"] = compiled["method"]
            if settings.get("initial_kb"):
                from architecture_iq.studio.knowledge import knowledge_inventory, resolve_initial_knowledge
                config["initial_kb"] = resolve_initial_knowledge(settings["initial_kb"], knowledge_inventory(jobs, archives()))
            if settings.get("task_question_set_id"):
                config["task_question_set"] = catalog.get_question_set(
                    settings["task_question_set_id"], include_private=True
                )
            if settings.get("runtime_lock_path"):
                chosen[0]["runtime_lock_path"] = str(
                    resolve_path(settings["runtime_lock_path"], sources)
                )
            if chosen[0].get("connection_type") == "api":
                if compiled.get("method", {}).get("id") != "basic_learning":
                    raise ValueError("API 模型仅支持单题学习；科学和配对研究仍需验证本地运行锁")
                if chosen[0].get("runtime_lock_path"):
                    raise ValueError("API 模型不能使用本地运行锁")
                models.credential(chosen[0])
            else:
                if not chosen[0].get("runtime_lock_path"):
                    raise ValueError("KB研究需要实际服务器运行锁")
                from architecture_iq.kb.cli import read_runtime_lock

                lock = _load(resolve_path(chosen[0]["runtime_lock_path"], sources))
                read_runtime_lock(
                    Path(chosen[0]["runtime_lock_path"]),
                    {
                        "model": model_config(chosen[0]),
                        "runtime_fingerprint": canonical_hash(lock),
                    },
                )
            count = sum(
                q.get("split", "discovery") == "discovery"
                for q in question_set["questions"]
            )
            from architecture_iq.kb.inputs import is_basic_learning
            basic = is_basic_learning(compiled["config"])
            needed = 1 if basic else (compiled["config"]["max_rounds"] * compiled["config"]["discovery_per_round"])
            if count < needed:
                raise ValueError(f"当前有{count}道发现题；配置需要{needed}道")
            from architecture_iq.studio.task_inputs import workflow_inputs, workflow_pairs
            from architecture_iq.kb.inputs import validate_public_inputs

            public, private = workflow_inputs(
                question_set, config.get("task_question_set"), phase=compiled["evaluate_phase"]
            )
            # Same pure contract as prepare_run; preflight never creates a run
            # or KB snapshot and never calls the model or training pipeline.
            coordinator = {**compiled["config"], "model": model_config(chosen[0])}
            pairs = workflow_pairs(question_set, config.get("task_question_set"), phase=compiled["evaluate_phase"])
            if pairs:
                coordinator["pair_manifest"] = pairs
            validate_public_inputs(coordinator, public, private)
            from architecture_iq.kb.pair_learning import validate_pair_config
            validate_pair_config(coordinator, public)
            if compiled["evaluate_phase"] and not any(
                q.get("split") == compiled["evaluate_phase"] for q in public
            ):
                raise ValueError("评估节点启用但题集中没有对应独立split")
            if settings.get("output_root"):
                config["output_root"] = str(
                    resolve_path(
                        settings["output_root"],
                        [state, ROOT / "data"],
                        must_exist=False,
                    )
                )
            if settings.get("kb_path"):
                legacy = _load(resolve_path(settings["kb_path"], sources))
                legacy = legacy["claims"] if isinstance(legacy, dict) else legacy
                if settings.get("rules_path"):
                    from architecture_iq.kb.legacy import import_legacy_claims

                    legacy = import_legacy_claims(
                        legacy, _load(resolve_path(settings["rules_path"], sources))
                    )
                config["legacy_claims"] = legacy
        for model in chosen:
            if model.get("connection_type") == "api":
                model["service_identity"] = api_identity(model)
                model["runtime_fingerprint"] = canonical_hash(model["service_identity"])
            elif model.get("runtime_lock_path"):
                lock_path = resolve_path(model["runtime_lock_path"], sources)
                model["runtime_lock_path"] = str(lock_path)
                model["runtime_fingerprint"] = canonical_hash(_load(lock_path))
        return config

    def preview_identity(config: dict) -> str:
        return canonical_hash(
            {"config": config, "source_fingerprint": source_fingerprint()}
        )

    @api.post(prefix + "/runs/preview")
    def preview(body: dict = Body(...)):
        config = freeze_run(body)
        identity = preview_identity(config)
        if body.get("kind") == "workflow":
            compiled = compile_workflow(config["workflow"])
            from architecture_iq.studio.task_inputs import task_summary

            phase = next(n["config"]["phase"] for n in config["workflow"]["nodes"] if n["id"] == "evaluate")
            config["prompt"] = compiled["role_instructions"].get("solver", "")
            config["models"] = [config["models"][0]]
            research_limit = compiled["config"]["max_rounds"] * compiled["config"]["discovery_per_round"]
            research = [q for q in config["question_set"]["questions"] if q.get("split", "discovery") == "discovery"]
            protocol = compiled["config"].get("learning_protocol", "single")
            experience = compiled["config"].get("experience_mode", "off") != "off"
            learning = {"protocol": protocol, "model_weights_fixed": True,
                        "experience_mode": compiled["config"].get("experience_mode", "off"),
                        "experience_calls_per_round": int(experience)}
            if config["models"][0].get("connection_type") == "api":
                learning.update(model_weights_fixed=False,
                                model_identity=config["models"][0]["service_identity"])
            if compiled.get("method", {}).get("id") == "basic_learning":
                research_limit = 1
                learning.update(max_calls_per_round=2,
                                max_calls_all_rounds=2 * compiled["config"]["max_rounds"],
                                output_reserve_per_round=2 * config["models"][0]["parameters"]["max_tokens"],
                                practice={"kind": "same_question_practice", "independent_evaluation": False},
                                notice="每轮一次作答、一次经验提炼；手动同题再练，经验未验证，不作独立效果评测。")
            elif protocol != "single":
                from architecture_iq.kb.pair_learning import ordered_pair_questions, pair_call_budget
                research = ordered_pair_questions(research, [p for p in config["question_set"]["pairs"] if p["split"] == "discovery"])
                calls = pair_call_budget(compiled["config"])
                learning.update(pair_count=research_limit // 2,
                                max_calls_per_round=calls,
                                max_calls_all_rounds=calls * compiled["config"]["max_rounds"],
                                output_reserve_per_round=calls * config["models"][0]["parameters"]["max_tokens"],
                                notice="调用上界含每对一次假说审查及本轮分析与整理；输入长度随上游输出变化，实际请求逐次校验文本预算。")
            else:
                # Solves, one proposal and possible skeptic per packet, analysis,
                # formal curation, and optional empirical consolidation.
                per_round = compiled["config"]["discovery_per_round"]
                packets = (per_round + compiled["config"]["packet_size"] - 1) // compiled["config"]["packet_size"]
                calls = per_round + packets * 2 + 2 + int(experience)
                learning.update(max_calls_per_round=calls,
                                max_calls_all_rounds=calls * compiled["config"]["max_rounds"],
                                output_reserve_per_round=calls * config["models"][0]["parameters"]["max_tokens"])
            preview_config = {**config, "question_set": {**config["question_set"], "questions": research[:research_limit]}}
            if preview_config["question_set"].get("pairs"):
                preview_ids = {q["id"] for q in research[:research_limit]}
                preview_config["question_set"]["pairs"] = [p for p in config["question_set"]["pairs"]
                    if all(m.get("key") in preview_ids or m.get("id") in preview_ids for m in p["members"])]
            result = preview_evaluation(preview_config)
            task = task_summary(config["question_set"], config.get("task_question_set"),
                                phase=phase, enabled=compiled["evaluate_phase"] is not None,
                                research_limit=research_limit)
            arms = ["clean", "initial", "current"] + (["experience_examples", "experience_lessons", "experience_combined"] if experience else [])
            evaluation_calls = task["executed_count"] * len(arms)
            result.update(
                kind="workflow",
                compiled=compiled,
                learning=learning,
                config_hash=identity,
                initial_kb=({key: config["initial_kb"][key] for key in ("id", "name", "kind", "version", "counts")}
                            if config.get("initial_kb") else None),
                task=task, evaluation_arms=arms,
                evaluation_budget={"max_calls": evaluation_calls,
                                   "output_reserve": evaluation_calls * config["models"][0]["parameters"]["max_tokens"],
                                   "notice": "仅为输出预留上界；每个实际请求的输入与输出预算由持久收据计费。"},
                notice=("首轮读取已选初始 KB（未选择则为空）；后续轮次按开关追加本次学习经验。反馈只在答案保存后揭示。"
                        if compiled.get("method", {}).get("id") == "basic_learning" else
                        "此处只预览研究侧 discovery 题目的公开 Solver 输入；Task 各组盲测请求将在最终 KB 冻结后生成，后续 agent 输入均按实际上游产物生成并记录。"),
            )
            return result
        return {**preview_evaluation(config), "config_hash": identity}

    @api.post(prefix + "/runs")
    def start_run(request: Request, body: dict = Body(...)):
        require_execution()
        config = freeze_run(body)
        if body.get("expected_config_hash") != preview_identity(config):
            raise HTTPException(409, "配置、模型版本或运行输入已变化，请重新预览后提交")
        if body.get("kind", "evaluation") == "evaluation":
            preview_evaluation(config)
        result = jobs.create(
            body.get("kind", "evaluation"),
            config,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        if result["status"] == "queued":
            jobs.launch(result["id"])
        return public_job(jobs.get(result["id"]))

    @api.get(prefix + "/runs")
    def run_list():
        values = [public_job(job) for job in jobs.list()] + archives()
        values.sort(key=lambda item: item["created_at"], reverse=True)
        return {"items": values, "total": len(values)}

    @api.get(prefix + "/runs/{identifier}")
    def run_detail(identifier: str):
        if identifier.startswith("archive_"):
            matches = [item for item in archives(full=True) if item["id"] == identifier]
            if not matches:
                raise KeyError(identifier)
            return matches[0]
        job = jobs.get(identifier)
        result = public_job(job)
        result["node_observations"] = node_observations(job, jobs.directory(identifier))
        return result

    @api.get(prefix + "/runs/{identifier}/stream")
    def run_stream(identifier: str, request: Request, after: int = Query(0, ge=0)):
        # Subscription is read-only: reconnecting never launches/resumes a job.
        job = jobs.get(identifier, full=False)
        cursor = after
        previous = request.headers.get("last-event-id")
        if previous is not None:
            try:
                previous_id = int(previous)
            except ValueError as exc:
                raise HTTPException(400, "Invalid Last-Event-ID") from exc
            if previous_id < 0:
                raise HTTPException(400, "Invalid Last-Event-ID")
            cursor = max(cursor, previous_id)
        transport = public_job(job)["transport"]

        def frame(event, value, sequence=None):
            prefix = f"id: {sequence}\n" if sequence is not None else ""
            return prefix + f"event: {event}\ndata: " + json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n\n"

        async def follow():
            nonlocal cursor
            yield frame("metadata", {"transport": transport, "status": job["status"]})
            if not transport["stream"]:
                yield frame("unavailable", {"reason": transport["notice"]})
                return
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                # Read terminal status before the journal: all prior durable
                # frames must drain before announcing terminal completion.
                state = await asyncio.to_thread(jobs.get, identifier, full=False)
                records = await asyncio.to_thread(jobs.stream_events, identifier, after=cursor)
                for value in records:
                    cursor = value["seq"]
                    yield frame("chunk", value, cursor)
                if len(records) < 200 and state["status"] in {"complete", "failed", "uncertain", "interrupted"}:
                    yield frame("terminal", {"status": state["status"], "error": state.get("error")})
                    return
                if time.monotonic() - heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                if len(records) < 200:
                    await asyncio.sleep(0.25)

        return StreamingResponse(follow(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })

    @api.post(prefix + "/runs/{identifier}/round-decision")
    def round_decision(identifier: str, body: dict = Body(...)):
        if set(body) != {"round_index", "action"}:
            raise ValueError("Round decision requires round_index and action")
        jobs.decide_round(identifier, round_index=body["round_index"], action=body["action"])
        return public_job(jobs.get(identifier))

    @api.post(prefix + "/runs/{identifier}/pause")
    def pause(identifier: str):
        jobs.control(identifier, "pause")
        return public_job(jobs.get(identifier))

    @api.post(prefix + "/runs/{identifier}/resume")
    def resume(identifier: str):
        jobs.control(identifier, "resume")
        return public_job(jobs.get(identifier))

    @api.post(prefix + "/generations/preview")
    def generation_preview(body: dict = Body(...)):
        from architecture_iq.studio.generation import validate_generation

        return validate_generation(body)

    @api.post(prefix + "/generations")
    def generation(request: Request, body: dict = Body(...)):
        require_execution()
        from architecture_iq.studio.generation import validate_generation

        config = validate_generation(body)
        job = jobs.create(
            "generation", config, idempotency_key=request.headers.get("Idempotency-Key")
        )
        if job["status"] == "queued":
            jobs.launch(job["id"])
        return public_job(jobs.get(job["id"]))

    @api.get(prefix + "/kb")
    def knowledge():
        from architecture_iq.studio.knowledge import knowledge_inventory

        return knowledge_inventory(jobs, archives())

    from .rag_routes import register_rag_routes
    from architecture_iq.studio.knowledge import knowledge_inventory
    register_rag_routes(api, catalog=catalog, models=models, jobs=jobs,
                        inventory_provider=knowledge,
                        require_execution=require_execution, allowed_roots=sources)

    build = dist_dir or ROOT / "frontend/workflow/dist"
    if (build / "assets").is_dir():
        api.mount("/assets", StaticFiles(directory=build / "assets"), name="assets")

    @api.get("/", include_in_schema=False)
    def index():
        if not (build / "index.html").exists():
            raise HTTPException(
                503, "前端尚未构建；在frontend/workflow执行npm run build"
            )
        return FileResponse(build / "index.html")

    return api


app = create_app()
