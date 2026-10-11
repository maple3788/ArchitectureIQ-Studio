# Rule Refinement Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可配置的结构化规则 KB 闭环：程序验证题目，模型修订错题、冲突及规则反例，通过不退步验收后挑战新题，在累计预算内保存最佳 KB 和完整证据。

**Architecture:** 新增 `rule_refinement` 方法及独立执行协议，复用 Dataset/Catalog、现有规则 DSL、模型客户端、封存收据、JobStore 和 canonical 构题引擎。纯规则预测、反馈评分、版本验收与有副作用的模型/生成操作分离；持久化状态机执行受约束的可编辑流程。研究规则 KB 使用独立产物类型，不改旧 scientific/paired/Basic/RAG 的解释、hash 或发布门槛。

**Tech Stack:** 现有 Python/FastAPI、JSON 原子文件与文件锁、SQLite Dataset/Catalog、React 19/TypeScript、React Flow、pytest、Vitest/Testing Library；不新增外部服务或图调度框架。

**Spec:** `docs/superpowers/specs/2026-10-11-rule-refinement-harness-design.md`，2026-10-11 用户已确认，含不退步原则与停止条件。总体布局继续遵守 `docs/superpowers/specs/2026-10-11-research-workspaces-design.md`。

## Global Constraints

- “规则冲突与错题一起进入修订环节，不投票、随机选择或调用模型强行补答案。”
- “先封存本批全部预测，再由评分器读取私有 GT。”
- “比较的两个版本必须使用同一个题池版本、题目/GT 引用及解释器版本。”
- “已接受版本答对的题组成保护集合，新版本不得把这些题变成答错、冲突或未覆盖。”
- “同分修补不允许明确作答题数下降；仅把错题改成未覆盖、清空 KB 或改措辞不算进展。”
- “每批新题先用未看过这批反馈的固定 KB 测试并保存首次成绩。随后整批加入研究池，包括当时答对的题。”
- “明确预留的 final 或独立 development 题不自动进入研究池，原有分区不改写。”
- “只有目标达到才标为成功，其余情况返回当前最好 KB、真实成绩及未解决问题。”
- 默认最大修订尝试 12、连续无改进 3、生成尝试 3 批、每批 16 道、新增题目最多 48 道、同一 KB 连续首测通过 2 批；调用、token、candidate × seed GT 工作量、总时长必须另设正的累计上限。
- “状态来自持久化事件/SSE。”确定性节点不显示伪造的模型回答；研究通过不提升为 `replicated_in_scope`。
- 实现和测试仅在本仓库。真实 LLM 和生成代码 GT 只在授权 Linux 执行服务器运行，连接资料保留在私有配置；本地测试全部 mock 外部执行。复用 spec → generated code → execution → stored results，不增加训练逻辑。
- 不提交运行状态、源数据、凭据、模型权重、构建缓存；不修改历史源码指纹以恢复旧运行，不引入迁移备份目录运行依赖。
- 用户已指定在当前对话逐项实施；本次仅交付计划。审阅后沿用当前对话执行方式，不重复要求用户选择工作方式。

## Review Focus

- 来源在预览后损坏或原 Dataset 被并发编辑：冻结成员不漂移，健康变化阻断执行，错误不进模型修订；Task 3、4、11 覆盖。
- 顶部候选正确但下位关系有环或断言被 GT 否定：分别拒答或进入修订，不能只看 top1 宣布通过；Task 2、3 覆盖。
- 模型返回截断/非法/重复提案，或者服务实际处理但响应丢失：尝试及预算仍计入，未知结果不能重发；Task 6、7、10 覆盖。
- 扩池、改选项顺序、同数据实例生成多题或不完整题对：同池回归、首测不改写，不把重复或缺题当作独立通过；Task 4、5、8 覆盖。
- 封存后崩溃、两个执行者竞争、浏览器重连或暂停跨越预算截止时间：恢复不重发、不重置预算，历史成绩及 UI 游标不倒退；Task 6、10、13、14 覆盖。

---

## 范围、依赖与执行准备

这是一个闭环子系统的一份计划；纯算法、运行持久化、API 和 UI 共用下列接口，不另行拆成互相漂移的计划。每个任务有独立测试和提交。首版支持导入/提出规则、配置受支持的处理节点与材料连接、完整闭环，以及把冻结的结果交给独立 Task 做确定性检查；不扩展任意 Python、任意 DAG、自动条件穷举或正式科学发布。

任务依赖：`1 → 2 → 3 → 4 → 5`；`1 → 6`；`1+3+6 → 7`；`4+6 → 8`；`1 → 9`；`3–9 → 10 → 11 → 12 → 13 → 14`。纯模块可按依赖并行，公共文件由一个实施者集成；前端先定义类型与 API，再实现运行阅读。不要在持久化、编译器接口尚未稳定时先拼 UI。每个提交步骤先 `git add` 该任务 Files 中实际变更的文件并检查 staged diff，不使用 `git add .` 收录运行状态。

执行开始按 using-git-worktrees 技能检查并复用合适的工作目录，再运行：

```bash
git rev-parse --show-toplevel
PYTHONPATH=src .venv/bin/python -c 'from pathlib import Path; import architecture_iq; p=Path(architecture_iq.__file__).resolve(); print(p); assert p.is_relative_to(Path.cwd()/"src/architecture_iq")'
```

工作目录应为本独立仓库或其工作树。隔离工作树如使用另一准确解释器路径，同步替换全部测试命令并重新检查来源。下文后端命令均从仓库根目录执行，前端命令用 `npm --prefix frontend/workflow`。测试只使用合成小 fixture，不读取 connected state 或外部题源。

## 文件与责任

新增包根为 `src/architecture_iq/studio/rule_refinement/`，下表简称 `RR/`。它是同一个功能包，不改 bundled benchmark 模块。

| 文件 | 唯一责任 |
| --- | --- |
| `RR/__init__.py`, `contracts.py` | 公共类型/版本/输入限制和默认值。 |
| `RR/artifacts.py` | 规则修订、补丁、不可变 KB 快照及来源导入。 |
| `RR/prediction.py` | 无 GT、无客户端的候选关系图与 top1 推理。 |
| `RR/scoring.py` | 整批预测封存、按封存结果评分、规则证据及问题清单。 |
| `RR/pool.py` | 累计题池、批次使用状态、独立性和完整题对检查。 |
| `RR/acceptance.py` | 同池不退步比较和保护集合更新。 |
| `RR/budget.py` | 累计预算预留、结算、截止时间和尝试计数。 |
| `RR/revision.py` | 有界修订材料、模型提案和模型回执适配。 |
| `RR/challenges.py` | canonical 生成子任务的冻结、运行、结果收录和恢复。 |
| `RR/workflow.py` | 新图协议模板、端口/连接校验与编译。 |
| `RR/runner.py` | 有界控制器和阶段恢复；独立规则评测入口。 |
| `RR/inputs.py`, `views.py` | 服务端配置冻结/预检；按封存状态返回公开投影。 |
| `services/kb_workflow_api/rule_refinement_routes.py` | 新方法预览、启动、规则详情、停止和独立评测 API。 |
| `frontend/workflow/src/ruleRefinementTypes.ts`, `ruleRefinementApi.ts` | 新协议类型与 API，不扩大通用 `Json` 的隐式语义。 |
| `RuleRefinementEditor.tsx`, `RuleRefinementCanvas.tsx`, `rule-refinement.css` | 四块配置、受支持节点编辑和内外循环画布。以上路径均在 `frontend/workflow/src/`。 |
| `RuleRefinementRun.tsx`, `RuleKnowledgeReader.tsx`, `ruleRefinementView.ts` | 实际运行视图、知识优先阅读与适用题目切换。以上路径均在 `frontend/workflow/src/`。 |
| `tests/rule_refinement_fixtures.py` | 合成公开规格、存储反馈、故障注入和 mock 客户端，无真实模型/训练。 |

