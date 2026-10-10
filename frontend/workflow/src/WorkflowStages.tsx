import { useState, type ReactNode } from "react";
import { BookOpen, Database, FlaskConical, Network } from "lucide-react";
import { Field, Status } from "./ui";
import { RolePrompt } from "./RolePrompt";
import type { MethodDefinition, ModelProfile, QuestionSet, Workflow, StageId } from "./types";
import { LiveWorkflowCanvas, LiveWorkflowStage, useWorkflowRun } from "./LiveWorkflowCanvas";
import { MethodPicker } from "./MethodPicker";
import "./workflow-stages.css";

function Stage({
  stageId,
  number,
  title,
  description,
  icon,
  children,
}: {
  stageId: StageId;
  number: string;
  title: string;
  description: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return <LiveWorkflowStage stageId={stageId} title={title} number={number} description={description} icon={icon}>{children}</LiveWorkflowStage>;
}
function count(set?: QuestionSet) {
  return set?.count ?? set?.keys?.length ?? set?.questions?.length;
}
const roleNames: Record<string, string> = {
  solver: "解题 Solver",
  discoverer: "提出假说 Discoverer",
  skeptic: "检验假说 Skeptic",
  analyst: "分析证据 Analyst",
  curator: "整理知识 Curator",
};
function RoleConfig({
  role,
  label,
  template,
  guidance,
  onGuidance,
}: {
  role: string;
  label: string;
  template?: string;
  guidance: string;
  onGuidance: (prompt: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="workflow-role-disclosure"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>{label}</summary>
      {open && (
        <RolePrompt
          role={role}
          template={template}
          guidance={guidance}
          onGuidance={onGuidance}
        />
      )}
    </details>
  );
}
export function WorkflowStages({
  workflow,
  models,
  researchSet,
  taskSet,
  rolePrompts,
  onResearch,
  onTask,
  onResearchPairs,
  onResearchSingles,
  onTaskPairs,
  onTaskSingles,
  onSetting,
  onPhase,
  onRoute,
  onPrompt,
  children,
  methods = [],
  onMethod,
}: {
  methods?: MethodDefinition[];
  onMethod?: (method:MethodDefinition)=>void;
  workflow: Workflow;
  models: ModelProfile[];
  researchSet?: QuestionSet;
  taskSet?: QuestionSet;
  rolePrompts?: Record<string, string>;
  onResearch: () => void;
  onTask: () => void;
  onResearchPairs?: () => void;
  onResearchSingles?: () => void;
  onTaskPairs?: () => void;
  onTaskSingles?: () => void;
  onSetting: (key: string, value: any) => void;
  onPhase: (phase: string) => void;
  onRoute: (route: "confirmation" | "evaluation", enabled: boolean) => void;
  onPrompt: (id: string, prompt: string) => void;
  children: ReactNode;
}) {
  const live = useWorkflowRun();
  const method = methods.find(m=>m.id===workflow.settings.method_id);
  const model = models.find((m) => m.id === workflow.settings.model_id);
  const evaluating = workflow.edges.some(
    (e) => e.source === "loop" && e.target === "evaluate",
  );
  const phase =
    workflow.nodes.find((n) => n.id === "evaluate")?.config.phase || "final";
  const confirming = workflow.edges.some(
    (e) => e.source === "experiment" && e.target === "confirmation",
  );
  const selectedCount = count(researchSet),
    taskCount = count(taskSet);
  return (
    <LiveWorkflowCanvas draft={workflow} methodDefinition={method} run={live.run} syncState={live.syncState} act={live.act}>
      <Stage
        stageId="data"
        number="01"
        title="Data · 研究数据"
        description="选择用来作答、获取反馈与发现知识的题目。"
        icon={<Database size={22} />}
      >
        <div className="workflow-stage-selection">
          <div>
            <strong>
              {researchSet?.name ||
                (workflow.settings.question_set_id
                  ? "已保存研究题集"
                  : "尚未选择研究题目")}
            </strong>
            <p>
              {selectedCount === undefined
                ? "选择后保存为固定题集"
                : researchSet?.selection_mode === "pairs" ? `${researchSet.pair_count ?? Number(selectedCount)/2} 对 · ${selectedCount} 题 · 正常题与 DataFlip 成对研究` : `${selectedCount} 题 · 按冻结顺序研究`}
            </p>
          </div>
          <button className="primary" onClick={onResearch}>
            {workflow.settings.question_set_id
              ? "调整研究题目"
              : "选择研究题目"}
          </button>
        </div>
        {onResearchPairs && <button onClick={onResearchPairs}>选择研究题目对 · 正常题 + DataFlip</button>}
        {researchSet?.selection_mode === "pairs" && onResearchSingles && <button onClick={onResearchSingles}>改为单题选择</button>}
        <p className="workflow-stage-note">
          每轮最多 {workflow.settings.discovery_per_round ?? "—"} 题，共{" "}
          {workflow.settings.max_rounds ?? 1} 轮。研究题目的反馈会用于学习；Task
          使用独立评测题集。
        </p>
      </Stage>
      <Stage
        stageId="harness"
        number="02"
        title="Harness · 研究策略"
        description="配置如何从回答与实验中形成知识。"
        icon={<Network size={22} />}
      >
        {onMethod && <MethodPicker methods={methods} methodId={workflow.settings.method_id} paired={researchSet?.selection_mode=== "pairs"} onChange={onMethod}/>}
        {!workflow.settings.method_id && <Field label="学习方式" hint="模型权重保持固定，观察知识与推理上下文怎样随反馈变化。">
          <select value={workflow.settings.learning_protocol || "single"} onChange={e=>onSetting("learning_protocol", e.target.value)}>
            <option value="single" disabled={researchSet?.selection_mode === "pairs"}>普通题目研究</option>
            <option value="paired_contrastive" disabled={researchSet?.selection_mode !== "pairs"}>题对对照 · 解释变化与不变</option>
            <option value="paired_progressive" disabled={researchSet?.selection_mode !== "pairs"}>渐进学习 · 归纳 → 迁移 → 修订</option>
          </select>
        </Field>}
        {workflow.settings.learning_protocol?.startsWith("paired_") && <p className="pair-protocol-note">
          {workflow.settings.learning_protocol === "paired_progressive"
            ? "先保留两题独立作答的基线；只看正常题反馈形成初步规律，再用它预测 DataFlip，最后揭示对照反馈，补充适用条件、例外与交互。"
            : "两题独立作答并保存后，再对照真实反馈，解释哪个因素可能影响方案优劣，并提出可验证的假说。"}
          初步规律记为待验证；通过实验与发布检查后才进入正式 KB。
        </p>}
        <div className="workflow-strategy">
          <span className="pill teal-pill">当前支持的策略</span>
          <h3>{method?.name ?? "多 agent 证据研究"}</h3>
          <p>
            {method?.description ?? "独立作答 → 揭示反馈 → 提出与审查假说 → 运行实验 → 分析证据 → 整理知识。知识发布由程序验证。"}
          </p>
        </div>
        <div className="workflow-stage-fields">
          <Field
            label="研究模型"
            hint="所有研究角色与 Task 三组评测使用同一个固定模型。"
          >
            <select
              value={workflow.settings.model_id || ""}
              onChange={(e) => onSetting("model_id", e.target.value)}
            >
              <option value="">选择已登记模型</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="研究轮数" hint="各轮按冻结顺序继续取题。">
            <input
              type="number"
              min={1}
              max={3}
              value={workflow.settings.max_rounds ?? 1}
              onChange={(e) => onSetting("max_rounds", Number(e.target.value))}
            />
          </Field>
        </div>
        <div className="workflow-stage-fields">
          <Field label="循环方式" hint="手动模式每轮封存后等待决定；自动模式受冻结预算与停止条件约束。">
            <select value={workflow.settings.loop_mode || "automatic"} onChange={e=>onSetting("loop_mode", e.target.value)}><option value="manual">每轮等待决定</option><option value="automatic">自动继续</option></select>
          </Field>
          <Field label="连续无变化停止轮数" hint="正式知识与经验均无更新时停止，最多 3 轮；未设置时不启用此停止条件。"><input type="number" min={1} max={3} placeholder="未设置" value={workflow.settings.stop_after_no_change_rounds ?? ""} onChange={e=>onSetting("stop_after_no_change_rounds", e.target.value === "" ? undefined : Number(e.target.value))}/></Field>
        </div>
        <p className="workflow-stage-note">下一轮使用冻结题集的下一批与刚保存的版本；无下一批、预算不足或达到停止条件时结束。</p>
        {model && (
          <div className="workflow-stage-model">
            <strong>{model.name}</strong>
            <Status value={model.health?.status || "unchecked"} />
            <span>
              单次回答上限 {model.parameters?.max_tokens ?? "未登记"} tokens
            </span>
          </div>
        )}
        <details className="workflow-stage-disclosure">
          <summary>角色与提示词</summary>
          <p className="workflow-stage-note">
            角色固定协议与附加指令均可查看。实际发送的数据在运行记录中保存。
          </p>
          {workflow.nodes
            .filter((n) => n.type === "agent")
            .map((n) => (
              <RoleConfig
                key={n.id}
                role={n.id === "discoverer" && workflow.settings.learning_protocol?.startsWith("paired_") ? "pair_researcher" : n.id}
                label={n.id === "discoverer" && workflow.settings.learning_protocol?.startsWith("paired_") ? "反事实研究员 Pair Researcher" : roleNames[n.id] || n.label || n.id}
                template={rolePrompts?.[n.id === "discoverer" && workflow.settings.learning_protocol?.startsWith("paired_") ? "pair_researcher" : n.id]}
                guidance={n.config.prompt || ""}
                onGuidance={(prompt) => onPrompt(n.id, prompt)}
              />
            ))}
        </details>
        <details className="workflow-stage-disclosure">
          <summary>实验确认与研究预算</summary>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirming}
              onChange={(e) => onRoute("confirmation", e.target.checked)}
            />
            探索后独立确认
          </label>
          <p className="workflow-stage-note">
            开启独立确认使用 48 个独立数据集、10
            个训练种子，并将训练执行预算至少设为 1600 次。关闭后保留已设预算。
          </p>
          <p className="workflow-stage-note">
            当前每轮最多 {workflow.settings.max_calls_per_round ?? "—"}{" "}
            次模型调用，文本预算{" "}
            {workflow.settings.max_tokens_per_round?.toLocaleString() ?? "—"}{" "}
            tokens；训练执行上限{" "}
            {workflow.settings.max_candidate_seed_runs ?? "—"}{" "}
            次。修改这些上限和分批设置，请展开内部高级配置。
          </p>
        </details>
        {children}
      </Stage>
      <Stage
        stageId="kb"
        number="03"
        title="KB · 知识积累"
        description="保留有来源、适用条件与验证状态的知识版本。"
        icon={<BookOpen size={22} />}
      >
        <p>
          研究会记录知识建议、实验依据和适用范围。只有通过发布检查的更新才写入知识版本；没有通过检查的假说不能当作已验证知识。
        </p>
        {method?.experience_mode==="expel_inspired"&&<p>经验记忆单独保存为未验证版本；不会自动启用正式科学 KB 规则。</p>}
        <div className="workflow-kb-expectation">
          <span>知识正文</span>
          <span>适用范围</span>
          <span>验证状态</span>
          <span>证据与来源</span>
          <span>版本历史</span>
        </div>
        <details className="workflow-stage-disclosure">
          <summary>
            初始知识配置
            {workflow.settings.kb_path ? " · 已指定来源" : " · 未指定"}
          </summary>
          <Field
            label="初始知识文件"
            hint="服务器上的已有知识文件。导入记录将保留来源，不能因导入就称已验证。"
          >
            <input
              value={workflow.settings.kb_path || ""}
              placeholder="留空从默认初始知识开始"
              onChange={(e) => onSetting("kb_path", e.target.value)}
            />
          </Field>
          <Field
            label="知识规则文件"
            hint="用于解释初始知识的规则定义，按实际服务端配置校验。"
          >
            <input
              value={workflow.settings.rules_path || ""}
              onChange={(e) => onSetting("rules_path", e.target.value)}
            />
          </Field>
          <p className="workflow-stage-note">
            历史知识以未验证状态导入，不自动成为已确认、已启用的知识。运行后可查看实际保存的
            KB 版本。
          </p>
        </details>
      </Stage>
      <Stage
        stageId="task"
        number="04"
        title="Task · 新题解答与效果验证"
        description="用独立题目检查知识是否帮助固定模型解题。"
        icon={<FlaskConical size={22} />}
      >
        <label className="workflow-task-toggle">
          <input
            aria-label="安排独立评测"
            type="checkbox"
            checked={evaluating}
            onChange={(e) => onRoute("evaluation", e.target.checked)}
          />
          <strong>研究结束后安排独立评测</strong>
        </label>
        <p>
          在同一固定 LLM、同一评测题集上比较三组：无 KB、初始 KB、本轮
          KB。评测答案不参与知识发现。
        </p>
        {method?.experience_mode==="expel_inspired"&&<p>额外比较经验案例、经验规律、两者组合三组；均标记为未验证经验。</p>}
        {!evaluating && (
          <p className="workflow-task-off">
            本次未安排独立评测。已选择的评测题集会保留，关闭不会把它并入研究题集。
          </p>
        )}
        <Field
          label="独立评测阶段"
          hint="只选用题目原有 development 或 final 分区，不会修改题目的分区。"
        >
          <select value={phase} onChange={(e) => onPhase(e.target.value)}>
            <option value="final">最终盲测</option>
            <option value="development">开发集评测</option>
          </select>
        </Field>
        <div className="workflow-stage-selection">
          <div>
            <strong>
              {taskSet?.name ||
                (workflow.settings.task_question_set_id
                  ? "已保存独立评测题集"
                  : "尚未选择独立评测题目")}
            </strong>
            <p>
              {taskCount === undefined
                ? "独立选择，与研究题集分开冻结"
                : `已选 ${taskCount} 题 · 目标：${phase === "final" ? "最终盲测" : "开发评测"}，分区以预览核对为准`}
            </p>
          </div>
          <button onClick={onTask}>
            {workflow.settings.task_question_set_id
              ? "调整独立评测题目"
              : "选择独立评测题目"}
          </button>
        </div>
        {onTaskPairs && <button onClick={onTaskPairs}>选择独立评测题目对</button>}
        {taskSet?.selection_mode === "pairs" && onTaskSingles && <button onClick={onTaskSingles}>独立评测改为单题选择</button>}
        <p className="workflow-stage-note">
          更换评测分区后，需要核对所选题目的原分区。与研究集重复的题目、数据实例或谱系会在预览时拒绝。
        </p>
      </Stage>
    </LiveWorkflowCanvas>
  );
}
