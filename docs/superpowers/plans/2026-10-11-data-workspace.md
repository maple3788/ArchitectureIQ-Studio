# Data Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可独立使用的 Dataset 管理、总题库去重、做题式阅读和分块构题，并将选定 Dataset 安全接入现有工作流。

**Architecture:** 在现有不可变 Catalog 记录之上增加严格等价索引和具有修订历史的 Dataset 集合层。保持旧 question_set、生成引擎和运行协议，新增 API 适配与独立 Data 前端组件。Dataset 输入契约供后续可组合 Harness 与 KB 适用题目查询复用。

**Tech Stack:** 现有 Python/FastAPI/SQLite、React 19/TypeScript、Vitest/Testing Library、pytest；复用项目依赖，不增加数据库或通用表单框架。

**Spec:** `docs/superpowers/specs/2026-10-11-research-workspaces-design.md`，重点实现第一阶段及共享对象、迁移、验证要求。

## Global Constraints

- “Dataset 是题目集合，可以相互重叠。另有统一去重的总题库。”
- “第一版不增加人工作答提交和评分。”
- “私有反馈保持隔离。”
- “不同 Dataset 名称不构成数据独立性证明。”
- “所有状态与文本来自持久化事件、收据或 SSE。”
- “运行状态、源数据、凭据、模型权重和构建缓存不进入 Git。”
- 实现与测试仅在本仓库；先运行 `git rev-parse --show-toplevel`，并用准确的测试解释器核对 import provenance。
- 真实模型及生成代码 GT 仅在私有配置指定的授权 Linux 服务器执行；本计划的本地测试全部 mock 执行和模型。复用 canonical spec → generated code → execution → stored results，不写第二套训练逻辑。
- 保留旧题目、草稿、科学/配对协议、封存收据和历史运行；不重写冻结 hash 以恢复旧运行。
- 既有 `dataset_id` 是题内训练实例；命名集合使用 `collection_id`，不得互相替换。
- 用户已选择在当前对话逐项实施。书面计划评审通过后沿用该方式；执行前按 using-git-worktrees 技能确定工作目录，不在计划阶段创建环境或改产品代码。

## Review Focus

- 两个窗口同时改 Dataset 或生成期间归档目标：不能丢失成员或覆盖更新；Task 2、6、7 测试 CAS、归档及用户选择保留。
- 相同展示 ID 但 GT、配置或来源健康状况不同：不能误合并或使坏来源变可用；Task 1、3 测试内容差异、损坏记录与公共输出。
- 跨页筛选、多个版本及历史题对出现新冲突：保留明确顺序与完整题对，不能重新猜测成员；Task 2、4、10 测试冻结引用和选择器行为。
- 生成已完成但收录前崩溃、或收录响应丢失：只重试收录，不能重跑 GT 或产生重复修订；Task 6、9 测试持久化结果与幂等恢复。
- 没有 GT 的公开题目以及旧 Basic 单题流程：前者仍可读，后者不能静默截取 Dataset 第一题；Task 4、8、10 测试用途检查、GT 隔离与旧草稿。

---

## 范围与后续阶段

本计划交付批准规格的第一阶段。可组合 Harness 调度器、KB 草稿管理、反向适用性查询和模型独立 RAG 接口分别进入后续第二、第三阶段计划；本阶段不以占位按钮宣称这些能力已上线。

已有 Harness、KB、Task 页面与旧 URL 继续可用。Data 的 Dataset 输入适配先服务现有方法，后续图执行器直接复用固定输入清单。

执行前核对：

```bash
git rev-parse --show-toplevel
PYTHONPATH=src .venv/bin/python -c 'from pathlib import Path; import architecture_iq; p=Path(architecture_iq.__file__).resolve(); print(p); assert p.is_relative_to(Path.cwd()/"src/architecture_iq")'
```

如果隔离工作目录使用不同解释器路径，记录该准确路径，并对同一解释器执行上面的来源断言和下文 pytest 命令。所有命令在选定仓库根目录运行。

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `src/architecture_iq/studio/question_equivalence.py` | 严格等价的私有投影和版本化指纹。 |
| `src/architecture_iq/studio/question_bank.py` | 可重建等价索引、统一分页和代表记录选择。 |
| `src/architecture_iq/studio/catalog.py` | 提取已验证原始记录读取；保留旧公共投影；增加绑定 Dataset 的新题集冻结适配。 |
| `src/architecture_iq/studio/datasets.py` | 集合、不可变修订、成员顺序、CAS 与操作幂等。 |
| `src/architecture_iq/studio/dataset_inputs.py` | 用途校验、确定性选择、公开清单及旧题集适配。 |
| `src/architecture_iq/studio/dataset_migration.py` | 从已有题源/题集建立 Dataset 引用，幂等迁移报告。 |
| `src/architecture_iq/studio/generation_forms.py` | 真实生成参数的类型、枚举、单位和编辑边界。 |
| `src/architecture_iq/studio/dataset_generation.py` | 生成目标绑定、已生成结果的收录与重试收据。 |
| `services/kb_workflow_api/dataset_routes.py` | Dataset、总题库和输入适配的结构化 HTTP 接口。 |
| `frontend/workflow/src/dataTypes.ts` | 与服务端一致的资源引用、修订、分页和状态类型。 |
| `DataWorkspace.tsx`、`DatasetLibrary.tsx`、`DatasetBrowser.tsx`、`GlobalQuestionBank.tsx` | Data 导航、集合浏览与成员管理。路径均位于 `frontend/workflow/src/`。 |
| `QuestionReadingPage.tsx`、既有 `QuestionReader.tsx` | 完整读题页与无网络副作用的阅读组件。 |
| `QuestionBuilder.tsx`、`GenerationBlocks.tsx`、`generationForm.ts` | schema 驱动构题、请求构造和预检状态。路径均位于 `frontend/workflow/src/`。 |
| `DatasetInputPicker.tsx` | Dataset 选择到既有 `onApply(QuestionSet)` 的适配。路径位于 `frontend/workflow/src/`。 |