必要集成修改：`studio/{methods,workflow,drafts,jobs,execution,generation,pair_generation,dataset_generation,dataset_inputs,knowledge,observations,events}.py`、`kb/{evaluation,roles}.py`（均位于 `src/architecture_iq/` 下）、API `app.py`；前端 `App.tsx`、`Workflow.tsx`、`MethodPicker.tsx`、`WorkflowWorkspace.tsx`、`Runs.tsx`、`RunMonitor.tsx`、`KB.tsx`、`types.ts` 及其对应测试。保留旧分派，避免整体重写这些文件。

## 共享契约

以下 JSON 对象在 `contracts.py` 定义为 TypedDict，并有严格运行时校验；函数签名中的 `dict` 指相应对象。未知字段、非有限数、bool 冒充 int 都拒绝。公开与私有对象分别建类型。

- 身份：`method_id="rule_refinement"`, `method_version="1"`, `protocol="rule_refinement_v1"`, `predictor_version="rule_top1_v1"`；新画布 `schema_version=2`。旧 schema v1/无 method 的运行走原代码，不迁移 hash。
- `RuleRevision={rule_id, revision, parents:[{rule_id,revision}], text, rationale, rule, state, source_refs}`；state 为 `active|retired`，rule 使用现有 `scope/same/differ/predict`。证据状态另由服务端从收据计算为 `candidate|research|tested_on_batch|retired`，模型不能写。
- `RuleKB={kind:"research_rules", schema_version:1, version, parent_version, rules, executable_hash}`；version hash 包含元数据和谱系，executable_hash 只依据排序去重后的活跃 DSL canonical JSON 及 predictor_version，忽略文字/ID/条目顺序，不尝试证明不同表达式逻辑等价。新 rule_id 服务端分配，文本变动仍保存提案，但不当作可执行进展。
- `RulePatch={base_version, operations, rationale, case_refs}`；operations 为 add/edit/split/merge/retire。edit/retire 指定原 rule_id+revision；split/merge 指定所有原条目、产生的条目及父关系；不允许借 ID 覆盖别的规则。
- `QuestionRef={key,hash}` 使用 Catalog 精确身份；`PublicCase={ref,question,dataset_spec,candidate_specs,objective}` 不含反馈、私有路径或结果。candidate_specs 与 choices 一一对应，以稳定候选 ID 为图顶点，letter 仅作显示/评分映射；objective 从 canonical 已存公开规格取值，不由模型发明。
- `Prediction={question_ref,kb_version,executable_hash,predictor_version,status,answer_id,edges,paths,issues}`；status 为 `answered|conflict|uncovered|invalid`，无答案时 answer_id=null。edge 记录 winner/loser ID 及直接支持规则修订；paths 记录到各候选的一条确定性路径，不枚举指数级所有路径。
- `PoolSnapshot={version,parent_version,members,pairs,source_bindings,usage_refs}`；members 为对象数组，每项包含 ref、公开身份/谱系、私有 GT 引用 hash，反馈正文仅评分侧读取。`BatchScore={receipt_ref,pool_version,kb_version,executable_hash,predictor_version,prediction_receipt,selected,scorable,unscorable,correct,answered,conflicts,wrong_assertions,all_pass,per_question,per_rule,problems}`，保存计数，展示时派生比例；零可评分时比例为 null，不显示 100%。预测收据绑定完整 KB 快照引用，供评分器统计未命中规则。
- `Decision={accepted,reason,before_score,after_score,protected_keys,newly_correct,regressed}`；protected_keys 是精确题目 key 的集合，冻结 hash 由 pool 核验。
- `Limits={max_revision_attempts:12,max_no_progress:3,max_generation_attempts:3,questions_per_batch:16,max_new_questions:48,required_fresh_passes:2,max_model_calls,max_tokens,max_candidate_seed_runs,wall_time_seconds}`。前六项可配置为正整数，必须满足目标有可能在批次/题数上限内完成；后四项无隐式默认，必填正整数。
- `Cost={model_calls,tokens,candidate_seed_runs,new_questions,revision_attempts,generation_attempts}`，所有维度非负整数。资源预算计算使用累计预留与结算；new_questions 预留请求量，失败/重复不退还尝试额度。
- 运行记录引用均为相对产物 ID，客户端不能传任意路径。运行目录 `runs/<id>/refinement/` 下保存 manifest、不可变 `kb/`/`pools/`/`predictions/`/`scores/`/`proposals/`/`decisions/`/`batches/`，以及加锁 CAS 的 `checkpoint.json`、`budget.json`、`control.json`。先保存封存产物，再提交引用它的 checkpoint；崩溃产生的孤立产物按相同身份复用。
- `RunResult={outcome:"target_reached"|"stopped",stop_reason,best_kb,pool,score,fresh_batches,unresolved,budget}`。stop_reason 枚举 `target_reached|revision_limit|generation_limit|no_progress|resource_limit|user_stop|execution_failure|uncertain`。Job 的完成只表示执行已结束；UI 成功只由 outcome 决定。

## Task 1: 研究规则产物、补丁和严格契约

**Files:** Create `RR/__init__.py`, `contracts.py`, `artifacts.py`, `tests/rule_refinement_fixtures.py`, `tests/test_rule_refinement_artifacts.py`；复用 `kb.rules`, `kb.legacy`, `kb.store`, `kb.roles`。

**Interfaces:** `validate_limits(value: dict) -> dict`；`RuleArtifactStore(root: Path).import_rules(source: dict, *, source_ref: dict) -> dict`、`.get(version: str) -> dict`、`.apply_patch(base_version: str, patch: dict) -> dict`、`.save_proposal(attempt_id: str, proposal: dict) -> dict`。`.apply_patch` 只创建候选快照，不更新已接受指针。公用 fixture 提供真实结构的三候选公开题、可分/不可分 seed metrics、完整正常/反事实题对及各自 tmp_path Catalog，不使用运行目录样本。

- [x] **Step 1: 写失败测试。** `test_revision_is_immutable_and_split_preserves_parents` 检查 split/merge/retire、旧文件字节和父关系；`test_hidden_fields_and_forged_evidence_are_rejected` 覆盖 DSL 禁用题号、答案、路径、额外字段和伪造证据；`test_limits_match_approved_defaults` 的关键断言：
  ```python
  assert limits["max_revision_attempts"] == 12
  assert limits["max_no_progress"] == 3
  assert limits["required_fresh_passes"] == 2
  assert edited_text["executable_hash"] == original["executable_hash"]
  assert edited_text["version"] != original["version"]
  ```
  测试同内容换 ID/调序/重复规则不会制造可执行改进；没有正资源上限、非法基版本、循环父关系、坏 hash 都拒绝。历史多 clause 经现有导入器拆分并保留来源；无法编译条目显示拒绝清单，不把自然语言自动当规则。
