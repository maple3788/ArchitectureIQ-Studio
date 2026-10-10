import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RunWorkflowView } from "./RunWorkflowView";
import type { Run } from "./types";
afterEach(cleanup);
const run: Run = {
  id: "test",
  kind: "workflow",
  status: "failed",
  created_at: 1,
  error: "Role payload exceeds conservative context budget",
  progress: { node_id: "discoverer", state: "running", round_index: 1 },
  config: {
    workflow: {
      schema_version: 1,
      name: "Frozen",
      settings: {},
      nodes: ["solver", "discoverer", "publish"].map((id, i) => ({
        id,
        type: id === "publish" ? "publish" : "agent",
        position: { x: 0, y: 100 * i },
        config: { role: id, prompt: "配置指导" },
      })),
      edges: [
        { id: "a", source: "solver", target: "discoverer" },
        { id: "b", source: "discoverer", target: "publish" },
      ],
    },
  },
  events: [
    {
      type: "stage",
      node_id: "solver",
      state: "running",
      key: "q1",
      round_index: 1,
      time: 2,
    },
    {
      type: "stage",
      node_id: "solver",
      state: "complete",
      key: "q1",
      round_index: 1,
      time: 4,
    },
    {
      type: "stage",
      node_id: "discoverer",
      state: "running",
      key: "packet-0",
      round_index: 1,
      time: 5,
    },
  ],
  records: [
    {
      inputs: { node_id: "solver" },
      sent_at: 3,
      status: "complete",
      actual_request: {
        payload: {
          messages: [
            {
              role: "user",
              content:
                'Real instruction\n\nDATA:\n{"question":{"id":"q1","prompt":"Public prompt <script>literal</script>"},"knowledge":[]}',
            },
          ],
        },
      },
      request: { prompt: "NOT ACTUALLY SENT" },
      raw: {
        choices: [
          {
            finish_reason: "stop",
            message: {
              content:
                '{"ranking":["B","A"],"rationale":"模型解释","citations":[]}',
              reasoning_content: "provider extra",
            },
          },
        ],
      },
    },
  ],
};
it("shows terminal failure and absence of IO, then readable actual solver input/output", () => {
  const { container } = render(<RunWorkflowView run={run} />);
  expect(screen.getByText("失败前未记录到实际发送收据")).toBeTruthy();
  expect(screen.queryByText("执行中")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /解题 Solver · 已完成/ }));
  expect(screen.getByText("模型解释")).toBeTruthy();
  expect(screen.getByText("B")).toBeTruthy();
  expect(screen.getByText("A")).toBeTruthy();
  expect(
    screen.queryByText("Public prompt <script>literal</script>"),
  ).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "输入" }));
  expect(screen.queryByText("Public prompt <script>literal</script>")).toBeNull();
  fireEvent.click(screen.getByText("查看题目详情"));
  fireEvent.click(screen.getByRole("tab", { name: "原始 Prompt" }));
  expect(
    screen.getByText("Public prompt <script>literal</script>"),
  ).toBeTruthy();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.queryByText("NOT ACTUALLY SENT")).toBeNull();
  expect(screen.getByText("高级详情：完整实际请求 JSON").closest("details")?.open).toBe(
    false,
  );
});
it("shows unstarted configuration honestly and stale sync warning without losing receipts", () => {
  render(<RunWorkflowView run={run} syncError="connection lost" />);
  expect(screen.getByText(/connection lost/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "证据验证 / 发布 · 未执行" }),
  );
  expect(screen.getByText("尚无执行记录")).toBeTruthy();
  const configuration = screen.getByText("高级详情：本次节点配置").closest("details");
  expect(configuration?.open).toBe(false);
  expect(configuration?.textContent).toContain("配置指导");
  expect(screen.queryByRole("heading", { name: "实际发送输入" })).toBeNull();
});
it("renders verified program outputs with missing input explicit, and changes round without mixing questions", () => {
  const next = {
    ...run,
    status: "complete",
    error: undefined,
    progress: { node_id: "publish", round_index: 2 },
    events: [
      ...run.events!,
      {
        type: "stage",
        node_id: "publish",
        state: "complete",
        round_index: 2,
        time: 9,
      },
    ],
    node_observations: [
      {
        node_id: "publish",
        round_index: 2,
        availability: "partial",
        source: ["rounds/round_0002/publish.json"],
        output: { claims: [] },
      },
    ],
  };
  render(<RunWorkflowView run={next} />);
  expect(screen.getByText("0 条知识")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "输入" }));
  expect(screen.getByText("输入产物未提供")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("查看轮次"), {
    target: { value: "1" },
  });
  expect(screen.getByText("该轮暂无此节点执行记录")).toBeTruthy();
});

