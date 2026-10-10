# Question-based RAG Answering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有 Studio 添加按当前题目自动匹配 KB、提取相关知识并调用现有 GLM/API 模型作答的完整模式。

**Architecture:** 新增独立的公开输入校验、确定性检索、预览与执行模块，复用 Catalog、只读知识目录、canonical 规则匹配以及 JobStore/模型客户端。增加独立 kind=rag 和薄路由注册模块，前端提供 RAG 页面及题目详情入口，运行历史复用现有轮询和 SSE。

**Tech Stack:** 当前 Python/FastAPI、标准库 BM25 实现、React/TypeScript、pytest、Vitest/Testing Library；不增加产品依赖。

**Spec:** [已批准设计](../specs/2026-10-10-question-rag-design.md)。实现者必须同时阅读本计划、设计和仓库 `AGENTS.md`。

## Global Constraints

- 实现和测试仅在本仓库；操作前验证 `git rev-parse --show-toplevel`，测试解释器的 `architecture_iq.__file__` 必须位于本仓库 `src/architecture_iq`。
- 「第一版每次选择一道题、一个模型。」
- 「展示最多 3 个候选 KB」；「自动选排名第一的 KB，从该快照提取最多 8 条合格知识。条数可设置为 1–12」。
- 策略版本为 `public_features_text_v1`；实际模型调用恰好一次，检索阶段零模型调用。
- 「预览与实际调用使用同一检索函数、同一已冻结结果。」
- 「此模式不读取或展示当前题目的私有 GT，也不执行评分。」保持所有既有科学/配对方法、草稿、历史哈希和封存收据。
- 「所有阶段由持久化事件驱动，界面不模拟模型文本。」无命中时禁止启动，不自动转为无知识作答。
- 「任何真实 GLM/API 冒烟调用只能在私有配置指定的授权 Linux 服务器运行；本地仅做预览、UI 构建和 mocked 测试。」测试不能建立外部模型连接。
- 不提交状态、知识源数据、凭据、模型、索引缓存或构建产物；只按任务文件清单提交源码、mocked 测试和文档。

## Review Focus

1. 旧目录记录没有新 readiness 字段，或只有公开题面没有 GT：RAG 仍可使用完整公开题面；来源全部被阻止时不可用。Task 1/6 钉住此行为。
2. 同一个知识条目被多个快照收录或 ID 相同但内容不同：重复不加分，不同内容不被吞掉，引用映射不能歧义。Task 2/3 钉住此行为。
3. 中文术语、重复词、零长度文档及大量相同 family 的无关经验：排名稳定、分数有限，family 标签本身不构成经验命中。Task 3 钉住此行为。
4. 用户改题时旧预览仍在返回，或来源在启动前被修改：旧结果不能覆盖新选择，服务器拒绝旧预览且不启动调用。Task 5/6 钉住此行为。
5. 模型给出不存在的引用、无效排名，或发送后连接中断：保留真实收据，未知引用不显示为可信来源，不自动重试。Task 4/7 钉住此行为。

## 文件职责与依赖

| 文件 | 职责 |
| --- | --- |
| 新增 `src/architecture_iq/studio/rag_inputs.py` | 仅公开字段的 RAG readiness 与题目校验，不依赖 Catalog，避免循环导入 |
| 修改 `src/architecture_iq/studio/catalog.py` | 新旧目录读取时补充 rag_ready；沿用公开投影与来源阻止策略 |
| 新增 `src/architecture_iq/studio/rag_retrieval.py` | 准入、来源排除、去重、索引缓存、排名与命中说明 |
| 新增 `src/architecture_iq/studio/rag.py` | 模型身份冻结、精确请求/预算、预览哈希、单次调用及回答封存 |
| 新增 `services/kb_workflow_api/rag_routes.py` | 校验请求、注册两个接口、启动任务；不复制 app.py 的通用路由 |
| 修改 `services/kb_workflow_api/app.py` | 注入 Catalog/Models/Jobs/archives/执行检查，挂载 RAG 路由 |
| 修改 `src/architecture_iq/studio/jobs.py`、`execution.py`、`events.py` | 接纳 rag 类型、包含新增路由源码的指纹、worker 分派及 retrieval 阶段归属 |
| 新增 `frontend/workflow/src/ragTypes.ts`、`Rag.tsx`、`RagRunView.tsx`、`rag.css` | 类型、配置与预览、真实运行和来源展示、局部样式 |
| 修改 `App.tsx`、`Questions.tsx`、`QuestionPicker.tsx`、`types.ts` | 侧栏/当前题目传递、RAG 单题选择和 readiness 类型 |
| 修改 `Runs.tsx`、`displayNames.ts` | 运行列表的类型筛选与 RAG 详情展示 |
| 新增 `tests/rag_fixtures.py`、4 个 `test_studio_rag_*.py` | 仅测试使用的来源/模型/客户端构造与后端行为验证 |
| 新增 `Rag.test.tsx`、`RagRunView.test.tsx`、`App.test.tsx` | 页面、来源、导航集成验证；同时扩展已有选择器/运行测试 |