- [x] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_artifacts.py -q`，预期新接口缺失导致 FAIL。
- [x] **Step 3: 实现上述接口。** JSON 原子写入、canonical_hash 和现有 exclusive_lock/read_receipt；规则逐条 `validate_rule`。导入可创建明确空 KB 作为模型初始化基线，但空 KB 不可作为通过结果；固定的形式化 KB 导入只保留原始来源，研究副本不回写原库。
- [x] **Step 4: 验证。** 同一命令加 `tests/test_kb_workflow_rules.py tests/test_kb_workflow_legacy.py`，预期全通过。
- [x] **Step 5: 提交本任务列出的新增文件。** `git commit -m "feat: add immutable research rule artifacts"`。

## Task 2: 无模型的整题规则预测

**Files:** Create `RR/prediction.py`, `tests/test_rule_refinement_prediction.py`。

**Interfaces:** `predict_question(case: dict, kb: dict) -> dict` 只接收 PublicCase/RuleKB；`predict_batch(cases: list[dict], kb: dict) -> list[dict]` 保留输入顺序。不接收 Catalog、GT、模型或文件读取回调。

- [x] **Step 1: 写失败测试。** 参数化构造 `A>B,B>C`、`A>B,B>A`、`A>B,B>C,C>A`、`A>B,A>C,A>D,B>C,C>D,D>B`、两个不连通组、缺公开字段与调换 choices 顺序。关键断言：
  ```python
  # test_transitive_winner_keeps_direct_evidence
  assert chain["answer_id"] == "candidate-a"
  assert len(chain["edges"]) == 2
  # test_lower_candidate_cycle_blocks_even_obvious_top1
  assert lower_cycle["status"] == "conflict"
  assert lower_cycle["answer_id"] is None
  # test_disconnected_candidates_abstain
  assert disconnected["status"] == "uncovered"
  ```
  重复同向规则不改变答案/覆盖；多指标不合并；重复 candidate ID、单候选、危险表达式为 invalid；禁止任何模型调用/GT访问的 mock 设置为一调用即失败。
- [x] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_prediction.py -q`。
- [x] **Step 3: 实现接口。** 使用 `public_views`、`match_rule`；直接边去重保留来源，以拓扑检查全图冲突，再计算可达性和唯一全覆盖起点。规则缺少必要字段时不命中，规范结构坏掉时返回 invalid；稳定排序决定显示路径，派生边不能增加直接断言证据数。
- [x] **Step 4: 验证。** 上述命令加 `tests/test_kb_workflow_rules.py`，预期全通过；20 候选的稠密无环图测试只保存有限路径，不枚举全部路径。
- [x] **Step 5: 提交。** `git commit -m "feat: execute rule graphs with conflict abstention"`。

## Task 3: 整批封存、评分与规则反例

**Files:** Create `RR/scoring.py`, `tests/test_rule_refinement_scoring.py`；Modify `src/architecture_iq/kb/evaluation.py`，只增加既有 `_decisive_pairs` 的公开适配 `decisive_pairs(question: dict, feedback: dict) -> list[tuple[str,str]]`，不改判据。

**Interfaces:** `seal_predictions(root: Path, *, batch_id: str, pool: dict, kb: dict, predictions: list[dict]) -> dict`；`score_sealed_batch(root: Path, *, prediction_receipt: str, pool: dict, feedback_loader: Callable[[dict], dict]) -> dict`。返回 BatchScore/封存收据；loader 只在全部成员预测及引用通过校验后调用。

- [x] **Step 1: 写失败测试。** `test_all_predictions_sealed_before_any_feedback_read` 用 loader spy 检查磁盘完整收据；`test_top1_correct_but_false_lower_assertion_blocks_pass`、`test_unscorable_cannot_disappear_from_completion` 的断言：
  ```python
  assert top1_correct["correct"] == 1
  assert top1_correct["wrong_assertions"] == 1
  assert top1_correct["all_pass"] is False
  assert missing_gt["unscorable"] == 1
  assert missing_gt["all_pass"] is False
  assert abstention_score["scorable"] == 1 and abstention_score["correct"] == 0
  ```
  覆盖只有 correct_letter、相交 seed 区间、未知指标方向、反馈 hash 改变、缺一份预测、篡改答案、空题池；GT 不明确只计 unknown。资料故障不得出现在供模型修订的可学习反例列表。
- [x] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_scoring.py -q`。
- [x] **Step 3: 实现接口。** 评分读封存 Prediction，以候选 ID→letter 映射核对存储答案；逐直接规则断言使用公开适配的 canonical 判据。按题/候选对/规则修订记录支持、反例、unknown 与独立数据实例，不伪造完整排序；all_pass 要求非空、无 incomplete/invalid、整题全对、无冲突/未覆盖/确定错误断言。
- [x] **Step 4: 验证。** 上述命令加 `tests/test_kb_workflow_evaluation.py tests/test_kb_claim_pairwise_eval.py`，预期全通过，旧评分结果保持不变。
- [x] **Step 5: 提交。** `git commit -m "feat: seal and score deterministic rule predictions"`。

## Task 4: 冻结研究池与新题使用账本

**Files:** Create `RR/pool.py`, `tests/test_rule_refinement_pool.py`；复用 `studio/dataset_inputs.py`, `question_equivalence.py`, `pairs.py`, `task_inputs.py`。

**Interfaces:** `PoolStore(root: Path, catalog: Catalog).initialize(binding: dict) -> dict`、`.get(version: str) -> dict`、`.public_cases(version: str) -> list[dict]`、`.record_first_test(batch_id: str, *, pool: dict, score: dict, generation: dict) -> dict`、`.promote(batch_id: str, *, expected_pool_version: str) -> dict`；`check_independence(existing: dict, incoming: dict) -> dict` 返回 overlap/missing_identity/eligible 及原因。

- [x] **Step 1: 写失败测试。** `test_dataset_edits_do_not_change_frozen_pool`、`test_first_result_is_immutable_and_full_batch_promotes_once`、`test_relabelled_question_and_shared_lineage_are_not_fresh`、`test_holdout_and_half_pairs_are_rejected`：
  ```python
  assert promoted_again["version"] == promoted["version"]
  assert {m["ref"]["key"] for m in promoted["members"]} == expected_all_member_keys
  assert first_score_bytes_after == first_score_bytes_before
  assert duplicate_report["eligible"] is False
  ```
  同 key 不同 hash 拒绝覆盖，显示题号相同但精确 key 不同的成员各自保留。测试来源损坏、并发两次扩池 CAS、initial development/final 拒绝、源 split 不变；缺少可靠谱系时标为无法证明独立，不能伪称新实例。
- [x] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_pool.py -q`。
- [x] **Step 3: 实现接口。** 冻结 DatasetBinding、精确成员和完整 pair_manifest；统一主键使用 key，不用显示题号。新批次按 unseen→sealed→revealed→promoted 推进，必须引用 Task 3 封存首测才能扩池。完整有效批次无论答对与否都收录，重复成员保留尝试记录但不重复添加；同批共享数据实例如实统计，跨批重用实例不算独立挑战。保留 canonical 筛选/不足记录，不允许按答案过滤。
  生成不足时，已核验的完整题/题对也先首测再整体入池，缺失与故障另存；空批次不生成 all_pass。批次账本同时保存 requested/actual/eligible/first_score 和 `batch_passed`，后者必须满足规模完整、独立与 all_pass，避免把“已有部分全对”展示为整批通过。
  另立 `novelty_policy="rule_challenge_v1"`：核对题目、数据实例/生成 seed 与规格、lineage、完整 pair 身份，并计算去展示 ID/letter 后按 canonical 内容排序的候选规格集合指纹；重排选项或改题号不能获得新题额度。现有 exact_question_v1 仍用于总题库去重，不能直接当作挑战独立性证明。先前批次无论是否通过都进入已见集合，避免只对当前池做重叠检查。