只对 `App.tsx`、`Workflow.tsx`、`Generation.tsx` 和 API `app.py` 做必要集成；不借机重写大组件或旧执行器。

## 共享接口约定

所有新接口位于 `/api/studio`。未知字段拒绝；JSON 错误使用 `detail: {code, message, current_revision?, blockers?}`，不回传私有正文。ID 和 hash 是资源引用，不接受客户端自报等价关系、来源身份或 ready 状态。

- `DatasetRef = {collection_id: string, revision: string}`，revision 为不可变内容 hash。
- `PairManifest` 沿用 `studio.pairs.pair_manifest` 的公开输出契约，保留 pair_key、精确 members、身份映射、ready 与 issues；读取旧修订时重新检查健康状态，不修改已冻结内容。
- `DatasetRevision = {collection_id, revision, parent_revision, name, description, archived, selection_mode: "single"|"pairs", keys: string[], pairs: PairManifest[], created_at}`。键顺序有意义；普通集合的 pairs 为空。
- `DatasetSummary = {collection_id, revision, name, description, archived, selection_mode, count, pair_count, families, updated_at}`。
- `BankItem = {equivalence_id, representative_key, keys, summary, sources, datasets}`；summary 为既有公开题目元数据，datasets 为所属集合摘要。不可用来源保留解释。
- `QuestionFilters = {search?: string, family?: string, type?: string, split?: "discovery"|"development"|"final"}`。`Selection = {keys?: string[], pair_keys?: string[], filters?: QuestionFilters, limit?: number, seed?: number}`；keys 与 pair_keys 互斥，显式成员与 filters 互斥。空对象代表整个修订；显式空列表代表空选择。先在修订内筛选、按集合顺序去重，再抽样，最后检查资格；不合格题不会被静默替换。limit 为正整数；指定 seed 时用固定算法抽样并按原顺序输出，未指定 seed 时 limit 表示取前 N 个。题对集合的抽样单位为完整题对。
- `DatasetBinding = DatasetRef & {selection, keys: string[], hashes: string[], pair_keys: string[]}`。
- `SelectionPreview = {binding, preview_hash, can_apply, blockers: {key, code, message}[], questions, count, pair_count}`。questions 只含公开投影；purpose 为 `public|research|evaluation`。
- `DatasetAttachment = {status: "attached"|"revision_conflict"|"archived"|"empty"|"unavailable", target: DatasetRef, result_revision?, question_keys: string[], pair_keys: string[], message?}`。
- 公共分页返回 `{items, total, offset, limit}`。默认 limit=25，范围 1..1000，offset 为非负整数，稳定排序；集合成员按保存顺序。

## Task 1: 严格等价索引和去重题库

**Files:** Create `question_equivalence.py`、`question_bank.py`（以上完整目录）；Modify `src/architecture_iq/studio/catalog.py` 的已验证读取；Test `tests/test_studio_question_bank.py`。

**Interfaces:**
- `Catalog._load_frozen_record(key: str) -> dict`：执行现有 hash 校验，返回服务器内部原始记录；不新增公共私有读取路由。`get_question` 复用它并保持旧投影。
- `equivalence_id(record: dict, *, question_key: str) -> str`：严格策略 `exact_question_v1`；不完整或无法证明等价的记录退回精确 revision 身份。
- `QuestionBank(catalog: Catalog).refresh() -> dict` 与 `.list_questions(*, filters: dict | None = None, offset: int = 0, limit: int = 25) -> dict`；本任务 datasets 暂为空，Task 3 按成员关系补齐。

- [x] **Step 1: 写失败测试。** 复用 `test_studio_catalog.baked/bakefile`；以下是跨显示 ID 的完整等价案例：

```python
def test_different_display_ids_share_exact_content_without_rewriting_records(tmp_path):
    c = Catalog(tmp_path / "state")
    c.import_source(bakefile(tmp_path / "in.json", [baked("q1"), baked("q2")]))
    before = {p.name: p.read_bytes() for p in (c.root / "records").glob("*.json")}
    bank = QuestionBank(c)
    bank.refresh()
    assert bank.list_questions()["total"] == 1
    assert len(bank.list_questions()["items"][0]["keys"]) == 2
    assert {p.name: p.read_bytes() for p in (c.root / "records").glob("*.json")} == before
```

同时增加参数化测试，分别改变候选顺序、候选 ID、dataset/lineage/pair/split、代码、配置和私有反馈，断言 total=2；相似 Prompt 不合并。测试同 ID 新内容保留版本、损坏文件可见但不可选、坏来源不能由等价组变为可用，以及跨分页总量无重复。