前端路径均相对于 `frontend/workflow/src/`。后端测试新文件分别为 `test_studio_rag_inputs.py`、`test_studio_rag_retrieval.py`、`test_studio_rag_execution.py`、`test_studio_rag_api.py`。

## 共享数据契约

- `RagSelection`：`{question_key: string, model_id: string, knowledge_limit: number}`，knowledge_limit 默认 8；启动另带 `preview_hash`（64 位十六进制）。拒绝其他输入字段、布尔条数和客户端知识正文/路径。
- `KBRef`：`{id, version, kind, name}`，kind 为 formal/experience。
- `KnowledgeHit`：`{citation_id, record_id, revision, kind, text, score, reasons, source_refs, payload}`。score 是有限 BM25 数值；reasons 为可展示文本列表。payload 是严格白名单 Solver 条目。
- `KBMatch`：`{kb: KBRef, hits: KnowledgeHit[]}`，仅包含该快照的不同合格条目，最多 knowledge_limit 条。候选 KB 数最多 3。
- `RetrievalResult`：`{strategy, inventory_hash, candidates, selected_kb, knowledge, provenance, excluded, omitted, warnings}`。knowledge 是最终 Solver 条目列表，provenance 与其逐条对应。
- `RagPreview`：`{preview_hash, sent:false, can_answer:boolean, blocked_reason:string|null, question_key, question, model_identity, knowledge_limit, retrieval:RetrievalResult, request:dict|null, reserved_tokens:number}`。can_answer 只表示输入/检索/预算允许作答；UI 另结合 bootstrap.service.execution_enabled。
- `FrozenRagConfig`：`{schema_version:1, name, question_key, question, models:[profile], knowledge_limit, strategy, inventory_hash, retrieval, request, transport:{stream:true}, max_calls:1, max_tokens}`。request 含 url、payload、reserved_tokens；max_tokens 等于本次保守预留。无命中预览 request=null，不允许创建 job。
- `RagResult`：`{answer, provenance, selected_kb, retrieval, model_identity, calls:1, charged_tokens, elapsed_seconds}`；不包含 feedback、correct 或 scores。
- `citation_id` 用 kind、原始 id、revision 及公开内容的 canonical hash 生成，例如 `rag_<完整64位hash>`。将此 ID 写入 Solver 条目的 id，原始标识留在 provenance；避免不同 KB 中相同 id 被错误引用。

任务按 1 → 2 → 3 → 4 → 5 → 6 → 7 执行。每个任务先写行为测试、确认预期失败，再实现、确认通过并独立提交。

### Task 1: 公开题面契约与 RAG readiness

**Files:** Create `rag_inputs.py`、`tests/rag_fixtures.py`、`tests/test_studio_rag_inputs.py`; modify `catalog.py`、`tests/test_studio_catalog.py`。

**Interfaces:** Produces `validate_rag_question(public: dict) -> dict`（返回公开载荷或 ValueError）、`rag_ready(public: dict) -> bool`。Catalog 的 list/get 公开 metadata/summary 增加 rag_ready，不改变 ready/kb_ready/evaluation_ready。