- [x] **Step 4: 验证。** 上述命令加 `tests/test_studio_dataset_inputs.py tests/test_studio_pairs.py tests/test_studio_task_inputs.py`，预期全通过。
- [x] **Step 5: 提交。** `git commit -m "feat: track frozen research pools and first-test usage"`。

## Task 5: 同池不退步验收

**Files:** Create `RR/acceptance.py`, `tests/test_rule_refinement_acceptance.py`。

**Interfaces:** `compare_candidate(before: dict, after: dict, *, protected_keys: list[str]) -> dict`；`advance_protection(protected_keys: list[str], accepted_score: dict) -> list[str]`。两者纯函数；runner 负责保存 Decision 和接受指针。

- [ ] **Step 1: 写失败测试。** `test_any_protected_regression_rejects_even_with_higher_total`、`test_same_score_repairs_follow_lexicographic_order`、`test_wrong_to_uncovered_is_not_progress`、`test_pool_mismatch_rejected_before_comparison`：
  ```python
  assert regression["accepted"] is False
  assert fewer_conflicts_same_answers["accepted"] is True
  assert fewer_errors_fewer_answers["accepted"] is False
  assert wrong_to_gap["accepted"] is False
  assert rejected_only_correct_key not in protected_after
  ```
  相同执行 hash 为 no_progress；正确题数优先，再按 conflicts↓、wrong_assertions↓、answered↑，较高优先级变差不得被低优先级掩盖；新增批次原本答对的题立即受保护，已接受规则零命中不可冒充证据。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_acceptance.py -q`。
- [ ] **Step 3: 实现接口。** 强制同 pool/GT/predictor 身份且全池评分完成，核验保护集合属于本池；先检验保护，再比较确定的优先序。整题正确数不变时额外要求 answered 不减少。保存稳定拒绝 reason 和题目 key，不能隐式放宽原则。
- [ ] **Step 4: 验证。** 上述命令加 `tests/test_rule_refinement_pool.py tests/test_rule_refinement_scoring.py`，预期全通过。
- [ ] **Step 5: 提交。** `git commit -m "feat: accept rule updates only after nonregressing pool checks"`。

## Task 6: 全程预算与尝试账本

**Files:** Create `RR/budget.py`, `tests/test_rule_refinement_budget.py`。

**Interfaces:** `BudgetLedger(root: Path, limits: dict, *, clock: Callable[[], float]).reserve(operation_key: str, cost: dict, *, inputs_hash: str) -> dict`、`.settle(operation_key: str, *, actual: dict, receipt_ref: str, outcome: str) -> dict`、`.snapshot() -> dict`、`.check_time() -> None`；`BudgetExceeded`、`UncertainOperation` 为明确异常。相同 operation_key 输入不同时冲突。

- [ ] **Step 1: 写失败测试。** `test_rejected_and_failed_attempts_consume_limits`、`test_two_processes_cannot_reserve_same_remaining_budget`、`test_restart_and_pause_never_reset_deadline`、`test_uncertain_reservation_is_not_refundable_or_retryable`：
  ```python
  assert after_invalid["revision_attempts"] == 1
  assert after_failed_generation["generation_attempts"] == 1
  assert resumed["deadline"] == original["deadline"]
  assert duplicate_reservation["operation_key"] == original_reservation["operation_key"]
  ```
  包含预算恰好用尽、零/负/NaN/bool、missing usage 保守计费、实际 usage 超预留后立即停止、所有失败仍计调用；reserved 与 settled 不重复累计。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_budget.py -q`。
- [ ] **Step 3: 实现接口。** 同一锁下校验、预留和提交账本；截止时间在首次运行启动固定，包含暂停时间。新题按请求的实际题数预留上限，确定终结后可结算实际新增数，但生成尝试永不返还；pending/uncertain 保持预留。模型以 UTF-8 输入字节+冻结 max_tokens+256 的现有保守方式预留，并检查模型 context 上限；GT 按 canonical candidate_seed_runs 预留整个挑战，执行前逐单元检查时间及控制信号。硬截止时终止受管理的调用/GT 子进程，无法证明完成的记 uncertain，保留完整结果且不再启动新单元。
- [ ] **Step 4: 验证。** 上述命令预期全通过；用独立 Ledger 实例和 fake clock，不依赖真实等待。
- [ ] **Step 5: 提交。** `git commit -m "feat: enforce cumulative refinement resource limits"`。

## Task 7: 初始化与修订模型适配

**Files:** Create `RR/revision.py`, `tests/test_rule_refinement_revision.py`；Modify `src/architecture_iq/kb/roles.py` 仅增加 `rule_initializer`/`rule_reviser` 的受约束提示词，`studio/execution.py` 的客户端可选超时；复用 `models.model_config`, `RoleCaller`。

**Interfaces:** `build_revision_payload(kb: dict, score: dict, *, seen_case_refs: list[str], max_input_bytes: int, grouping: list[str]) -> dict` 返回材料、所选 case_refs、剩余数量；`propose_patch(caller: RoleCaller, ledger: BudgetLedger, *, attempt_id: str, kb: dict, payload: dict, initialize: bool = False) -> dict` 返回提案/拒绝原因/回执引用，不能写接受指针。现有 `create_client` 新增可选 keyword `timeout_s: float | None = None`，None 保持原 900 秒；新调用使用 min(900, 剩余总时长)，超时保留 uncertain 回执，不自动重发。