- [x] **Step 2: 确认测试失败。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_question_bank.py -q`，预期新模块/接口缺失，不能把依赖安装失败当作红灯。
- [x] **Step 3: 实现接口。** 从已校验记录复制私有等价投影，只移除 `public.id`、`metadata.id/key/hash` 和已知导入管理字段；保留所有语义字段。派生可用性不参与指纹，逐请求从原记录重新核验。未知审计结构无法安全归一时保守分开，禁止递归删除所有 `id` 或 `path`。缓存表位于 Catalog SQLite，带策略版本、原 key/hash 与索引状态；新增记录重建索引，返回代表记录前再次核验，损坏源作为结构化问题保留。代表记录在匹配筛选的有效成员中按 key 稳定选择，不改变 Dataset 中已选精确 key。
- [x] **Step 4: 验证。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_question_bank.py tests/test_studio_catalog.py -q`，预期全部通过；旧公共投影与固定题集 hash 行为不变。
- [x] **Step 5: 提交。** `git add src/architecture_iq/studio/question_equivalence.py src/architecture_iq/studio/question_bank.py src/architecture_iq/studio/catalog.py tests/test_studio_question_bank.py`；`git commit -m "feat: index exact question equivalence for Data"`。

## Task 2: 可编辑 Dataset 和不可变修订

**Files:** Create `src/architecture_iq/studio/datasets.py`; Test `tests/test_studio_datasets.py`。

**Interfaces:**
- `DatasetStore(catalog: Catalog)` 使用同一 SQLite；新增 collections、collection_revisions、collection_operations 表，不修改 questions/question_sets。
- `.create(*, name: str, description: str = "", keys: list[str] | None = None, pair_keys: list[str] | None = None, operation_id: str) -> dict`。
- `.get(collection_id: str, revision: str | None = None) -> dict`、`.list(*, search: str = "", family: str = "", archived: bool = False, offset: int = 0, limit: int = 25) -> dict`。
- `.list_members(ref: dict, *, filters: dict | None = None, offset: int = 0, limit: int = 25) -> dict` 返回分页公开题目摘要，按修订顺序；损坏成员返回原 key 与结构化不可用状态，不让整页失败。
- `.revise(collection_id: str, *, expected_revision: str, changes: dict, operation_id: str) -> dict`，changes 仅接受 name、description、archived、keys、pair_keys；成员修改采用完整有序替换，keys 与 pair_keys 互斥。提交 keys 切换为 single，提交 pair_keys 切换为 pairs，未提交成员字段则保留模式；空 pair_keys 允许建立空题对集合。
- `.memberships(keys: list[str]) -> dict[str, list[dict]]`；`DatasetConflict` 提供 current_revision，`DatasetArchived` 表示目标不可修改。

- [x] **Step 1: 写失败测试。** 新集合可空、包含未 ready 记录、跨集合共享题目；用完整公开 fixture 做以下断言：

```python
def test_shared_membership_and_duplicate_operation_do_not_copy_questions(tmp_path):
    c = Catalog(tmp_path / "state")
    c.import_source(bakefile(tmp_path / "in.json", [baked()]))
    key = c.list_questions()["items"][0]["key"]
    s = DatasetStore(c)
    a = s.create(name="A", keys=[key, key], operation_id="a")
    b = s.create(name="B", keys=[key], operation_id="b")
    assert a["keys"] == b["keys"] == [key]
    assert s.create(name="A", keys=[key, key], operation_id="a") == a
    assert c.stats()["questions"] == 1
```

追加 `test_stale_revision_preserves_both_memberships`、`test_remove_and_archive_preserve_old_revision_and_question`、`test_operation_id_reuse_with_different_body_conflicts`、`test_pair_revision_survives_later_catalog_pair_ambiguity`；断言旧修订字节/JSON 不变、同操作重试只生成一个修订、冲突不改变当前版本。成员分页覆盖混合 family、损坏成员与保存顺序；集合类型筛选匹配包含该类型的集合。测试模式切换完整替换成员、不能留下旧 pairs。

- [x] **Step 2: 确认红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_datasets.py -q`，预期缺少 DatasetStore。
- [x] **Step 3: 实现事务。** 稳定 ID 使用 `ds_` 加随机 UUID；revision 对身份、父修订和完整内容计算 hash。内容、当前指针和操作结果在同一 `BEGIN IMMEDIATE` 事务提交，归档也产生修订。等价成员按首个明确选择去重，不切换其来源 key。Dataset 保存题对时从 Catalog 核验并复制完整 pair_manifest；以后通过精确成员重新核验，不依赖全目录重新猜测配对。名称去空白后必填，未知题目拒绝；不以 ready 状态限制集合成员。
- [x] **Step 4: 验证。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_datasets.py tests/test_studio_question_bank.py tests/test_studio_pairs.py -q`，预期 PASS，包含两个独立 Store 实例竞争相同基准修订的测试。
- [x] **Step 5: 提交。** `git add src/architecture_iq/studio/datasets.py tests/test_studio_datasets.py`；`git commit -m "feat: add versioned Dataset collections"`。

## Task 3: Data API、导入和旧资源迁移

