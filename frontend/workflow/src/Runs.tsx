import {RuleRefinementRun} from './RuleRefinementRun';
import {RuleEvaluation} from './RuleEvaluation';
import type {KBRef} from './ruleRefinementTypes';
import {RagRunView} from './RagRunView';
import { useEffect, useState } from "react";
import {
  ArrowRight,
  Clock3,
  Eye,
  FlaskConical,
  Pause,
  Play,
  RefreshCw,
  Search,
  Terminal,
  X,
} from "lucide-react";
import { api, ApiError, items } from "./api";
import { runProgress } from "./progress";
import { RunWorkflowView } from "./RunWorkflowView";
import { nodeLabel } from "./runWorkflow";
import { RunConnection, RunControls, runStateLabels, useRunMonitor } from "./RunMonitor";
import { formatTimestamp } from "./time";
import { runLabel, readableName } from "./displayNames";
import { auditRecord } from "./audit";
import { ReceiptContent } from "./ReceiptContent";
import { ResultSummary } from "./ResultSummary";
import { evaluationRequest, modelReady } from "./state";
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
import type { Json, List, ModelProfile, QuestionSet, Run } from "./types";
import type { Action } from "./Questions";
export function Runs({
  version,
  act,
  executionEnabled,
  initialSet,
  ruleKB,
  selectedRun,
  onRun,
  onWorkflowRun,
}: {
  version: number;
  act: Action;
  executionEnabled: boolean;
  initialSet?: string;
  ruleKB?: KBRef;
  selectedRun?: string;
  onRun: (id: string) => void;
  onWorkflowRun?: (id: string) => void;
}) {
  const [evaluationMode,setEvaluationMode]=useState(ruleKB?"规则 KB 检查":"模型评测");
  useEffect(()=>{if(ruleKB)setEvaluationMode("规则 KB 检查");},[ruleKB?.id,ruleKB?.version]);
  const runs = useResource<List<Run>>("/runs", version, 5000);
  const models = useResource<List<ModelProfile>>("/models", version);
  const sets = useResource<List<QuestionSet>>("/question-sets", version);
  const [setId, setSetId] = useState(initialSet || "");
  const [modelIds, setModelIds] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [maxCalls, setMaxCalls] = useState(50);
  const [maxTokens, setMaxTokens] = useState(2000000);
  const [preview, setPreview] = useState<{
    signature: string;
    data: any;
    submissionKey: string;
  }>();
  const signature = JSON.stringify({
    setId,
    modelIds,
    prompt,
    maxCalls,
    maxTokens,
  });
  const previewReady =
    preview?.signature === signature &&
    typeof preview?.data.config_hash === "string" &&
    !!preview.data.config_hash;
  const [previewOpen, setPreviewOpen] = useState(false);
  const [openRun, setOpenRun] = useState(selectedRun);
  const [kind, setKind] = useState("all");
  useEffect(() => {
    if (initialSet) setSetId(initialSet);
  }, [initialSet]);
  useEffect(() => {
    if (selectedRun) setOpenRun(selectedRun);
  }, [selectedRun]);
  useEffect(
    () => setPreview(undefined),
    [setId, modelIds, prompt, maxCalls, maxTokens],
  );
  const request = () =>
    evaluationRequest(setId, modelIds, prompt, maxCalls, maxTokens);
  const selected = items(sets.data).find((s) => s.id === setId);
  const count =
    selected?.count ?? selected?.keys?.length ?? selected?.questions?.length;
  const start = async () => {
    const r = await act(async () => {
      if (!previewReady || !preview)
        throw new Error("请先完成当前配置的完整输入预览。");
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
    }, "评测任务已提交");
    if (r) {
      onRun(r.id);
      setOpenRun(r.id);
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">EVALUATION & RUN HISTORY</span>
          <h1>让每次测试可追溯。</h1>
          <p>冻结题集与模型，预览完整输入，再查看实际请求、原始响应与评分。</p>
        </div>
        <span className="pill">
          <Clock3 size={13} />
          运行由服务器持久化
        </span>
      </div>
      <Tabs tabs={["模型评测","规则 KB 检查"]} value={evaluationMode} onChange={setEvaluationMode}/>
      {evaluationMode === "规则 KB 检查" ? <RuleEvaluation kbRef={ruleKB} onStarted={id=>{onRun(id);setOpenRun(id);}}/> : <div className="run-setup-grid">
        <Card
          title="新建模型评测"
          subtitle="相同公开输入与题目顺序 · 一个或多个被测 LLM"
        >
          <div className="form-grid">
            <Field label="冻结题集">
              <select
                aria-label="评测题集"
                value={setId}
                onChange={(e) => setSetId(e.target.value)}
              >
                <option value="">选择已保存题集</option>
                {items(sets.data).map((s) => (
                  <option value={s.id} key={s.id}>
                    {readableName(s.name, "冻结题集")} ·{" "}
                    {s.count ?? s.keys?.length ?? s.questions?.length ?? "—"} 题
                  </option>
                ))}
              </select>
            </Field>
            <div className="request-estimate">
              <small>预计题目 × 模型</small>
              <b>{count !== undefined ? count * modelIds.length : "—"}</b>
              <span>实际请求仍受预算限制</span>
            </div>
          </div>
          <Field label="被测 LLM（可多选）">
            <div className="model-select-grid">
              {items(models.data).map((m) => (
                <label
                  className={`model-option ${modelIds.includes(m.id) ? "checked" : ""}`}
                  key={m.id}
                >
                  <input
                    type="checkbox"
                    aria-label={"被测模型 " + m.name}
                    checked={modelIds.includes(m.id)}
                    disabled={!modelReady(m)}
                    onChange={(e) =>
                      setModelIds(
                        e.target.checked
                          ? [...modelIds, m.id]
                          : modelIds.filter((id) => id !== m.id),
                      )
                    }
                  />
                  <div>
                    <b>{m.name || m.id}</b>
                    <small>
                      {m.model} · 单次输出上限{" "}
                      {m.parameters?.max_tokens ?? "未登记"} tokens
                    </small>
                  </div>
                  <Status value={m.health?.status || "unchecked"} />
                </label>
              ))}
              {!models.loading && !items(models.data).length && (
                <p className="muted">先在模型页面登记并检查服务。</p>
              )}
            </div>
          </Field>
          <ErrorBox error={models.error || sets.error} />
          <Field
            label="评测任务提示词"
            hint="空值沿用服务端默认任务。完整最终 messages 请查看预览。"
          >
            <textarea
              rows={5}
              aria-label="评测提示词"
              placeholder="添加明确的答题要求…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </Field>
          <div className="form-grid">
            <Field label="最大调用数">
              <input
                type="number"
                min={1}
                value={maxCalls}
                onChange={(e) => setMaxCalls(Number(e.target.value))}
              />
            </Field>
            <Field
              label="整次评测 token 总预算"
              hint="整次任务输入与输出的保守总预算。单次输出上限来自各模型登记参数；预览显示 reserved_tokens。"
            >
              <input
                type="number"
                min={1}
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value))}
              />
            </Field>
          </div>
          <div className="actions">
            <button
              disabled={!setId || !modelIds.length}
              onClick={async () => {
                const frozenSignature = signature;
                setPreview(undefined);
                const r = await act(() => api("/runs/preview", request()));
                if (r) {
                  setPreview({
                    signature: frozenSignature,
                    data: r,
                    submissionKey: crypto.randomUUID(),
                  });
                  setPreviewOpen(true);
                }
              }}
            >
              <Eye size={16} />
              完整输入预览
            </button>
            <button
              className="primary"
              disabled={
                !executionEnabled || !setId || !modelIds.length || !previewReady
              }
              onClick={() => void start()}
            >
              <Play size={15} />
              提交模型评测
            </button>
          </div>
          {!previewReady && (
            <p className="muted">
              提交前请预览当前完整输入、实际模型参数及整次任务保守 token 预留。
            </p>
          )}
          {!executionEnabled && (
            <p className="muted">
              当前服务未启用执行。可保存配置并预览；模型推理在指定服务器执行。
            </p>
          )}
        </Card>
        <Card className="protocol-card" title="一次公平的比较">
          <div className="protocol-number">01</div>
          <h3>精确题目版本</h3>
          <p>题集保留版本、内容哈希和顺序。更换 LLM 不改变题内候选与 GT。</p>
          <div className="protocol-number">02</div>
          <h3>明确生效参数</h3>
          <p>每个模型使用登记的解码参数；不兼容参数由服务器拒绝。</p>
          <div className="protocol-number">03</div>
          <h3>真实调用记录</h3>
          <p>预览与已发送请求分栏保存。失败、超时与无效输出同样保留。</p>
          <div className="divider" />
          <span className="eyebrow">KB RESEARCH</span>
          <p>五角色研究使用工作流页面中的固定单模型配置。</p>
        </Card>
      </div>}
      <Card
        title="运行历史"
        subtitle="刷新或离开页面不会取消已提交的服务器任务。"
        action={
          <select
            aria-label="运行类型筛选"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="all">全部类型</option>
            <option value="evaluation">模型评测</option>
            <option value="workflow">KB 研究</option>
            <option value="rule_refinement">规则 KB 闭环</option><option value="rule_evaluation">规则评测</option>
            <option value="generation">题目生成</option>
            <option value="rag">RAG 作答</option>
          </select>
        }
      >
        <ErrorBox error={runs.error} />
        {runs.loading ? (
          <Loading />
        ) : items(runs.data).filter((r) => kind === "all" || r.kind === kind)
            .length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>运行</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>创建时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items(runs.data)
                  .filter((r) => kind === "all" || r.kind === kind)
                  .map((r) => (
                    <tr key={r.id}>
                      <td>
                        <button
                          className="row-link"
                          onClick={() => setOpenRun(r.id)}
                        >
                          {runLabel(r)}
                        </button>
                      </td>
                      <td>
                        {r.kind === "rule_refinement" ? "规则 KB 闭环" : r.kind === "rule_evaluation" ? "规则评测" : r.kind === "workflow"
                          ? "KB 研究"
                          : r.kind === "generation"
                            ? "题目生成"
                            : r.kind === "evaluation"
                              ? "模型评测"
                              : r.kind === "rag" ? "RAG 作答" : r.kind}
                      </td>
                      <td>
                        <Status value={runStateLabels[r.status] || r.status} />
                      </td>
                      <td>
                        {r.kind === "workflow" ? <>
                          {r.progress?.node_id ? nodeLabel(r.progress.node_id) : "等待首条执行记录"}
                          {r.progress?.round_index && <small>{r.progress.node_id === "evaluate" || r.progress.round_index === 1000 ? "最终独立评测" : `第 ${r.progress.round_index} 轮`}</small>}
                        </> : <>
                          {runProgress(r).completed ?? "—"}
                          {runProgress(r).total ? ` / ${runProgress(r).total}` : ""}
                          {r.progress?.stage && <small>{r.progress.stage}</small>}
                        </>}
                      </td>
                      <td>
                        <small>{formatTimestamp(r.created_at)}</small>
                      </td>
                      <td>
                        <button
                          className="icon-button"
                          aria-label={"查看运行 " + r.id}
                          onClick={() => setOpenRun(r.id)}
                        >
                          <ArrowRight size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="尚无此类运行">
            提交真实任务后，状态和记录将在这里出现。
          </Empty>
        )}
      </Card>
      {previewOpen && (
        <Drawer
          title="评测完整输入预览"
          subtitle="未发送 · 服务端展开的公开输入与生效参数"
          onClose={() => setPreviewOpen(false)}
        >
          <JsonView value={preview?.data} />
        </Drawer>
      )}
      {openRun && (
        <RunDetail
          id={openRun}
          act={act}
          onClose={() => setOpenRun(undefined)}
          onWorkflowRun={onWorkflowRun}
        />
      )}
    </>
  );
}
export function RunDetail({
  id,
  act,
  onClose,
  onWorkflowRun,
}: {
  id: string;
  act: Action;
  onClose: () => void;
  onWorkflowRun?: (id: string) => void;
}) {
  const { data, error, loading, lastSyncedAt } = useRunMonitor(id);
  const [tab, setTab] = useState("概览");
  const [recordIndex, setRecordIndex] = useState(0);
  const [recordTab, setRecordTab] = useState("实际请求");
  const records = data?.records || [];
  const record = records[recordIndex];
  if(data&&["rule_refinement","rule_evaluation"].includes(data.kind))return <Drawer title={runLabel(data)} subtitle="持久化规则研究与检查记录" onClose={onClose}><ErrorBox error={error}/><RunConnection lastSyncedAt={lastSyncedAt} error={error}/>{data.kind==="rule_refinement"&&onWorkflowRun&&<button onClick={()=>onWorkflowRun(id)}>在 Harness 中查看</button>}<RuleRefinementRun run={data} act={act}/></Drawer>;

  return (
    <Drawer
      title={runLabel(data)}
      subtitle="持久化运行 · 查看记录不会触发新的模型调用"
      onClose={onClose}
    >
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        data && (
          <>
            <div className="run-detail-head">
              <Status value={runStateLabels[data.status] || data.status} />
              <span>{{workflow:"KB 研究",evaluation:"模型评测",generation:"题目生成",rag:"RAG 作答"}[data.kind] || data.kind}</span>
              <small title="创建时间">{formatTimestamp(data.created_at)}</small>
              <RunControls run={data} act={act} />
              {data.kind === "workflow" && onWorkflowRun && <button className="run-workflow-link" onClick={()=>onWorkflowRun(id)}>在工作流图中查看 <ArrowRight size={14}/></button>}
            </div>
            <RunConnection lastSyncedAt={lastSyncedAt} error={error}/><details><summary>运行标识与来源</summary><p className="mono wrap">{id}</p></details>
            <Tabs
              tabs={["概览", "调用记录", "事件", "冻结配置", "结果与产物"]}
              value={tab}
              onChange={setTab}
            />
            {tab === "概览" ? (
              <>
                {data.kind === "rag" ? <RagRunView run={data}/> : data.kind === "workflow" ? <RunWorkflowView run={data} syncError={error} /> : <Card title="运行进度">
                  <p>{runStateLabels[data.status] || data.status}</p>
                  {runProgress(data).completed !== undefined && <p>已处理 {runProgress(data).completed}{runProgress(data).total ? ` / ${runProgress(data).total}` : ""}</p>}
                  <details><summary>完整进度记录</summary><JsonView value={data.progress} /></details>
                </Card>}
                {data.error && data.kind !== "workflow" && (
                  <Card title="失败 / 不确定记录">
                    <JsonView value={data.error} />
                  </Card>
                )}
                {data.kind !== "rag" && <Card title="结果摘要">
                  <ResultSummary
                    result={data.result}
                    records={records}
                    onRecord={(index) => {
                      setRecordIndex(index);
                      setTab("调用记录");
                      setRecordTab("实际请求");
                    }}
                  />
                </Card>}
                <p className="muted">
                  暂停在当前调用或训练完成后生效。uncertain 调用不会自动重试。
                </p>
              </>
            ) : tab === "调用记录" ? (
              <>
                {records.length ? (
                  <>
                    <Field label={`实际调用 · ${records.length} 条`}>
                      <select
                        value={recordIndex}
                        onChange={(e) => setRecordIndex(Number(e.target.value))}
                      >
                        {records.map((r: any, i: number) => (
                          <option key={r.id || i} value={i}>
                            {i + 1}.{" "}
                            {auditRecord(r).nodeId ? nodeLabel(auditRecord(r).nodeId!) : auditRecord(r).modelId || "调用"}{" "}
                            · {runStateLabels[r.status] || r.status || "已记录"}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Tabs
                      tabs={["实际请求", "原始响应", "完整输入", "解析与评分"]}
                      value={recordTab}
                      onChange={setRecordTab}
                    />
                    <ReceiptContent record={record} tab={recordTab} />
                  </>
                ) : (
                  <Empty title="尚无模型调用收据">
                    等待服务器产生记录，或此任务不包含模型调用。
                  </Empty>
                )}
              </>
            ) : tab === "事件" ? (
              <div className="event-list">
                {data.events?.length ? (
                  data.events.map((event: any, i: number) => (
                    <div className="event" key={event.id || i}>
                      <span className="event-dot" />
                      <div>
                        <b>
                          {event.type || event.event || event.stage || "事件"}
                        </b>
                        <small>
                          {formatTimestamp(
                            event.timestamp ?? event.time ?? event.created_at,
                          )}
                        </small>
                        <JsonView value={event} />
                      </div>
                    </div>
                  ))
                ) : (
                  <Empty title="尚无持久化事件" />
                )}
              </div>
            ) : tab === "冻结配置" ? (
              <JsonView value={data.config} />
            ) : (
              <JsonView value={data.result} />
            )}
          </>
        )
      )}
    </Drawer>
  );
}
