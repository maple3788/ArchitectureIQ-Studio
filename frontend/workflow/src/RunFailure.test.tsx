import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { RunFailure } from "./RunFailure";
import type { Run } from "./types";

afterEach(cleanup);
const run: Run = {
  id: "too-long", kind: "workflow", status: "failed", created_at: 1,
  error: "Role payload exceeds conservative context budget; use smaller packets",
  progress: { node_id: "discoverer", round_index: 1 },
  config: { workflow: { settings: { context_size: 32768, packet_size: 1 } }, models: [{ parameters: { max_tokens: 8192 } }] },
};

it("explains a pre-send length failure without calling the estimate actual token usage", () => {
  render(<RunFailure run={run} nodeId="discoverer" />);
  expect(screen.getByRole("heading", { name: "研究材料太长，Discoverer 尚未开始" })).toBeTruthy();
  expect(screen.getByText(/模型还没有收到这次请求/)).toBeTruthy();
  expect(screen.getByText(/题面、模型回答和真实训练反馈/)).toBeTruthy();
  expect(screen.queryByText(/减小批次|减少题目/)).toBeNull();
  const detail = screen.getByText("技术详情：本次长度限制与原始错误").closest("details");
  expect(detail?.open).toBe(false);
  expect(detail?.textContent).toContain("不是实际 token 用量");
  expect(detail?.textContent).toContain("32,768");
});

it("does not claim completed work without same-round stage evidence", () => {
  const { rerender } = render(<RunFailure run={run} nodeId="discoverer" />);
  expect(screen.queryByText(/本轮已完成/)).toBeNull();
  const stages = ["solver", "commit", "reveal"].map(node_id => ({ type: "stage", node_id, state: "complete", round_index: 1 }));
  rerender(<RunFailure run={{ ...run, events: stages }} nodeId="discoverer" />);
  expect(screen.getByText(/本轮已完成：解题、保存答案、对照标准答案/)).toBeTruthy();
  rerender(<RunFailure run={{ ...run, events: stages.map(e=>({...e, round_index:2})) }} nodeId="discoverer" />);
  expect(screen.queryByText(/本轮已完成/)).toBeNull();
});

it("keeps unknown error text in technical detail without inventing its cause", () => {
  render(<RunFailure run={{...run,error:"unexpected <script>error</script>"}} nodeId="solver" />);
  expect(screen.queryByText(/材料太长/)).toBeNull();
  expect(screen.getByText("原始失败原因").closest("details")?.textContent).toContain("unexpected <script>error</script>");
  expect(document.querySelector("script")).toBeNull();
});