**Files:** Create `src/architecture_iq/studio/dataset_migration.py`、`services/kb_workflow_api/dataset_routes.py`、`tests/test_studio_dataset_api.py`、`tests/test_studio_dataset_migration.py`; Modify `services/kb_workflow_api/app.py`。

**Interfaces:**
- `migrate_legacy_datasets(catalog: Catalog, datasets: DatasetStore) -> dict`：返回 created/skipped/errors；一次性启动迁移按 origin kind/id/hash 幂等登记已存题集与题源，不扫描源目录，不自动导入外部文件。
- `register_dataset_routes(api, *, catalog, bank, datasets, allowed_roots)`；将实例登记到 `api.state.datasets`、`api.state.question_bank`。
- `GET/POST /datasets`、`GET /datasets/{id}?revision=...`、`GET /datasets/{id}/questions?revision=...`、`POST /datasets/{id}/revisions`、`GET /question-bank`；成员与总题库支持 QuestionFilters 和分页，Dataset 列表支持 search/family/archived。写请求使用 Idempotency-Key，修订携带 expected_revision。
- `POST /datasets/{id}/imports` 接收 `{expected_revision, source_id}`，只加入已登记来源报告中的精确 key；上传/路径导入继续走已有受限 source API，再执行成员收录。

- [x] **Step 1: 写失败 API 测试。** 复用 `test_studio_api.make_client`：

```python
def test_dataset_api_is_available_locally_and_returns_structured_conflict(tmp_path):
    client, _ = make_client(tmp_path)
    a = client.post("/api/studio/datasets", json={"name": "A"},
                    headers={"Idempotency-Key": "create"}).json()
    path = f"/api/studio/datasets/{a['collection_id']}/revisions"
    body = {"expected_revision": a["revision"], "changes": {"name": "B"}}
    assert client.post(path, json=body, headers={"Idempotency-Key": "edit"}).status_code == 200
    body["changes"] = {"name": "C"}
    response = client.post(path, json=body, headers={"Idempotency-Key": "stale"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dataset_revision_conflict"
```

增加响应序列化不含 GT sentinel、旧 `/questions` 计数不受等价分组改变、`/question-bank` 汇总全部成员 Dataset、来源导入重试不重复收录、路径越界仍拒绝的测试。迁移测试连续运行两次，断言相同集合身份、旧 records/sets 字节不变；缺失题目记录报告错误并保持原资源可查。

- [x] **Step 2: 确认红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_dataset_api.py tests/test_studio_dataset_migration.py -q`，预期新路由 404 或新迁移接口缺失。
- [x] **Step 3: 实现路由和迁移。** API 保留结构化 404/409/422，默认分页值来自共享约定。按现有 `register_rag_routes` 模式注册，避免继续扩充 app.py 内联业务。迁移仅首次登记 origin；已有用户编辑的 Dataset 不被后续启动覆盖。新来源导入失败或目标冲突时保留来源和用户选择，不能回滚已登记题目或静默截断成员。
- [x] **Step 4: 验证。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_dataset_api.py tests/test_studio_dataset_migration.py tests/test_studio_api.py -q`，预期 PASS，真实执行保持关闭。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: expose Dataset management and legacy resource migration"`。

## Task 4: Dataset 选择预览和旧工作流输入适配

**Files:** Create `src/architecture_iq/studio/dataset_inputs.py`、`tests/test_studio_dataset_inputs.py`; Modify `catalog.py`、`dataset_routes.py`、`tests/test_studio_dataset_api.py`。

**Interfaces:**
- `DatasetInputs(catalog: Catalog, datasets: DatasetStore).preview(ref: dict, selection: dict, *, purpose: str, method_id: str | None = None, phase: str | None = None) -> dict` 返回 SelectionPreview，无写入和真实调用。
- `.materialize(ref: dict, selection: dict, *, purpose: str, preview_hash: str, method_id: str | None = None, phase: str | None = None) -> dict` 返回既有公共 QuestionSet，包含服务器生成的 dataset_binding。
- `POST /datasets/{id}/selection-preview`、`POST /datasets/{id}/question-set` 接受上述明确字段；public 用途只提供预览，不创建要求反馈的旧题集。
- `Catalog.create_question_set(name, keys, *, dataset_binding: dict | None = None)`；新增 `create_bound_pair_set(name: str, pairs: list[dict], *, dataset_binding: dict) -> dict`，核验冻结 pair_manifest 精确成员后组装旧格式。pairs 只能由 DatasetInputs 从服务端修订提供，不从 API 请求接收。复用 `_question_set_body`、`_store_question_set` 及现有配对验证，不创建第二套反馈封存格式。绑定在新快照 hash 计算前加入，旧调用默认输出不变。

- [x] **Step 1: 写失败测试。** `test_public_only_question_previews_without_gt` 断言 purpose=public、rag_ready 题的 can_apply=true 且无 feedback；`test_basic_dataset_does_not_silently_select_first_question` 使用两道完整题：

```python
preview = inputs.preview(ref, {}, purpose="research", method_id="basic_learning")
assert preview["can_apply"] is False
assert preview["count"] == 2
assert any(b["code"] == "basic_requires_one_question" for b in preview["blockers"])
assert catalog.list_question_sets() == []
```

