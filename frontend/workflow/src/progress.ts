import type { Run } from "./types";
export function runProgress(
  run: Pick<Run, "kind" | "status"> & Partial<Pick<Run, "progress" | "result">>,
) {
  const completed = run.progress?.completed ?? run.progress?.current;
  const total = run.progress?.total;
  if (run.kind === "evaluation" && run.status === "complete") {
    if (typeof total === "number" && total > 0)
      return { completed: total, total };
    if (typeof run.result?.calls === "number" && run.result.calls > 0)
      return { completed: run.result.calls, total: run.result.calls };
  }
  return { completed, total };
}