- [ ] **Step 1: 写失败测试。** `test_conflicts_and_rule_counterexamples_share_revision_queue`、`test_context_chunking_preserves_full_index_and_seen_ledger`、`test_invalid_patch_still_charged_once`、`test_lost_response_never_reissues_request`：
  ```python
  assert {"conflict", "rule_counterexample"} <= sent_problem_types
  assert receipt["seen_case_refs"] == payload["case_refs"]
  assert usage["revision_attempts"] == 1
  assert fake_client.call_count == 1  # 包括相同 attempt 恢复
  ```
  初始化材料只有公开题面/规格和可用 DSL；现有题 GT 首先经确定性基线封存后才可出现在修订材料。测试输出截断、文本声称通过但规则非法、改变 GT/预算的字段、case_refs 不存在、base_version 过期、token 预算不足导致零调用、请求超时不超过剩余时长且超时计费不重试。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_revision.py -q`。
- [ ] **Step 3: 实现接口。** 复用禁用自动重试的客户端及 RoleCaller 封存，不伪造模型身份；该运行所有新角色调用统一 `round_index=0` 作为累计桶，真实尝试序号单独记入事件。完整问题索引存为产物，超上下文时按类型→规则→family 确定性分组，优先未展示案例；当前调用只附可容纳的索引页和案例，显示“本次/全部”数量。首版每个修订尝试一次模型调用，后续尝试轮转未展示组；必需 KB/提示词也装不下则明确停止，不截断规则。无效/重复补丁保留回执，仍计尝试和 no_progress。
- [ ] **Step 4: 验证。** 上述命令加 `tests/test_kb_workflow_roles.py tests/test_studio_api_models.py`，预期全通过，旧角色 prompt/hash 不变；fake provider 中的凭据 sentinel 不得进入产物或事件。
- [ ] **Step 5: 提交。** `git commit -m "feat: propose bounded rule revisions from persisted feedback"`。

## Task 8: canonical 新题子任务与安全恢复

**Files:** Create `RR/challenges.py`, `tests/test_rule_refinement_challenges.py`；Modify `studio/dataset_generation.py` 添加公开只读 accessor，`studio/execution.py` 为受绑定的生成子任务选用适配 Store；按需要给 `studio/generation.py`/`pair_generation.py` 的现有边界补齐稳定单元身份。全部完整路径见文件结构。

**Interfaces:** `prepare_challenge(config: dict, *, attempt_index: int, questions_per_batch: int) -> dict`；`run_challenge(jobs: JobStore, *, parent_id: str, attempt_index: int, frozen_config: dict, ledger: BudgetLedger) -> dict`；`recover_challenge(jobs: JobStore, catalog: Catalog, *, child_id: str, parent_id: str) -> dict`；`BoundGenerationStore(JobStore).boundary(identifier: str, event: dict | None = None) -> None` 检查父控制/截止时间再调用原边界；`dataset_generation.completed_generation_result(store, catalog, run_id: str) -> dict` 返回验证后的结果、keys、pairs，不执行 GT。

- [ ] **Step 1: 写失败测试。** `test_sixteen_questions_becomes_eight_complete_pairs`、`test_child_cost_is_reserved_before_launch`、`test_recover_terminal_manifest_without_rerunning_gt`、`test_partial_and_duplicate_batch_never_counts_as_pass`：
  ```python
  assert paired["num_questions"] == 8
  assert paired["requested_question_count"] == 16
  assert paired["candidate_seed_runs"] == 16 * candidate_count * n_seeds
  assert fake_gt.call_count == calls_before_recovery
  assert repeated_attempt["child_id"] == first_attempt["child_id"]
  ```
  覆盖奇数配对目标拒绝、生成不足/筛选失败、同批共享实例、重复批次、冻结 profile 改变、已有 generated/ 但无完整结果、父暂停/停止阻止下一候选、到截止时间受管理子进程结束且待定工作保守计费。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_challenges.py -q`。
- [ ] **Step 3: 实现接口。** 调用 `validate_generation` 冻结 profile/spec/seed/规模及 candidate_seed_runs；首版按用户配置生成范围和确定性不重叠 seed 区间出题，不让修订模型自由改生成预算。子任务沿用 `generation` kind，幂等键 `parent_id:challenge:attempt_index`；父关联单独封存并验证双方定义 hash，不塞进 canonical config 的字段白名单。禁用 dataset_target 自动收录研究池，必须先经首测账本。
  预留整个批次 GT 成本后使用 `JobStore.launch`；单题生成利用 candidates 前边界与每个候选完成后的回调检查下一单元，配对生成利用现有 candidate/candidate_complete 边界，绝不复制训练循环。新增 `enforce_child_deadline(jobs: JobStore, child_id: str, deadline: float) -> None`，由独立监控进程在真实 GT 前启动，核对冻结父关联及 PID/process_stamp，截止时结束该生成任务拥有的进程组及受管理后代，不误杀别的任务；子任务完成则监控退出。父关联校验也在子执行入口进行，子边界读父持久化控制；即使父进程崩溃、单个候选超时，监控仍有效。用 fake process tree 测试归属与终止，旧生成任务不启用这套父预算适配。
  从完整 outer result 或已终结 generation_manifest 恢复时复用现有 `_completed_keys` 的配置、来源和成员检查，并封存恢复引用；非终结输出标 uncertain。保留所有生成候选的筛选/失败统计，不补题凑满、不按成绩挑题。
- [ ] **Step 4: 验证。** 上述命令加 `tests/test_studio_generation.py tests/test_studio_pair_generation.py tests/test_studio_dataset_generation.py`，预期全通过。mock subprocess/GT 验证回调顺序和终止，不在本地实际生成训练代码执行。
- [ ] **Step 5: 提交。** `git commit -m "feat: run bounded canonical challenge batches"`。

## Task 9: 新方法与可编辑流程协议

**Files:** Create `RR/workflow.py`, `tests/test_rule_refinement_workflow.py`；Modify `src/architecture_iq/studio/{methods,workflow,drafts}.py`；Test `tests/test_studio_methods.py`, `test_studio_workflow.py`, `test_studio_drafts.py`。

**Interfaces:** `default_rule_workflow() -> dict`、`validate_rule_workflow(spec: dict) -> dict`、`compile_rule_workflow(spec: dict) -> dict`；编译返回 `{workflow,method,protocol,workflow_hash,execution_hash,limits,initialization,grouping,model_nodes,generation,execution_order}`。新方法支持 `data_modes=["single","pairs"]`、`publication_policy="research_rules_only"`；旧 descriptor 原样保留。