- [ ] **Step 1: 写失败测试。** `test_public_only_question_is_rag_ready_without_gt`：三种 split 均允许，缺 GT 不影响 rag_ready，原 ready 不被提升；`test_invalid_public_choices_are_rejected`：不足两项、重复/非法字母、重复候选 ID、空 prompt/family 拒绝；`test_old_record_readiness_is_derived_without_rewriting_hash`：旧记录无 rag_ready 时读出正确值且原文件/hash 不变；`test_all_blocked_sources_disable_rag`：全部 alias.blocked 时 rag_ready=false；`test_private_fields_never_enter_rag_input`：顶层和 view 中注入 correct_letter/metrics/secret 后，公开载荷和 query 不含标记。
- [ ] **Step 2: 运行红灯。** `.venv/bin/python -m pytest tests/test_studio_rag_inputs.py -q`，预期新接口不存在或新 readiness 断言失败，不能因网络/环境失败。
- [ ] **Step 3: 实现。** Catalog 先使用现有公开结构投影，rag_inputs 只验证投影后的必要字段并返回白名单深拷贝；直接传入含未知 view 字段的对象则拒绝，rag_inputs 不反向导入 Catalog。Catalog 导入纯 rag_inputs，老 summary 缺 rag_ready 时按记录 hash 读取其 public 派生，不能递归调用 get_question 或重写记录；来源过滤仍取原 alias.blocked。RAG 后端只使用 `Catalog.get_question(key, include_private=False)['public']`，不得调用私有题集路径。共享测试帮助函数 `make_rag_case(tmp_path: Path, monkeypatch, *, execution_enabled: bool = False) -> dict` 返回 app/client/catalog/models/jobs/question_key/public/model/inventory/selection/state_root/client_factory/calls；只构造临时来源与 dummy 凭据。启用执行的 API 测试也替换 host 检查和 launch；训练与外部网络始终禁止，client_factory 只返回捕获 calls 的 fake。
- [ ] **Step 4: 运行绿灯。** `.venv/bin/python -m pytest tests/test_studio_rag_inputs.py tests/test_studio_catalog.py -q`，预期全部通过。
- [ ] **Step 5: 提交。** 仅暂存本任务文件，commit message：`feat: add public-only RAG question readiness`。

关键断言（测试各自构造公开输入及临时 Catalog）：
```python
# test_public_only_question_is_rag_ready_without_gt
assert rag_ready(public_without_gt) is True
assert record["metadata"]["rag_ready"] is True
assert record["metadata"]["ready"] is False
# test_old_record_readiness_is_derived_without_rewriting_hash
assert original_file.read_bytes() == original_bytes
```

### Task 2: 可信知识准入、来源排除与去重

**Files:** Create `rag_retrieval.py`、`tests/test_studio_rag_retrieval.py`; extend `tests/rag_fixtures.py`。

**Interfaces:** Consumes Task 1 的公开题面；produces `collect_candidates(question: dict, inventory: dict) -> dict`，返回 entries/excluded/warnings/inventory_hash。entry 包含 kb refs、原始身份、白名单 payload、公开索引文本和匹配条件理由。

- [ ] **Step 1: 写失败测试。** `test_only_verified_enabled_applicable_rules_are_admitted`：legacy/disabled/out-of-scope 无法进入 entries，合格规则通过；`test_related_episode_excludes_dependent_lessons` 参数化 id/dataset_id/lineage_id/pair_id：任一非空重合即排除关联经验，None 不排除无关案例；`test_retired_unsealed_other_family_lessons_are_excluded`；`test_corrupt_source_does_not_hide_valid_library`：坏来源有 warning，合格来源仍可用；`test_duplicate_records_preserve_all_provenance_without_extra_weight`：相同版本/内容只有一个 entry，但 source refs 保留；同 ID 不同内容/版本保留为不同 entry。
- [ ] **Step 2: 运行红灯。** `.venv/bin/python -m pytest tests/test_studio_rag_retrieval.py -q`，预期 collect_candidates 缺失。
- [ ] **Step 3: 实现。** 使用 `resolve_initial_knowledge` 核验目录身份及来源。正式规则对本题所有候选组合调用 `match_validated_scope` 和 `match_rule`，记录适用组合，不使用已提前截断的 `_knowledge` 结果。经验沿用 sealed 检查，refs 必须非空且全部来自允许案例；仅投影 text/conditions/exceptions 和来源标识。内容去重键为 kind+原始 id+revision+公开 payload hash；不同快照保留成员关系，用于之后分别排名。inventory_hash 包含全部目录 item 的 id/version/kind 和来源身份，不含读取时间；不把私有反馈或路径作为检索文本。
- [ ] **Step 4: 运行绿灯。** `.venv/bin/python -m pytest tests/test_studio_rag_retrieval.py tests/test_studio_knowledge.py tests/test_studio_initial_knowledge.py -q`，预期通过。
- [ ] **Step 5: 提交。** `feat: admit provenance-checked RAG knowledge`。

