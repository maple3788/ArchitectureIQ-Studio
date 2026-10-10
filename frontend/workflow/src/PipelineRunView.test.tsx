import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PipelineRunView, pipelineStatus } from "./PipelineRunView";
import type { Run } from "./types";
vi.mock("./RunWorkflowView", () => ({
  RunWorkflowView: ({ nodeIds }: any) => (
    <div data-testid="internal-view">{nodeIds?.join(",") ?? "all-nodes"}</div>
  ),
}));
afterEach(cleanup);
const run: Run = {
  id: "run-complete",
  kind: "workflow",
  status: "complete",
  created_at: 1,
  config: {
    workflow: {
      name: "Research",
      settings: {},
      nodes: ["input", "solver", "discoverer", "publish", "evaluate"].map(
        (id) => ({
          id,
          type: id === "solver" ? "agent" : "program",
          position: { x: 0, y: 0 },
          config: {},
        }),
      ),
      edges: [{ source: "input", target: "solver" }],
    },
    question_set: { name: "研究题集", question_count: 1 },
  },
  events: [
    { type: "stage", node_id: "publish", state: "complete", round_index: 1 },
  ],
  node_observations: [
    {
      node_id: "publish",
      round_index: 1,
      availability: "available",
      input: { patch: { operations: [] } },
      output: {
        version: "v1",
        claims: [
          {
            id: "K1",
            text: "A pending claim",
            status: "legacy_unverified",
            enabled: false,
            evidence_ids: [],
          },
        ],
        evidence: [],
      },
    },
  ],
};
it("does not call an unarranged Task complete or an unchanged KB new verified knowledge", () => {
  expect(pipelineStatus(run, "task")).toBe("skipped");
  render(<PipelineRunView run={run} />);
  expect(screen.getAllByText(/本次未安排/).length).toBeGreaterThan(0);

  expect(screen.queryByText("all-nodes")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /查看 KB · 知识积累/ }));
  expect(screen.getByText("0 条已验证且启用")).toBeTruthy();
  expect(screen.getByText("A pending claim")).toBeTruthy();
});
it("opens only the chosen stage and keeps internal graph out of the default view", () => {
  render(<PipelineRunView run={run} />);
  fireEvent.click(screen.getByRole("button", { name: /查看 Harness · 研究策略/ }));
  expect(screen.getByTestId("internal-view").textContent).toContain(
    "discoverer",
  );
  fireEvent.click(
    screen.getByRole("button", { name: /查看 Task · 新题解答与效果验证/ }),
  );
  expect(screen.queryByTestId("internal-view")).toBeNull();
  expect(screen.getByText(/此运行没有执行 Task/)).toBeTruthy();
});

it("does not inherit completed Harness or KB states after the next research round begins", () => {
  const next: Run = {
    ...run,
    status: "running",
    progress: { node_id: "input", round_index: 2, state: "running" },
    events: [
      { type: "stage", node_id: "solver", state: "complete", round_index: 1 },
      {
        type: "stage",
        node_id: "discoverer",
        state: "complete",
        round_index: 1,
      },
      { type: "stage", node_id: "publish", state: "complete", round_index: 1 },
      { type: "stage", node_id: "input", state: "running", round_index: 2 },
    ],
  };
  expect(pipelineStatus(next, "data")).toBe("running");
  expect(pipelineStatus(next, "harness")).toBe("not_run");
  expect(pipelineStatus(next, "kb")).toBe("not_run");
});
it("keeps the last research round completed during final evaluation and never masks a current-round failure", () => {
  const final: Run = {
    ...run,
    status: "running",
    progress: { node_id: "evaluate", round_index: 1000, state: "running" },
    config: {
      ...run.config,
      workflow: {
        ...run.config.workflow,
        edges: [
          ...run.config.workflow.edges,
          { source: "publish", target: "evaluate" },
        ],
      },
    },
    events: [
      ...(run.events ?? []),
      {
        type: "stage",
        node_id: "evaluate",
        state: "running",
        round_index: 1000,
        key: "eval-clean-q1",
      },
    ],
  };
  expect(pipelineStatus(final, "harness")).toBe("complete");
  expect(pipelineStatus(final, "kb")).toBe("complete");
  expect(pipelineStatus(final, "task")).toBe("running");
  const failed = {
    ...final,
    status: "failed",
    progress: { node_id: "discoverer", round_index: 2, state: "running" },
    events: [
      ...(run.events ?? []),
      {
        type: "stage",
        node_id: "discoverer",
        state: "running",
        round_index: 2,
        key: "packet-0",
      },
    ],
  };
  expect(pipelineStatus(failed, "harness")).toBe("failed");
  expect(pipelineStatus(failed, "kb")).toBe("not_run");
});
