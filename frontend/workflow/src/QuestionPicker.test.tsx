import { afterEach, it, expect, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QuestionPicker } from "./QuestionPicker";
import type { Question } from "./types";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const q = (n: number, type = "architecture_only"): Question => ({
  key: `q${n}@rev`,
  id: `q${n}`,
  family: "regression",
  type,
  model_types: ["mlp", "resnet"],
  choices: 3,
  budget: 64,
  metric: "test_mse",
  ready: true,
  issues: [],
  source_count: 1,
});
const catalog = Array.from({ length: 26 }, (_, i) =>
  q(
    i + 1,
    i === 1 ? "optimizer_only" : i === 2 ? "future_axis" : "architecture_only",
  ),
);
const response = (data: any, status = 200) =>
  new Response(JSON.stringify(data), { status });
function setup(
  options: {
    purpose?: "research" | "evaluation";
    single?: boolean;
    phase?: "development" | "final";
    setId?: string;
    existing?: any;
    initialError?: boolean;
    saveError?: boolean;
    rows?: any[];
    unavailable?: string[];
  } = {},
) {
  const calls: { path: string; body: any }[] = [];
  const onApply = vi.fn();
  let attempts = 0;
  vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ path, body });
    if (path === "/api/studio/question-sets/existing") {
      attempts++;
      if (options.initialError && attempts === 1)
        return response({ detail: "原题集暂时无法读取" }, 503);
      return response(
        options.existing ?? {
          id: "existing",
          name: "Prior frozen set",
          keys: ["q26@rev"],
          questions: [],
          hash: "sethash",
        },
      );
    }
    if (path.startsWith("/api/studio/questions?")) {
      const query = new URL(path, "http://studio.test").searchParams;
      const filtered = (options.rows || catalog).filter(
        (item) =>
          (!query.get("type") || item.type === query.get("type")) &&
          (!query.get("search") || item.id.includes(query.get("search")!)),
      );
      const start = Number(query.get("offset"));
      return response({
        items: filtered.slice(start, start + Number(query.get("limit"))),
        total: filtered.length,
      });
    }
    if (
      path.startsWith("/api/studio/questions/") &&
      options.unavailable?.includes(
        decodeURIComponent(path.split("/questions/")[1]),
      )
    )
      return response({ detail: "题目版本不可用" }, 404);
    if (path.startsWith("/api/studio/questions/")) {
      const key = decodeURIComponent(path.split("/questions/")[1]);
      return response({
        schema_version: 1,
        public: {
          id: key,
          family: "regression",
          dataset_id: "dataset1",
          lineage_id: "lineage1",
          prompt: "请根据训练预算比较三个候选架构。\n公开题面第二段。",
          split: "discovery",
          choices: [
            { id: "c1", letter: "A", view: { model_type: "mlp" } },
            { id: "c2", letter: "B", view: { model_type: "resnet" } },
          ],
        },
        detail: {
          prompt: "请根据训练预算比较三个候选架构。\n公开题面第二段。",
          dataset: { files: { "dataset_spec.json": { family: "regression" } } },
          choices: [
            {
              letter: "A",
              candidateId: "c1",
              files: { "model.py": "class VisibleModel: pass" },
            },
          ],
        },
        metadata: { id: key.split("@")[0], key },
        sources: [],
      });
    }
    if (path === "/api/studio/question-sets" && init?.method === "POST") {
      if (options.saveError)
        return response({ detail: "题目版本不可冻结" }, 400);
      return response({
        id: "new-set",
        name: body.name,
        keys: body.keys,
        questions: [],
        hash: "new-set-hash",
        created_at: "2026-10-09T04:00:00Z",
      });
    }
    throw Error("Unexpected API route " + path);
  });
  const action = async (op: () => Promise<any>) => {
    try {
      return await op();
    } catch {
      return undefined;
    }
  };
  render(
    <QuestionPicker
      version={0}
      single={options.single}
      purpose={options.purpose}
      phase={options.phase}
      act={action}
      questionSetId={options.setId}
      onApply={onApply}
      onClose={() => {}}
    />,
  );
  return { calls, onApply };
}
it("retains exact selections across pages, Chinese type filters, search and public detail", async () => {
  const { calls, onApply } = setup();
  await screen.findByLabelText("选择 q1");
  fireEvent.click(screen.getByLabelText("选择 q1"));
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  fireEvent.click(await screen.findByLabelText("选择 q26"));
  fireEvent.change(screen.getByLabelText("题型筛选"), {
    target: { value: "optimizer_only" },
  });
  fireEvent.click(await screen.findByLabelText("选择 q2"));
  fireEvent.change(screen.getByLabelText("搜索题目"), {
    target: { value: "q2" },
  });
  fireEvent.click(await screen.findByRole("button", { name: "查看题目 q2" }));
  fireEvent.click(await screen.findByRole("tab", { name: "原始 Prompt" }));
  expect(
    (await screen.findByRole("article", { name: "公开题面" })).textContent,
  ).toBe("请根据训练预算比较三个候选架构。\n公开题面第二段。");
  expect(screen.getByRole("option", { name: "优化器对比" })).toBeTruthy();
  expect(
    screen.getByRole("option", { name: "其他题型 · future_axis" }),
  ).toBeTruthy();
  expect(screen.getByText(/已选 3 题/)).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "题目概览" }));
  fireEvent.click(screen.getByText("A · model.py"));
  expect(await screen.findByText(/VisibleModel/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledTimes(1));
  expect(
    calls.find((call) => call.path === "/api/studio/question-sets")?.body.keys,
  ).toEqual(["q1@rev", "q26@rev", "q2@rev"]);
  expect(onApply.mock.calls[0][0]).toMatchObject({
    id: "new-set",
    keys: ["q1@rev", "q26@rev", "q2@rev"],
  });
  expect(
    calls.some(
      (call) => call.path.includes("/feedback") || call.path.includes("/gt"),
    ),
  ).toBe(false);
});
it("restores all frozen keys including invisible pages before applying additions", async () => {
  const { calls } = setup({ setId: "existing" });
  await screen.findByLabelText("选择 q1");
  await waitFor(() =>
    expect(
      (screen.getByLabelText("选择 q1") as HTMLInputElement).disabled,
    ).toBe(false),
  );
  expect(screen.getByText(/已选 1 题/)).toBeTruthy();
  fireEvent.click(screen.getByLabelText("选择 q1"));
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() =>
    expect(
      calls.some((call) => call.path === "/api/studio/question-sets"),
    ).toBe(true),
  );
  expect(
    calls.find((call) => call.path === "/api/studio/question-sets")?.body.keys,
  ).toEqual(["q26@rev", "q1@rev"]);
});
it("keeps filters and prior selections when switching between full-width reading and the list", async () => {
  const { calls, onApply } = setup({ setId: "existing" });
  await screen.findByLabelText("选择 q2");
  fireEvent.change(screen.getByLabelText("题型筛选"), {
    target: { value: "optimizer_only" },
  });
  fireEvent.click(await screen.findByRole("button", { name: "查看题目 q2" }));
  const reading = await screen.findByLabelText("选用当前题目");
  await waitFor(() =>
    expect((reading as HTMLInputElement).disabled).toBe(false),
  );
  expect(screen.getByRole("dialog").classList.contains("is-reading")).toBe(
    true,
  );
  fireEvent.click(reading);
  fireEvent.click(screen.getByRole("button", { name: "返回题目列表" }));
  expect(screen.getByRole("dialog").classList.contains("is-reading")).toBe(
    false,
  );
  expect((screen.getByLabelText("题型筛选") as HTMLSelectElement).value).toBe(
    "optimizer_only",
  );
  expect((screen.getByLabelText("选择 q2") as HTMLInputElement).checked).toBe(
    true,
  );
  expect(screen.getByText(/已选 2 题/)).toBeTruthy();
  expect(calls.some((call) => call.body)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledTimes(1));
  expect(onApply.mock.calls[0][0].keys).toEqual(["q26@rev", "q2@rev"]);
});
it("blocks applying after initial set failure and preserves its selection after retry", async () => {
  const { onApply } = setup({ setId: "existing", initialError: true });
  expect(await screen.findByText(/原题集暂时无法读取/)).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "应用所选题目" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    ((await screen.findByLabelText("选择 q1")) as HTMLInputElement).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "重试读取原题集" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "应用所选题目",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(screen.getByText(/已选 1 题/)).toBeTruthy();
  expect(onApply).not.toHaveBeenCalled();
});
it("rejects a set response without exact keys instead of replacing it with a new empty selection", async () => {
  setup({
    setId: "existing",
    existing: {
      id: "existing",
      name: "Old set",
      questions: [{ id: "q26@rev" }],
    },
  });
  expect(await screen.findByText(/未返回完整题目版本 keys/)).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "应用所选题目" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
it("keeps the selected questions visible when immutable set creation is rejected", async () => {
  const { onApply } = setup({ saveError: true });
  fireEvent.click(await screen.findByLabelText("选择 q1"));
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  expect(await screen.findByText(/题目版本不可冻结/)).toBeTruthy();
  expect((screen.getByLabelText("选择 q1") as HTMLInputElement).checked).toBe(
    true,
  );
  expect(onApply).not.toHaveBeenCalled();
});

it("allows reading excluded KB questions but never selects them via individual or page selection", async () => {
  const { calls } = setup({
    rows: [{ ...q(1), kb_ready: false }, { ...q(2), split: "final" }, q(3)],
  });
  await screen.findByLabelText("选择 q1");
  expect((screen.getByLabelText("选择 q1") as HTMLInputElement).disabled).toBe(
    true,
  );
  expect((screen.getByLabelText("选择 q2") as HTMLInputElement).disabled).toBe(
    true,
  );
  expect(screen.getByText(/此题不具备 KB 学习所需的完整公开配置/)).toBeTruthy();
  expect(screen.getByText(/最终评估集题目不能用于知识学习/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看题目 q1" }));
  fireEvent.click(await screen.findByRole("tab", { name: "原始 Prompt" }));
  expect(await screen.findByRole("article", { name: "公开题面" })).toBeTruthy();
  expect(
    (screen.getByLabelText("选用当前题目") as HTMLInputElement).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByLabelText("选择当前页"));
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() =>
    expect(
      calls.some((call) => call.path === "/api/studio/question-sets"),
    ).toBe(true),
  );
  expect(
    calls.find((call) => call.path === "/api/studio/question-sets")?.body.keys,
  ).toEqual(["q3@rev"]);
});
it("preserves old selected non-discovery keys and requires explicit removal before applying", async () => {
  const { calls } = setup({
    setId: "existing",
    existing: {
      id: "existing",
      name: "Old final set",
      keys: ["q1@rev"],
      questions: [{ id: "q1@rev", split: "final" }],
    },
  });
  await screen.findByLabelText("选择 q1");
  await screen.findByText(/已选 1 题/);
  expect((screen.getByLabelText("选择 q1") as HTMLInputElement).checked).toBe(
    true,
  );
  expect(
    (screen.getByRole("button", { name: "应用所选题目" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "移除不可用于学习的已选题目" }),
  );
  fireEvent.click(screen.getByLabelText("选择 q2"));
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() =>
    expect(
      calls.some((call) => call.path === "/api/studio/question-sets"),
    ).toBe(true),
  );
  expect(
    calls.find((call) => call.path === "/api/studio/question-sets")?.body.keys,
  ).toEqual(["q2@rev"]);
});

it("shows ordered selected items across pages and filters, opens details and removes only the chosen version", async () => {
  const { calls, onApply } = setup({ setId: "existing" });
  await waitFor(() =>
    expect(
      (screen.getByLabelText("选择 q1") as HTMLInputElement).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByLabelText("选择 q1"));
  fireEvent.change(screen.getByLabelText("题型筛选"), {
    target: { value: "optimizer_only" },
  });
  fireEvent.click(await screen.findByLabelText("选择 q2"));
  fireEvent.click(screen.getByRole("button", { name: "查看已选 3 题" }));
  const list = screen.getByRole("list", { name: "已选题目" });
  expect(
    Array.from(list.querySelectorAll("li")).map((item) =>
      item.getAttribute("data-question-key"),
    ),
  ).toEqual(["q26@rev", "q1@rev", "q2@rev"]);
  fireEvent.click(
    within(list).getByRole("button", { name: "查看已选题目 q26@rev" }),
  );
  expect(await screen.findByRole("tab", { name: "题目概览" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "返回已选题目" }));
  fireEvent.click(screen.getByRole("button", { name: "移除已选题目 q1@rev" }));
  expect(
    Array.from(
      screen.getByRole("list", { name: "已选题目" }).querySelectorAll("li"),
    ).map((item) => item.getAttribute("data-question-key")),
  ).toEqual(["q26@rev", "q2@rev"]);
  expect(calls.some((call) => call.body)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "返回题库" }));
  expect((screen.getByLabelText("题型筛选") as HTMLSelectElement).value).toBe(
    "optimizer_only",
  );
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledTimes(1));
  expect(onApply.mock.calls[0][0].keys).toEqual(["q26@rev", "q2@rev"]);
});

it("retains unavailable and excluded off-page selections until their exact versions are explicitly removed", async () => {
  const { calls } = setup({
    setId: "existing",
    unavailable: ["missing@rev"],
    existing: {
      id: "existing",
      name: "Legacy",
      keys: ["missing@rev", "q26@rev"],
      questions: [{ id: "q26@rev", split: "final" }],
    },
  });
  fireEvent.click(await screen.findByRole("button", { name: "查看已选 2 题" }));
  expect(screen.getByText("missing@rev")).toBeTruthy();
  expect(screen.getByText("q26@rev")).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "应用所选题目" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "查看已选题目 missing@rev" }),
  );
  await screen.findByText("题目版本不可用");
  fireEvent.click(screen.getByRole("button", { name: "返回已选题目" }));
  const list = screen.getByRole("list", { name: "已选题目" });
  expect(within(list).getByText(/题目资料暂不可用/)).toBeTruthy();
  expect(within(list).getByText(/最终评估集题目不能用于知识学习/)).toBeTruthy();
  fireEvent.click(
    within(list).getByRole("button", { name: "移除已选题目 q26@rev" }),
  );
  expect(
    (screen.getByRole("button", { name: "应用所选题目" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(screen.getByRole("button", { name: "查看已选 1 题" })).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "移除已选题目 missing@rev" }),
  );
  expect(screen.getByText("还没有选择题目")).toBeTruthy();
  expect(calls.some((call) => call.body)).toBe(false);
});