it("failed agent remains explicitly without a wire receipt when backend returns unavailable observation", () => {
  render(
    <RunWorkflowView
      run={{
        ...run,
        node_observations: [
          {
            node_id: "discoverer",
            round_index: 1,
            key: "packet-0",
            availability: "unavailable",
            source: [],
            reason: "No completed stage is attested",
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("失败前未记录到实际发送收据")).toBeTruthy();
  expect(screen.queryByText("执行中")).toBeNull();
  expect(screen.queryByText("输入产物未提供")).toBeNull();
  expect(screen.getByText("高级详情：原始产物读取记录").closest("details")?.open).toBe(
    false,
  );
});

it("lets the user return to the actual last stage after inspecting another node", () => {
  render(<RunWorkflowView run={run} />);
  fireEvent.click(screen.getByRole("button", { name: "解题 Solver · 已完成" }));
  fireEvent.click(screen.getByRole("button", { name: "定位最后执行节点" }));
  expect(screen.getByText("失败前未记录到实际发送收据")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "提出假说 Discoverer · 失败" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("keeps the historical round during polling, and locate selects the current round", () => {
  const first = { ...run, status: "running", error: undefined };
  const { rerender } = render(<RunWorkflowView run={first} />);
  fireEvent.change(screen.getByLabelText("查看轮次"), {
    target: { value: "1" },
  });
  const second = {
    ...first,
    progress: { node_id: "solver", round_index: 2, state: "running" },
    events: [
      ...first.events!,
      {
        type: "stage",
        node_id: "solver",
        round_index: 2,
        state: "running",
        key: "q2",
        time: 8,
      },
    ],
  };
  rerender(<RunWorkflowView run={second} />);
  expect((screen.getByLabelText("查看轮次") as HTMLSelectElement).value).toBe(
    "1",
  );
  fireEvent.click(screen.getByRole("button", { name: "定位当前阶段" }));
  expect((screen.getByLabelText("查看轮次") as HTMLSelectElement).value).toBe(
    "2",
  );
  expect(screen.getByTitle("q2")).toBeTruthy();
  rerender(
    <RunWorkflowView
      run={{
        ...second,
        progress: { node_id: "solver", round_index: 3, state: "running" },
        events: [
          ...second.events,
          {
            type: "stage",
            node_id: "solver",
            round_index: 3,
            state: "running",
            key: "q3",
            time: 9,
          },
        ],
      }}
    />,
  );
  expect((screen.getByLabelText("查看轮次") as HTMLSelectElement).value).toBe(
    "3",
  );
  expect(screen.getByTitle("q3")).toBeTruthy();
});

it("follows the current node and round by default as live polling advances", () => {
  const first = { ...run, status: "running", error: undefined };
  const { rerender } = render(<RunWorkflowView run={first} />);
  const second = {
    ...first,
    progress: { node_id: "solver", round_index: 2, state: "running" },
    events: [
      ...first.events!,
      {
        type: "stage",
        node_id: "solver",
        round_index: 2,
        state: "running",
        key: "q2",
        time: 8,
      },
    ],
  };
  rerender(<RunWorkflowView run={second} />);
  expect((screen.getByLabelText("查看轮次") as HTMLSelectElement).value).toBe(
    "2",
  );
  expect(
    screen
      .getByRole("button", { name: "解题 Solver · 执行中" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(screen.getByTitle("q2")).toBeTruthy();
});

it("preserves a manually clicked node when live polling advances to another node", () => {
  const first = { ...run, status: "running", error: undefined };
  const { rerender } = render(<RunWorkflowView run={first} />);
  fireEvent.click(screen.getByRole("button", { name: "解题 Solver · 已完成" }));
  const second = {
    ...first,
    progress: { node_id: "publish", round_index: 1, state: "running" },
    events: [
      ...first.events!,
      {
        type: "stage",
        node_id: "publish",
        round_index: 1,
        state: "running",
        time: 9,
      },
    ],
  };
  rerender(<RunWorkflowView run={second} />);
  expect(
    screen
      .getByRole("button", { name: "解题 Solver · 已完成" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(screen.getByText("模型解释")).toBeTruthy();
});

it("keeps a verified role result folded when an authoritative wire output already exists", () => {
  render(
    <RunWorkflowView
      run={{
        ...run,
        node_observations: [
          {
            node_id: "solver",
            round_index: 1,
            key: "q1",
            availability: "available",
            source: ["calls/solver.json"],
            input: { prompt: "logical prompt" },
            output: { result: { ranking: ["B", "A"], rationale: "封存解释" } },
          },
        ],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "解题 Solver · 已完成" }));
  const fold = screen.getByText("查看封存处理结果").closest("details");
  expect(fold?.open).toBe(false);
  expect(screen.getByText("模型解释")).toBeTruthy();
  expect(fold?.textContent).toContain("封存解释");
});

it("shows a sealed answer output first with Chinese checks and no repeated raw rationale", () => {
  const input = { ranking: ["B", "A"], rationale: "答题解释", citations: [] };
  const output = {
    ...input,
    valid: true,
    knowledge_count: 0,
    invalid_citations: false,
    raw: input,
  };
  const workflow = {
    ...run.config.workflow,
    nodes: [
      ...run.config.workflow.nodes,
      {
        id: "commit",
        type: "answer_commit",
        position: { x: 0, y: 50 },
        config: {},
      },
    ],
    edges: [
      ...run.config.workflow.edges,
      { id: "commit-edge", source: "solver", target: "commit" },
    ],
  };
  render(
    <RunWorkflowView
      run={{
        ...run,
        status: "complete",
        error: undefined,
        config: { workflow },
        progress: { node_id: "commit", round_index: 1 },
        events: [
          ...run.events!,
          {
            type: "stage",
            node_id: "commit",
            state: "complete",
            key: "q1",
            round_index: 1,
            time: 5,
          },
        ],
        node_observations: [
          {
            node_id: "commit",
            round_index: 1,
            key: "q1",
            availability: "available",
            input,
            output,
            source: ["answers/q1.json"],
          },
        ],
      }}
    />,
  );
  expect(
    screen.getByRole("tab", { name: "输出" }).getAttribute("aria-selected"),
  ).toBe("true");
  expect(screen.getAllByText("答题解释")).toHaveLength(1);
  expect(screen.getByText(/答案格式校验通过/)).toBeTruthy();
  expect(screen.getByText("正式知识 0 条")).toBeTruthy();
  expect(screen.getByText("未记录到无效知识引用")).toBeTruthy();
  expect(screen.queryByText("raw")).toBeNull();
  const exact = screen.getByText("高级详情：完整原始数据与来源").closest("details");
  expect(exact?.open).toBe(false);
  expect(exact?.textContent).toContain('"raw"');
  fireEvent.click(screen.getByRole("tab", { name: "输入" }));
  expect(screen.getAllByText("答题解释")).toHaveLength(1);
  expect(screen.queryByText("可用知识数量")).toBeNull();
});

it('keeps Harness on its own research round after final evaluation starts', () => {
  const evaluated:Run={...run,status:'running',error:undefined,progress:{node_id:'evaluate',round_index:1000},events:[...run.events!,{type:'stage',node_id:'evaluate',round_index:1000,state:'running',time:10}],config:{...run.config,workflow:{...run.config.workflow,nodes:[...run.config.workflow.nodes,{id:'evaluate',type:'evaluation',config:{},position:{x:0,y:500}}]}}};
  render(<RunWorkflowView run={evaluated} nodeIds={['solver']} compact/>);
  expect((screen.getByLabelText('查看轮次') as HTMLSelectElement).value).toBe('1');
  expect(screen.queryByRole('option',{name:'最终独立评测'})).toBeNull();
  expect(screen.getByText('模型解释')).toBeTruthy();
});
