import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkflowWorkspace } from "./WorkflowWorkspace";
import { useWorkflowRun } from "./LiveWorkflowCanvas";
function FrozenRun(){const {run}=useWorkflowRun();return run?<div data-testid="run-graph">{run.id} · {run.status} · {run.config.workflow.name}</div>:null;}

vi.mock("./RunWorkflowView", () => ({ RunWorkflowView: ({ run }: any) => <div data-testid="run-graph">{run.id} · {run.status} · {run.config.workflow.name}</div> }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const run = (id: string, status: string) => ({ id, kind: "workflow", status, created_at: 1791529737,
  config: { name: id, workflow: { name: "冻结版本 " + id, nodes: [], edges: [], settings: {} } }, events: [], records: [] });

it("opens the requested frozen run without submitting a job, and retains the editor across modes", async () => {
  const submitted: unknown[] = [];
  const one = run("run-one", "failed"), two = run("run-two", "complete");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") submitted.push(init);
    return new Response(JSON.stringify(url.endsWith("/runs") ? { items: [two, one], total: 2 } : url.endsWith("run-one") ? one : two));
  }));
  render(<WorkflowWorkspace selectedRun="run-one" version={0} act={async op=>op()}>
    <FrozenRun/><input aria-label="编辑中的草稿" defaultValue="未提交的设置" />
  </WorkflowWorkspace>);
  expect((await screen.findByTestId("run-graph")).textContent).toContain("run-one · failed · 冻结版本 run-one");
  expect(await screen.findByText(/连接正常/)).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "编辑工作流" }));
  fireEvent.change(screen.getByLabelText("编辑中的草稿"), { target: { value: "保留这一版" } });
  fireEvent.click(screen.getByRole("tab", { name: "运行追踪" }));
  await screen.findByTestId("run-graph");
  fireEvent.change(screen.getByLabelText("追踪的工作流运行"), { target: { value: "run-two" } });
  await waitFor(()=>expect(screen.getByTestId("run-graph").textContent).toContain("run-two · complete"));
  fireEvent.click(screen.getByRole("tab", { name: "编辑工作流" }));
  expect((screen.getByLabelText("编辑中的草稿") as HTMLInputElement).value).toBe("保留这一版");
  expect(submitted).toEqual([]);
});

it("explains an empty run history without fabricating progress", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }))));
  render(<WorkflowWorkspace version={0} act={async op=>op()}><FrozenRun/><span>草稿</span></WorkflowWorkspace>);
  fireEvent.click(screen.getByRole("tab", { name: "运行追踪" }));
  expect(await screen.findByText("还没有工作流运行")).toBeTruthy();
  expect(screen.queryByTestId("run-graph")).toBeNull();
});

it("keeps the current run pinned when a newly created run appears in the list", async () => {
  const one = run("run-one", "failed"), two = run("run-two", "running");
  let listed = [one];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.endsWith("/runs") ? { items: listed, total: listed.length } : url.endsWith("run-one") ? one : two))));
  const view = render(<WorkflowWorkspace version={0} act={async op=>op()}><FrozenRun/><span>草稿</span></WorkflowWorkspace>);
  fireEvent.click(screen.getByRole("tab", { name: "运行追踪" }));
  expect((await screen.findByTestId("run-graph")).textContent).toContain("run-one");
  listed = [two, one];
  view.rerender(<WorkflowWorkspace version={1} act={async op=>op()}><FrozenRun/><span>草稿</span></WorkflowWorkspace>);
  await screen.findByRole("option", { name: /run-two/ });
  expect((screen.getByLabelText("追踪的工作流运行") as HTMLSelectElement).value).toBe("run-one");
  expect(screen.getByTestId("run-graph").textContent).toContain("run-one");
});
