import { auditRecord } from "./audit";
import type { Run, Workflow, WorkflowNode } from "./types";
import { migrateWorkflowLayout } from "./workflowLayout";
export type NodeStatus =
  | "ready"
  | "running"
  | "complete"
  | "failed"
  | "paused"
  | "interrupted"
  | "unknown"
  | "not_run"
  | "skipped"
  | "pending"
  | "uncertain";
export type Invocation = {
  id: string;
  stepId?: string;
  round?: number;
  key?: string;
  status: NodeStatus;
  events: any[];
  records: any[];
  observation?: any;
  unbound?: boolean;
  start?: number;
  end?: number;
};
export type RunNode = WorkflowNode & {
  status: NodeStatus;
  invocations: Invocation[];
};
export const nodeStatusLabel: Record<NodeStatus, string> = {
  ready: "等待执行",
  running: "执行中",
  complete: "已完成",
  failed: "失败",
  paused: "已暂停",
  interrupted: "已中断",
  unknown: "未确认完成",
  not_run: "未执行",
  skipped: "路由跳过",
  pending: "等待响应",
  uncertain: "结果不确定",
};
const labels: Record<string, string> = {
  input: "题目选择",
  experience_curator: "提炼经验",
  experience_save: "保存经验版本",
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
export function nodeLabel(node: WorkflowNode | string) {
  return typeof node === "string"
    ? (labels[node] ?? node)
    : (labels[node.id] ?? node.label ?? node.id);
}
export function runStatusLabel(status: string) {
  return (
    (
      {
        queued: "排队中",
        running: "执行中",
        waiting_round: "轮次已封存 · 等待决定",
        pausing: "等待安全暂停",
        paused: "已暂停",
        complete: "已完成",
        completed: "已完成",
        failed: "失败",
        cancelled: "已取消",
        canceled: "已取消",
        interrupted: "已中断",
        uncertain: "结果不确定",
      } as Record<string, string>
    )[status] ?? status
  );
}
function timestamp(value: any): number | undefined {
  if (typeof value === "number" && Number.isFinite(value))
    return value > 1e11 ? value / 1000 : value;
  if (typeof value === "string") {
    const n = Date.parse(value);
    if (Number.isFinite(n)) return n / 1000;
  }
  return undefined;
}
function eventTime(e: any) {
  return timestamp(e.time ?? e.timestamp ?? e.created_at);
}
function roundOf(e: any): number | undefined {
  const value = e.round_index ?? e.inputs?.round_index;
  return typeof value === "number" ? value : undefined;
}
function keyOf(e: any): string | undefined {
  return e.question_key ?? e.inputs?.question_key ?? e.key;
}
function statusOf(status: any): NodeStatus {
  return (
    Object.keys(nodeStatusLabel).includes(status)
      ? status
      : status === "completed"
        ? "complete"
        : status === "starting"
          ? "ready"
          : "unknown"
  ) as NodeStatus;
}
function terminalStatus(status: string): NodeStatus | undefined {
  if (status === "failed") return "failed";
  if (status === "uncertain") return "uncertain";
  if (["cancelled", "canceled", "interrupted"].includes(status))
    return "interrupted";
  if (["complete", "completed"].includes(status)) return "unknown";
  if (status === "paused") return "paused";
  return undefined;
}
export function deriveRunWorkflow(run: Run): {
  workflow?: Workflow;
  nodes: RunNode[];
  rounds: number[];
  currentNodeId?: string;
} {
  const original = run.config?.workflow;
  if (
    !original ||
    !Array.isArray(original.nodes) ||
    !Array.isArray(original.edges)
  )
    return { nodes: [], rounds: [] };
  const workflow = migrateWorkflowLayout(original);
  const stageEvents = (run.events ?? []).filter(
    (e) =>
      e.type === "stage" &&
      e.node_id &&
      !(
        e.candidate_id &&
        e.key === undefined &&
        ["experiment", "confirmation"].includes(e.node_id)
      ),
  );
  if (
    run.progress?.node_id &&
    run.progress.state &&
    !stageEvents.some(
      (e) =>
        e.node_id === run.progress!.node_id &&
        roundOf(e) === roundOf(run.progress),
    )
  )
    stageEvents.push({ type: "stage", ...run.progress, source: "progress" });
  const observations = Array.isArray(run.node_observations)
    ? run.node_observations
    : [];
  const nodes: RunNode[] = workflow.nodes
    .map((node) => {
      const invocations: Invocation[] = [];
      for (const event of stageEvents.filter((e) => e.node_id === node.id)) {
        if (!event.state) continue;
        const round = roundOf(event),
          key = keyOf(event);
        let inv = invocations.find((i) => i.round === round && i.key === key && i.stepId === event.step_id);
        if (!inv) {
          inv = {
            id: `${node.id}:${round ?? "?"}:${key ?? ""}${event.step_id ? ":"+event.step_id : ""}`,
            stepId: event.step_id,
            round,
            key,
            status: "unknown",
            events: [],
            records: [],
          };
          invocations.push(inv);
        }
        inv.events.push(event);
        inv.status = statusOf(event.state);
        const time = eventTime(event);
        if (time !== undefined) {
          inv.start ??= time;
          if (event.state === "complete" || event.state === "failed")
            inv.end = time;
        }
      }
      for (const obs of observations.filter(
        (o: any) => o.node_id === node.id,
      )) {
        const round = roundOf(obs),
          key = keyOf(obs);
        if (round === 0 && obs.availability === "unavailable") continue;
        let matches = invocations.filter(
          (i) => i.round === round && (key === undefined || i.key === key) && (obs.step_id === undefined || i.stepId === obs.step_id),
        );
        let inv = matches.length === 1 ? matches[0] : undefined;
        if (!inv) {
          inv = {
            id: `${node.id}:observation:${invocations.length}`,
            stepId: obs.step_id,
            round,
            key,
            status: "unknown",
            events: [],
            records: [],
          };
          invocations.push(inv);
        }
        inv.observation = obs;
      }
      for (const record of (run.records ?? []).filter(
        (r) => auditRecord(r).nodeId === node.id,
      )) {
        const round = roundOf(record),
          key = record.inputs?.question_key ?? record.question_key;
        const time = timestamp(record.sent_at ?? record.created_at);
        const inInterval = (i: Invocation) =>
          time !== undefined &&
          i.start !== undefined &&
          time >= i.start &&
          (i.end !== undefined
            ? time <= i.end
            : !invocations.some(
                (next) =>
                  next.start !== undefined &&
                  next.start > i.start! &&
                  next.start <= time,
              ));
        let matches = invocations.filter(
          (i) =>
            !i.unbound &&
            (!(record.step_id ?? record.inputs?.step_id) || i.stepId === (record.step_id ?? record.inputs?.step_id)) &&
            (round !== undefined
              ? i.round === round && (key === undefined || i.key === key)
              : inInterval(i)),
        );
        if (matches.length > 1 && time !== undefined)
          matches = matches.filter(inInterval);
        if (!matches.length && time === undefined && round === undefined) {
          const messages =
            record.actual_request?.payload?.messages ??
            record.transport?.request?.payload?.messages;
          if (
            Array.isArray(messages) &&
            messages.length === 1 &&
            typeof messages[0]?.content === "string"
          )
            matches = invocations.filter(
              (i) =>
                !i.unbound &&
                i.observation?.input?.prompt === messages[0].content,
            );
        }
        let inv = matches.length === 1 ? matches[0] : undefined;
        if (!inv) {
          inv = {
            id: `${node.id}:wire:${invocations.length}`,
            round,
            key,
            status:
              record.status === "complete"
                ? "unknown"
                : statusOf(record.status),
            events: [],
            records: [],
            unbound: true,
          };
          invocations.push(inv);
        }
        inv.records.push(record);
      }
      const terminal = terminalStatus(run.status);
      if (terminal)
        for (const inv of invocations)
          if (["running", "ready", "pending"].includes(inv.status))
            inv.status = terminal;
      const connected = workflow.edges.some(
        (e) => e.source === node.id || e.target === node.id,
      );
      let status: NodeStatus = connected ? "not_run" : "skipped";
      if (invocations.length) {
        // Unbound transport receipts do not override a newer known stage's status.
        const known = invocations.filter((i) => !i.unbound);
        const relevant = known.length ? known : invocations;
        status =
          relevant.find((i) =>
            ["failed", "uncertain", "interrupted"].includes(i.status),
          )?.status ??
          relevant.find((i) =>
            ["running", "pending", "paused", "ready"].includes(i.status),
          )?.status ??
          (relevant.every((i) => i.status === "complete")
            ? "complete"
            : relevant[relevant.length - 1].status);
      }
      return { ...node, status, invocations };
    })
    .sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x);
  const rounds = [
    ...new Set(
      nodes.flatMap((n) =>
        n.invocations.flatMap((i) => (i.round !== undefined ? [i.round] : [])),
      ),
    ),
  ].sort((a, b) => a - b);
  const latest = stageEvents.filter((e) => e.state).at(-1);
  return {
    workflow,
    nodes,
    rounds,
    currentNodeId: run.progress?.node_id ?? latest?.node_id,
  };
}
export function parseSentContent(content: any): {
  original: any;
  instructions?: string;
  data?: any;
  parseError?: boolean;
} {
  if (typeof content !== "string") return { original: content };
  const marker = /\n(?:\n)?DATA:\n/.exec(content);
  if (!marker) return { original: content, instructions: content };
  try {
    return {
      original: content,
      instructions: content.slice(0, marker.index),
      data: JSON.parse(content.slice(marker.index + marker[0].length)),
    };
  } catch {
    return { original: content, parseError: true };
  }
}
export function parseOutput(content: any): any | undefined {
  if (typeof content !== "string") return undefined;
  try {
    return JSON.parse(
      content
        .trim()
        .replace(/^```(?:json)?\s*/i, "")
        .replace(/\s*```$/, ""),
    );
  } catch {
    return undefined;
  }
}