- [ ] **Step 1: 写失败测试。** `test_rule_template_has_separate_protocol_and_no_solver`、`test_graph_cannot_bypass_sealing_acceptance_or_limits`、`test_supported_grouping_routes_compile_in_edited_order`、`test_legacy_recipe_and_draft_hashes_remain_identical`：
  ```python
  assert compiled["protocol"] == "rule_refinement_v1"
  assert "solver" not in compiled["model_nodes"]
  assert reordered["grouping"] == ["family", "rule"]
  assert moved_layout["execution_hash"] == original["execution_hash"]
  assert changed_prompt["execution_hash"] != original["execution_hash"]
  ```
  schema v2 草稿允许保存尚未连完的图，但验证/运行必须失败；测试 schema v1 正常保存、CAS 冲突有恢复副本，v2 不被旧 schema 静默接受。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_workflow.py -q`。
- [ ] **Step 3: 实现协议。** 增加早期分派，schema v2 仅接受新方法。固定职责节点为 `input,initialize,verify,revise,accept,challenge,save`；verify 内封装程序预测→整批封存→评分，accept 内含候选全池验证。两层有界循环由控制器拥有，画布使用分组容器展示；它们不是可绕过的普通材料边。
  支持 initialize 的 import/model 模式、节点模型/提示词配置，以及 verify→revise 之间添加/删除/排序最多 3 个 `group_cases` 节点（config.strategy 为 `type|rule|family`，不重复）。合法端口为 `public_cases,rule_kb,sealed_feedback,patch,decision`；mapping 只允许对应类型的完整引用，不支持任意表达式。循环出口 `needs_revision|pool_passed|accepted|rejected|target_reached|continue|stopped` 由后端状态决定，禁止用户伪造条件值。反馈只能从 verify 流向分组/修订，初始规则模型只能接公开材料。
  允许重连支持的材料路径，但编译器拒绝少节点、错类型、跳过验证、任意额外环和无可达终点；布局/标签只影响 workflow_hash。草稿只做结构校验，运行另做完整语义校验。
- [ ] **Step 4: 验证。** 上述命令加三个旧测试文件，预期全通过；新方法无独立确认/科学发布的伪节点。
- [ ] **Step 5: 提交。** `git commit -m "feat: compile editable rule refinement workflows"`。

## Task 10: 持久化有界控制器、停止与恢复

**Files:** Create `RR/runner.py`, `tests/test_rule_refinement_runner.py`, `tests/test_rule_refinement_recovery.py`；Modify `studio/jobs.py`, `studio/execution.py`, `studio/events.py`（完整路径同上）。

**Interfaces:** `execute_refinement(jobs: JobStore, identifier: str, config: dict, *, catalog: Catalog, client_factory: Callable = create_client, clock: Callable = time.time) -> dict`；`request_refinement_control(jobs: JobStore, identifier: str, action: str) -> dict`（pause/resume/stop）；`recover_refinement(jobs: JobStore, identifier: str) -> dict`。后者只调和封存产物并重新启动安全 checkpoint，不改变冻结定义；`RefinementCheckpoint` 在 contracts.py 定义 `{revision,phase,kb_version,pool_version,score_ref,protected_keys,attempt_index,no_progress,fresh_passes,pending_operation,artifact_refs}`。

- [ ] **Step 1: 写失败测试。** mock 模型返回预设合法补丁、mock 生成返回 Catalog fixture，完整经过初始题错→修订通过→新批失败入池→修订→两批首测通过；此场景显式把 generation cap 设为 3。断言：
  ```python
  assert result["outcome"] == "target_reached"
  assert len(result["fresh_batches"]) == 3
  assert result["fresh_batches"][0]["first_score"]["all_pass"] is False
  assert final_checkpoint["fresh_passes"] == 2
  assert all(batch["first_score"] == saved_first[batch["id"]] for batch in result["fresh_batches"])
  ```
  `test_stops_after_three_invalid_or_nonimproving_proposals`、`test_rejected_proposal_does_not_reset_fresh_streak`、`test_accepted_change_resets_streak`、`test_all_limit_reasons_keep_best_kb`、`test_empty_initialization_cannot_pass` 覆盖默认 12/3/3/16/48/2；初始化失败也有明确限制。恢复测试分别在预测封存、评分完成、提案回执、决定封存、指针更新、子任务完成、首测落盘、扩池落盘后注入崩溃，检查每个操作/事件/预算只提交一次。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_runner.py tests/test_rule_refinement_recovery.py -q`。
- [ ] **Step 3: 实现状态机。** 阶段为 initialize→baseline→revise→candidate_check→accept/reject→challenge→first_test→promote→baseline/finish；accepted 指针、保护集合和 no_progress 在一个 CAS checkpoint 中提交。初始化使用 Task 7 的 initialize 模式，失败尝试计入修订尝试上限但单列类型；没有已接受规则时仍保存空基线与失败记录。扩池后对旧 KB 重新取得完整 baseline；已封存同身份分片可复用，但保存新的完整同池 score 后才允许验收。
  当前池 all_pass 后才能出新题；批次必须完整、独立、首次 all_pass 且扩池后仍 all_pass 才增加 streak；失败、不足或重复挑战使 streak 归零，接受任何 KB 变动也归零，拒绝提案不改 KB。预算耗尽前优先检查已经达到的成功条件；无条件可继续时明确停止。
  新增 job kind `rule_refinement`，worker 分派在受授权执行门禁内；同一 run 只许一个 worker 锁。新增恢复路径只适用于本协议，验证 source/config/model/pool/全部 receipt 身份，pending 外部调用先调和，无法确定则停止 uncertain。不要放宽旧 JobStore.control 的 dead-worker 规则。pause 等待安全边界且仍检查 deadline；stop 幂等并保存最好版本，浏览器刷新不能触发恢复。
  事件写 `protocol,node_id,stage_id,step_id,attempt_id,kb_version,pool_version,artifact_refs`；模型增量用现有 append_stream 独立游标，确定性节点只发事实事件。终结阶段保存 RunResult；failed/uncertain 的 Job 状态仍保留，资源耗尽等正常停止可为 complete，但 outcome=stopped。
- [ ] **Step 4: 验证。** 上述命令加 `tests/test_studio_jobs.py tests/test_studio_execution.py tests/test_studio_streaming.py`，预期全通过；两个恢复请求竞争只产生一个 worker，旧 source mismatch 仍拒绝。
- [ ] **Step 5: 提交。** `git commit -m "feat: orchestrate resumable bounded rule refinement"`。

## Task 11: API、公开边界与独立 Task 检查

**Files:** Create `RR/inputs.py`, `views.py`, `services/kb_workflow_api/rule_refinement_routes.py`, `tests/test_rule_refinement_api.py`, `tests/test_rule_refinement_evaluation.py`；Modify `studio/{dataset_inputs,knowledge,observations,execution,jobs}.py`、API `app.py`；Task-only 入口添加在 `RR/runner.py`。

**Interfaces:** `prepare_refinement(catalog: Catalog, datasets: DatasetStore, models: ModelRegistry, inventory: dict, body: dict) -> tuple[dict,dict]` 返回私有冻结 config/公开 preview；`public_refinement_job(job: dict, jobs: JobStore) -> dict`；`execute_rule_evaluation(jobs: JobStore, identifier: str, config: dict, *, catalog: Catalog) -> dict` 仅使用冻结 KB、已有独立题目和 stored GT，返回 `{score:BatchScore,kb_ref,dataset_binding,usage_receipt,independence}`；`register_rule_refinement_routes(api, *, catalog, datasets, models, jobs, inventory_provider, require_execution) -> None`。

API 位于 `/api/studio/rule-refinement`：

| 方法与路径 | 契约 |
| --- | --- |
| `POST /match` | `{dataset_ref,selection,kb_ref}` → 公开 Prediction 列表/计数，不读反馈、不要求模型或运行预算；分页明示匹配范围。 |
| `POST /preview` | `{workflow,dataset_ref,selection,initial_kb_ref?}` → `{preview_hash,can_run,blockers,counts,cost,limits,protocol}`；角色模型/生成参数在 workflow 中。缺少设置返回 blockers。 |
| `POST /runs` | 同 preview 请求加 preview_hash，必填 Idempotency-Key；重冻并比较后建立 `rule_refinement` job，调用 require_execution。 |
| `GET /runs/{id}/artifacts/{artifact_id}` | 按服务端索引解析收据、补丁、差异、题目问题；不接受任意路径。未释放反馈不可读。 |
| `POST /runs/{id}/control`、`POST /runs/{id}/recover` | 前者 `{action:"pause"|"resume"|"stop"}`；后者只恢复冻结安全边界。触发执行的 resume/recover 检查主机门禁。 |
| `POST /evaluations/preview`、`POST /evaluations` | `{kb_ref,dataset_ref,selection,phase:"development"|"final"}`；启动额外带 preview_hash/Idempotency-Key，kind=`rule_evaluation`，无模型/生成/补丁参数。冻结整个评测集并先封存全部预测，永不进入研究池。 |