it("distinguishes revisions of the same question and removes one without changing the other's identity", async () => {
  setup({
    setId: "existing",
    existing: {
      id: "existing",
      keys: ["q1@older", "q1@newer"],
      questions: [
        { id: "q1@older", family: "regression" },
        { id: "q1@newer", family: "regression" },
      ],
    },
  });
  fireEvent.click(await screen.findByRole("button", { name: "查看已选 2 题" }));
  fireEvent.click(
    screen.getByRole("button", { name: "移除已选题目 q1@older" }),
  );
  const items = screen
    .getByRole("list", { name: "已选题目" })
    .querySelectorAll("li");
  expect(items.length).toBe(1);
  expect(items[0].getAttribute("data-question-key")).toBe("q1@newer");
});

it("selects only the declared Task phase without requiring research eligibility", async () => {
  const { calls, onApply } = setup({
    purpose: "evaluation",
    phase: "final",
    rows: [
      { ...q(1), split: "final", kb_ready: false, evaluation_ready: true },
      { ...q(2), split: "development", evaluation_ready: true },
      { ...q(3), split: "final", evaluation_ready: false },
      q(4),
    ],
  });
  await screen.findByLabelText("选择 q1");
  expect(
    screen.getByRole("heading", { name: "选择独立评测题目" }),
  ).toBeTruthy();
  expect(calls.find((c) => c.path.includes("questions?"))?.path).toContain(
    "split=final",
  );
  await waitFor(() =>
    expect(
      (screen.getByLabelText("选择 q1") as HTMLInputElement).disabled,
    ).toBe(false),
  );
  for (const id of [2, 3, 4])
    expect(
      (screen.getByLabelText(`选择 q${id}`) as HTMLInputElement).disabled,
    ).toBe(true);
  fireEvent.click(screen.getByLabelText("选择当前页"));
  fireEvent.click(screen.getByRole("button", { name: "应用所选题目" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledTimes(1));
  expect(onApply.mock.calls[0][0].keys).toEqual(["q1@rev"]);
});
it("preserves incompatible existing Task keys and blocks apply rather than changing their split", async () => {
  const { calls } = setup({
    purpose: "evaluation",
    phase: "development",
    setId: "existing",
    existing: {
      id: "existing",
      keys: ["q1@rev"],
      questions: [{ id: "q1@rev", split: "final", evaluation_ready: true }],
    },
    rows: [{ ...q(1), split: "final" }],
  });
  await screen.findByText(/已选 1 题/);
  expect(
    (screen.getByRole("button", { name: "应用所选题目" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect((screen.getByLabelText("选择 q1") as HTMLInputElement).checked).toBe(
    true,
  );
  expect(calls.some((c) => c.body)).toBe(false);
});

it("explains that an empty Task partition needs independent data instead of suggesting a broken search", async () => {
  setup({purpose:"evaluation",phase:"final",rows:[]});
  expect(await screen.findByText("这个独立评测分区还没有题目")).toBeTruthy();
  expect(screen.getByText(/请先在题库导入已划分为 final/)).toBeTruthy();
});

it("single mode replaces the earlier choice and freezes exactly one real key",async()=>{
 const {calls}=setup({single:true});
 fireEvent.click(await screen.findByLabelText('选择 q1'));
 fireEvent.click(screen.getByLabelText('选择 q2'));
 expect((screen.getByLabelText('选择 q1') as HTMLInputElement).checked).toBe(false);
 expect((screen.getByLabelText('选择 q2') as HTMLInputElement).checked).toBe(true);
 expect((screen.getByLabelText('选择当前页') as HTMLInputElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 await waitFor(()=>expect(calls.find(c=>c.path==='/api/studio/question-sets'&&c.body)?.body.keys).toEqual(['q2@rev']));
});

it('RAG accepts non-discovery public questions without GT and does not create a set',async()=>{
 const calls:string[]=[];const onSelectQuestion=vi.fn();
 vi.stubGlobal('fetch',async(path:string)=>{
  calls.push(path);
  if(path.includes('/questions?'))return response({items:[{...q(1),split:'final',ready:false,rag_ready:true}],total:1});
  return response({metadata:{key:'q1@rev',rag_ready:true},public:{id:'q1',family:'regression',prompt:'公开问题',choices:[{letter:'A',id:'a',view:{}},{letter:'B',id:'b',view:{}}]}});
 });
 render(<QuestionPicker version={0} act={async fn=>fn()} purpose="rag" single onSelectQuestion={onSelectQuestion} onClose={()=>{}}/>);
 fireEvent.click(await screen.findByLabelText('选择 q1'));fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 await waitFor(()=>expect(onSelectQuestion).toHaveBeenCalledWith('q1@rev'));
 expect(calls.some(p=>p.includes('split='))).toBe(false);expect(calls.some(p=>p.includes('/question-sets'))).toBe(false);
});

it('RAG validates old metadata from public detail before returning a question key',async()=>{
 const onSelectQuestion=vi.fn();let valid=false;
 vi.stubGlobal('fetch',async(path:string)=>path.includes('/questions?')?response({items:[{...q(1),ready:false,split:'development'}],total:1}):response({metadata:{key:'q1@rev'},public:{id:'q1',family:'regression',prompt:'public',choices:valid?[{letter:'A',id:'a',view:{}},{letter:'B',id:'b',view:{}}]:[]}}));
 render(<QuestionPicker version={0} act={async fn=>fn()} purpose="rag" single onSelectQuestion={onSelectQuestion} onClose={()=>{}}/>);
 fireEvent.click(await screen.findByLabelText('选择 q1'));fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 await screen.findByText('题目公开输入不可用');expect(onSelectQuestion).not.toHaveBeenCalled();valid=true;
 fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));await waitFor(()=>expect(onSelectQuestion).toHaveBeenCalledWith('q1@rev'));
});