同一测试文件按 Task 2 接口创建 catalog/datasets/ref/inputs；两题 fixture 使用不同训练实例，避免被严格等价去重。另测确定性抽样、显式顺序、空列表与整套选择的区别、完整题对、evaluation phase、源健康变化使 preview_hash 失效、旧 Dataset 修订不随当前版本变化，以及 materialize 后新编辑不改变已保存题集。未知/不可用成员不能静默消失。

- [x] **Step 2: 确认红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_dataset_inputs.py -q`，预期接口缺失。
- [x] **Step 3: 实现选择与冻结。** 固定集合 revision 后进行筛选/抽样，保留明确精确 key；检查用途、方法和 phase，复用现有公开 readiness 与研究/配对校验。预览 hash 包含选择、顺序、题目 hash、用途和可用性依据。materialize 重新校验同一输入后才创建题集；不修改 workflow 草稿。历史 pair_manifest 按精确成员重算核验，不能被后来导入的同 pair_id 新版本替换。
- [x] **Step 4: 验证。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_dataset_inputs.py tests/test_studio_dataset_api.py tests/test_studio_catalog.py tests/test_studio_pairs.py tests/test_studio_task_inputs.py -q`，预期 PASS。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: freeze Dataset selections for existing research methods"`。

## Task 5: 真实生成能力的分块表单 schema

**Files:** Create `src/architecture_iq/studio/generation_forms.py`、`tests/test_studio_generation_forms.py`; Modify `src/architecture_iq/studio/generation.py`。

**Interfaces:**
- `family_form_schema(profile, family) -> dict`：返回 version、editable_fields 和 read_only_facts；字段具有 name、label、type、enum/min/max、unit、required、default_mode。
- `validate_family_options(profile, family, options: dict) -> dict`：与 schema 使用同一枚举/约束来源，替代 `_family_options` 内重复分支；旧合法输入与归一化结果一致。
- `capabilities().profiles[].families[].form_schema` 新增上述值；现有 options/config/data_interventions 保留。

- [x] **Step 1: 写失败测试。** 对当前注册的全部 profile/family 逐一断言 editable_fields 的字段名等于真实 instance_option_names；input_dim、rule_family 枚举来自 profile。断言 univariate、spiral、bigram 的普通可编辑 family options 为空；只读采样条件不会变为请求参数。

```python
def test_univariate_exposes_read_only_rules_and_rejects_fake_noise_option():
    caps = capabilities()
    profile = next(p for p in caps["profiles"] if p["name"] == "v1.4")
    family = next(f for f in profile["families"] if f["name"] == "univariate_regression")
    assert family["form_schema"]["editable_fields"] == []
    with pytest.raises(ValueError):
        validate_generation(config(family_options={"noise_std": 0.1}))
```

`config` 复用 `test_studio_generation.config`。题对表单验证现有 domain 区间和 alpha `[0,100]`，后端仍调用 family-owned intervention validator。

- [x] **Step 2: 确认红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_generation_forms.py -q`，预期 form_schema 缺失。
- [x] **Step 3: 实现 schema。** Studio 层包装现有能力，不修改 bundled family 引擎。沿用 candidate_count 2..20、n_seeds 1..10、num_questions 1..100、candidate-seed runs ≤200 及 profile budgets；自动采样值与显式设置区分，不编造默认值。无可编辑参数的块展示只读说明。
- [x] **Step 4: 验证。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_generation_forms.py tests/test_studio_generation.py tests/test_studio_pair_generation.py -q`，预期 PASS，GT 使用已有 mock。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: describe canonical generation fields for Data forms"`。

## Task 6: 生成结果加入 Dataset 与独立收录恢复

**Files:** Create `src/architecture_iq/studio/dataset_generation.py`、`tests/test_studio_dataset_generation.py`; Modify `src/architecture_iq/studio/{generation.py,pair_generation.py,datasets.py}`、`services/kb_workflow_api/{app.py,dataset_routes.py}`、`tests/test_studio_dataset_api.py`。

**Interfaces:**
- 生成配置新增可选 `dataset_target: DatasetRef`；`validate_generation` 仅校验形状、保留值，canonical 数据/候选身份计算不使用它。旧无 target 配置和归一化结果不变。
- `validate_generation_target(config: dict, datasets: DatasetStore) -> str | None` 检查目标存在、当前修订一致且未归档，返回与规范化配置绑定的 preview hash。
- `/generations/preview` 对带 target 的请求额外返回 `dataset_preview_hash`；`/generations` 提取该字段，重新规范化、校验并比较；带 target 时缺失或失效返回 409，旧不带 target 请求保持原行为。
- `attach_generation_result(store, catalog, datasets, *, run_id: str, target: dict, operation_id: str) -> dict`：仅读取该运行已持久化 manifest 的 import_report，返回 DatasetAttachment。
- `get_generation_attachment(datasets, *, run_id: str) -> dict | None` 返回最新持久化收录投影；由专用查询及 app.py 的 job 响应组装复用，不让 `public_job` 自行访问文件系统。
- `DatasetStore.attach(collection_id: str, *, expected_revision: str, keys: list[str], pairs: list[dict], run_id: str, operation_id: str) -> dict` 以运行/操作 ID 记录 DatasetAttachment；成功的成员追加与收据在同一事务。失败结果也有持久化收据但不改变集合；相同 ID 不同正文返回冲突。
- `GET /generations/{run_id}/dataset-attachment`、`POST /generations/{run_id}/dataset-attachment`；POST 仅接受 target 和 Idempotency-Key，不接受题目正文或客户端题目清单，不调用 worker launch。

