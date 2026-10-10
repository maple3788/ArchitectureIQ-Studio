import { useEffect, useState } from "react";
import { Pause, Play } from "lucide-react";
import { api } from "./api";
import { formatTimestamp } from "./time";
import { useResource } from "./ui";
import type { Action } from "./Questions";
import type { Run } from "./types";

export const runStateLabels: Record<string, string> = {
  queued: "等待启动", starting: "正在启动", running: "运行中", pausing: "等待当前步骤结束后暂停",
  paused: "已暂停", waiting_round: "轮次已封存 · 等待决定", complete: "已完成", completed: "已完成", failed: "运行失败",
  interrupted: "已中断", uncertain: "执行结果待确认", cancelled: "已取消",
};

export function useRunMonitor(id?: string) {
  const resource = useResource<Run>(id ? "/runs/" + encodeURIComponent(id) : null, 0, id ? 2500 : 0);
  const [lastSyncedAt, setLastSyncedAt] = useState<number>();
  useEffect(() => { setLastSyncedAt(undefined); }, [id]);
  useEffect(() => { if (resource.data) setLastSyncedAt(Date.now()); }, [resource.data]);
  return { ...resource, data: resource.data?.id === id ? resource.data : undefined, lastSyncedAt };
}

export function RunConnection({ lastSyncedAt, error }: { lastSyncedAt?: number; error?: string }) {
  return <p className={`run-connection ${error ? "is-offline" : ""}`} role="status">
    <span className="run-connection-dot" />
    {error ? (lastSyncedAt ? "同步中断 · 当前显示上次记录" : "连接失败 · 尚未取得运行记录") : lastSyncedAt ? "连接正常 · 每 2.5 秒更新" : "正在连接服务器"}
    {lastSyncedAt && <small>最近同步 {formatTimestamp(lastSyncedAt)}</small>}
  </p>;
}

export function RunControls({ run, act }: { run: Run; act: Action }) {
  const [pending, setPending] = useState(false);
  const pause = ["running", "queued", "pausing"].includes(run.status);
  const resume = run.status === "paused";
  if (!pause && !resume) return null;
  return <button disabled={pending || run.status === "pausing"} onClick={async () => {
    setPending(true);
    try {
      await act(() => api(`/runs/${encodeURIComponent(run.id)}/${pause ? "pause" : "resume"}`, {}),
        pause ? "已请求在安全边界暂停" : "恢复请求已提交");
    } finally { setPending(false); }
  }}>{pause ? <Pause size={14} /> : <Play size={14} />}
    {pending ? "提交中…" : run.status === "pausing" ? "等待安全暂停" : pause ? "暂停" : "恢复"}
  </button>;
}