关键断言（测试中的 foreign_lesson_id 与 related_lesson_id 来自各自封存来源）：
```python
# test_related_episode_excludes_dependent_lessons
assert foreign_lesson_id in admitted_original_ids
assert related_lesson_id not in admitted_original_ids
# test_duplicate_records_preserve_all_provenance_without_extra_weight
assert len(duplicate_entries) == 1
assert len(duplicate_entries[0]["source_refs"]) == 2
```

### Task 3: 确定性检索、KB 排名与精确预算预览

**Files:** Extend `rag_retrieval.py`、`tests/test_studio_rag_retrieval.py`; create `rag.py`；预览测试先放入 `tests/test_studio_rag_execution.py`。

**Interfaces:** Produces `retrieve_knowledge(question: dict, inventory: dict, *, knowledge_limit: int = 8) -> dict`（RetrievalResult）、`freeze_rag_model(models: ModelRegistry, model_id: str, *, allowed_roots: list[Path]) -> dict`、`build_rag_request(question: dict, knowledge: list[dict], model: dict) -> dict`、`prepare_rag(catalog: Catalog, models: ModelRegistry, inventory: dict, *, question_key: str, model_id: str, knowledge_limit: int = 8, allowed_roots: list[Path]) -> tuple[dict, dict]`（FrozenRagConfig, RagPreview）。

- [ ] **Step 1: 写失败测试。** `test_chinese_and_identifier_terms_rank_relevant_kb_first`；`test_verified_applicable_rule_precedes_unverified_lesson`；`test_ranking_is_stable_after_inventory_permutation`；`test_same_family_alone_is_not_a_lesson_match`；`test_duplicate_terms_and_empty_documents_have_finite_scores`；`test_best_hit_after_twelfth_record_is_not_preclipped`（第 13 条最相关条目仍胜出）；`test_candidates_max_three_and_knowledge_limit_one_to_twelve`；`test_empty_library_and_no_match_have_distinct_block_reasons`（empty_library/no_match，request=null，can_answer=false）。预算测试验证最后一条放不下时整条省略、Prompt 与选中列表一致，零条剩余或题面超限返回明确预算错误。
- [ ] **Step 2: 运行红灯。** `.venv/bin/python -m pytest tests/test_studio_rag_retrieval.py tests/test_studio_rag_execution.py -q`，预期新检索/预览接口未实现。
- [ ] **Step 3: 实现排名。** strategy=`public_features_text_v1`；英文/数字标识符小写，中文连续片段用相邻双字；BM25 用 k1=1.2、b=0.75、正 IDF `log(1+(N-df+0.5)/(df+0.5))`，查询词去重。零文档或平均长度零时分数为零。经验索引不把共同 family 及身份字段当作实质命中；使用文本与条件/例外词项。公开条件信号为去重的查询条件词与规则/经验条件词交集数；family 限制和规则适用性单独作为门槛。理由将此信号标为「条件文本相关」，不能把词项重合宣称为数值条件已满足；正式规则适用理由只能来自 canonical 匹配结果。条目按 verified-applicable、条件信号、BM25 降序，citation_id 升序排序；快照比较其前三条不同命中的三项信号（不含 citation_id），不足三条补最低键，最后 id/version 升序。相同 entry 可属于多个快照，但每个快照与最终载荷中只计一次。
- [ ] **Step 4: 实现预览。** 在内存维护最多 8 个索引的 LRU 缓存，key 为策略版本、目录指纹和去重候选公开内容哈希；每次先核验来源再查询缓存。profile 停用即拒绝；API 冻结 api_identity 并在服务端检查凭据可读，不调用 models.check；自托管有 lock 时使用 resolve_path、read_runtime_lock 并冻结其 hash，没有 lock 时诚实标注 weights_verified=false。用原 Solver role_prompt、model_config 和 build_request_payload 构造唯一 request；载荷为公开 question 与 citation_id 化的 knowledge。预算沿用 `len(prompt.encode()) + max_tokens + 256 <= context_size`，按排名依次整条尝试，超限记录 omitted。仅使用排名第一的 KB，不拼其他快照。preview_hash 为 config 与 source_fingerprint 的 canonical hash，不能包含时间戳。冻结和外部预览均不包含完整 snapshots/episodes/evidence、GT 或明文凭据。
- [ ] **Step 5: 运行绿灯。** `.venv/bin/python -m pytest tests/test_studio_rag_retrieval.py tests/test_studio_rag_execution.py tests/test_studio_initial_knowledge.py -q`，预期通过且测试捕获的模型调用为零。
- [ ] **Step 6: 提交。** `feat: rank KB matches and preview bounded RAG requests`。