- [x] **Step 1: 写失败测试。** 复用现有 generation/pair_generation fixture 和 GT mock；测试目标进入预览 hash、修改目标使提交失效；成功/部分成功导入用 `import_report.entries[].key` 收录，不按原始 ID 查最新题。最关键的恢复断言：

```python
first = attach_generation_result(store, catalog, datasets, run_id=run_id,
                                 target=target, operation_id="attach")
second = attach_generation_result(store, catalog, datasets, run_id=run_id,
                                  target=target, operation_id="attach")
assert first == second
assert first["status"] == "attached"
assert canonical_calls == calls_before_attachment
```

在测试内按 Task 2 建立目标，以现有 mocked generator 生成持久化 manifest，并将 generation/GT 重入函数替换成 `pytest.fail`。增加“导入后收录前崩溃”“事务已提交但响应丢失”“目标被修改或归档”“完整题对且两侧可用”“零成功题”“来源 blocked”“同 ID 新版本”场景。

- [x] **Step 2: 确认红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_dataset_generation.py -q`，预期新接口缺失。
- [x] **Step 3: 实现两阶段持久化。** 两条生成路径先沿原逻辑写入带 import_report 的 generation_manifest，再尝试 Dataset 收录。用精确成功 key，允许 added/duplicate/conflict 状态但拒绝 error/blocked；配对按完整 manifest 收录。实现上述 DatasetStore.attach，既有成员顺序保持。dataset_preview_hash 由 API 提取，不能泄入冻结生成配置；dataset_target 明确加入归一化输出，且无 target 的旧配置不新增空字段。

收录失败不改写生成完成事实，也不抛成要求重跑 GT 的失败。收录状态单独持久化并记录事件，公开 job 查询可读取最新 attachment 投影；重试不改旧 job definition、source fingerprint 或原生成 manifest。中断后从已验证的 job-local manifest 读取既有结果，manifest 不完整则返回 unavailable，不执行生成恢复。相同操作重试取事务内原结果；新目标必须使用新操作 ID。

- [x] **Step 4: 验证。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_studio_dataset_generation.py tests/test_studio_dataset_api.py tests/test_studio_generation.py tests/test_studio_pair_generation.py -q`，预期 PASS；显式断言本地收录可用但生成提交仍被执行主机检查拦住。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: attach generated questions to versioned Datasets"`。

## Task 7: Dataset 首页、成员管理与总题库

**Files:** Create `frontend/workflow/src/{dataTypes.ts,dataTestFixtures.ts,DataWorkspace.tsx,DatasetLibrary.tsx,DatasetBrowser.tsx,GlobalQuestionBank.tsx,data-workspace.css,DataWorkspace.test.tsx,GlobalQuestionBank.test.tsx}`; Modify `api.ts`、`api.test.ts`、`App.tsx`、`App.test.tsx`。

**Interfaces:**
- dataTypes 与共享接口逐字段对应；fixture 只使用人工公开题面。
- `ApiError(message, status, details?: unknown)` 新增结构化详情，保持 message/status 兼容。
- `DataWorkspace({version:number, act:Action, bootstrap:Bootstrap, onRag:(key:string)=>void, onRun:(id:string)=>void})` 负责 Data 内导航；Action 复用 Questions.tsx，Bootstrap 复用 types.ts。子组件接收 DatasetRef、精确 key 和回调。
- `BrowseLocation` 是 `{view:"datasets"}`、`{view:"bank",filters:QuestionFilters,offset:number}`、`{view:"dataset",ref:DatasetRef,filters:QuestionFilters,offset:number}` 的判别联合；`DataLocation = BrowseLocation | {view:"question",key:string,returnTo:BrowseLocation} | {view:"builder",target?:DatasetRef,returnTo:BrowseLocation}`。读题与构题视图由 Task 8、9 交付后接入。

- [x] **Step 1: 写失败组件测试。** 使用 fetch mock 和真实用户事件：

```tsx
it('keeps membership choices after a revision conflict', async () => {
  render(<DataWorkspace {...dataWorkspaceProps} />);
  await openDatasetAndSelectQuestion('A', 'Q2');
  fireEvent.click(screen.getByRole('button', {name:'保存题目选择'}));
  await screen.findByText('题库已在其他窗口更新');
  expect((screen.getByRole('checkbox', {name:'Q2'}) as HTMLInputElement).checked).toBe(true);
});
```

测试文件内定义 `dataWorkspaceProps` 和 `openDatasetAndSelectQuestion`，用 dataTestFixtures 的 Dataset/BankItem 与冲突响应实现，不依赖生产私有状态。另测跨集合共享计数、移除只影响当前集合、未 ready 题仍可浏览、分组由服务端决定、空状态、分页选择、重连失败与旧 route 兼容。

