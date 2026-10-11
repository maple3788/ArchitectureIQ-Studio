import {RuleRefinementRun} from './RuleRefinementRun';
import { useEffect, useState, type ReactNode } from "react";
import { items } from "./api";
import { ErrorBox, Loading, Empty, Tabs, useResource } from "./ui";
import { LiveRunContext } from "./LiveWorkflowCanvas";
import { RunConnection, RunControls, runStateLabels, useRunMonitor } from "./RunMonitor";
import { runLabel } from "./displayNames";
import type { Action } from "./Questions";
import type { List, Run } from "./types";
import "./workflow-workspace.css";

export function WorkflowWorkspace({ children, version, selectedRun, act }: {
  children: ReactNode; version: number; selectedRun?: string; act: Action;
}) {
  const [mode, setMode] = useState(selectedRun ? "运行追踪" : "编辑工作流");
  const [runId, setRunId] = useState(selectedRun || "");
  const runs = useResource<List<Run>>("/runs", version, 5000);
  const workflowRuns = items(runs.data).filter(run => ["workflow","rule_refinement"].includes(run.kind));
  const effectiveId = runId || workflowRuns[0]?.id;
  const monitor = useRunMonitor(mode === "运行追踪" ? effectiveId : undefined);
  useEffect(() => {
    if (!runId && workflowRuns[0]?.id) setRunId(workflowRuns[0].id);
  }, [runId, workflowRuns[0]?.id]);
  useEffect(() => {
    if (selectedRun) { setRunId(selectedRun); setMode("运行追踪"); }
  }, [selectedRun]);
  return <div className="workflow-workspace">
    <div className="workflow-workspace-switch">
      <Tabs tabs={["编辑工作流", "运行追踪"]} value={mode} onChange={setMode} />
      <span>{mode === "运行追踪" ? "查看实际执行与节点输入输出" : "配置下一次研究"}</span>
    </div>

    {mode === "运行追踪" && <section className="workflow-monitor" aria-label="工作流运行追踪">
      <div className="workflow-monitor-toolbar">
        <label>选择运行
          <select aria-label="追踪的工作流运行" value={effectiveId || ""} onChange={e => setRunId(e.target.value)}>
            {!effectiveId && <option value="">暂无工作流运行</option>}
            {effectiveId && !workflowRuns.some(run=>run.id===effectiveId) && <option value={effectiveId}>正在读取所选运行…</option>}
            {workflowRuns.map(run=><option key={run.id} value={run.id}>
              {runLabel(run)} · {runStateLabels[run.status] || run.status}
            </option>)}
          </select>
        </label>
        {monitor.data && <RunControls run={monitor.data} act={act} />}
      </div>
      <p className="workflow-monitor-note">从研究题目到知识，再到独立新题上的效果；点击阶段查看实际记录。</p>
      <ErrorBox error={runs.error || monitor.error} />
      {effectiveId ? <>
        <RunConnection lastSyncedAt={monitor.lastSyncedAt} error={monitor.error} />
        {monitor.loading && <Loading />}
      </> : runs.loading ? <Loading /> : <Empty title="还没有工作流运行">提交研究后，可在这里跟踪每个节点；查看历史记录不会启动新的调用。</Empty>}
    </section>}
    <LiveRunContext.Provider value={{run:mode === "运行追踪" ? monitor.data : undefined, syncState:{error:monitor.error,lastSyncedAt:monitor.lastSyncedAt},act}}>{mode === "运行追踪" && monitor.data?.kind === "rule_refinement" ? <RuleRefinementRun run={monitor.data} act={act}/> : children}</LiveRunContext.Provider>
  </div>;
}