关键断言（正向 case、预算用例及空目录分别构造）：
```python
assert result["strategy"] == "public_features_text_v1"
assert len(result["candidates"]) <= 3
assert len(result["knowledge"]) <= 8
assert reversed_result == result
assert clipped_preview["request"]["payload"] == clipped_config["request"]["payload"]
assert empty_preview["blocked_reason"] == "empty_library"
assert empty_preview["request"] is None and empty_preview["can_answer"] is False
```

### Task 4: 单次 RAG 调用、收据与 worker 集成

**Files:** Extend `rag.py`、`tests/test_studio_rag_execution.py`; modify `jobs.py`、`execution.py`、`events.py`、`tests/test_studio_jobs.py`、`tests/test_studio_streaming.py`。

**Interfaces:** Consumes FrozenRagConfig；produces `execute_rag(store: JobStore, identifier: str, config: dict, *, client_factory=None) -> dict`（RagResult）。None 时惰性导入现有 create_client，测试显式注入 fake；不调用 execute_evaluation。

- [ ] **Step 1: 写失败测试。** `test_wire_equals_preview_and_completed_call_replays_once`：保存的 actual_request messages 与预览逐字相同，首次 calls=1，重放不再调用；`test_rag_result_has_no_gt_or_scores`：查询/请求/配置/结果/事件无 GT 标记，评分/训练 mock 从不调用；`test_rag_worker_dispatch_preserves_matching_artifact`：worker 读取冻结 job 并保存 result.json；`test_unknown_citations_are_flagged_not_resolved`；`test_invalid_ranking_preserves_raw_response_and_fails`；`test_timeout_after_send_is_uncertain_and_never_retried`；`test_api_alias_is_recorded_but_self_hosted_identity_is_strict`；`test_split_reflected_api_secret_is_redacted_in_rag_stream_and_records`；`test_new_route_source_changes_job_fingerprint`。
- [ ] **Step 2: 运行红灯。** `.venv/bin/python -m pytest tests/test_studio_rag_execution.py -q`，预期 rag kind/execute_rag 缺失。
- [ ] **Step 3: 实现持久调用。** 执行前核对 request 与从冻结 question/knowledge/model 重建的请求相等，拒绝 transport 非 stream:true。先保存 `retrieval.json`，再发送 input/retrieval 阶段事件。operation key=`rag:<question_key>:<model_id>`；使用 store.boundary/reserve/update_record/append_stream/finish，stream 归属 solver、round_index=0。create_client 复用 credential_root 与脱敏，runtime verifier 前后执行。API 保留实际 response model，其他模型保持精确身份匹配。正常 stop 才 parse_json_response 并 `_answer`；unknown citation 用 invalid_citations 标注并仅解析提供过的 ID。无效 ranking/finish 保存 raw 和 invalid 记录后报错，不写替代答案。发送后无响应是 uncertain，发送前失败是 failed；usage 使用正整数，缺失时取预留，有实际超预算时保存并报错。已 complete 收据直接复用，invalid 收据维持失败，pending/uncertain 禁止新调用。
- [ ] **Step 4: 接入 worker。** JobStore.create 允许 rag；worker 惰性分派 execute_rag，仍先 require_execution_host 与 source_fingerprint 校验。指纹包含 `services/kb_workflow_api` 下所有 Python 源码，保留原扫描范围；旧运行的 fingerprint 不修改。事件增加 retrieval→harness/retrieve，提交答案使用现有 commit 节点；功能顺序为 input/retrieval/solver/commit/complete。
- [ ] **Step 5: 运行绿灯。** `.venv/bin/python -m pytest tests/test_studio_rag_execution.py tests/test_studio_jobs.py tests/test_studio_streaming.py tests/test_studio_execution.py tests/test_studio_api_models.py -q`，预期全部通过，无真实网络。
- [ ] **Step 6: 提交。** `feat: execute RAG answers with durable receipts and streams`。

