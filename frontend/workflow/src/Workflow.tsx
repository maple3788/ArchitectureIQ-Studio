import { questionLabel, readableName } from "./displayNames";
import { useEffect, useState, useRef } from "react";
import { useWorkflowDraft } from "./SharedWorkflowDraft";
import "./shared-draft.css";
import {
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  Panel,
  PanOnScrollMode,
  type ReactFlowInstance,
  applyNodeChanges,
  applyEdgeChanges,
  type NodeProps,
  type Node,
  type Edge,
  type EdgeProps,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowRight,
  CheckCircle2,
  Code2,
  Download,
  FileJson,
  Maximize2,
  Play,
  RotateCcw,
  Save,
  Settings2,
  History,
  ShieldCheck,
  Upload,
  Workflow as WorkflowIcon,
} from "lucide-react";
import { api, ApiError, items } from "./api";
import { formatTimestamp } from "./time";
import { RolePrompt } from "./RolePrompt";
import {DatasetInputPicker} from "./DatasetInputPicker";
import { QuestionPicker } from "./QuestionPicker";
import { PairPicker } from "./PairPicker";
import { WorkflowStages } from "./WorkflowStages";
import { BasicLearning } from "./BasicLearning";
import { InitialKBPreview } from "./InitialKBPreview";
import { useWorkflowRun } from "./LiveWorkflowCanvas";
import { migrateWorkflowLayout, stageWidth } from "./workflowLayout";
import {
  workflowModelReady,
  parseWorkflow,
  serializeWorkflow,
  updatePrompt,
  setOptionalRoute,
} from "./state";
import {
  Card,
  Drawer,
  Empty,
  ErrorBox,
  Field,
  JsonView,
  Loading,
  Status,
  Tabs,
  useResource,
} from "./ui";
import type {
  List,
  ModelProfile,
  MethodDefinition,
  QuestionSet,
  Workflow as Spec,
  WorkflowNode,
} from "./types";
import type { Action } from "./Questions";
function cleanMethodDraft(value: Spec): Spec {
  if (!value.settings.method_id || !("experience_mode" in value.settings)) return value;
  const settings = {...value.settings};
  delete settings.experience_mode;
  return {...value, settings};
}
const labels: Record<string, string> = {
  input: "题目选择",
  solver: "解题 Solver",
  commit: "保存答案",
  reveal: "反馈揭示",
  discoverer: "提出假说 Discoverer",
  skeptic: "检验假说 Skeptic",
  experiment: "探索实验",
  confirmation: "独立确认",
  analyst: "分析证据 Analyst",
  curator: "整理知识 Curator",
  publish: "证据验证 / 发布",
  loop: "轮次控制",
  evaluate: "最终评估",
  end: "结束",
};
const descriptions: Record<string, string> = {
  input: "选择本次研究要回答的题目",
  solver: "独立作答，比较各个候选方案",
  commit: "保存回答，固定本轮解题记录",
  reveal: "将标准答案和反馈交给研究步骤",
  discoverer: "从本轮答题反馈提出可检验的假说",
  skeptic: "寻找反例，设计检验假说的实验",
  experiment: "执行生成代码，得到实验结果",
  confirmation: "用独立数据确认探索发现",
  analyst: "分析证据，判断假说适用的范围",
  curator: "把有依据的发现整理为知识更新",
  publish: "验证证据并保存通过检查的知识",
  loop: "按题目顺序进入下一轮研究",
  evaluate: "用独立题目评估当前知识的效果",
  end: "保存研究结果与完整运行记录",
};
const purposes: Record<string, string> = {
  input: "从题库选择题目，保存为固定题集。这些题目将用于本次解题和研究。",
  solver:
    "阅读题目并选择最佳候选方案，说明判断依据。作答时只使用题目公开的信息和当前知识。",
  commit:
    "保存 Solver 的原始回答和解析后的选择。本轮作答固定后，后续步骤才会获得答案反馈。",
  reveal:
    "读取标准答案、训练指标与答题反馈，供后续角色研究哪些判断有效、哪些需要改进。",
  discoverer:
    "阅读本轮答题反馈与现有知识，提出可以通过实验检验的新假说。题目按批次提供给这个角色。",
  skeptic: "审查假说的证据和适用条件，寻找反例，并提出需要运行的探索实验。",
  experiment:
    "按实验设计生成数据与候选代码，并执行这些代码获得标准结果，供后续分析。",
  confirmation: "对探索发现进行独立确认，使用新的数据与种子收集可复核的证据。",
  analyst:
    "综合探索和确认结果，评估假说是否成立，并说明支持范围、反例或尚未确定的部分。",
  curator: "根据分析结果整理候选知识更新，保留证据引用、适用条件与研究历史。",
  publish: "由程序检查证据、预算和更新合同，通过检查的知识会写入新的知识快照。",
  loop: "按固定题集的顺序分轮取题。在轮数和预算范围内继续研究，随后进入结束或独立评估。",
  evaluate: "在选定评估阶段上比较当前知识的解题效果，并记录真实回答和评分。",
  end: "保存本次研究的回答、实验、知识变化和调用收据，可在运行记录中继续查看。",
};
function StageNode({
  data,
  selected,
}: NodeProps<Node<{ stage: WorkflowNode; onActivate: () => void }>>) {
  const stage = data.stage;
  return (
    <div
      className={`stage-node ${stage.type === "agent" ? "agent" : "program"} ${selected ? "stage-selected" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`画布步骤：${labels[stage.id] || stage.label || stage.id}`}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          data.onActivate();
        }
      }}
    >
      <Handle type="target" position={Position.Top} id="in" />
      <div className="stage-kind">
        {stage.type === "agent" ? (
          <>
            <span className="agent-dot" />
            模型角色
          </>
        ) : (
          <>
            <Code2 size={11} />
            程序步骤
          </>
        )}
      </div>
      <strong>{labels[stage.id] || stage.label || stage.id}</strong>
      <small>{descriptions[stage.id] || stage.type}</small>
      <Handle type="source" position={Position.Bottom} id="out" />
    </div>
  );
}
const nodeTypes = { stage: StageNode };
function LoopEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  style,
}: EdgeProps) {
  const gutter = Math.min(sourceX, targetX) - stageWidth / 2 - 54;
  const path = `M ${sourceX} ${sourceY} L ${sourceX} ${sourceY + 26} L ${gutter} ${sourceY + 26} L ${gutter} ${targetY - 28} L ${targetX} ${targetY - 28} L ${targetX} ${targetY}`;
  return (
    <>
      <BaseEdge path={path} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <span
          className="workflow-loop-label"
          style={{
            position: "absolute",
            transform: `translate(-50%,-50%) translate(${gutter}px,${(sourceY + targetY) / 2}px)`,
            pointerEvents: "none",
          }}
        >
          下一轮
        </span>
      </EdgeLabelRenderer>
    </>
  );
}
const edgeTypes = { roundLoop: LoopEdge };

const numericSettings: [string, string, number, number?, string?][] = [
  [
    "discovery_per_round",
    "每轮题数（题）",
    1,
    undefined,
    "按冻结顺序分轮取题，后续轮次继续使用下一组题目。",
  ],
  [
    "packet_size",
    "每批分析题数（题）",
    1,
    undefined,
    "每轮最多分析4批。较大的批次可能超过模型上下文，请先预览。",
  ],
  [
    "exploration_count",
    "探索实验数量（个）",
    1,
    undefined,
    "每个实验计划最多选择多少个适用的独立数据实例；每个实例比较两个候选。找不到足够实例时会报告不足。",
  ],
  [
    "n_seeds",
    "每个候选的训练种子数（次）",
    1,
    undefined,
    "同一候选用不同随机种子重复训练多少次，用于比较结果的稳定性。",
  ],
  [
    "max_calls_per_round",
    "每轮调用上限（次）",
    1,
    undefined,
    "这一轮所有模型角色的调用总上限，包括逐题解答和研究分析。",
  ],
  [
    "max_tokens_per_round",
    "每轮文本预算（token）",
    1,
    undefined,
    "这一轮输入与输出文本的总预算。调用前保守预留输入、最大输出与消息开销，实际消耗可能少于预留。",
  ],
  [
    "max_candidate_seed_runs",
    "训练执行上限（候选 × 种子）",
    1,
    undefined,
    "整次运行的候选训练总次数上限，按候选数量乘以重复训练种子数计费；探索与独立确认共用。",
  ],
  [
    "seed_start",
    "起始随机种子",
    1,
    undefined,
    "用于固定实验数据采样；相同配置与种子可复现同一计划。",
  ],
  [
    "wall_time_seconds",
    "运行时限（秒）",
    1,
    undefined,
    "整次运行允许的总时长。程序在安全步骤边界检查，正在执行的步骤可能超过此时限。",
  ],
];
const pathSettings: [string, string, string][] = [
  ["output_root", "结果保存目录", "服务器上的输出目录；留空使用本任务目录。"],
  [
    "runtime_lock_path",
    "模型运行锁文件",
    "验证服务身份与请求参数；通常继承已登记模型。",
  ],
  ["kb_path", "初始知识文件", "服务器上的现有知识，留空按默认配置开始。"],
  ["rules_path", "知识规则文件", "服务器上的知识规则定义。"],
];
export function Workflow({
  version,
  act,
  executionEnabled,
  rolePrompts,
  onRun,
  onModels,
}: {
  version: number;
  act: Action;
  executionEnabled: boolean;
  rolePrompts?: Record<string, string>;
  onRun: (id: string) => void;
  onModels?: () => void;
}) {
  const liveRun = useWorkflowRun();
  const shared = useWorkflowDraft();
  const { workflow, setWorkflow, advancedBackup, setAdvancedBackup } = shared;
  const catalogVersion = version + (shared.revision ?? 0);
  const methods = useResource<{items:MethodDefinition[]}>("/methods", version);
  const flowRef = useRef<ReactFlowInstance | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [datasetPickerOpen,setDatasetPickerOpen]=useState(false);
  const [pickerMode, setPickerMode] = useState<"single" | "pairs">("single");
  const [pickerPurpose, setPickerPurpose] = useState<"research" | "evaluation">(
    "research",
  );
  const [internalOpen, setInternalOpen] = useState(false);
  const [appliedTaskSet, setAppliedTaskSet] = useState<QuestionSet>();
  const openPicker = (purpose: "research" | "evaluation" = "research", mode?: "single" | "pairs") => {
    setPickerMode(mode ?? ((purpose === "evaluation" ? chosenTaskSet : chosenSet)?.selection_mode === "pairs" ? "pairs" : "single"));
    setPickerPurpose(purpose);
    setPickerOpen(true);
  };
  const [appliedSet, setAppliedSet] = useState<QuestionSet>();
  const history = useResource<List<any>>("/workflows", version);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historySelection, setHistorySelection] = useState<any>();
  const defaults = useResource<Spec>("/workflow/default");
  const models = useResource<List<ModelProfile>>("/models", catalogVersion);
  const sets = useResource<List<QuestionSet>>("/question-sets", catalogVersion);
  const initializedDraft = useRef(false);
  const [freshBasic, setFreshBasic] = useState(false);
  const modelSelectionTouched=useRef(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewAttempted, setPreviewAttempted] = useState(false);
  const [nodeId, setNodeId] = useState("input");
  const [edgeId, setEdgeId] = useState<string>();
  const [mode, setMode] = useState("节点");
  const [validation, setValidation] = useState<{
    valid: boolean;
    errors: any[];
  }>();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<{
    signature: string;
    data: any;
    submissionKey: string;
  }>();
  const signature = JSON.stringify(workflow);
  const currentSignature = useRef(signature);
  currentSignature.current = signature;
  const previewReady =
    preview?.signature === signature &&
    typeof preview?.data.config_hash === "string" &&
    !!preview.data.config_hash;
  const [previewOpen, setPreviewOpen] = useState(false);
  const [saved, setSaved] = useState<any>();
  const [mapping, setMapping] = useState("{}");
  useEffect(() => {
    if (!shared.loading && workflow && !initializedDraft.current) {
      initializedDraft.current = true;
      setFreshBasic(workflow.settings.method_id === "basic_learning");
    }
  }, [shared.loading, workflow]);
  useEffect(() => {
    setValidation(undefined);
    setPreview(undefined);
  }, [signature]);
  useEffect(() => {
    if (historyOpen) void shared.refreshBackups();
  }, [historyOpen, shared.refreshBackups]);
  useEffect(() => {
    if (!freshBasic || workflow?.settings.method_id !== "basic_learning" || workflow.settings.question_set_id) return;
    let active=true;
    void (async()=>{
      try {
        let offset=0, question:any;
        while(active&&!question){
          const page=await api<List<any>>(`/questions?split=discovery&offset=${offset}&limit=200`);
          question=page.items.find(q=>q.ready===true&&q.kb_ready===true&&(!q.split||q.split==='discovery'));
          offset+=page.items.length;
          if(question||!page.items.length||offset>=page.total)break;
        }
        if(!active)return;
        if(!question){setNotice("题库暂无可用于单题学习的完整发现题，请导入或选择真实题目。");return;}
        const savedSet=await api<QuestionSet>("/question-sets",{name:`单题学习 · ${questionLabel(question)}`,keys:[question.key]});
        if(!active)return;
        setAppliedSet(savedSet);
        setWorkflow(current=>current?.settings.method_id==='basic_learning'&&!current.settings.question_set_id?{...current,settings:{...current.settings,question_set_id:savedSet.id}}:current);
        setNotice("已从题库选入 1 道真实发现题，可点击题目节点查看或更换。");
      } catch(e) { if(active)setError(`默认题目读取失败：${(e as Error).message}`); }
    })();
    return()=>{active=false;};
  },[freshBasic,workflow?.settings.method_id,workflow?.settings.question_set_id]);
  useEffect(()=>{
    if(!freshBasic||!workflow||workflow.settings.model_id||modelSelectionTouched.current)return;
    const ready=items(models.data).find(m=>workflowModelReady(m,workflow.settings.method_id));
    if(ready)setWorkflow(current=>current&&!current.settings.model_id?{...current,settings:{...current.settings,model_id:ready.id}}:current);
  },[freshBasic,models.data,workflow?.settings.model_id]);
  const node = workflow?.nodes.find((n) => n.id === nodeId);
  const edge = workflow?.edges.find((e) => e.id === edgeId);
  const chosenModel = items(models.data).find(
    (m) => m.id === workflow?.settings.model_id,
  );
  const setSetting = (key: string, value: any) => {
    if(key==='model_id')modelSelectionTouched.current=true;
    if(workflow)setWorkflow({...workflow,settings:{...workflow.settings,[key]:value}});
  };
  const chosenSet =
    appliedSet?.id === workflow?.settings.question_set_id
      ? appliedSet
      : items(sets.data).find(
          (s) => s.id === workflow?.settings.question_set_id,
        );
  const chosenTaskSet =
    appliedTaskSet?.id === workflow?.settings.task_question_set_id
      ? appliedTaskSet
      : items(sets.data).find(
          (s) => s.id === workflow?.settings.task_question_set_id,
        );
  const taskPhase =
    workflow?.nodes.find((n) => n.id === "evaluate")?.config.phase ===
    "development"
      ? "development"
      : "final";
  const applyTaskQuestions = (set: QuestionSet) => {
    if (!workflow) return;
    const count = set.count ?? set.keys?.length ?? set.questions?.length;
    if (!Number.isInteger(count) || !count || count < 1) {
      setError("独立评测题集缺少明确的题数，请重新选择。");
      return;
    }
    setAppliedTaskSet(set);
    setSetting("task_question_set_id", set.id);
    setPreview(undefined);
    setPickerOpen(false);
    setError("");
    setNotice(`已保存${count}道独立评测题目；研究集、轮数和预算保持当前配置。`);
  };
  const setPhase = (phase: string) =>
    workflow &&
    setWorkflow({
      ...workflow,
      nodes: workflow.nodes.map((n) =>
        n.id === "evaluate" ? { ...n, config: { ...n.config, phase } } : n,
      ),
    });
  const questionCount =
    chosenSet?.keys?.length ?? chosenSet?.questions?.length ?? chosenSet?.count;
  const applyQuestions = (set: QuestionSet) => {
    setFreshBasic(false);
    if (!workflow) return;
    const count = set.keys?.length ?? set.questions?.length ?? set.count;
    if (!Number.isInteger(count) || !count || count < 1) {
      setError("题集缺少明确的题目数量，请重新选择。");
      return;
    }
    if(workflow.settings.method_id==='basic_learning'){
      if(count!==1||set.selection_mode==='pairs'){setError("单题学习每次只选 1 道题；多题与题对请切换高级方法。");return;}
      setAppliedSet(set);setSetting('question_set_id',set.id);setPickerOpen(false);setError('');setNotice('已更换真实题目，学习轮数与提示词保持当前配置。');return;
    }
    const paired = set.selection_mode === "pairs";
    const compatibleMethod = methods.data?.items.find(m=>m.status === "available" && m.learning_protocol.startsWith("paired_") === paired && m.experience_mode === (methods.data?.items.find(selected=>selected.id===workflow.settings.method_id)?.experience_mode ?? "off"));
    if (workflow.settings.method_id && !compatibleMethod) {
      setError("当前方法与题集类型不兼容，请先选择可用的方法配方。");
      return;
    }
    const settings = {...workflow.settings};
    if (settings.method_id) delete settings.experience_mode;
    setAppliedSet(set);
    setWorkflow({
      ...workflow,
      settings: {
        ...settings,
        question_set_id: set.id,
        max_rounds: 1,
        discovery_per_round: count,
        ...(workflow.settings.method_id && compatibleMethod ? {method_id: compatibleMethod.id, method_version: compatibleMethod.version} : {}),
        learning_protocol: workflow.settings.method_id && compatibleMethod ? compatibleMethod.learning_protocol : set.selection_mode === "pairs"
          ? (workflow.settings.method_id || workflow.settings.learning_protocol === "paired_progressive" ? "paired_progressive" : "paired_contrastive") : "single",
        packet_size: set.selection_mode === "pairs" ? 2 : Math.max(
          Number(workflow.settings.packet_size) || 1,
          Math.ceil(count / 4),
        ),
      },
    });
    setPreview(undefined);
    setError("");
    setPickerOpen(false);
    setNotice(
      set.selection_mode === "pairs" ? `已选 ${count / 2} 对，正常题与 DataFlip 原子配对；调用预算请在预览中核对。` : `已选${count}题，按1轮逐题作答；分为最多4批分析。调用与文本预算保持当前设置。`,
    );
  };
  const coverage = `${questionCount == null ? "当前题集" : `题集共${questionCount}题`}；每轮最多${workflow?.settings.discovery_per_round ?? "—"}题，共${workflow?.settings.max_rounds ?? 1}轮，按冻结顺序使用下一组题目。`;
  const startViewport = () => {
    const start = workflow?.nodes.find((n) => n.id === "input");
    const zoom = 0.9;
    return {
      x:
        (canvasRef.current?.clientWidth || 520) / 2 -
        ((start?.position.x || 0) + stageWidth / 2) * zoom,
      y: 84 - (start?.position.y || 0) * zoom,
      zoom,
    };
  };
  const selectStage = (stage: WorkflowNode, center = true) => {
    setNodeId(stage.id);
    setEdgeId(undefined);
    setMode("节点");
    if (center)
      void flowRef.current?.setCenter(
        stage.position.x + stageWidth / 2,
        stage.position.y + 50,
        { zoom: 1, duration: 200 },
      );
    if (stage.id === "input") openPicker();
  };
  const numberField = (
    key: string,
    label: string,
    min = 1,
    max?: number,
    hint?: string,
  ) => (
    <Field key={key} label={label} hint={hint}>
      <input
        type="number"
        min={min}
        max={max}
        value={workflow?.settings[key] ?? ""}
        onChange={(e) => setSetting(key, Number(e.target.value))}
      />
    </Field>
  );
  const questionSummary = (
    <div className="workflow-question-summary">
      <strong>
        {chosenSet?.name ||
          (workflow?.settings.question_set_id ? "已保存题集" : "尚未选择题目")}
      </strong>
      <p>
        {questionCount == null
          ? workflow?.settings.question_set_id
            ? "题目数量待加载"
            : "从题库挑选本次研究的题目"
          : `${questionCount} 题 · 固定题集`}
      </p>
      <button className="primary wide" onClick={() => openPicker()}>
        {workflow?.settings.question_set_id ? "重新选择题目" : "选择题目"}
      </button>
      <small>{coverage}</small>
    </div>
  );
  const modelSummary = (
    <div className="workflow-model-summary">
      <strong>{chosenModel?.name || "尚未选择模型"}</strong>
      <p>
        {chosenModel
          ? `${chosenModel.model || chosenModel.name} · 所有研究角色使用这个模型`
          : "请在运行设置中选择已登记模型"}
      </p>
      {chosenModel && (
        <Status value={chosenModel.health?.status || "unchecked"} />
      )}
    </div>
  );
  const routes = (
    <>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={
            workflow?.edges.some(
              (e) => e.source === "experiment" && e.target === "confirmation",
            ) || false
          }
          onChange={(e) =>
            workflow &&
            setWorkflow(
              setOptionalRoute(workflow, "confirmation", e.target.checked),
            )
          }
        />
        探索后独立确认
      </label>
      <p className="muted">
        启用后使用48个独立数据集、10个训练种子；训练执行预算至少1600次。关闭后保留当前预算。
      </p>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={
            workflow?.edges.some(
              (e) => e.source === "loop" && e.target === "evaluate",
            ) || false
          }
          onChange={(e) =>
            workflow &&
            setWorkflow(
              setOptionalRoute(workflow, "evaluation", e.target.checked),
            )
          }
        />
        结束前独立评估
      </label>
    </>
  );
  const validate = async () => {
    if (!workflow) return;
    const r = await act(() => api("/workflows/validate", workflow));
    if (r) {
      setValidation(r);
      setNotice(r.valid ? "科学流程校验通过" : "存在未通过的科学约束");
    }
    return r;
  };
  const save = async () => {
    const r = await validate();
    if (r?.valid) {
      const record = await act(
        () => api("/workflows", workflow),
        "工作流版本已保存",
      );
      if (record) {
        setSaved(record);
        setNotice("已保存工作流固定版本，可在版本与备份中查看。");
      }
    }
  };
  const request = () => {
    if (!workflow?.settings.question_set_id || !workflow?.settings.model_id)
      throw new Error("请在运行设置中选择冻结题集与被测 LLM。");
    return {
      kind: "workflow",
      question_set_id: workflow.settings.question_set_id,
      model_ids: [workflow.settings.model_id],
      workflow,
    };
  };
  const loadPreview = async () => {
    if(previewLoading || shared.status !== "saved")return;
    setPreviewLoading(true);setPreviewAttempted(true);
    const frozenSignature = signature;
    setPreview(undefined);
    const r = await act(() => api("/runs/preview", request()));
    setPreviewLoading(false);
    if (r) {
      setPreview({
        signature: frozenSignature,
        data: r,
        submissionKey: crypto.randomUUID(),
      });
      setPreviewOpen(true);
    }
  };
  const run = async () => {
    if (shared.status !== "saved") return;
    if (!previewReady || !preview) {
      await loadPreview();
      return;
    }
    const frozenSignature = signature;
    if (!(await validate())?.valid) return;
    const r = await act(async () => {
      if (currentSignature.current !== frozenSignature)
        throw new Error("工作流已修改，请重新预览当前配置。");
      try {
        return await api(
          "/runs",
          { ...request(), expected_config_hash: preview.data.config_hash },
          undefined,
          { "Idempotency-Key": preview.submissionKey },
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          setPreview(undefined);
          throw new Error("预览配置版本已变化，请重新预览。" + e.message);
        }
        throw e;
      }
    }, "研究运行已提交");
    if (r) { if (liveRun.act) setPreviewOpen(false); onRun(r.id); }
  };
  const connect = (connection: Connection) => {
    if (!workflow || !connection.source || !connection.target) return;
    const source = connection.source,
      target = connection.target;
    const id = `${source}-${target}-${Date.now()}`;
    setWorkflow({
      ...workflow,
      edges: [
        ...workflow.edges,
        {
          id,
          source,
          target,
          source_handle: connection.sourceHandle || "out",
          target_handle: connection.targetHandle || "in",
          condition:
            source === "loop"
              ? target === "input"
                ? "continue"
                : "done"
              : "always",
          mapping: {},
        },
      ],
    });
    setEdgeId(id);
    setMode("连线");
  };
  const importFile = async (file: File) => {
    try {
      const next = parseWorkflow(await file.text());
      setFreshBasic(false);
      setWorkflow(migrateWorkflowLayout(cleanMethodDraft(next)));
      setNodeId("input");
      setMode("节点");
      setNotice("JSON 已载入草稿，请校验后保存");
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const exportJson = () => {
    if (!workflow) return;
    const url = URL.createObjectURL(
      new Blob([serializeWorkflow(workflow)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "workflow.json";
    a.click();
    URL.revokeObjectURL(url);
  };
  const switchMethod=async(identifier:string)=>{
    if(!workflow||identifier===workflow.settings.method_id)return;
    if(identifier!=='basic_learning'&&workflow.settings.method_id!=='basic_learning'){
      const method=methods.data?.items.find(m=>m.id===identifier);if(!method)return;
      const settings={...workflow.settings};delete settings.experience_mode;
      setWorkflow({...workflow,settings:{...settings,method_id:method.id,method_version:method.version,learning_protocol:method.learning_protocol}});return;
    }
    const next=await act(()=>api<Spec>(`/workflow/default?method_id=${encodeURIComponent(identifier)}`));
    if(!next)return;
    setFreshBasic(false);
    if(identifier==='basic_learning'){
      setAdvancedBackup(workflow);
    }
    const retained:Record<string,any>={};
    if(workflow.settings.model_id)retained.model_id=workflow.settings.model_id;
    if(identifier!=='basic_learning'||(questionCount===1&&chosenSet?.selection_mode!=='pairs'))retained.question_set_id=workflow.settings.question_set_id;
    const nextWorkflow={...next,settings:{...next.settings,...retained},nodes:next.nodes.map((n:WorkflowNode)=>{const old=workflow.nodes.find(o=>o.id===n.id);return old?.type==='agent'?{...n,config:{...n.config,prompt:old.config.prompt??''}}:n;})};
    setWorkflow(migrateWorkflowLayout(nextWorkflow));setFreshBasic(identifier==='basic_learning'&&!retained.question_set_id);setPreview(undefined);setPreviewAttempted(false);setNotice(identifier==='basic_learning'?'已进入单题学习；原高级草稿已保留，可随时恢复。':'已切换高级方法，请核对题目与运行配置。');
  };
  if (shared.loading) return <Loading />;
  if (!workflow)
    return (
      <>
        <ErrorBox error={shared.error} />
        <Empty title="无法读取服务器草稿">连接恢复后继续读取同一份工作流配置。</Empty>
        <button onClick={() => void shared.retry()}>重新连接服务器</button>
      </>
    );
  const nodes: Node[] = workflow.nodes.map((stage) => ({
    id: stage.id,
    type: "stage",
    position: stage.position,
    data: { stage, onActivate: () => selectStage(stage, false) },
    selected: stage.id === nodeId && mode === "节点",
    deletable: false,
  }));
  const edges: Edge[] = workflow.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_handle || "out",
    targetHandle: e.target_handle || "in",
    label:
      e.condition === "continue"
        ? undefined
        : e.condition === "done"
          ? "完成"
          : undefined,
    type:
      e.source === "loop" && e.target === "input" ? "roundLoop" : "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
    selected: e.id === edgeId,
    style: {
      stroke: e.condition === "continue" ? "#78a29c" : "#7f8d9c",
      strokeWidth: 1.6,
    },
    data: e,
  }));
  const showBasic=(liveRun.run?liveRun.run.config?.method?.id??liveRun.run.config?.workflow?.settings.method_id:workflow.settings.method_id)==='basic_learning';
  const startReasons=[
    shared.status !== "saved" ? "请先将当前配置同步到服务器" : undefined,
    !workflow.settings.question_set_id?'尚未选择真实题目':undefined,
    !workflow.settings.model_id?'尚未选择模型':!workflowModelReady(chosenModel,workflow.settings.method_id)?(chosenModel?.connection_type==='api'?'模型尚未通过运行验证，请先检查 API 服务':'模型尚未通过运行验证'):undefined,
    !executionEnabled?'当前服务为只读 / 预览模式，请连接服务器执行服务':undefined,
    previewLoading?'正在生成冻结预览':!previewReady?(previewAttempted?'配置已变化或预览未成功，请重新预览':'尚未预览当前配置'):undefined,
  ].filter((reason):reason is string=>!!reason);
  return (
    <div className={`workflow-page stage-editor ${showBasic?'is-basic':''}`}>
      <div className="workflow-title">
        <div>
          <span className="eyebrow">DATA → HARNESS → KB → TASK</span>
          <input
            aria-label="工作流名称"
            className="workflow-name"
            value={workflow.name}
            onChange={(e) => setWorkflow({ ...workflow, name: e.target.value })}
          />
          <p>
            可编辑草稿 <span>·</span>{" "}
            {saved ? "版本 " + saved.revision : "尚未保存版本"} <span>·</span>{" "}
            从研究题目，到知识与独立验证
          </p>
        </div>
        <div className="workflow-toolbar">
          <label className="upload-button compact">
            <Upload size={15} />
            导入
            <input
              type="file"
              accept=".json"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importFile(f);
                e.target.value = "";
              }}
            />
          </label>
          <button onClick={exportJson}>
            <Download size={15} />
            导出
          </button>
          <button onClick={() => setHistoryOpen(true)}>
            <History size={15} />
            版本
          </button>
          <button onClick={() => void validate()}>
            <ShieldCheck size={15} />
            校验
          </button>
          <button onClick={() => void save()}>
            <Save size={15} />
            保存
          </button>
        </div>
      </div>
      {!liveRun.run && <section className={`shared-draft shared-draft-${shared.status}`} aria-label="服务器共享草稿">
        <div className="shared-draft-heading">
          <div role="status" aria-live="polite"><span className="shared-draft-dot"/>{({
            loading: "正在读取服务器草稿…", saved: "已保存到服务器", saving: "正在保存到服务器…",
            pending: "等待保存到服务器…", offline: "服务器连接中断，修改尚未同步", conflict: "另一窗口已更新配置",
          })[shared.status]}</div>
          <button className="text-button" onClick={() => setHistoryOpen(true)}>版本与备份</button>
        </div>
        <p>Chrome 与 GPT 共用此配置{shared.revision ? ` · 第 ${shared.revision} 版` : ""}{shared.updatedAt ? ` · ${formatTimestamp(shared.updatedAt)}` : ""}</p>
        {shared.status === "conflict" && <div className="shared-draft-conflict" role="alert">
          <p>你的修改暂未覆盖服务器。选择保留哪一版，另一版会留在服务器备份中。</p>
          <div className="actions"><button onClick={() => void shared.acceptRemote()}>使用服务器版本</button><button onClick={() => void shared.keepLocal()}>保留我的修改</button><button onClick={exportJson}>导出我的草稿</button></div>
        </div>}
        {shared.status === "offline" && <div className="actions"><button onClick={() => void shared.retry()}>重试同步</button><button onClick={exportJson}>导出未同步草稿</button></div>}
        <ErrorBox error={shared.error}/>
        {shared.error && shared.status === "saved" && <button onClick={() => void shared.retry()}>重试备份同步</button>}
      </section>}
      <ErrorBox error={error || defaults.error} />
      {!showBasic&&!liveRun.run&&<div className="basic-entry"><p>保留当前高级草稿，也可以从一道题开始学习。</p><button onClick={()=>void switchMethod('basic_learning')}>单题学习</button></div>}
      {!liveRun.run&&<div className="dataset-workflow-entry"><span>从命名 Dataset 固定实验输入</span><button onClick={()=>{setFreshBasic(false);setPickerPurpose('research');setDatasetPickerOpen(true);}}>从 Dataset 选择</button>{!showBasic&&<button onClick={()=>{setPickerPurpose('evaluation');setDatasetPickerOpen(true);}}>从 Dataset 选择评测题</button>}</div>}
      {showBasic?<><BasicLearning workflow={workflow} models={items(models.data)} researchSet={chosenSet} onResearch={()=>{setFreshBasic(false);openPicker('research','single');}} onSetting={setSetting} onPrompt={(id,prompt)=>setWorkflow(updatePrompt(workflow,id,prompt))} rolePrompts={rolePrompts} version={version} run={liveRun.run} syncError={liveRun.syncState?.error} act={liveRun.act}/>
        {!liveRun.run&&<details className="basic-advanced"><summary>高级方法与草稿管理</summary><Field label="切换学习方法"><select aria-label="切换学习方法" value={workflow.settings.method_id??''} onChange={e=>void switchMethod(e.target.value)}><option value="basic_learning">单题学习</option>{(methods.data?.items??[]).filter(m=>m.id!=='basic_learning').map(m=><option key={m.id} value={m.id} disabled={m.status!=='available'}>{m.name}</option>)}</select></Field><div className="basic-advanced-tools"><button onClick={()=>void save()}>保存版本</button><button onClick={exportJson}>导出 JSON</button><label className="upload-button compact">导入 JSON<input type="file" accept=".json" onChange={e=>{const f=e.target.files?.[0];if(f)void importFile(f);e.target.value='';}}/></label><button onClick={()=>setHistoryOpen(true)}>历史版本</button>{advancedBackup&&<button onClick={()=>{setFreshBasic(false);setWorkflow(advancedBackup);setNotice('已恢复切换前的高级草稿。');}}>恢复原高级草稿</button>}</div></details>}
      </>:<WorkflowStages
        workflow={workflow}
        methods={methods.data?.items ?? []}
        onMethod={method=>{void switchMethod(method.id);}}
        models={items(models.data)}
        researchSet={chosenSet}
        taskSet={chosenTaskSet}
        rolePrompts={rolePrompts}
        onResearch={() => openPicker("research")}
        onTask={() => openPicker("evaluation")}
        onResearchPairs={() => openPicker("research", "pairs")}
        onResearchSingles={() => openPicker("research", "single")}
        onTaskPairs={() => openPicker("evaluation", "pairs")}
        onTaskSingles={() => openPicker("evaluation", "single")}
        onSetting={setSetting}
        onPhase={setPhase}
        onRoute={(route, enabled) =>
          setWorkflow(setOptionalRoute(workflow, route, enabled))
        }
        onPrompt={(id, prompt) =>
          setWorkflow(updatePrompt(workflow, id, prompt))
        }
      >
        <details
          className="workflow-stage-disclosure"
          onToggle={(e) => setInternalOpen(e.currentTarget.open)}
        >
          <summary>内部流程与高级配置</summary>
          <p className="workflow-stage-note">
            查看完整竖向流程，编辑内部步骤、连线和服务器配置。主阶段选择与这里共用一份草稿。
          </p>
          {internalOpen && (
            <>
              <div className="workflow-layout">
                <aside className="node-library">
                  <div className="panel-title">
                    <WorkflowIcon size={15} />
                    <b>流程节点</b>
                  </div>
                  <small className="panel-caption">单击查看职责与配置</small>
                  {workflow.nodes.map((stage) => (
                    <button
                      className={`library-item ${stage.id === nodeId && mode === "节点" ? "active" : ""}`}
                      key={stage.id}
                      onClick={() => selectStage(stage)}
                    >
                      <span
                        className={
                          stage.type === "agent"
                            ? "node-dot agent-dot"
                            : "node-dot"
                        }
                      />
                      <div>
                        <strong>
                          {labels[stage.id] || stage.label || stage.id}
                        </strong>
                        <small>{descriptions[stage.id] || "查看配置"}</small>
                      </div>
                    </button>
                  ))}
                  <div className="library-foot">
                    <ShieldCheck size={17} />
                    <p>
                      保存答案 → 揭示反馈
                      <br />
                      KB 发布必须经过证据验证
                    </p>
                  </div>
                </aside>
                <div className="canvas-wrap" ref={canvasRef}>
                  <div className="canvas-caption">
                    <span className="pill teal-pill">研究流程</span>
                    <span>从上到下 · 滚动浏览 · 单击步骤查看配置</span>
                  </div>
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={nodeTypes}
                    edgeTypes={edgeTypes}
                    onNodesChange={(changes) => {
                      const next = applyNodeChanges(changes, nodes);
                      if (changes.some((c) => c.type === "position"))
                        setWorkflow({
                          ...workflow,
                          nodes: workflow.nodes.map((n) => ({
                            ...n,
                            position:
                              next.find((x) => x.id === n.id)?.position ||
                              n.position,
                          })),
                        });
                    }}
                    onEdgesChange={(changes) => {
                      if (changes.some((c) => c.type === "remove")) {
                        const next = applyEdgeChanges(changes, edges);
                        setWorkflow({
                          ...workflow,
                          edges: workflow.edges.filter((e) =>
                            next.some((x) => x.id === e.id),
                          ),
                        });
                      }
                    }}
                    onNodeClick={(_, n) =>
                      selectStage(n.data.stage as WorkflowNode, false)
                    }
                    onEdgeClick={(_, e) => {
                      setEdgeId(e.id);
                      setMapping(
                        JSON.stringify(
                          workflow.edges.find((x) => x.id === e.id)?.mapping ||
                            {},
                          null,
                          2,
                        ),
                      );
                      setMode("连线");
                    }}
                    onConnect={connect}
                    onReconnect={(_, connection) => {
                      if (!edge) return;
                      setWorkflow({
                        ...workflow,
                        edges: workflow.edges.map((e) =>
                          e.id === edge.id
                            ? {
                                ...e,
                                source: connection.source || e.source,
                                target: connection.target || e.target,
                                source_handle: connection.sourceHandle || "out",
                                target_handle: connection.targetHandle || "in",
                              }
                            : e,
                        ),
                      });
                    }}
                    defaultViewport={startViewport()}
                    onInit={(instance) => {
                      flowRef.current = instance;
                      void instance.setViewport(startViewport());
                    }}
                    panOnScroll
                    nodesFocusable={false}
                    panOnScrollMode={PanOnScrollMode.Vertical}
                    zoomOnScroll={false}
                    minZoom={0.15}
                    maxZoom={1.5}
                  >
                    <Panel position="top-right">
                      <div className="canvas-view-actions">
                        <button
                          className="canvas-jump"
                          onClick={() =>
                            void flowRef.current?.fitView({
                              padding: 0.15,
                              duration: 200,
                              minZoom: 0.15,
                              maxZoom: 1,
                            })
                          }
                        >
                          <Maximize2 size={14} />
                          查看全貌
                        </button>
                        <button
                          className="canvas-jump"
                          onClick={() =>
                            void flowRef.current?.setViewport(startViewport(), {
                              duration: 200,
                            })
                          }
                        >
                          回到起点
                        </button>
                      </div>
                    </Panel>
                    <Background color="#cdd6db" gap={22} size={1} />
                    <Controls />
                    <MiniMap
                      pannable
                      zoomable
                      nodeColor={(n) =>
                        (n.data.stage as WorkflowNode).type === "agent"
                          ? "#168878"
                          : "#a8b3c0"
                      }
                    />
                  </ReactFlow>
                </div>
                <aside className="inspector">
                  <Tabs
                    tabs={["节点", "连线", "运行设置"]}
                    value={mode}
                    onChange={setMode}
                  />
                  <div className="inspector-content">
                    {mode === "节点" && node ? (
                      <>
                        <span className="eyebrow">
                          {node.type === "agent" ? "研究角色" : "流程步骤"}
                        </span>
                        <h2>{labels[node.id] || node.label || node.id}</h2>
                        <p className="workflow-program-copy">
                          {purposes[node.id] || descriptions[node.id]}
                        </p>
                        {node.type === "agent" ? (
                          <>
                            {modelSummary}
                            <RolePrompt
                              key={node.id}
                              role={node.id}
                              template={rolePrompts?.[node.id]}
                              guidance={node.config.prompt || ""}
                              onGuidance={(prompt) =>
                                setWorkflow(
                                  updatePrompt(workflow, node.id, prompt),
                                )
                              }
                            />
                            <details className="workflow-advanced">
                              <summary>模型参数与运行身份</summary>
                              {chosenModel?.parameters && (
                                <p className="muted">
                                  temperature
                                  控制回答的随机程度，较低值通常更稳定；top_p
                                  限制可选文本的概率范围；max_tokens
                                  限制每次回答的最大输出长度，并参与调用前的预算预留。实际值继承已登记模型，下方记录便于核对。
                                </p>
                              )}
                              <JsonView
                                value={
                                  chosenModel
                                    ? {
                                        model: chosenModel.model,
                                        parameters: chosenModel.parameters,
                                        health: chosenModel.health,
                                      }
                                    : { status: "尚未选择模型" }
                                }
                              />
                            </details>
                          </>
                        ) : node.id === "input" ? (
                          questionSummary
                        ) : node.id === "experiment" ? (
                          <>
                            {numberField(
                              "exploration_count",
                              "探索实验数量（个）",
                              1,
                              undefined,
                              numericSettings.find(
                                (setting) => setting[0] === "exploration_count",
                              )?.[4],
                            )}
                            {numberField(
                              "n_seeds",
                              "每个候选的训练种子数（次）",
                              1,
                              undefined,
                              numericSettings.find(
                                (setting) => setting[0] === "n_seeds",
                              )?.[4],
                            )}
                            <p className="muted">
                              训练会在服务器执行；先预览输入和预算，再提交运行。
                            </p>
                          </>
                        ) : node.id === "loop" ? (
                          <>
                            {numberField("max_rounds", "研究轮数", 1, 3)}
                            <p className="muted">{coverage}</p>
                            <details className="workflow-advanced">
                              <summary>分轮取题与分析批次</summary>
                              {numberField(
                                "discovery_per_round",
                                "每轮题数（题）",
                              )}
                              {numberField(
                                "packet_size",
                                "每批分析题数（题）",
                                1,
                                undefined,
                                "每轮最多4批，请预览批次是否适合模型上下文。",
                              )}
                            </details>
                          </>
                        ) : node.id === "confirmation" ? (
                          <>
                            <p className="muted">
                              {workflow.edges.some(
                                (e) => e.target === "confirmation",
                              )
                                ? "本次流程已启用独立确认。"
                                : "本次流程尚未启用独立确认，可在运行设置的可选路线中开启。"}
                            </p>
                            <button
                              className="wide"
                              onClick={() => setMode("运行设置")}
                            >
                              查看可选路线
                            </button>
                          </>
                        ) : node.id === "evaluate" ? (
                          <>
                            <p className="muted">
                              {workflow.edges.some(
                                (e) => e.target === "evaluate",
                              )
                                ? "本次流程已启用独立评估。"
                                : "本次流程尚未启用独立评估。"}
                            </p>
                            <Field label="评估阶段">
                              <select
                                value={node.config.phase || "final"}
                                onChange={(e) =>
                                  setWorkflow({
                                    ...workflow,
                                    nodes: workflow.nodes.map((n) =>
                                      n.id === node.id
                                        ? {
                                            ...n,
                                            config: {
                                              ...n.config,
                                              phase: e.target.value,
                                            },
                                          }
                                        : n,
                                    ),
                                  })
                                }
                              >
                                <option value="final">最终盲测</option>
                                <option value="development">开发集测试</option>
                              </select>
                            </Field>
                          </>
                        ) : null}
                        <details className="workflow-advanced">
                          <summary>步骤标识与输出记录</summary>
                          <p className="muted">
                            步骤标识：{node.id}
                            。执行后在运行详情查看相应收据、实验与知识产物。
                          </p>
                          {Object.keys(node.config).length > 0 && (
                            <JsonView value={node.config} />
                          )}
                        </details>
                        <button
                          className="wide"
                          onClick={() => void loadPreview()}
                        >
                          预览完整运行输入
                          <ArrowRight size={15} />
                        </button>
                      </>
                    ) : mode === "连线" ? (
                      edge ? (
                        <>
                          <span className="eyebrow">步骤连接</span>
                          <h2>
                            {labels[edge.source] || edge.source} →{" "}
                            {labels[edge.target] || edge.target}
                          </h2>
                          <p className="workflow-program-copy">
                            这条连线决定步骤的执行顺序。保存或运行前会检查数据权限与科学流程。
                          </p>
                          <details className="workflow-advanced">
                            <summary>高级连线配置</summary>
                            <Field label="源节点">
                              <select
                                value={edge.source}
                                onChange={(e) =>
                                  setWorkflow({
                                    ...workflow,
                                    edges: workflow.edges.map((x) =>
                                      x.id === edge.id
                                        ? { ...x, source: e.target.value }
                                        : x,
                                    ),
                                  })
                                }
                              >
                                {workflow.nodes.map((n) => (
                                  <option key={n.id} value={n.id}>
                                    {labels[n.id] || n.id}
                                  </option>
                                ))}
                              </select>
                            </Field>
                            <Field label="目标节点">
                              <select
                                value={edge.target}
                                onChange={(e) =>
                                  setWorkflow({
                                    ...workflow,
                                    edges: workflow.edges.map((x) =>
                                      x.id === edge.id
                                        ? { ...x, target: e.target.value }
                                        : x,
                                    ),
                                  })
                                }
                              >
                                {workflow.nodes.map((n) => (
                                  <option key={n.id} value={n.id}>
                                    {labels[n.id] || n.id}
                                  </option>
                                ))}
                              </select>
                            </Field>
                            <div className="form-grid">
                              <Field label="源端口">
                                <input
                                  value={edge.source_handle || "out"}
                                  readOnly
                                />
                              </Field>
                              <Field label="目标端口">
                                <input
                                  value={edge.target_handle || "in"}
                                  readOnly
                                />
                              </Field>
                            </div>
                            <Field label="执行条件">
                              <select
                                value={edge.condition || "always"}
                                onChange={(e) =>
                                  setWorkflow({
                                    ...workflow,
                                    edges: workflow.edges.map((x) =>
                                      x.id === edge.id
                                        ? { ...x, condition: e.target.value }
                                        : x,
                                    ),
                                  })
                                }
                              >
                                <option value="always">继续执行</option>
                                <option value="continue">还有下一轮</option>
                                <option value="done">轮次已结束</option>
                              </select>
                            </Field>
                            <Field
                              label="字段映射（JSON）"
                              hint="当前协议使用固定数据权限，自定义映射会在校验时被检查。"
                            >
                              <textarea
                                className="mono"
                                rows={4}
                                value={mapping}
                                onChange={(e) => setMapping(e.target.value)}
                                onBlur={() => {
                                  try {
                                    const value = JSON.parse(mapping);
                                    setWorkflow({
                                      ...workflow,
                                      edges: workflow.edges.map((x) =>
                                        x.id === edge.id
                                          ? { ...x, mapping: value }
                                          : x,
                                      ),
                                    });
                                    setError("");
                                  } catch {
                                    setError("字段映射须为合法 JSON");
                                  }
                                }}
                              />
                            </Field>
                            <button
                              className="danger wide"
                              onClick={() => {
                                setWorkflow({
                                  ...workflow,
                                  edges: workflow.edges.filter(
                                    (x) => x.id !== edge.id,
                                  ),
                                });
                                setEdgeId(undefined);
                              }}
                            >
                              删除此连线
                            </button>
                          </details>
                          <p className="muted">
                            可选路线在运行设置中开启：探索后独立确认、结束前独立评估。
                          </p>
                        </>
                      ) : (
                        <Empty title="单击画布上的连线">
                          查看步骤之间的执行关系。
                        </Empty>
                      )
                    ) : (
                      <>
                        <span className="eyebrow">本次研究</span>
                        <h2>运行设置</h2>
                        <div className="workflow-core-settings">
                          {questionSummary}
                          <Field
                            label="研究模型"
                            hint="Solver 等所有研究角色继承同一个模型。"
                          >
                            <select
                              value={workflow.settings.model_id || ""}
                              onChange={(e) =>
                                setSetting("model_id", e.target.value)
                              }
                            >
                              <option value="">选择已登记模型</option>
                              {items(models.data).map((m) => (
                                <option key={m.id} value={m.id}>
                                  {m.name} · {m.health?.status || "未检查"}
                                </option>
                              ))}
                            </select>
                          </Field>
                          {numberField(
                            "max_rounds",
                            "研究轮数",
                            1,
                            3,
                            "各轮按冻结顺序使用下一组题目。重新选择题目会设为1轮覆盖所选题目。",
                          )}
                        </div>
                        <details className="workflow-advanced">
                          <summary>可选科学路线</summary>
                          {routes}
                        </details>
                        <details className="workflow-advanced">
                          <summary>预算与服务器文件</summary>
                          <p className="muted">
                            较大的题集可能超出当前调用、文本或训练预算。先查看完整预览，再调整这些上限。
                          </p>
                          {numericSettings.map(([key, label, min, max, hint]) =>
                            numberField(key, label, min, max, hint),
                          )}
                          <Field
                            label="生成配置（Profile）"
                            hint="约束数据、模型和训练配置的已登记 profile。"
                          >
                            <input
                              value={workflow.settings.profile || ""}
                              onChange={(e) =>
                                setSetting("profile", e.target.value)
                              }
                            />
                          </Field>
                          <h3>服务器文件</h3>
                          {pathSettings.map(([key, label, hint]) => (
                            <Field key={key} label={label} hint={hint}>
                              <input
                                className="mono"
                                value={workflow.settings[key] || ""}
                                onChange={(e) =>
                                  setSetting(key, e.target.value)
                                }
                              />
                            </Field>
                          ))}
                        </details>
                        <button
                          className="wide"
                          onClick={() => void loadPreview()}
                        >
                          预览输入与运行预算
                        </button>
                      </>
                    )}
                  </div>
                </aside>
              </div>
            </>
          )}
        </details>
      </WorkflowStages>}
      <ErrorBox error={models.error || sets.error} />
      <div className="workflow-stage-submit" hidden={!!liveRun.run}>
        <div>
          <strong>预览后开始研究</strong>
          <p>
            冻结研究集、独立评测集、模型、KB 与预算；修改配置后需要重新预览。
          </p>
        </div>
        <div className="actions">
          <button
            disabled={
              !workflow.settings.question_set_id || !workflow.settings.model_id || previewLoading || shared.status !== "saved"
            }
            onClick={() => void loadPreview()}
          >
            预览研究配置
          </button>
          <button
            className="primary"
            disabled={
              startReasons.length > 0
            }
            onClick={() => void run()}
          >
            <Play size={15} />
            开始研究
          </button>
        </div>
        {startReasons.length>0&&<ul className="basic-start-reasons" aria-label="开始前需要完成">{startReasons.map(reason=><li key={reason}><span>{reason}</span>{reason==='尚未选择真实题目'&&<button onClick={()=>openPicker()}>选择题目</button>}{reason.startsWith('模型尚未通过运行验证')&&chosenModel&&<button onClick={()=>void act(()=>api(`/models/${encodeURIComponent(chosenModel.id)}/check`,{}))}>检查模型</button>}{reason==='尚未选择模型'&&onModels&&<button onClick={onModels}>模型设置</button>}</li>)}</ul>}
      </div>
      <div className="workflow-status">
        <div>
          <span className={`status-dot ${validation?.valid ? "ok" : ""}`} />
          {notice || "配置自动保存到服务器，所有浏览器共用"}
          <span className="muted">· 冻结版本与历史运行保持独立</span>
        </div>
        <button
          className="text-button"
          onClick={() => {
            if (defaults.data){
              setWorkflow(migrateWorkflowLayout(cleanMethodDraft(defaults.data)));
              setFreshBasic(defaults.data.settings.method_id==='basic_learning');
            }
            setNodeId("input");
            setMode("节点");
            setSaved(undefined);
            setNotice("已恢复服务器默认模板");
          }}
        >
          <RotateCcw size={14} />
          恢复默认
        </button>
      </div>
      {datasetPickerOpen&&<DatasetInputPicker purpose={pickerPurpose} phase={taskPhase} methodId={workflow.settings.method_id} selectionMode={workflow.settings.learning_protocol?.startsWith('paired')?'pairs':'single'} single={workflow.settings.method_id==='basic_learning'&&pickerPurpose==='research'} onApply={set=>{(pickerPurpose==='evaluation'?applyTaskQuestions:applyQuestions)(set);setDatasetPickerOpen(false);}} onClose={()=>setDatasetPickerOpen(false)}/>}
      {pickerOpen && pickerMode === "pairs" && (
        <PairPicker version={version} act={act} purpose={pickerPurpose} phase={taskPhase}
          questionSetId={(pickerPurpose === "evaluation" ? chosenTaskSet : chosenSet)?.selection_mode === "pairs"
            ? (pickerPurpose === "evaluation" ? workflow.settings.task_question_set_id : workflow.settings.question_set_id) : undefined}
          onApply={pickerPurpose === "evaluation" ? applyTaskQuestions : applyQuestions}
          onClose={() => setPickerOpen(false)} />
      )}
      {pickerOpen && pickerMode === "single" && (
        <QuestionPicker
          key={`${pickerPurpose}-${taskPhase}`}
          version={version}
          act={act}
          purpose={pickerPurpose}
          phase={taskPhase}
          single={workflow.settings.method_id==='basic_learning'&&pickerPurpose==='research'}
          questionSetId={
            (pickerPurpose === "evaluation"
              ? workflow.settings.task_question_set_id
              : workflow.settings.question_set_id) || undefined
          }
          onApply={
            pickerPurpose === "evaluation" ? applyTaskQuestions : applyQuestions
          }
          onClose={() => setPickerOpen(false)}
        />
      )}
      {validation && !validation.valid && (
        <div className="validation-errors">
          <ShieldCheck size={18} />
          <div>
            <b>请修正后保存或运行</b>
            {validation.errors.map((e, i) => (
              <p key={i}>{typeof e === "string" ? e : JSON.stringify(e)}</p>
            ))}
          </div>
        </div>
      )}
      {historyOpen && (
        <Drawer
          title="工作流版本与备份"
          subtitle="服务器统一保留。载入后更新共享草稿，其他浏览器会同步。"
          onClose={() => setHistoryOpen(false)}
        >
          <h3>草稿备份</h3>
          <p className="muted">包括浏览器迁移、自动保存前的版本和冲突时保留的配置。</p>
          {shared.backups.length ? shared.backups.map(record => <Card key={record.id}
            title={readableName(record.workflow.name, "未命名工作流")}
            subtitle={`${({legacy_browser:"浏览器迁移备份", conflict:"冲突保留", manual:"手动备份", revision:"先前草稿"} as Record<string,string>)[record.source] || "草稿备份"} · ${formatTimestamp(record.created_at)}`}>
            <button onClick={() => {
              setWorkflow(migrateWorkflowLayout(cleanMethodDraft(record.workflow)));
              setAdvancedBackup(record.advanced_backup ?? undefined);
              setFreshBasic(false); setSaved(undefined); setHistoryOpen(false);
              setNotice("已载入备份，正在同步到共享草稿。");
            }}>恢复此草稿</button>
          </Card>) : <p className="muted">暂无草稿备份</p>}
          <h3>已保存的固定版本</h3>
          <ErrorBox error={history.error} />
          {history.loading ? (
            <Loading />
          ) : items(history.data).length ? (
            items(history.data).map((record: any, i: number) => (
              <Card
                key={record.id || i}
                title={readableName(record.workflow?.name || record.name, "工作流草稿")}
                subtitle={
                  "版本 " +
                  (record.revision ?? "—") +
                  " · " +
                  formatTimestamp(record.created_at ?? record.updated_at)
                }
                action={
                  <button onClick={() => setHistorySelection(record)}>
                    查看
                  </button>
                }
              >
                {historySelection === record && (
                  <>
                    <JsonView value={record.workflow || record} />
                    <button
                      className="wide"
                      disabled={!record.workflow}
                      onClick={() => {
                        setWorkflow(migrateWorkflowLayout(cleanMethodDraft(record.workflow)));
                        setNodeId("input");
                        setMode("节点");
                        setSaved(undefined);
                        setHistoryOpen(false);
                        setNotice(
                          "已从版本 " + record.revision + " 派生新草稿",
                        );
                      }}
                    >
                      载入为新草稿
                    </button>
                  </>
                )}
              </Card>
            ))
          ) : (
            <Empty title="尚未保存版本" />
          )}
        </Drawer>
      )}
      {previewOpen && (
        <Drawer
          title="完整输入预览"
          subtitle="仅预览 · 尚未发送任何模型请求"
          onClose={() => setPreviewOpen(false)}
        >
          <p className="muted">
            预览绑定模型、题集、KB
            与执行配置版本。修改后请重新预览；提交时服务器再次核对版本。
          </p>
          <div className="actions">
            <button onClick={() => void loadPreview()}>重新预览</button>
            <button
              className="primary"
              disabled={
                shared.status !== "saved" ||
                !previewReady ||
                !executionEnabled ||
                !workflowModelReady(chosenModel, workflow.settings.method_id)
              }
              onClick={() => void run()}
            >
              <Play size={15} />
              按此配置运行
            </button>
          </div>
          {!previewReady && (
            <p className="muted">
              预览已失效或缺少配置签名，请重新预览当前配置。
            </p>
          )}
          <div className="workflow-preview-summary">
            <div>
              <strong>Data · 冻结研究题集</strong>
              <p>
                {chosenSet?.name || "研究题集"} ·{" "}
                {questionCount ?? "题数待确认"} 题
                {preview?.data.task?.effective_research_count !== undefined &&
                  `；实际研究 ${preview.data.task.effective_research_count} 题`}
              </p>
              {preview?.data.task?.notice && <p>{preview.data.task.notice}</p>}
            </div>
            <div>
              <strong>{showBasic?"Harness · 单题学习":"Harness · 多 agent 证据研究"}</strong>
              <p>
                {chosenModel?.name || "模型待确认"} ·{" "}
                {workflow.settings.max_rounds ?? 1}{" "}
                轮；预算与上下文以服务端预览结果为准。
              </p>
              {preview?.data.learning?.model_identity?.kind==='api_configuration'&&<p>API 服务，权重身份未验证；冻结服务地址、模型名与请求参数。</p>}
              {showBasic&&<p>每轮作答与提炼经验，共 {preview?.data.learning?.max_calls_all_rounds??"见冻结记录"} 次调用上限；每轮结束后等待决定。</p>}
              {preview?.data.learning?.pair_count !== undefined && <p>{preview.data.learning.pair_count} 对 · 全程最多 {preview.data.learning.max_calls_all_rounds} 次研究模型调用（含审查、分析与整理）。{preview.data.learning.notice}</p>}
            </div>
            <div>
              <strong>KB · 初始知识</strong>
              {showBasic?<InitialKBPreview preview={preview?.data}/>:<p>
                {workflow.settings.kb_path
                  ? "已指定历史来源；导入不等于已验证。"
                  : "未指定历史知识文件。"}
              </p>}
            </div>
            {!showBasic&&<div>
              <strong>Task · 独立验证</strong>
              <p>
                {preview?.data.task
                  ? preview.data.task.enabled
                    ? `${preview.data.task.count} 题 · ${preview.data.task.phase === "final" ? "最终盲测" : "开发评测"} · 无 KB / 初始 KB / 本轮 KB`
                    : "本次未安排独立评测，保留已有选择。"
                  : workflow.edges.some((e) => e.target === "evaluate")
                    ? "已安排三组评测；实际执行题数请核对完整服务端预览。"
                    : "本次未安排独立评测。"}
              </p>
            </div>}
          </div>
          <details className="workflow-stage-disclosure">
            <summary>完整冻结输入与预算记录</summary>
            <JsonView value={preview?.data} />
          </details>
        </Drawer>
      )}
    </div>
  );
}