- [x] **Step 2: 确认红灯。** `npm --prefix frontend/workflow test -- src/DataWorkspace.test.tsx src/GlobalQuestionBank.test.tsx src/api.test.ts src/App.test.tsx`，预期新组件/API details 能力缺失。
- [x] **Step 3: 实现界面。** 首次打开默认 Data；已有合法 hash 优先，展示位置可保存 sessionStorage，不存题目正文或修改旧草稿。保留 #questions/#generation/#workflow/#rag/#runs/#kb/#models 路由。Dataset 使用内容摘要与少量上下文操作，成员编辑独立于研究 QuestionPicker。Data 顶部提供 Dataset/总题库导航；import 使用现有上传后再绑定的流程，冲突保留选择和已导入 source_id。
- [x] **Step 4: 验证。** 重跑 Step 2，预期 PASS；`npm --prefix frontend/workflow run build`，预期 TypeScript/Vite 成功。尚未交付的 reader/builder 子视图不得放置失效入口。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: add Dataset-first Data workspace"`。

## Task 8: 完整题目阅读与候选对比

**Files:** Create `frontend/workflow/src/QuestionReadingPage.tsx`、`QuestionReadingPage.test.tsx`; Modify `QuestionReader.tsx`、`QuestionReader.test.tsx`、`question-reader.css`、`DataWorkspace.tsx`。

**Interfaces:**
- `QuestionReader({record, interactive?: boolean, questionKey?: string})`；旧 `record` 单参数使用方式保持有效。Reader 不发网络请求。
- `QuestionReadingPage({questionKey:string, context:BrowseLocation, onBack:()=>void, onQuestion:(key:string)=>void, onAddToDataset:(key:string)=>void, onRag:(key:string)=>void})` 拉取精确题目版本；前后题沿当前集合修订和筛选顺序，不用字母或数组下标跨题关联候选。

- [x] **Step 1: 写失败测试。** 扩展已有 public spec、不同预算和 private sentinel fixture：

```tsx
it('selects a candidate without submitting an answer', () => {
  render(<QuestionReader record={record} interactive questionKey="q@v1" />);
  fireEvent.click(screen.getByRole('radio', {name:/候选 B/}));
  expect((screen.getByRole('radio', {name:/候选 B/}) as HTMLInputElement).checked).toBe(true);
  expect(fetch).not.toHaveBeenCalled();
  expect(document.body.textContent).not.toContain('PRIVATE');
});
```

测试中设置 fetch mock；record 复用本文件既有 fixture。另测键盘操作、选择两候选比较有效公开身份、换 exact key 后重置状态、保留集合筛选与位置、未知字段/缺失数据不补值，旧嵌入式 Reader 仍可读。

- [x] **Step 2: 确认红灯。** `npm --prefix frontend/workflow test -- src/QuestionReader.test.tsx src/QuestionReadingPage.test.tsx`，预期候选交互缺失。
- [x] **Step 3: 实现布局和交互。** 题干、数据规则与候选为主体；选择状态与对比选择分别管理。差异高亮、共同设置折叠、原始 Prompt/代码按需展开；无评分提交入口。为完整阅读页提供返回、前后题、加入 Dataset 和已有 RAG 快捷操作。
- [x] **Step 4: 验证。** 重跑 Step 2 并运行 `npm --prefix frontend/workflow test -- src/QuestionPicker.test.tsx src/Questions.test.tsx src/Rag.test.tsx`，预期 PASS。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: add interactive question reading and comparison"`。

## Task 9: Dataset 内分块构题与真实生成状态

**Files:** Create `frontend/workflow/src/{QuestionBuilder.tsx,GenerationBlocks.tsx,generationForm.ts,question-builder.css,QuestionBuilder.test.tsx}`; Modify `Generation.tsx`、`Generation.test.tsx`、`DataWorkspace.tsx`、`dataTypes.ts`。

**Interfaces:**
- `QuestionBuilder({capabilities, target?: DatasetRef, version, act, executionEnabled, onRun})`；Data 传入 target，旧 Generation 路由可无 target。
- `buildGenerationRequest(form, capabilities, target?: DatasetRef) -> GenerationRequest` 与 `generationSignature(request) -> string` 定义在 generationForm.ts；仅序列化 schema 允许且被用户显式设置的参数。
- `GenerationBlocks({schema, value, onChange})` 渲染字段；现有预检、稳定 Idempotency-Key 和目标 binding 组成一个状态机。

- [x] **Step 1: 写失败测试。** 复用 Generation 的 fetch mock，追加 schema fixture：无 options family 显示只读说明，切换 family 清除失效参数；配置/目标 revision 变化使预检无效；题对预检显示完整成本。

```tsx
// fixture 已返回持久化 revision_conflict attachment；点击只重试收录。
fireEvent.click(await screen.findByRole('button', {name:'将已有结果加入 Dataset'}));
await waitFor(() => expect(requestedPaths).toContain('/api/studio/generations/run_fixture/dataset-attachment'));
expect(requestedPaths.filter(p => p === '/api/studio/generations')).toHaveLength(0);
```

在 `shows attachment conflict without regenerating questions` 测试中完整建立 fixture、render 和 requestedPaths；另测空/部分结果、归档目标、预览不展示伪造题目、每次新预览产生新提交 key 而同次重试沿用原 key。