关键断言（使用 fake client 与临时 JobStore）：
```python
assert len(calls) == 1  # 成功重放后仍为一次
assert record["actual_request"]["payload"]["messages"] == preview["request"]["payload"]["messages"]
assert not {"feedback", "correct", "scores"} & result.keys()
assert timeout_record["status"] == "uncertain"
assert answer["invalid_citations"] is True
```

### Task 5: RAG API、预览失效与幂等启动

**Files:** Create `services/kb_workflow_api/rag_routes.py`、`tests/test_studio_rag_api.py`; modify `services/kb_workflow_api/app.py`。

**Interfaces:** Consumes prepare_rag/JobStore；produces `register_rag_routes(api: FastAPI, *, catalog: Catalog, models: ModelRegistry, jobs: JobStore, inventory_provider: Callable[[], dict], require_execution: Callable[[], None], allowed_roots: list[Path]) -> None`。注册 `POST /api/studio/rag/preview` 和 `POST /api/studio/rag/runs`。

- [ ] **Step 1: 写失败测试。** `test_preview_is_public_and_creates_no_job_or_call`；`test_preview_rejects_invalid_limit_extra_fields_and_inline_knowledge` 参数化 false/0/13、snapshot、path 和未知键；`test_run_requires_authorized_execution`；`test_stale_preview_rejects_before_job_or_launch` 参数化知识 version/来源篡改/model revision/credential rotation/题目 key/limit/source fingerprint；`test_duplicate_submission_returns_one_job_and_one_launch`；`test_idempotency_key_reuse_with_other_selection_conflicts`；`test_no_match_cannot_create_rag_job`；`test_run_can_be_read_and_streamed_through_existing_routes`。
- [ ] **Step 2: 运行红灯。** `.venv/bin/python -m pytest tests/test_studio_rag_api.py -q`，预期接口 404。
- [ ] **Step 3: 实现。** 薄注册模块按共享契约严格校验输入。preview 调用 inventory_provider 和 prepare_rag，返回 RagPreview。runs 先 require_execution，必须重新解析并核验来源/模型，再比 preview_hash；合法选择但来源/配置变化统一 409，没有预览或无匹配拒绝。未知题目/模型为 404，初次预览输入不合法为 422。由 jobs.create('rag', config, idempotency_key=...) 冻结，再 launch queued job，返回 public_job。幂等同键同配置不再次 launch，冲突用 409；启动过程中 queued→starting 的并发竞争也只允许一个 worker，重复请求读取同一 job。app.py 注入 `lambda: knowledge_inventory(jobs, archives())` 以及原 require_execution，不修改旧 freeze_run 分支和科学 API 模型限制。
- [ ] **Step 4: 运行绿灯。** `.venv/bin/python -m pytest tests/test_studio_rag_api.py tests/test_studio_api.py tests/test_studio_api_models.py tests/test_studio_workflow.py -q`，预期通过；测试替换 host 检查及 jobs.launch，不能实际启动服务器调用。
- [ ] **Step 5: 提交。** `feat: expose preview-guarded RAG APIs`。

关键断言（fixture 的 host/launch 已替换）：
```python
assert stale_response.status_code == 409
assert not jobs.list() and launch.call_count == 0
assert first_response.json()["id"] == repeated_response.json()["id"]
assert launch.call_count == 1
assert preview_response.json()["sent"] is False
```

