import { useEffect, useId, useMemo, useState, useRef } from "react";
import { auditRecord } from "./audit";
import {
  deriveRunWorkflow,
  nodeLabel,
  nodeStatusLabel,
  parseOutput,
  parseSentContent,
  runStatusLabel,
  type Invocation,
  type NodeStatus,
} from "./runWorkflow";
import type { Run } from "./types";
import { NodeStory } from "./NodeStory";
import { RunFailure } from "./RunFailure";
import { LiveOutput, useLiveOutput } from "./LiveOutput";
import "./run-workflow.css";
type NodeReadingContext = {
  nodeId: string;
  run: Run;
  questionKey?: string;
  roundIndex?: number;
  ioDirection?: "input" | "output";
};
const nodePurpose: Record<string, string> = {
  input: "选定本轮要回答的题目，交给解题模型。此时不提供标准答案。",
  solver: "阅读题目和已有知识，对候选方案排序，并说明判断理由。",
  commit: "保存模型的原始回答，之后才能揭示标准答案，保证回答不会事后修改。",
  reveal: "用真实训练结果核对模型的回答，找出选对和选错的地方，交给下一步研究。",
  discoverer: "从答题结果和训练反馈中，提出一条可以用实验验证的假说。",
  skeptic: "寻找假说的漏洞和可能的反例，判断是否值得进入实验。",
  experiment: "执行生成的训练代码，用真实实验检验假说。",
  confirmation: "换用独立数据再做实验，确认探索阶段的结论是否仍成立。",
  analyst: "解释实验支持或反驳了什么，并说明结论的适用范围。",
  curator: "根据证据提出知识库的新增、保留或退役建议。建议还需下一步校验。",
  publish: "核对证据和使用条件，将通过检查的知识保存到知识库。",
  loop: "检查还有没有下一轮题目，决定继续研究或结束本次流程。",
  evaluate: "用独立题目检验知识库的效果，不把评测答案用于发现知识。",
  end: "保存本次研究结果和运行记录，结束流程。",
};
function shortKey(key: string, ordinal?: number) {
  return /^packet-\d+$/.test(key) ? `第 ${Number(key.slice(7)) + 1} 组研究材料` : ordinal === undefined ? "本次研究题目" : `题目 ${ordinal}`;
}
function exact(value: any) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
function Exact({ title, value }: { title: string; value: any }) {
  return (
    <details className="rw-fold">
      <summary>{title}</summary>
      <pre>{exact(value) ?? "未提供"}</pre>
    </details>
  );
}
function WireReceipt({ record, ioDirection, ...context }: { record: any } & NodeReadingContext) {
  const audit = auditRecord(record);
  const sent = record.actual_request ?? record.transport?.request;
  const payload = sent?.payload ?? sent?.json;
  const messages = payload?.messages;
  const choices = audit.response?.choices;
  const [localTab, setTab] = useState<"input" | "output">(
    Array.isArray(choices) && choices.length ? "output" : "input",
  );
  const tab = ioDirection ?? localTab;
  const tabId = useId();
  return (
    <div className="rw-io">
      {!ioDirection && <div className="rw-io-tabs" role="tablist" aria-label="节点实际输入输出">
        <button
          type="button"
          role="tab"
          id={`${tabId}-output-tab`}
          aria-controls={`${tabId}-output`}
          aria-selected={tab === "output"}
          onClick={() => setTab("output")}
        >
          输出
        </button>
        <button
          type="button"
          role="tab"
          id={`${tabId}-input-tab`}
          aria-controls={`${tabId}-input`}
          aria-selected={tab === "input"}
          onClick={() => setTab("input")}
        >
          输入
        </button>
      </div>}
      {tab === "input" && (
        <section
          className="rw-card"
          role="tabpanel"
          id={`${tabId}-input`}
          aria-labelledby={`${tabId}-input-tab`}
        >
          <h4>实际发送输入</h4>
          <p className="rw-source">
            模型实际收到的内容
          </p>
          {Array.isArray(messages) ? (
            messages.map((message: any, index: number) => {
              const parsed = parseSentContent(message.content);
              return (
                <div className="rw-message" key={index}>
                  <span className="rw-chip">
                    消息 {index + 1}
                  </span>
                  {parsed.data !== undefined ? (
                    <NodeStory {...context} direction="input" value={parsed.data} />
                  ) : (
                    <>
                      <p className="rw-muted">
                        {parsed.parseError
                          ? "这份输入没有可用的阅读摘要，可在高级详情查看原文。"
                          : "这份消息以文本形式发送，可在高级详情查看原文。"}
                      </p>
                      
                    </>
                  )}
                  <details className="rw-fold"><summary>高级详情：本次实际 Prompt</summary>
                    {parsed.instructions && <Exact title="本次实际角色指令" value={parsed.instructions} />}
                    <Exact title="完整实际消息原文" value={parsed.original} />
                  </details>
                </div>
              );
            })
          ) : (
            <p className="rw-muted">
              未提供实际发送 messages；逻辑请求不能替代发送收据。
            </p>
          )}
          <Exact title="高级详情：完整实际请求 JSON" value={sent} />
        </section>
      )}
      {tab === "output" && (
        <section
          className="rw-card"
          role="tabpanel"
          id={`${tabId}-output`}
          aria-labelledby={`${tabId}-output-tab`}
        >
          <h4>实际模型返回</h4>
          <p className="rw-source">模型实际给出的回答</p>
          {Array.isArray(choices) ? (
            choices.map((choice: any, index: number) => {
              const content = choice.message?.content;
              const output = parseOutput(content);
              return (
                <div className="rw-message" key={index}>
                  {choices.length > 1 && (
                    <span className="rw-chip">
                      返回选项 {choice.index ?? index}
                    </span>
                  )}
                  {output !== undefined ? (
                    <NodeStory {...context} direction="output" value={output} />
                  ) : (
                    <div className="rw-text">
                      {content === undefined
                        ? "服务未提供 content"
                        : exact(content)}
                    </div>
                  )}
                  <p className="rw-muted">
                    {(choice.finish_reason ?? audit.finishReason) === "stop" ? "模型已正常结束回答。" : (choice.finish_reason ?? audit.finishReason) === "length" ? "回答达到长度限制，可能未完整返回。" : "服务结束状态见高级详情。"}
                  </p>
                  {choice.message?.reasoning_content !== undefined && (
                    <Exact
                      title="高级详情：服务返回的推理文本"
                      value={choice.message.reasoning_content}
                    />
                  )}
                  <Exact title="高级详情：完整回答原文" value={content} />
                </div>
              );
            })
          ) : (
            <p className="rw-muted">尚无原始模型响应。</p>
          )}
          {audit.usage && <Exact title="高级详情：实际 token 用量" value={audit.usage} />}
          <Exact title="高级详情：完整原始响应 JSON" value={audit.response} />
        </section>
      )}
    </div>
  );
}
function ObservedIO({
  observation,
  hasWire,
  ...context
}: {
  observation: any;
  hasWire: boolean;
} & NodeReadingContext) {
  if (observation.availability === "unavailable")
    return <Exact title="高级详情：原始产物读取记录" value={observation} />;
  if (hasWire)
    return (
      <details className="rw-fold">
        <summary>查看封存处理结果</summary>
        <ObservedContent observation={observation} {...context} />
      </details>
    );
  return <ObservedContent observation={observation} {...context} />;
}
function ObservedContent({ observation, ioDirection, ...context }: { observation: any } & NodeReadingContext) {
  const [localTab, setTab] = useState<"input" | "output">(
    observation.output !== undefined ? "output" : "input",
  );
  const tab = ioDirection ?? localTab;
  const id = useId();
  return (
    <section className="rw-card">
      <p className="rw-source">
        来自本次运行已保存、已核对的记录 ·{" "}
        {observation.availability === "available" ? "输入输出可用" : "部分可用"}
      </p>
      {!ioDirection && <div className="rw-io-tabs" role="tablist" aria-label="节点封存输入输出">
        <button
          type="button"
          role="tab"
          id={`${id}-output-tab`}
          aria-controls={`${id}-output`}
          aria-selected={tab === "output"}
          onClick={() => setTab("output")}
        >
          输出
        </button>
        <button
          type="button"
          role="tab"
          id={`${id}-input-tab`}
          aria-controls={`${id}-input`}
          aria-selected={tab === "input"}
          onClick={() => setTab("input")}
        >
          输入
        </button>
      </div>}
      {tab === "input" ? (
        <div
          role="tabpanel"
          id={`${id}-input`}
          aria-labelledby={`${id}-input-tab`}
        >
          {observation.input !== undefined ? (
            <NodeStory {...context} direction="input" value={observation.input} />
          ) : (
            <p className="rw-muted">输入产物未提供</p>
          )}
          {observation.input?.prompt && (
            <p className="rw-muted">
              这是程序保存的任务内容；模型实际收到的版本请查看发送记录。
            </p>
          )}
        </div>
      ) : (
        <div
          role="tabpanel"
          id={`${id}-output`}
          aria-labelledby={`${id}-output-tab`}
        >
          {observation.output !== undefined ? (
            <NodeStory {...context} direction="output" value={observation.output?.result ?? observation.output} />
          ) : (
            <p className="rw-muted">输出产物未提供</p>
          )}
        </div>
      )}
      <Exact title="高级详情：完整原始数据与来源" value={observation} />
    </section>
  );
}
function InvocationDetail({
  invocation,
  nodeConfig,
  nodeType,
  ...context
}: {
  invocation?: Invocation;
  nodeConfig: any;
  nodeType: string;
} & NodeReadingContext) {
  const [recordIndex, setRecordIndex] = useState(0);
  const id = useId();
  useEffect(() => setRecordIndex(0), [invocation?.id]);
  if (!invocation)
    return (
      <section className="rw-card">
        <h4>尚无执行记录</h4>
        <p className="rw-muted">这一步在所选轮次尚无可查看的结果。</p>
        <Exact title="高级详情：本次节点配置" value={nodeConfig} />
      </section>
    );
  const records = invocation.records;
  const record = records[Math.min(recordIndex, records.length - 1)];
  return (
    <>
      {invocation.unbound && (
        <p className="rw-notice">
          此传输收据未绑定到确定轮次或题目；没有推测关联。
        </p>
      )}
      {records.length > 1 && (
        <label className="rw-select" htmlFor={id}>
          本次传输收据
          <select
            id={id}
            value={recordIndex}
            onChange={(e) => setRecordIndex(Number(e.target.value))}
          >
            {records.map((r, i) => (
              <option value={i} key={i}>
                收据 {i + 1} · {r.status ?? "已记录"}
              </option>
            ))}
          </select>
        </label>
      )}
      {record ? (
        <WireReceipt record={record} {...context} />
      ) : (
        (!invocation.observation ||
          invocation.observation.availability === "unavailable" ||
          (nodeType === "agent" && invocation.status === "failed")) && (
          <section className="rw-card">
            <h4>
              {nodeType === "agent" && invocation.status === "failed"
                ? "失败前未记录到实际发送收据"
                : "仅有事件记录"}
            </h4>
            <p className="rw-muted">
              没有保存可展示的输入输出，暂时只能确认这一步的执行状态。
            </p>
          </section>
        )
      )}
      {invocation.observation && (
        <ObservedIO observation={invocation.observation} hasWire={!!record} {...context} />
      )}
      <details className="rw-fold"><summary>高级详情：执行事件与节点配置</summary>
        <Exact title="此节点阶段事件" value={invocation.events} />
        <Exact title="冻结节点配置" value={nodeConfig} />
      </details>
    </>
  );
}
function displayStatus(
  invocations: Invocation[],
  fallback: NodeStatus,
): NodeStatus {
  if (!invocations.length)
    return fallback === "skipped" ? "skipped" : "not_run";
  return (
    invocations.find((i) =>
      ["failed", "uncertain", "interrupted"].includes(i.status),
    )?.status ??
    invocations.find((i) =>
      ["running", "pending", "paused", "ready"].includes(i.status),
    )?.status ??
    (invocations.every((i) => i.status === "complete")
      ? "complete"
      : invocations.at(-1)!.status)
  );
}
export function RunWorkflowView({
  run,
  syncError,
  nodeIds,
  compact = false,
  fixedRound,
  stepId,
}: {
  run: Run;
  syncError?: string;
  nodeIds?: readonly string[];
  compact?: boolean;
  fixedRound?: number;
  stepId?: string;
}) {
  const graphRef = useRef<HTMLElement | null>(null);
  const nodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const graph = useMemo(() => {
    const all = deriveRunWorkflow(run);
    if (!nodeIds) return all;
    const nodes=all.nodes.filter(n=>nodeIds.includes(n.id)).map(n=>!stepId?n:{...n,invocations:n.invocations.filter(i=>i.events.some(e=>e.step_id===stepId)).map(i=>({...i,events:i.events.filter(e=>e.step_id===stepId),records:i.records.filter(r=>r.step_id===stepId||r.inputs?.step_id===stepId)}))});
    const rounds=[...new Set(nodes.flatMap(n=>n.invocations.filter(i=>!i.unbound&&i.round!==undefined).map(i=>i.round!)))].sort((a,b)=>a-b);
    return {...all, nodes, rounds,
      currentNodeId:all.currentNodeId&&nodeIds.includes(all.currentNodeId)?all.currentNodeId:undefined};
  }, [run,nodeIds,stepId]);
  const live = useLiveOutput(run);
  const [selected, setSelected] = useState<string | undefined>(
    graph.currentNodeId ?? graph.nodes[0]?.id,
  );
  const [round, setRound] = useState<string>(() =>
    String(graph.rounds.at(-1) ?? "all"),
  );
  const [invocationId, setInvocationId] = useState<string>();
  const [followingCurrent, setFollowingCurrent] = useState(true);
  const [locateVersion, setLocateVersion] = useState(0);
  const currentRound =
    (!nodeIds || nodeIds.includes(run.progress?.node_id ?? "") ? run.progress?.round_index : undefined) ??
    graph.nodes
      .find((n) => n.id === graph.currentNodeId)
      ?.invocations.filter((i) => !i.unbound)
      .at(-1)?.round ??
    graph.rounds.at(-1);
  const roundId = useId(),
    invokeId = useId();
  useEffect(() => {
    setFollowingCurrent(true);
    setSelected(graph.currentNodeId ?? graph.nodes[0]?.id);
    setRound(String(graph.rounds.at(-1) ?? "all"));
    setInvocationId(undefined);
  }, [run.id]);
  useEffect(() => {
    if (!followingCurrent) return;
    setSelected(graph.currentNodeId ?? graph.nodes[0]?.id);
    setRound(String(currentRound ?? "all"));
    setInvocationId(undefined);
  }, [followingCurrent, graph.currentNodeId, currentRound, run.id]);
  useEffect(() => {
    const nav = graphRef.current,
      button = selected ? nodeRefs.current[selected] : undefined;
    if (!nav || !button) return;
    const navBox = nav.getBoundingClientRect(),
      box = button.getBoundingClientRect();
    if (nav.scrollWidth > nav.clientWidth)
      nav.scrollLeft +=
        box.left - navBox.left - nav.clientWidth / 2 + box.width / 2;
    else
      nav.scrollTop +=
        box.top - navBox.top - nav.clientHeight / 2 + box.height / 2;
  }, [selected, run.id, locateVersion]);
  if (!graph.workflow)
    return (
      <div className="rw-notice">
        此任务没有冻结工作流图，无法还原节点执行路径。
      </div>
    );
  const node = graph.nodes.find((n) => n.id === selected) ?? graph.nodes[0];
  const displayedRound = fixedRound === undefined ? round : String(fixedRound);
  const filtered = (invocations: Invocation[]) =>
    displayedRound === "all"
      ? invocations
      : invocations.filter((i) => i.round === Number(displayedRound) || i.unbound);
  const invocations = node ? filtered(node.invocations) : [];
  const invocation =
    invocations.find((i) => i.id === invocationId) ??
    invocations.filter((i) => !i.unbound).at(-1) ??
    invocations.at(-1);
  const currentLabel = [
    "failed",
    "complete",
    "completed",
    "interrupted",
    "uncertain",
    "cancelled",
    "canceled",
  ].includes(run.status)
    ? "最后执行节点"
    : "当前阶段";
  return (
    <div className={`rw-view ${compact ? "rw-compact" : ""}`}>
      {(!compact || fixedRound === undefined) && <header className="rw-header">
        <div>
          <strong>{compact ? "本阶段记录" : "冻结执行图"}</strong>
          <span className="rw-muted">
            {compact ? "选择步骤查看输入与输出" : `${graph.workflow.name} · ${runStatusLabel(run.status)}`}
          </span>
        </div>
        <div className="rw-header-actions">
          {graph.currentNodeId && (
            <button
              type="button"
              className="rw-locate"
              onClick={() => {
                setFollowingCurrent(true);
                setLocateVersion((v) => v + 1);
                setSelected(graph.currentNodeId);
                const currentRound =
                  (!nodeIds || nodeIds.includes(run.progress?.node_id ?? "") ? run.progress?.round_index : undefined) ??
                  graph.nodes
                    .find((n) => n.id === graph.currentNodeId)
                    ?.invocations.filter((i) => !i.unbound)
                    .at(-1)?.round;
                if (currentRound !== undefined) setRound(String(currentRound));
                setInvocationId(undefined);
              }}
            >
              定位{currentLabel}
            </button>
          )}
          <label className="rw-select" htmlFor={roundId}>
            查看轮次
            <select
              id={roundId}
              value={displayedRound}
              disabled={fixedRound !== undefined}
              onChange={(e) => {
                setFollowingCurrent(false);
                setRound(e.target.value);
                setInvocationId(undefined);
              }}
            >
              <option value="all">全部轮次</option>
              {graph.rounds.map((r) => (
                <option key={r} value={r}>
                  {r === 1000 ? "最终独立评测" : `第 ${r} 轮`}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>}
      {syncError && (
        <p className="rw-notice" role="status">
          同步失败，以下保留最近记录：{syncError}
        </p>
      )}
      {!compact && <RunFailure run={run} nodeId={graph.currentNodeId} />}
      {compact && graph.nodes.length>1 && <label className="rw-select">查看 Harness 步骤
        <select aria-label="查看 Harness 步骤" value={node?.id ?? ""} onChange={e=>{setFollowingCurrent(false);setSelected(e.target.value);setInvocationId(undefined);}}>
          {graph.nodes.map(n=><option key={n.id} value={n.id}>{nodeLabel(n)} · {nodeStatusLabel[n.status]}</option>)}
        </select>
      </label>}
      <div className="rw-workspace">
        {!compact && <nav
          ref={graphRef}
          className="rw-graph"
          aria-label="冻结工作流节点与路由"
        >
          {graph.nodes.map((n) => {
            const count = filtered(n.invocations);
            const status =
              round === "all" ? n.status : displayStatus(count, n.status);
            const outgoing = graph.workflow!.edges.filter(
              (e) => e.source === n.id,
            );
            return (
              <div className="rw-stage" key={n.id}>
                <button
                  type="button"
                  ref={(button) => {
                    nodeRefs.current[n.id] = button;
                  }}
                  className={`rw-node rw-${status} ${node?.id === n.id ? "is-selected" : ""}`}
                  aria-pressed={node?.id === n.id}
                  aria-label={`${nodeLabel(n)} · ${nodeStatusLabel[status]}`}
                  onClick={() => {
                    setFollowingCurrent(false);
                    setSelected(n.id);
                    setInvocationId(undefined);
                  }}
                >
                  <span className="rw-dot" />
                  <span>
                    <strong>{nodeLabel(n)}</strong>
                    <small>
                      {nodeStatusLabel[status]}
                      {count.length > 1 ? ` · ${count.length} 次` : ""}
                    </small>
                    {graph.currentNodeId === n.id && <em>{currentLabel}</em>}
                  </span>
                </button>
                {outgoing.length > 0 && (
                  <div className="rw-routes">
                    {outgoing.map((edge) => (
                      <div key={edge.id}>
                        ↓{" "}
                        {nodeLabel(
                          graph.nodes.find((t) => t.id === edge.target) ??
                            edge.target,
                        )}
                        {edge.condition === "continue"
                          ? " · 继续下一轮"
                          : edge.condition === "done"
                            ? " · 轮次结束"
                            : ""}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>}
        <section className="rw-detail" aria-label="节点真实输入输出">
          {node && (
            <>
              <div className="rw-detail-title">
                <h3>{nodeLabel(node)}</h3>
                <span
                  className={`rw-status rw-${round === "all" ? node.status : displayStatus(invocations, node.status)}`}
                >
                  {
                    nodeStatusLabel[
                      round === "all"
                        ? node.status
                        : displayStatus(invocations, node.status)
                    ]
                  }
                </span>
              </div>
              <p className="rw-node-purpose">{nodePurpose[node.id] ?? "查看此步骤保存的输入和输出，了解它传递给下一步的信息。"}</p>
              {invocations.length > 1 && (
                <label className="rw-select" htmlFor={invokeId}>
                  节点执行记录
                  <select
                    id={invokeId}
                    value={invocation?.id ?? ""}
                    onChange={(e) => {
                      setFollowingCurrent(false);
                      setInvocationId(e.target.value);
                    }}
                  >
                    {invocations.map((i, index) => (
                      <option value={i.id} key={i.id}>
                        {i.unbound
                          ? "未绑定轮次"
                          : i.round === 1000
                            ? "最终评测"
                            : i.round === undefined
                              ? "轮次未提供"
                              : `第 ${i.round} 轮`}{" "}
                        · {i.key ? shortKey(i.key, index + 1) : `记录 ${index + 1}`} ·{" "}
                        {nodeStatusLabel[i.status]}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {invocation?.key && (
                <p className="rw-key" title={invocation.key}>题目 / 研究包：{shortKey(invocation.key)}</p>
              )}
              {!invocations.length &&
                round !== "all" &&
                node.invocations.length > 0 && (
                  <p className="rw-notice">该轮暂无此节点执行记录</p>
                )}
              {(node.type==="agent"||node.id==="evaluate") && invocation && invocation.status!=="complete" && <LiveOutput live={live} nodeId={node.id} round={invocation.round} operationKey={invocation.key}
                terminal={["failed","interrupted","uncertain","complete","completed","cancelled"].includes(run.status)} />}
              <InvocationDetail
                key={`${run.id}:${node.id}:${invocation?.id ?? "none"}`}
                invocation={invocation}
                nodeId={node.id}
                run={run}
                questionKey={invocation?.key}
                roundIndex={invocation?.round}
                nodeConfig={node.config}
                nodeType={node.type}
              />
            </>
          )}
        </section>
      </div>
    </div>
  );
}

/** Read a single observed node invocation; never substitute another round or stage. */
export function RunNodeIO({run,nodeId,stepId,round,direction}:{run:Run;nodeId:string;stepId:string;round:number;direction:"input"|"output"}) {
  const live=useLiveOutput(run);
  const node=deriveRunWorkflow(run).nodes.find(n=>n.id===nodeId);
  const invocations=node?.invocations.filter(i=>!i.unbound&&i.round===round&&i.stepId===stepId)??[];
  const [selected,setSelected]=useState<string>();
  const invocation=invocations.find(i=>i.id===selected)??invocations.at(-1);
  const context={run,nodeId,roundIndex:round,questionKey:invocation?.key,ioDirection:direction};
  if(!invocation)return <p className="rw-muted">此节点在第 {round} 轮尚无实际{direction==='input'?'输入':'输出'}记录。</p>;
  const record=invocation.records.at(-1);
  return <div className="basic-node-io">
    {invocations.length>1&&<label>执行记录<select value={invocation.id} onChange={e=>setSelected(e.target.value)}>{invocations.map((i,index)=><option key={i.id} value={i.id}>记录 {index+1} · {nodeStatusLabel[i.status]}</option>)}</select></label>}
    {direction==='output'&&node?.type==='agent'&&invocation.status!=='complete'&&<LiveOutput live={live} nodeId={nodeId} round={round} operationKey={invocation.key} terminal={['failed','interrupted','uncertain','cancelled','complete'].includes(run.status)}/>}
    {record&&<WireReceipt record={record} {...context}/>}
    {invocation.observation&&<ObservedIO observation={invocation.observation} hasWire={!!record} {...context}/>}
    {!record&&!invocation.observation&&<p className="rw-muted">节点已进入{nodeStatusLabel[invocation.status]}状态，等待可读取的持久化记录。</p>}
  </div>;
}