run 列表/详情及文本 SSE 沿用已有 `/runs` 路由，通过 kind 分派投影/observations。分页参数统一 offset/limit，与现有 Data 接口一致。新 API 未知字段返回 422，预览失效/CAS/不确定结果返回 409，错误结构 `{detail:{code,message,blockers?}}`，不输出私有正文。

- [ ] **Step 1: 写失败测试。** `test_local_match_needs_no_model_and_never_reads_gt`、`test_previews_and_queued_jobs_never_expose_gt_or_credentials`、`test_source_health_change_invalidates_preview`、`test_two_choice_readiness_is_specific_to_new_method`、`test_task_overlap_is_rejected_without_pool_mutation`：
  ```python
  assert local_match.status_code == 200
  assert "GT_SENTINEL" not in serialized_public_responses
  assert local_loop_start.status_code == 409
  assert stale_preview.status_code == 409
  assert fake_model.call_count == 0  # 匹配及独立规则评测
  assert pool_bytes_after_evaluation == pool_bytes_before_evaluation
  ```
  测试 idempotency 重试、非法任意路径、无 receipt 读取反馈、模型版本变化、来源健康失败不变成“错题”、已知研究题/实例/lineage/pair 与 Task 重叠拒绝。独立评测关闭修订回路；同一 holdout 后续重复评测显示已使用，不伪称首次。