### Task 6: 单题选择、匹配预览与页面入口

**Files:** Create `ragTypes.ts`、`Rag.tsx`、`rag.css`、`Rag.test.tsx`、`App.test.tsx`; modify `App.tsx`、`Questions.tsx`、`QuestionPicker.tsx`、`types.ts`、`Questions.test.tsx`、`QuestionPicker.test.tsx`。

**Interfaces:** Produces `Rag({version, act, models, executionEnabled, questionKey, onQuestion, onRun})`。props 分别为 number、Action、ModelProfile[]、boolean、可选 string、`(key:string)=>void`、`(id:string)=>void`。Questions 新增可选 `onRag:(key:string)=>void`；QuestionPicker purpose 增加 rag，并增加可选 `onSelectQuestion:(key:string)=>void`，原 onApply 仅在 research/evaluation 必需。

- [ ] **Step 1: 写失败测试。** `Rag.test.tsx`：选择题/模型后预览展示三候选、命中、验证状态和实际输入；空目录与无命中提示分别准确且启动禁用；修改任一选择清空旧预览；旧请求晚返回不能覆盖新选择；本地 executionEnabled=false 允许预览而拒绝启动；提交带精确 preview_hash 和重复点击防护；409 清除预览提示重查。`QuestionPicker.test.tsx`：rag 单选没有 discovery split 参数，所有有效分区和无 GT 题面可选，直接返回 key，**不 POST /question-sets**；原 research/evaluation 行为保持。`App.test.tsx`：题目详情按钮带正确版本 key 打开 #rag，既有共享 workflow draft 不变。
- [ ] **Step 2: 运行红灯。** 在 `frontend/workflow` 运行 `npm test -- Rag.test.tsx App.test.tsx QuestionPicker.test.tsx Questions.test.tsx`，预期缺组件/新行为断言失败。
- [ ] **Step 3: 实现。** App 增加 rag 导航及当前 question key；Questions 详情添加快捷入口。RAG 选择器用 rag_ready 和公开题面验证，旧 metadata 缺字段时读取详情再判断；不得借 ready/kb_ready 或 GT 判断。保持原选择器用途的流程与回调兼容。Rag 复用 QuestionReader、模型 select、ErrorBox/Loading/Card；knowledge_limit 默认 8 范围 1–12。页面调用 /rag/preview，使用请求序号或取消机制处理过时响应。can_answer 与 executionEnabled 同时满足才启动；POST /rag/runs 使用本次固定 Idempotency-Key，失败重试同选择同键，变更选择换键。成功 onRun(id)；匹配分数标为相关性信号，经验明确待验证。配置恢复不涉及旧 workflow draft。
- [ ] **Step 4: 运行绿灯。** 同 Step 2 命令；再运行 `npm run build`，预期 Vitest 通过且 TypeScript/Vite 构建成功。
- [ ] **Step 5: 提交。** `feat: add question-aware RAG preview and launch page`。

关键断言（复用当前 Vitest mock 风格，不新增 DOM matcher 依赖）：
```typescript
expect((screen.getByRole('button', {name:'启动 RAG 作答'}) as HTMLButtonElement).disabled).toBe(true);
expect(onSelectQuestion).toHaveBeenCalledWith('q1@revision');
expect(postedPaths).not.toContain('/question-sets');
expect(screen.queryByText('旧题的匹配结果')).toBeNull();
```

### Task 7: 回答/引用、历史运行与完整回归

**Files:** Create `RagRunView.tsx`、`RagRunView.test.tsx`; modify `Runs.tsx`、`Runs.test.tsx`、`displayNames.ts`、`displayNames.test.ts`、`rag.css`、`docs/WORKFLOW_STUDIO.md`；extend `tests/test_studio_rag_api.py`。

**Interfaces:** Consumes Run/FrozenRagConfig/RagResult；produces `RagRunView({run}: {run: Run})`。使用 RunStreamProvider/useLiveOutput/LiveOutput，nodeId=solver、round=0，operation key 与 Task 4 相同；RunDetail 用 useRunMonitor 已有轮询，不建立新状态通道。