- [x] **Step 2: 确认红灯。** `npm --prefix frontend/workflow test -- src/QuestionBuilder.test.tsx src/Generation.test.tsx`，预期新组件/状态缺失。
- [x] **Step 3: 实现分块编辑。** 按数据类型与规则、候选、比较因素、预算、规模与目标分块；折叠后显示摘要。右侧只预览构题规格和题面结构。Generation.tsx 作为旧入口包装与历史展示，复用 builder。以服务器 run/attachment 状态显示真实进度和收录结果，onRun 只表示已提交，不能即时增加 Dataset 题数。
- [x] **Step 4: 验证。** 重跑 Step 2 并执行 `npm --prefix frontend/workflow run build`，预期 PASS/构建成功。
- [x] **Step 5: 提交。** 仅暂存本任务文件；`git commit -m "feat: build questions in Dataset context"`。

## Task 10: Dataset 接入既有 Harness、全阶段回归与使用说明

**Files:** Create `frontend/workflow/src/DatasetInputPicker.tsx`、`DatasetInputPicker.test.tsx`; Modify `Workflow.tsx`、`Workflow.test.tsx`、`App.test.tsx`、`types.ts`、`docs/WORKFLOW_STUDIO.md`。

**Interfaces:**
- `DatasetInputPicker({purpose:"research"|"evaluation", phase?, methodId, selectionMode, single, onApply:(set:QuestionSet)=>void, onClose})`：调用 Task 4 的服务端选择预览/题集适配，成功后才回调。
- `QuestionSet.dataset_binding?: DatasetBinding`；Workflow 的 `applyQuestions/applyTaskQuestions` 接收仍是原 QuestionSet，不在 UI 内改写私有快照或跳过方法校验。

- [x] **Step 1: 写失败集成测试。** 用两个题 Dataset 验证 Basic 错误，明确选一题后成功；配对和 evaluation phase 完整传到 API。测试保存失败保持原输入和选择，成功后预览失效。旧 QuestionPicker 的 research/evaluation/rag 模式完全保留，RAG 仍不创建 question_set。

```tsx
// setup 将选择预览 fixture 设为 basic_requires_one_question。
fireEvent.click(await screen.findByRole('button', {name:'使用整个 Dataset'}));
await screen.findByText('单题学习需要明确选择一道题');
expect(onApply).not.toHaveBeenCalled();
```

将该断言放入完整 `rejects multi-question Dataset without truncation` 测试，fixtures 来自 dataTestFixtures；另测旧 hash 路由、共享草稿恢复，以及集合后续修改不替换已应用题集。

- [x] **Step 2: 确认红灯。** `npm --prefix frontend/workflow test -- src/DatasetInputPicker.test.tsx src/Workflow.test.tsx src/App.test.tsx`，预期新选择入口缺失。
- [x] **Step 3: 接入与文档。** 在现有工作流提供“从 Dataset 选择”入口，调用已有 apply 函数；避免使用 App.onSet 误当工作流绑定（它只设置 Runs 输入）。更新 Data 使用说明、修订/去重口径与生成冲突恢复。文档只描述本阶段已交付能力，明确后续可组合 Harness 仍按后续计划实施。
- [x] **Step 4: 阶段验证。** 核对 root/import provenance 后运行 `PYTHONPATH=src .venv/bin/python -m pytest -q`、`npm --prefix frontend/workflow test`、`npm --prefix frontend/workflow run build`；预期全部通过。针对失败定位修复，不以缩小测试集代替回归。

本地浏览器验证 Dataset 创建/共享/去重、读题键盘操作、构题预检、冲突保留、旧工作流输入和窄屏。遵守实际浏览器工具访问限制；若不允许访问本地页面，不换工具绕过，报告视觉验证未完成。所有实时调用保持禁用；需要真实 GT 冒烟时仅在授权服务器按单独明确范围执行。

- [x] **Step 5: 提交与交付检查。** 仅暂存本任务文件；`git commit -m "feat: connect Dataset selections to research workflows"`。执行一次覆盖全分支的独立代码审查；修复实际问题并重跑受影响检查。报告已完成的 Data 路径、测试结果、视觉验证状态和下一阶段入口；不宣称 Harness v2 或 KB 适用题目已实现。

## 计划自查与执行顺序

- 规格映射：Data 集合/总题库/去重 → Task 1–3、7；读题 → Task 8；构题 → Task 5、6、9；运行输入与冻结 → Task 4、10；迁移/错误/兼容 → Task 2–4、6、7、10。
- 共享对象中的 DatasetRef、DatasetBinding、BankItem 与 DatasetAttachment 在服务端和前端一致；后续阶段沿用，不改训练实例 dataset_id。
- Review Focus 的五类问题均在对应任务中有具体断言和回归命令。
- 顺序为 1→2→3→4→5→6→7→8→9→10；每项完成测试与提交后进入下一项。调研可并行，计划的实现与最终审查按已选执行方式进行。
- 新的真实图执行、KB 逻辑管理及覆盖匹配是第二/第三阶段，不属于本阶段完成声明。它们分别另写实施计划，使用已批准的总体规格。
- 本阶段十项实现已完成；最终回归为 793 项后端测试、255 项前端测试及生产构建全部通过。独立审查发现的页面刷新、迁移隔离、历史题对保留、模式变化冲突和 API 参数校验问题已补回归并修复。浏览器访问受限，视觉与窄屏验证未完成；本地未执行真实模型或 GT。