- [ ] **Step 2: 红灯。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_api.py tests/test_rule_refinement_evaluation.py -q`。
- [ ] **Step 3: 实现适配。** 新方法研究选择仍强制 discovery，但 readiness 按至少 2 个唯一候选、存储答案和合法公开规格判定；添加方法专用分支并保留 scientific 的 kb_ready≥3 语义。配对模式核验完整身份及双方新方法资格，不因旧 kb_ready 错拒两候选题对。
  preview hash 覆盖编译语义、Dataset 精确修订与健康状态、KB/模型修订、生成计划、limits、源码身份。公开数据采用显式字段白名单；未封存研究反馈、尚未测试的生成私有结果、凭据引用/原始配置不能被递归复制到响应。新知识类型只从已接受 checkpoint/收据进入 inventory，不能让被拒 proposal 成为可选 KB；复用旧 KB 需显式转换为研究规则副本。
  rule_evaluation 为纯 stored-result job：worker 仅对此受严格校验的 kind 允许本地运行，其余真实执行维持原主机门禁；它不构造客户端、不生成代码、不修改 KB/pool。Task 使用全部累计研究及 KB 祖先使用记录检查重叠，已知重叠或题目身份不足以检查时阻断提交。评测使用账本独立保存，以后显式新研究运行才可学习这些反馈。若题目身份完整且无已知重叠，但初始 KB 无历史学习谱系，可保存描述性成绩并返回 `independence="unknown_prior_exposure"`，展示“此前接触情况未知”，不能标为已证明无泄漏的独立评测；完全可核验且首次使用时为 `verified_first_use`，已使用 holdout 为 `repeated_evaluation`。
- [ ] **Step 4: 验证。** 上述命令加 `tests/test_studio_api.py tests/test_studio_dataset_inputs.py tests/test_studio_knowledge.py tests/test_studio_initial_knowledge.py tests/test_studio_observations.py tests/test_execution_host_privacy.py`，预期全通过。
- [ ] **Step 5: 提交。** `git commit -m "feat: expose rule refinement and isolated rule evaluation APIs"`。

## Task 12: Harness 配置与受约束画布

**Files:** Create `frontend/workflow/src/{ruleRefinementTypes.ts,ruleRefinementApi.ts,RuleRefinementEditor.tsx,RuleRefinementCanvas.tsx,rule-refinement.css,RuleRefinementEditor.test.tsx,RuleRefinementCanvas.test.tsx}`；Modify 同目录 `App.tsx`, `Workflow.tsx`, `MethodPicker.tsx`, `types.ts`, `state.ts`, `workflowLayout.ts`, `useSharedWorkflowDraft.ts` 及对应测试。

**Interfaces:** `RuleRefinementEditor({workflow,onChange,bootstrap,onStarted})`、`RuleRefinementCanvas({workflow,onChange,validation,run?})`；onChange 接收完整 v2 Workflow，onStarted(runId: string)。types 镜像共享契约；API `matchRules(request)`、`previewRefinement(request)`、`startRefinement(request, idempotencyKey)` 使用 Task 11 路由。Dataset 选择器沿用固定修订预览，不将多题变成 Basic 首题。

- [ ] **Step 1: 写失败测试。** 四块配置、选择单题/完整题对 Dataset、规则匹配无模型、只在初始化/修订节点选择模型、编译失败禁止提交、改模型/KB/生成参数使预览失效、CAS 冲突保留本地草稿。关键交互断言：
  ```tsx
  expect(screen.queryByLabelText("作答模型")).not.toBeInTheDocument();
  expect(screen.getByLabelText("最大修订尝试")).toHaveValue(12);
  expect(screen.getByLabelText("连续新批次通过目标")).toHaveValue(2);
  expect(screen.getByRole("button", {name: "开始研究"})).toBeDisabled(); // 资源上限未填写
  ```
  测试 group_cases 增删/拖线/重排改变实际请求、protected port 禁止错误连接、布局变化不失去材料选择；schema v1 导入/导出/方法切换和旧草稿恢复仍工作。
- [ ] **Step 2: 红灯。** `npm --prefix frontend/workflow test -- src/RuleRefinementEditor.test.tsx src/RuleRefinementCanvas.test.tsx`。
- [ ] **Step 3: 实现 UI。** 研究 Dataset、初始规则 KB、修订模型/提示词、新题方案与限制四块；主要动作是“匹配预览”和“开始研究”。默认 12/3/3/16/48/2，资源上限空值必须填写并预检；配对数量展示 8 对/16 道及真实 GT 工作量。画布显示内外循环分组、可读节点及端口，参数在选中节点侧栏配置；避免所有内容都变成等宽按钮列表。
  新方法切换获取新模板，不沿用旧科学图；方法可选性由 data_modes/capabilities 判断，去掉对新方法的 paired_ 名称推断。parseWorkflow/draft/layout 显式支持 v2，并保留旧 JSON 不变。初始化知识使用独立研究规则选择器，不能放宽旧 InitialKBField 正式 KB 筛选。提交用稳定幂等键，浏览器刷新只恢复草稿/读取状态，不执行新任务。
- [ ] **Step 4: 验证。** 上述命令加 `src/Workflow.test.tsx src/DatasetInputPicker.test.tsx src/useSharedWorkflowDraft.test.tsx src/state.test.ts src/workflowLayout.test.ts`，预期全通过；`npm --prefix frontend/workflow run build` 通过。
- [ ] **Step 5: 提交。** `git commit -m "feat: configure rule refinement in the Harness canvas"`。

## Task 13: 实际运行、规则阅读和题目适用性

**Files:** Create `frontend/workflow/src/{RuleRefinementRun.tsx,RuleKnowledgeReader.tsx,ruleRefinementView.ts,RuleRefinementRun.test.tsx,RuleKnowledgeReader.test.tsx}`；Modify 同目录 `WorkflowWorkspace.tsx`, `Runs.tsx`, `RunMonitor.tsx`, `KB.tsx`, `displayNames.ts` 及各自测试。复用 QuestionReader、LiveOutput 和已定义 API/types。

**Interfaces:** `deriveRuleRefinementView(run: Run) -> RuleRefinementView`（在 types 文件补充），只接受实际 job/events/收据引用；`RuleRefinementRun({run,act})`、`RuleKnowledgeReader({kbRef,runId?,onEvaluate?})`；`onEvaluate(kbRef)` 打开 Task 专用规则评测配置，仅选 Dataset/phase 并执行 Task 11 预览与提交，不要求 LLM。

- [ ] **Step 1: 写失败测试。** `does_not_label_budget_stop_as_success`、`keeps_all_first_test_scores_after_later_success`、`reads_knowledge_before_applicable_questions`、`does_not_invent_model_text_for_rule_execution`、`reconnect_deduplicates_events_without_starting_run`：
  ```tsx
  expect(screen.getByText("资源上限已达到")).toBeVisible();
  expect(screen.queryByText("目标已达成")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", {name: "知识"})).toHaveAttribute("aria-selected", "true");
  expect(startRequests).toHaveLength(0); // 阅读/重连
  ```
  混合历史 run.kind 正常分派、无事件显示等待、未判定证据与零命中规则显示准确、下位关系反例可见、被拒补丁仍可读且不能选作当前 KB。断言 first-score 与累计成绩有不同标签，不能覆盖展示。
- [ ] **Step 2: 红灯。** `npm --prefix frontend/workflow test -- src/RuleRefinementRun.test.tsx src/RuleKnowledgeReader.test.tsx`。
- [ ] **Step 3: 实现视图。** 顶部展示 KB/题池版本、正确/可评分/未完成数量、明确作答率与真实当前阶段；中部按错题/冲突/缺口/规则反例组织阅读。点题沿用做题式 QuestionReader，旁边显示规则直接关系/传递路径及已释放 GT；KB 默认直接阅读条件、版本差异和证据，再切“适用题目”。通过记录视图进入完整首测历史和拒绝原因，不以重复点击卡片代替主要内容。
  接入持久化 stage polling 和 provider SSE；分别维护 sequence/seq，无推算阶段、假进度、假模型文本。暂停、停止、恢复按钮仅在后端允许状态出现。知识界面使用“在这些批次通过/尚未检验/有反例”的事实文案；预算结束仍能阅读最佳版本。独立 Task 界面只显示规则 KB 冻结快照与既有题集，终结结果不出现“继续修订同一运行”按钮。
- [ ] **Step 4: 验证。** 上述命令加 `src/WorkflowWorkspace.test.tsx src/Runs.test.tsx src/RunMonitor.test.tsx src/KB.test.tsx src/QuestionReader.test.tsx src/LiveOutput.test.tsx src/liveOutput.test.ts`，预期全通过。
- [ ] **Step 5: 提交。** `git commit -m "feat: inspect refinement evidence and executable rule knowledge"`。

## Task 14: 跨模块验收、使用说明与交付

**Files:** Create `tests/test_rule_refinement_integration.py`, `frontend/workflow/src/RuleRefinement.integration.test.tsx`, `docs/rule-refinement.md`；Modify `README.md` 的功能/启动说明，仅在实际完成后写能力；按失败定位修复本计划相关文件。

**Interfaces:** 只通过公开 API/worker 和现有 UI 入口验收；不新增第二套控制器。文档讲清研究用途、默认停止条件、模型参与位置、首测与回归区别、暂停恢复以及纯规则 Task 检查。

- [ ] **Step 1: 写贯穿失败测试。** mock 模型和 canonical 生成，在 API 层完成 Dataset→KB→规则预测→冲突修订→不退步验收→新题失败入池→两批连续通过；检查每一版评分和原始首测仍存在、调用/GT/题目数量与账本一致、全部预测先于任何反馈揭示。第二条贯穿测试中途断开 UI、重启控制器、重复提交，外部调用次数不增加；第三条验证最终 Task 反馈不改变任何研究产物。
- [ ] **Step 2: 运行新增贯穿测试。** `PYTHONPATH=src .venv/bin/python -m pytest tests/test_rule_refinement_integration.py -q`；`npm --prefix frontend/workflow test -- src/RuleRefinement.integration.test.tsx`。新增断言应先暴露未接通处，修复后全部 PASS，不能用删除断言完成验收。
- [ ] **Step 3: 一次完整回归。** 再核对 Git 根及准确解释器来源，运行 `PYTHONPATH=src .venv/bin/python -m pytest tests -q`、`npm --prefix frontend/workflow test`、`npm --prefix frontend/workflow run build`、`git diff --check`。预期全部通过；只在新改动或未解决失败出现时重复相应检查。必须包含 scientific/paired/Basic/RAG、旧草稿、封存 hash、模型 API、Data 生成和源健康测试。
- [ ] **Step 4: 实际页面检查与受限远端试验。** 本地启动构建页面，用合成/已存资料验证配置、无模型匹配、读题、规则阅读、恢复状态及 1280px/窄屏布局；真实调用仍关闭。如当时工具不能访问本地 UI，记录限制并交付构建及集成测试证据，不绕开权限，也不声称完成视觉验证。远端真实试验须在授权服务器按用户届时已提供的模型/数据/正预算执行；未确定这些值前停留在本地 mocked 验收，不把 mock 成绩宣传为真实模型效果。真实试验最小范围与资源上限先形成可复核配置再执行，不运行默认全量 48 道挑战来“顺便验证”。
- [ ] **Step 5: 完成文档和提交。** `git commit -m "test: verify the rule refinement research loop end to end"`；检查 diff 只含源码、测试、设计与说明，没有 state、题源、凭据、构建产物或私有服务器地址。按既有用户授权在验证和最终代码审查通过后同步 GitHub；如仍有其他任务在清理公开内容，先核实已完成再同步，不覆盖其修改。记录提交与实际测试结果，不修改旧运行指纹来演示恢复。

## 实施里程碑与审阅结果

- Task 1–5：纯程序规则验证和不退步比较，可在本地 fixture 上独立检验。
- Task 6–10：预算受控、可恢复的完整闭环，真实操作用 mock 验证。
- Task 11–13：可用的 Harness 配置、运行阅读、KB 适用题目与独立 Task 入口。
- Task 14：兼容性回归、实际页面核验、文档和 GitHub 交付；远端真实试验单独记录使用范围和结果。

本计划未改变已确认的验收原则和默认停止条件。实施前需审阅这份书面计划；沿用在当前对话逐项实施的选择。计划中的复选框仅在相应实现及验证完成后勾选，当前均未执行。