- [ ] **Step 1: 写失败测试。** `RagRunView.test.tsx`：只有实际 chunk 才产生正文，终态显示封存 ranking/rationale；提供知识与返回引用分别展示；未知 ID 无链接且有异常提示，重复内容保留所有来源；无任何 accuracy/GT 图表；失败/uncertain 保留已收到文本和实际收据提示。`Runs.test.tsx`：rag 类型筛选、中文名称、详情及重新打开不触发 POST。API 集成 `test_preview_start_fake_worker_history_and_sse_agree`：完整预览→提交→mocked worker→历史与 SSE，三处知识/来源一致，一次模型调用，KB 源文件内容及已有 workflow definition 未变。
- [ ] **Step 2: 运行红灯。** 前端 `npm test -- RagRunView.test.tsx Runs.test.tsx displayNames.test.ts`；后端 `.venv/bin/python -m pytest tests/test_studio_rag_api.py -q`，预期缺 RAG 详情/集成行为。
- [ ] **Step 3: 实现。** RunDetail 针对 kind=rag 展示 RagRunView，列表增加 RAG 过滤与 label；展示冻结 question/KB/模型身份、匹配理由、明确的验证状态和可信来源映射。模型使用来源只解析已提供 citation_id，invalid_citations 原样提示。使用原 RunControls 与 RunFailure 信息，不提供 GT 或评分入口。WORKFLOW_STUDIO.md 增加真实入口、空目录处理、预览/启动环境差异、所用文本检索策略和来源说明，不写私有服务器信息。
- [ ] **Step 4: 执行最终验证。** 先验证 repository/import provenance；在仓库运行 `.venv/bin/python -m pytest -q`，在 `frontend/workflow` 运行 `npm test` 和 `npm run build`，最后 `git diff --check`。预期全部测试和构建通过；已知 warning 如未改变可记录，不重复跑已通过套件。
- [ ] **Step 5: 做本地无调用验收。** `bash tools/studio_server.sh --check` 核对源码/进口路径及编辑模式；启动本地服务并检查真实接口/前端资源。用允许的浏览器工具验证窄屏选择器、空 KB 页面和匹配预览；若浏览器安全策略仍阻止 localhost，不能绕过，报告 HTTP/组件测试证据与未完成的可视验收。生产页面仅呈现持久化真实数据，mock 来源留在测试内。
- [ ] **Step 6: 提交与交付。** `feat: show RAG answers and traceable sources in run history`。检查 git status/diff 只含预期源码、文档和测试；报告测试计数、实际检索策略及真实模型调用是否验证。遵守已授权的 GitHub 同步范围，推送前确认公开仓库不含私有配置/运行产物。本任务不自动部署服务器；若进行真实 smoke，只在私有配置中指定的授权服务器，以合法非空 KB 执行并单独记录结果。

关键断言（模拟 SSE 只在测试中注入，生产不产生示例输出）：
```typescript
expect(screen.queryByText('真实增量正文')).toBeNull(); // 尚未收到 chunk
// 测试发出匹配 node/round/operation 的持久化 chunk 后：
expect(await screen.findByText('真实增量正文')).toBeTruthy();
expect(screen.queryByRole('link', {name:'未知知识条目'})).toBeNull();
```

## 开始执行前与审阅记录

- [ ] 用户审阅本计划并选择执行方式后才开始产品代码修改。
- [ ] 执行前使用 using-git-worktrees 检查是否需要隔离；以仓库实际状态和既有合适 worktree 为准，不复制 ignored 数据或秘密。
- [ ] 选择当前对话执行时使用 executing-plans；选择子代理时使用 subagent-driven-development，不提前派发实现任务。
- [x] 计划自检：设计中的流程、准入、排名、预算、事件/收据、错误、页面和回归均有对应任务；Task 1 的 readiness 不改既有评测资格，Task 4 不复用 GT 评测执行器。
- [x] 接口自检：7 个任务中的 knowledge_limit/preview_hash、模型载荷、引用 ID、事件节点与运行类型一致；新增路由源码纳入指纹。
- [x] Review Focus 五类输入均已分配到具体失败测试；无产品实现或真实模型调用发生。
