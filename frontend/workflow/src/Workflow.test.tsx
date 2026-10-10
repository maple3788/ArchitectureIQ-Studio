import { afterEach, it, expect, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  act as reactAct,
} from "@testing-library/react";
import { Workflow } from "./Workflow";
import { WorkflowWorkspace } from "./WorkflowWorkspace";
import { SharedWorkflowDraftProvider } from "./SharedWorkflowDraft";
import { useState } from "react";
// Exercise the real editor and transport; only the external canvas renderer is replaced.
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children, nodes, onNodeClick, nodeTypes }: any) => {
    const Stage = nodeTypes.stage;
    return (
      <div>
        {children}
        {nodes.map((node: any) => (
          <div key={node.id}>
            <button onClick={() => onNodeClick({}, node)}>
              画布节点 {node.id}
            </button>
            {node.id === "input" && (
              <Stage data={node.data} selected={node.selected} />
            )}
          </div>
        ))}
      </div>
    );
  },
  Panel: ({ children }: any) => <div>{children}</div>,
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  MiniMap: () => null,
  MarkerType: { ArrowClosed: "closed" },
  PanOnScrollMode: { Vertical: "vertical" },
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  applyNodeChanges: (_: any, nodes: any) => nodes,
  applyEdgeChanges: (_: any, edges: any) => edges,
}));
vi.mock("./QuestionPicker", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./QuestionPicker")>()),
  QuestionPicker: ({
    onApply,
    onClose,
    questionSetId,
    purpose,
    phase,
  }: any) => (
    <div role="dialog" aria-label="题目选择器">
      <output>{questionSetId}</output>
      <output>
        {purpose} {phase}
      </output>
      <button
        onClick={() =>
          onApply({
            id: "set-three",
            name: "三题研究集",
            count: 3,
            keys: ["q1", "q2", "q3"],
          })
        }
      >
        应用三题
      </button>
      <button onClick={onClose}>关闭选择器</button>
    </div>
  ),
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("opens the picker from the actual canvas stage with Enter or Space", async () => {
  setup();
  await openInternals();
  const input = screen.getByRole("button", { name: "画布步骤：题目选择" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(
    await screen.findByRole("dialog", { name: "题目选择器" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "关闭选择器" }));
  fireEvent.keyDown(input, { key: " " });
  expect(
    await screen.findByRole("dialog", { name: "题目选择器" }),
  ).toBeTruthy();
});
const graph = {
  schema_version: 1,
  name: "Contract workflow",
  nodes: [
    {
      id: "input",
      type: "question_input",
      position: { x: 0, y: 0 },
      config: {},
    },
    {
      id: "solver",
      type: "agent",
      position: { x: 200, y: 0 },
      config: { role: "solver", prompt: "" },
    },
    {
      id: "evaluate",
      type: "evaluation",
      position: { x: 0, y: 500 },
      config: { phase: "final" },
    },
  ],
  edges: [
    {
      id: "input-solver",
      source: "input",
      target: "solver",
      source_handle: "out",
      target_handle: "in",
      condition: "always",
    },
  ],
  settings: {
    model_id: "model1",
    question_set_id: "set1",
    kb_path: "/server/kb.json",
  },
};
const response = (data: any, status = 200) =>
  new Response(JSON.stringify(data), { status });
function setup(
  custom?: (path: string, init?: RequestInit) => Promise<Response> | undefined,
  workspace=false,
  initialDraft?:any,
  serverWorkflow:any = graph,
) {
  const drafts = new Map<string, string>();
  if(initialDraft)drafts.set("architectureiq-studio-workflow-v1",JSON.stringify(initialDraft));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => drafts.get(key) ?? null,
    setItem: (key: string, value: string) => drafts.set(key, value),
    removeItem: (key: string) => drafts.delete(key),
  });
  const submissions: { body: any; headers: any }[] = [];
  let previewCount = 0;
  let sharedDraft = {workflow: structuredClone(serverWorkflow), advanced_backup: null as any, revision: 1, updated_at: 1};
  let draftReads=0;
  const draftWrites:any[]=[];
  const backups:any[]=[];
  vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
    const special = custom?.(path, init);
    if (special) return special;
    if (path === "/api/studio/workflow/draft") {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        draftWrites.push(body);
        if(body.expected_revision !== sharedDraft.revision) return response({detail:"draft revision changed"},409);
        sharedDraft = {workflow:body.workflow,advanced_backup:body.advanced_backup,revision:sharedDraft.revision+1,updated_at:sharedDraft.updated_at+1};
      }
      if(init?.method !== "PUT") draftReads++;
      return response(sharedDraft);
    }
    if (path === "/api/studio/workflow/draft/backups") {
      if(init?.method === "POST") {
        const body=JSON.parse(String(init.body));
        const backup={id:`backup-${backups.length+1}`,...body,created_at:1};
        backups.push(backup);
        return response(backup);
      }
      return response({items:backups,total:backups.length});
    }
    if (path === "/api/studio/workflow/default") return response(graph);
    if (path === "/api/studio/models")
      return response({
        items: [
          {
            id: "model1",
            name: "Attested",
            enabled: true,
            health: { status: "verified" },
            parameters: { max_tokens: 2048 },
          },
        ],
        total: 1,
      });
    if (path === "/api/studio/question-sets")
      return response({
        items: [{ id: "set1", name: "Frozen", count: 1 }],
        total: 1,
      });
    if (path === "/api/studio/workflows/validate")
      return response({ valid: true, errors: [] });
    if (path === "/api/studio/runs/preview")
      return response({
        config_hash: `workflow-hash-${++previewCount}`,
        requests: [
          {
            payload: { messages: [{ role: "user", content: "exact request" }] },
          },
        ],
      });
    if (path === "/api/studio/runs" && init?.method === "POST") {
      submissions.push({
        body: JSON.parse(init.body as string),
        headers: init.headers,
      });
      return response({ id: "workflow-job" });
    }
    return response({ items: [], total: 0 });
  });
  const onRun = vi.fn();
  const action = async (op: () => Promise<any>) => {
    try {
      return await op();
    } catch {
      return undefined;
    }
  };
  function Editor(){
    const [id,setId]=useState<string>();
    const editor=<Workflow version={0} act={action} executionEnabled onRun={value=>{onRun(value);setId(value);}}/>;
    return workspace?<WorkflowWorkspace version={0} act={action} selectedRun={id}>{editor}</WorkflowWorkspace>:editor;
  }
  const tree=(visible:boolean)=><SharedWorkflowDraftProvider>{visible?<Editor/>:<div>题库页面</div>}</SharedWorkflowDraftProvider>;
  const view=render(tree(true));
  return { submissions, onRun, drafts, draftWrites, backups, getSharedDraft:()=>sharedDraft, getDraftReads:()=>draftReads, showEditor:(visible:boolean)=>view.rerender(tree(visible)) };
}
async function openInternals() {
  await screen.findByRole("heading", { name: "Data · 研究数据" });
  fireEvent.click(screen.getByText("内部流程与高级配置"));
  await screen.findByRole("button", { name: "画布节点 input" });
}
async function enterRun() {
  const run = await screen.findByRole("button", { name: "预览研究配置" });
  await waitFor(() => expect((run as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(run);
  return screen.findByRole("button", { name: "按此配置运行" });
}
it("opens preview before execution and submits its frozen hash and a stable idempotency key", async () => {
  const { submissions, onRun } = setup();
  const submit = await enterRun();
  expect(submissions).toHaveLength(0);
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0].body).toMatchObject({
    kind: "workflow",
    question_set_id: "set1",
    model_ids: ["model1"],
    workflow: { name: graph.name, settings: graph.settings },
    expected_config_hash: "workflow-hash-1",
  });
  const key = submissions[0].headers["Idempotency-Key"];
  expect(key).toBeTruthy();
  expect(onRun).toHaveBeenCalledWith("workflow-job");
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(2));
  expect(submissions[1].headers["Idempotency-Key"]).toBe(key);
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  await openInternals();
  fireEvent.click(screen.getByRole("button", { name: /^解题 Solver/ }));
  fireEvent.change(screen.getByLabelText("角色任务补充指令"), {
    target: { value: "updated exact guidance" },
  });
  const next = await enterRun();
  expect(submissions).toHaveLength(2);
  fireEvent.click(next);
  await waitFor(() => expect(submissions).toHaveLength(3));
  expect(submissions[2].body.expected_config_hash).toBe("workflow-hash-2");
  expect(submissions[2].body.workflow.nodes[1].config.prompt).toBe(
    "updated exact guidance",
  );
  expect(submissions[2].headers["Idempotency-Key"]).not.toBe(key);
});
it("cannot authorize edited settings with an older asynchronous preview", async () => {
  let resolvePreview!: (response: Response) => void;
  const { submissions } = setup((path) =>
    path === "/api/studio/runs/preview"
      ? new Promise((resolve) => (resolvePreview = resolve))
      : undefined,
  );
  const run = await screen.findByRole("button", { name: "预览研究配置" });
  await waitFor(() => expect((run as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(run);
  await waitFor(() => expect(resolvePreview).toBeTruthy());
  fireEvent.change(screen.getByLabelText("工作流名称"), {
    target: { value: "Changed while previewing" },
  });
  await reactAct(async () =>
    resolvePreview(response({ config_hash: "old-hash" })),
  );
  expect(
    (
      (await screen.findByRole("button", {
        name: "按此配置运行",
      })) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(submissions).toHaveLength(0);
  expect(screen.getByText(/预览已失效/)).toBeTruthy();
});
it("requires a new preview after the server rejects a stale model revision", async () => {
  const { onRun } = setup((path, init) =>
    path === "/api/studio/runs" && init?.method === "POST"
      ? Promise.resolve(response({ detail: "model revision changed" }, 409))
      : undefined,
  );
  const submit = await enterRun();
  fireEvent.click(submit);
  await waitFor(() =>
    expect((submit as HTMLButtonElement).disabled).toBe(true),
  );
  expect(onRun).not.toHaveBeenCalled();
  expect(screen.getByText(/预览已失效/)).toBeTruthy();
});

it("blocks an edit made while submission validation is in flight", async () => {
  let resolveValidation!: (value: Response) => void;
  const { submissions } = setup((path) =>
    path === "/api/studio/workflows/validate"
      ? new Promise((resolve) => (resolveValidation = resolve))
      : undefined,
  );
  const submit = await enterRun();
  fireEvent.click(submit);
  await waitFor(() => expect(resolveValidation).toBeTruthy());
  fireEvent.change(screen.getByLabelText("工作流名称"), {
    target: { value: "Edited during validation" },
  });
  await reactAct(async () =>
    resolveValidation(response({ valid: true, errors: [] })),
  );
  expect(submissions).toHaveLength(0);
});

it("starts at question selection and opens the picker from either input surface", async () => {
  setup();
  await openInternals();
  expect(screen.queryByLabelText("角色任务补充指令")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "画布节点 input" }));
  expect(
    await screen.findByRole("dialog", { name: "题目选择器" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("dialog", { name: "题目选择器" }).textContent,
  ).toContain("set1");
  fireEvent.click(screen.getByRole("button", { name: "关闭选择器" }));
  fireEvent.click(screen.getByRole("button", { name: /^题目选择/ }));
  expect(
    await screen.findByRole("dialog", { name: "题目选择器" }),
  ).toBeTruthy();
});
it("applies frozen multi-question selection to the actual run and invalidates old preview", async () => {
  const { submissions } = setup();
  await enterRun();
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  fireEvent.click(screen.getByRole("button", { name: "调整研究题目" }));
  fireEvent.click(await screen.findByRole("button", { name: "应用三题" }));
  expect(screen.queryByRole("dialog", { name: "题目选择器" })).toBeNull();
  expect(screen.getByText("三题研究集")).toBeTruthy();
  expect(screen.getByText(/已选3题，按1轮逐题作答/)).toBeTruthy();
  const submit = await enterRun();
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0].body).toMatchObject({
    question_set_id: "set-three",
    expected_config_hash: "workflow-hash-2",
    workflow: {
      settings: {
        question_set_id: "set-three",
        max_rounds: 1,
        discovery_per_round: 3,
        packet_size: 1,
      },
    },
  });
});
it("keeps budgets and file references closed until requested", async () => {
  setup();
  await openInternals();
  fireEvent.click(screen.getByRole("tab", { name: "运行设置" }));
  const detail = screen.getByText("预算与服务器文件").closest("details")!;
  expect(detail.open).toBe(false);
  expect(screen.getAllByLabelText("研究轮数").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByText("预算与服务器文件"));
  expect(detail.open).toBe(true);
  expect(screen.getByLabelText("每轮调用上限（次）")).toBeTruthy();
});

it("presents four vertical stages and hides the internal workflow initially", async () => {
  setup();
  for (const title of [
    "Data · 研究数据",
    "Harness · 研究策略",
    "KB · 知识积累",
    "Task · 新题解答与效果验证",
  ])
    expect(await screen.findByRole("heading", { name: title })).toBeTruthy();
  expect(screen.getByText("内部流程与高级配置").closest("details")?.open).toBe(
    false,
  );
  expect(screen.queryByRole("button", { name: "画布节点 input" })).toBeNull();
  expect(screen.getByText(/无 KB、初始 KB、本轮 KB/)).toBeTruthy();
});
it("keeps independent Task selection separate from research coverage and invalidates the preview", async () => {
  const { submissions } = setup();
  fireEvent.click(await screen.findByRole("button", { name: "预览研究配置" }));
  await screen.findByRole("button", { name: "按此配置运行" });
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  fireEvent.click(screen.getByLabelText("安排独立评测"));
  fireEvent.click(screen.getByRole("button", { name: "选择独立评测题目" }));
  expect(screen.getByRole("dialog").textContent).toContain("evaluation final");
  fireEvent.click(screen.getByRole("button", { name: "应用三题" }));
  expect(
    (screen.getByRole("button", { name: "开始研究" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  const submit = await enterRun();
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0].body.workflow.settings).toMatchObject({
    ...graph.settings,
    task_question_set_id: "set-three",
  });
  expect(
    submissions[0].body.workflow.settings.discovery_per_round,
  ).toBeUndefined();
  expect(submissions[0].body.workflow.settings.max_rounds).toBeUndefined();
  expect(submissions[0].body.workflow.settings.packet_size).toBeUndefined();
});

it("invalidates preview on Task phase changes and preserves the set when Task is disabled", async () => {
  const { submissions } = setup();
  fireEvent.click(await screen.findByLabelText("安排独立评测"));
  fireEvent.click(screen.getByRole("button", { name: "选择独立评测题目" }));
  fireEvent.click(await screen.findByRole("button", { name: "应用三题" }));
  await enterRun();
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  expect(
    (screen.getByRole("button", { name: "开始研究" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
  fireEvent.change(screen.getByLabelText("独立评测阶段"), {
    target: { value: "development" },
  });
  expect(
    (screen.getByRole("button", { name: "开始研究" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "调整独立评测题目" }));
  expect(screen.getByRole("dialog").textContent).toContain("set-three");
  expect(screen.getByRole("dialog").textContent).toContain(
    "evaluation development",
  );
  fireEvent.click(screen.getByRole("button", { name: "关闭选择器" }));
  fireEvent.click(screen.getByLabelText("安排独立评测"));
  expect(screen.getByText(/本次未安排独立评测。已选择/)).toBeTruthy();
  fireEvent.click(await enterRun());
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0].body.workflow.settings.task_question_set_id).toBe(
    "set-three",
  );
  expect(
    submissions[0].body.workflow.nodes.find((n: any) => n.id === "evaluate")
      .config.phase,
  ).toBe("development");
  expect(
    submissions[0].body.workflow.edges.some(
      (e: any) => e.target === "evaluate",
    ),
  ).toBe(false);
});
it("shows the server's effective research and Task coverage in the preview", async () => {
  setup((path) =>
    path === "/api/studio/runs/preview"
      ? Promise.resolve(
          response({
            config_hash: "frozen",
            task: {
              enabled: true,
              phase: "final",
              count: 4,
              effective_research_count: 7,
              effective_evaluation_count: 4,
              omitted_data_evaluation_count: 2,
              notice: "独立 Task 模式下，Data 中 2 道旧评测题不参与本次执行。",
            },
          }),
        )
      : undefined,
  );
  await enterRun();
  expect(screen.getByText(/实际研究 7 题/)).toBeTruthy();
  expect(
    screen.getByText(/独立 Task 模式下，Data 中 2 道旧评测题不参与/, {
      selector: "p",
    }),
  ).toBeTruthy();
  expect(screen.getByText(/4 题 · 最终盲测 · 无 KB/)).toBeTruthy();
});

function setupPairedWorkflow() {
  const pair = (key: string, split: string) => ({
    pair_key: key,
    pair_id: key,
    family: "bigram_lm",
    type: "architecture_only",
    split,
    ready: true,
    kb_ready: true,
    evaluation_ready: true,
    members: [
      { role: "original", key: key + "-original", id: key + "-original" },
      { role: "counterfactual", key: key + "-counter", id: key + "-counter" },
    ],
    intervention: { changes: [], controls: [] },
    candidate_mapping: [],
  });
  const research = pair("research-pair", "discovery");
  const task = pair("task-pair", "final");
  const set = (id: string, name: string, value: ReturnType<typeof pair>) => ({
    id, name, selection_mode: "pairs", count: 2, pair_count: 1,
    keys: value.members.map(member => member.key),
    pair_keys: [value.pair_key], pairs: [value],
  });
  const researchSet = set("research-pairs", "已冻结研究题对", research);
  const taskSet = set("task-pairs", "已冻结评测题对", task);
  const pairedDraft = {...graph,settings:{...graph.settings,
    question_set_id:researchSet.id, task_question_set_id:taskSet.id,
    learning_protocol:"paired_progressive",discovery_per_round:2,packet_size:2,max_rounds:1,
  }};
  return setup((path) => {
    if (path === "/api/studio/question-sets")
      return Promise.resolve(response({ items: [researchSet, taskSet], total: 2 }));
    if (path === "/api/studio/question-sets/" + researchSet.id)
      return Promise.resolve(response(researchSet));
    if (path === "/api/studio/question-sets/" + taskSet.id)
      return Promise.resolve(response(taskSet));
    if (path.startsWith("/api/studio/question-pairs?")) {
      const value = path.includes("split=discovery") ? research : task;
      return Promise.resolve(response({ items: [value], total: 1 }));
    }
    return undefined;
  },false,undefined,pairedDraft);
}

it("reopens saved research and Task pair sets through their default edit actions", async () => {
  setupPairedWorkflow();
  await screen.findByText("已冻结研究题对");
  const protocol = screen.getByLabelText("学习方式") as HTMLSelectElement;
  expect(protocol.value).toBe("paired_progressive");
  expect(protocol.querySelector<HTMLOptionElement>('option[value="single"]')?.disabled).toBe(true);

  fireEvent.click(screen.getByRole("button", { name: "调整研究题目" }));
  expect(await screen.findByRole("dialog", { name: "选择题目对" })).toBeTruthy();
  await waitFor(() => expect((screen.getByRole("checkbox", { name: "选择题对 research-pair" }) as HTMLInputElement).checked).toBe(true));
  expect(screen.queryByRole("dialog", { name: "题目选择器" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "关闭题对选择" }));

  fireEvent.click(screen.getByRole("button", { name: "调整独立评测题目" }));
  expect(await screen.findByRole("dialog", { name: "选择题目对" })).toBeTruthy();
  await waitFor(() => expect((screen.getByRole("checkbox", { name: "选择题对 task-pair" }) as HTMLInputElement).checked).toBe(true));
  expect(screen.queryByRole("dialog", { name: "题目选择器" })).toBeNull();
});

it("keeps pair selection when opening the research input from the advanced canvas", async () => {
  setupPairedWorkflow();
  await screen.findByText("已冻结研究题对");
  await openInternals();
  fireEvent.keyDown(screen.getByRole("button", { name: "画布步骤：题目选择" }), { key: "Enter" });
  expect(await screen.findByRole("dialog", { name: "选择题目对" })).toBeTruthy();
  expect(screen.queryByRole("dialog", { name: "题目选择器" })).toBeNull();
});

it("changes a pair set to ordinary research only through explicit single-question selection", async () => {
  const { submissions } = setupPairedWorkflow();
  fireEvent.click(await screen.findByRole("button", { name: "改为单题选择" }));
  expect(await screen.findByRole("dialog", { name: "题目选择器" })).toBeTruthy();
  expect(screen.queryByRole("dialog", { name: "选择题目对" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "应用三题" }));
  const protocol = screen.getByLabelText("学习方式") as HTMLSelectElement;
  expect(protocol.value).toBe("single");
  expect(protocol.querySelector<HTMLOptionElement>('option[value="single"]')?.disabled).toBe(false);
  fireEvent.click(await enterRun());
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0].body.workflow.settings).toMatchObject({
    question_set_id: "set-three", task_question_set_id: "task-pairs",
    learning_protocol: "single", discovery_per_round: 3,
  });
});

it("keeps the actual draft canvas and stage DOM mounted after an idempotent Start attaches the run",async()=>{
 const {submissions}=setup(path=>path==="/api/studio/runs/workflow-job"?Promise.resolve(response({id:"workflow-job",kind:"workflow",created_at:1,status:"running",config:{workflow:graph},progress:{node_id:"solver",state:"running",round_index:1}})):undefined,true);
 await screen.findByRole("heading",{name:"Data · 研究数据"});
 const canvas=screen.getByTestId("live-workflow-canvas"),data=screen.getByTestId("live-stage-data");
 fireEvent.click(await enterRun());
 await screen.findByText("本次冻结运行");
 expect(submissions).toHaveLength(1);expect(screen.getByTestId("live-workflow-canvas")).toBe(canvas);expect(screen.getByTestId("live-stage-data")).toBe(data);
 expect(screen.queryByRole("button",{name:"按此配置运行"})).toBeNull();
});
it("invalidates preview when changing the catalog method and binds its authoritative settings",async()=>{
 const method=(id:string,name:string,experience_mode:string)=>({id,version:"1",name,description:"Description",adaptation:"Adapted",paper_url:null,status:"available",learning_protocol:"single",experience_mode,hash:id,steps:[]});
 const {submissions}=setup(path=>path==="/api/studio/methods"?Promise.resolve(response({items:[method("scientific","Scientific","off"),method("expel","ExpeL","expel_inspired")]})):undefined,false,undefined,{...graph,settings:{...graph.settings,method_id:"scientific",method_version:"1",loop_mode:"manual"}});
 await enterRun();fireEvent.click(screen.getByRole("button",{name:"关闭详情"}));fireEvent.change(screen.getByLabelText("论文方法"),{target:{value:"expel"}});
 expect((screen.getByRole("button",{name:"开始研究"}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(await enterRun());await waitFor(()=>expect(submissions).toHaveLength(1));expect(submissions[0].body.workflow.settings).toMatchObject({method_id:"expel",method_version:"1",learning_protocol:"single",loop_mode:"manual"});
 expect(Object.hasOwn(submissions[0].body.workflow.settings,"experience_mode")).toBe(false);
 fireEvent.click(screen.getByRole("button",{name:"关闭详情"}));
 fireEvent.click(screen.getByRole("button",{name:"调整研究题目"}));fireEvent.click(await screen.findByRole("button",{name:"应用三题"}));fireEvent.click(await enterRun());await waitFor(()=>expect(submissions).toHaveLength(2));expect(Object.hasOwn(submissions[1].body.workflow.settings,"experience_mode")).toBe(false);
});
it('shows legacy missing no-change stop as unconfigured without writing a phantom default',async()=>{
 const {submissions}=setup();const field=await screen.findByLabelText('连续无变化停止轮数');expect((field as HTMLInputElement).value).toBe('');fireEvent.click(await enterRun());await waitFor(()=>expect(submissions).toHaveLength(1));expect(Object.hasOwn(submissions[0].body.workflow.settings,'stop_after_no_change_rounds')).toBe(false);
});

const basicGraph={...graph,name:'单题学习',settings:{method_id:'basic_learning',method_version:'1',loop_mode:'manual',max_rounds:2,discovery_per_round:1,packet_size:1,use_previous_experience:true,record_conditions:true}};
it('fresh single-question mode freezes one eligible real question and keeps manual repeat settings',async()=>{
 const saved:any[]=[];
 setup((path,init)=>{
  if(path==='/api/studio/workflow/default')return Promise.resolve(response(basicGraph));
  if(path.startsWith('/api/studio/questions?'))return Promise.resolve(response({total:3,items:[{key:'bad',id:'bad',ready:true,kb_ready:false,split:'discovery'},{key:'real@v1',id:'real',ready:true,kb_ready:true,split:'discovery'},{key:'next@v2',id:'next',ready:true,kb_ready:true,split:'discovery'}]}));
  if(path==='/api/studio/question-sets'&&init?.method==='POST'){saved.push(JSON.parse(String(init.body)));return Promise.resolve(response({id:'one',name:'真实单题',count:1,keys:['real@v1']}));}
  if(path==='/api/studio/questions/real%40v1')return Promise.resolve(response({metadata:{key:'real@v1'},detail:{prompt:'真实公开题面',choices:[]}}));
 },false,undefined,basicGraph);
 await screen.findByRole('region',{name:'单题学习工作流'});
 await waitFor(()=>expect(saved).toHaveLength(1));
 expect(saved[0].keys).toEqual(['real@v1']);
 fireEvent.click(screen.getByRole('button',{name:'是否继续'}));
 expect((screen.getByLabelText('最多学习轮数') as HTMLSelectElement).value).toBe('2');
 expect(screen.getByText(/尚未预览当前配置/)).toBeTruthy();
 const start=screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement;
 expect(start.disabled).toBe(true);
});
it('uses the shared single-question draft and preserves an obsolete browser draft only as a server backup',async()=>{
 const original={...graph,name:'旧浏览器复杂流程',settings:{...graph.settings,method_id:'scientific',max_rounds:3},nodes:graph.nodes.map(n=>n.id==='solver'?{...n,config:{role:'solver',prompt:'保留原始提示词'}}:n)};
 const current={...basicGraph,name:'服务器单题学习',settings:{...basicGraph.settings,model_id:'model1',question_set_id:'set1'}};
 const {backups,draftWrites,getSharedDraft}=setup(undefined,false,original,current);
 await screen.findByRole('region',{name:'单题学习工作流'});
 await waitFor(()=>expect(backups.some(item=>item.workflow.name===original.name)).toBe(true));
 expect(backups.find(item=>item.workflow.name===original.name).workflow.nodes.find((n:any)=>n.id==='solver').config.prompt).toBe('保留原始提示词');
 expect(screen.queryByDisplayValue(original.name)).toBeNull();
 expect(getSharedDraft().workflow.name).toBe(current.name);
 expect(draftWrites.some(item=>item.workflow.name===original.name)).toBe(false);
});
it('saves editor changes to the shared server draft instead of replacing the browser backup',async()=>{
 const {draftWrites,getSharedDraft,drafts}=setup();
 fireEvent.change(await screen.findByLabelText('工作流名称'),{target:{value:'跨浏览器研究配置'}});
 await waitFor(()=>expect(draftWrites.some(item=>item.workflow.name==='跨浏览器研究配置')).toBe(true));
 expect(getSharedDraft().workflow.name).toBe('跨浏览器研究配置');
 expect(getSharedDraft().revision).toBeGreaterThan(1);
 await screen.findByText('已保存到服务器');
 expect(drafts.get('architectureiq-studio-workflow-v1')).toBeUndefined();
});
it('persists an initial KB choice to the shared draft and uses that selection in the frozen preview',async()=>{
 const selected={id:'learning-library',version:'a'.repeat(64),name:'多元回归学习经验',kind:'experience',counts:{active_lessons:2},snapshot:{lessons:[],episodes:[]}};
 const requests:any[]=[];
 const {getSharedDraft}=setup((path,init)=>{
  if(path==='/api/studio/kb')return Promise.resolve(response({items:[selected]}));
  if(path==='/api/studio/runs/preview'){
   requests.push(JSON.parse(String(init?.body)));
   return Promise.resolve(response({config_hash:'with-selected-kb',initial_kb:selected,requests:[{initial_experience:{lessons:[{id:'one'}],omitted:{lessons:1},excluded:{lessons_with_excluded_sources:0}}}]}));
  }
 },false,undefined,{...basicGraph,settings:{...basicGraph.settings,model_id:'model1',question_set_id:'set1'}});
 fireEvent.click(await screen.findByRole('button',{name:'作答'}));
 fireEvent.click(screen.getByRole('button',{name:'选择 KB'}));
 fireEvent.click(await screen.findByRole('button',{name:'使用这个 KB'}));
 await waitFor(()=>expect(getSharedDraft().workflow.settings.initial_kb).toEqual({id:selected.id,version:selected.version}));
 await enterRun();
 expect(requests[0].workflow.settings.initial_kb).toEqual({id:selected.id,version:selected.version});
 expect(screen.getByText(/本题实际带入 1 条起始经验/)).toBeTruthy();
 expect(screen.getByText(/1 条因输入长度限制省略/)).toBeTruthy();
});
it('explains the unavailable model and preview beside the disabled start button',async()=>{
 setup(path=>path==='/api/studio/models'?Promise.resolve(response({items:[{id:'model1',name:'Not verified',enabled:true,health:{status:'reachable'}}]})):undefined);
 await screen.findByRole('button',{name:'开始研究'});
 await screen.findByText(/模型尚未通过运行验证/);
 expect(screen.getByText(/尚未预览当前配置/)).toBeTruthy();
 expect(screen.getByRole('button',{name:'检查模型'})).toBeTruthy();
});
it('keeps an explicit empty model choice after fresh default auto-selection',async()=>{
 setup(path=>{
  if(path==='/api/studio/workflow/default')return Promise.resolve(response({...basicGraph,settings:{...basicGraph.settings,question_set_id:'set1'}}));
 },false,undefined,{...basicGraph,settings:{...basicGraph.settings,question_set_id:'set1'}});
 await screen.findByRole('region',{name:'单题学习工作流'});
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 const select=screen.getByRole('combobox',{name:'作答模型'}) as HTMLSelectElement;
 await waitFor(()=>expect(select.value).toBe('model1'));
 fireEvent.change(select,{target:{value:''}});
 await waitFor(()=>expect(select.value).toBe(''));
 expect(screen.getByText('尚未选择模型')).toBeTruthy();
});
it('switches to single-question learning only explicitly and restores the backed-up advanced draft',async()=>{
 const original={...graph,name:'高级实验草稿',settings:{...graph.settings,method_id:'scientific',max_rounds:3},nodes:graph.nodes.map(n=>n.id==='solver'?{...n,config:{role:'solver',prompt:'自定义指令'}}:n)};
 const {getSharedDraft}=setup(path=>path==='/api/studio/workflow/default?method_id=basic_learning'?Promise.resolve(response(basicGraph)):undefined,false,undefined,original);
 fireEvent.click(await screen.findByRole('button',{name:'单题学习'}));
 await screen.findByRole('region',{name:'单题学习工作流'});
 await waitFor(()=>expect(getSharedDraft().advanced_backup?.settings.max_rounds).toBe(3));
 fireEvent.click(screen.getByText('高级方法与草稿管理'));
 fireEvent.click(screen.getByRole('button',{name:'恢复原高级草稿'}));
 await screen.findByDisplayValue('高级实验草稿');
 await waitFor(()=>expect(getSharedDraft().workflow.name).toBe(original.name));
 expect(getSharedDraft().workflow.nodes.find((n:any)=>n.id==='solver').config.prompt).toBe('自定义指令');
});

it('blocks preview and execution until the edited shared configuration is saved',async()=>{
 let finishSave:((value:Response)=>void)|undefined;
 let pending:any;
 const {submissions}=setup((path,init)=>{
   if(path==='/api/studio/workflow/draft'&&init?.method==='PUT'){
     pending=JSON.parse(String(init.body));
     return new Promise(resolve=>{finishSave=resolve;});
   }
 });
 await enterRun();
 fireEvent.click(screen.getByRole('button',{name:'关闭详情'}));
 fireEvent.change(screen.getByLabelText('工作流名称'),{target:{value:'等待服务器确认的配置'}});
 const preview=screen.getByRole('button',{name:'预览研究配置'}) as HTMLButtonElement;
 const start=screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement;
 expect(preview.disabled).toBe(true);
 expect(start.disabled).toBe(true);
 await waitFor(()=>expect(finishSave).toBeDefined());
 fireEvent.click(start);
 expect(submissions).toHaveLength(0);
 await reactAct(async()=>finishSave!(response({workflow:pending.workflow,advanced_backup:pending.advanced_backup,revision:2,updated_at:2})));
 await screen.findByText('已保存到服务器');
 expect(start.disabled).toBe(true);
 fireEvent.click(await enterRun());
 await waitFor(()=>expect(submissions).toHaveLength(1));
 expect(submissions[0].body.workflow.name).toBe('等待服务器确认的配置');
 expect(submissions[0].body.expected_config_hash).toBe('workflow-hash-2');
});
it('keeps unsynced edits visible and prevents execution when the server save fails',async()=>{
 const {submissions}=setup((path,init)=>path==='/api/studio/workflow/draft'&&init?.method==='PUT'?Promise.reject(new TypeError('Network request failed')):undefined);
 await enterRun();
 fireEvent.click(screen.getByRole('button',{name:'关闭详情'}));
 fireEvent.change(screen.getByLabelText('工作流名称'),{target:{value:'尚未同步的修改'}});
 await screen.findByText('服务器连接中断，修改尚未同步');
 expect((screen.getByLabelText('工作流名称') as HTMLInputElement).value).toBe('尚未同步的修改');
 expect((screen.getByRole('button',{name:'预览研究配置'}) as HTMLButtonElement).disabled).toBe(true);
 expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(true);
 expect(submissions).toHaveLength(0);
});

it('restores an archived browser draft only through the explicit server backup action',async()=>{
 const original={...graph,name:'迁移保留的研究流程',settings:{...graph.settings,method_id:'scientific',max_rounds:3}};
 const current={...basicGraph,settings:{...basicGraph.settings,model_id:'model1',question_set_id:'set1'}};
 const {backups,getSharedDraft}=setup(undefined,false,original,current);
 await screen.findByRole('region',{name:'单题学习工作流'});
 await waitFor(()=>expect(backups).toHaveLength(1));
 fireEvent.click(screen.getByRole('button',{name:'版本与备份'}));
 await screen.findByRole('heading',{name:original.name});
 fireEvent.click(screen.getByRole('button',{name:'恢复此草稿'}));
 await screen.findByDisplayValue(original.name);
 await waitFor(()=>expect(getSharedDraft().workflow.name).toBe(original.name));
 expect(getSharedDraft().workflow.settings.max_rounds).toBe(3);
 expect(screen.queryByRole('region',{name:'单题学习工作流'})).toBeNull();
});

it('continues saving a pending edit when navigating away and restores it on return',async()=>{
 const {showEditor,getSharedDraft}=setup();
 fireEvent.change(await screen.findByLabelText('工作流名称'),{target:{value:'离开页面前的共享修改'}});
 showEditor(false);
 expect(screen.queryByLabelText('工作流名称')).toBeNull();
 await waitFor(()=>expect(getSharedDraft().workflow.name).toBe('离开页面前的共享修改'));
 showEditor(true);
 await screen.findByDisplayValue('离开页面前的共享修改');
 await screen.findByText('已保存到服务器');
});
it('preserves the frozen preview when an unchanged server refresh returns new object references',async()=>{
 const {getDraftReads,submissions}=setup();
 await enterRun();
 fireEvent.click(screen.getByRole('button',{name:'关闭详情'}));
 const start=screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement;
 expect(start.disabled).toBe(false);
 const reads=getDraftReads();
 await reactAct(async()=>{window.dispatchEvent(new Event('focus'));});
 expect(getDraftReads()).toBeGreaterThan(reads);
 expect(start.disabled).toBe(false);
 fireEvent.click(start);
 await waitFor(()=>expect(submissions).toHaveLength(1));
 expect(submissions[0].body.expected_config_hash).toBe('workflow-hash-1');
});

it('refreshes question-set metadata when another browser selects a newly created server set',async()=>{
 let remoteUpdated=false;
 const remoteWorkflow={...graph,name:'远端更新的配置',settings:{...graph.settings,question_set_id:'new-shared-set'}};
 setup((path,init)=>{
   if(path==='/api/studio/workflow/draft'&&init?.method!=='PUT'&&remoteUpdated)
     return Promise.resolve(response({workflow:remoteWorkflow,advanced_backup:null,revision:2,updated_at:2}));
   if(path==='/api/studio/question-sets')
     return Promise.resolve(response({items:remoteUpdated
       ? [{id:'set1',name:'Frozen',count:1},{id:'new-shared-set',name:'另一浏览器新建的三题研究集',count:3}]
       : [{id:'set1',name:'Frozen',count:1}],total:remoteUpdated?2:1}));
 });
 await screen.findByText('Frozen');
 expect(screen.getByText('1 题 · 按冻结顺序研究')).toBeTruthy();
 remoteUpdated=true;
 await reactAct(async()=>{window.dispatchEvent(new Event('focus'));});
 await screen.findByDisplayValue('远端更新的配置');
 expect(await screen.findByText('另一浏览器新建的三题研究集')).toBeTruthy();
 expect(screen.getByText('3 题 · 按冻结顺序研究')).toBeTruthy();
});
it('opens Dataset selection from the current workflow without replacing the old picker',async()=>{
 setup();
 fireEvent.click(await screen.findByRole('button',{name:'从 Dataset 选择'}));
 expect(await screen.findByRole('dialog',{name:'选择 Dataset 输入'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'关闭 Dataset 选择'}));
 expect(screen.queryByRole('dialog',{name:'选择 Dataset 输入'})).toBeNull();
});
