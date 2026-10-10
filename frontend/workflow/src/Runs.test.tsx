import { afterEach, it, expect, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { Runs } from "./Runs";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("uses a total evaluation token budget and requires a successful current preview", async () => {
  let previewRequest: any;
  const submissions: { body: any; headers: any }[] = [];
  let previewCount = 0;
  vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
    if (path === "/api/studio/models")
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "api",
              name: "API model",
              model: "request-id",
              enabled: true,
              health: { status: "reachable" },
              parameters: { max_tokens: 4096 },
            },
          ],
          total: 1,
        }),
      );
    if (path === "/api/studio/question-sets")
      return new Response(
        JSON.stringify({
          items: [{ id: "set1", name: "fixed set", count: 1 }],
          total: 1,
        }),
      );
    if (path === "/api/studio/runs/preview") {
      previewRequest = JSON.parse(init?.body as string);
      return new Response(
        JSON.stringify({
          config_hash: `frozen-${++previewCount}`,
          request_count: 1,
          reserved_tokens: 5000,
          requests: [
            {
              payload: {
                messages: [{ role: "user", content: "exact public prompt" }],
              },
            },
          ],
        }),
      );
    }
    if (path === "/api/studio/runs" && init?.method === "POST") {
      submissions.push({
        body: JSON.parse(init.body as string),
        headers: init.headers,
      });
      return new Response('{"id":"job1"}');
    }
    if (path === "/api/studio/runs/job1")
      return new Response(
        '{"id":"job1","status":"queued","kind":"evaluation"}',
      );
    return new Response('{"items":[],"total":0}');
  });
  render(
    <Runs
      initialSet="set1"
      version={0}
      act={async (op) => op()}
      executionEnabled
      onRun={() => {}}
    />,
  );
  const model = (await screen.findByLabelText(
    "被测模型 API model",
  )) as HTMLInputElement;
  expect(model.disabled).toBe(false);
  fireEvent.click(model);
  expect(
    (screen.getByLabelText("整次评测 token 总预算") as HTMLInputElement).value,
  ).toBe("2000000");
  const submit = screen.getByRole("button", {
    name: "提交模型评测",
  }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "完整输入预览" }));
  await waitFor(() => expect(screen.getByText(/reserved_tokens/)).toBeTruthy());
  expect(previewRequest.max_tokens).toBe(2000000);
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  expect(submit.disabled).toBe(false);
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0].body.expected_config_hash).toBe("frozen-1");
  expect(submissions[0].headers["Idempotency-Key"]).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "关闭详情" }));
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(2));
  expect(submissions[1].headers["Idempotency-Key"]).toBe(
    submissions[0].headers["Idempotency-Key"],
  );
  fireEvent.click(await screen.findByRole("button", { name: "关闭详情" }));
  fireEvent.click(screen.getByRole("button", { name: "完整输入预览" }));
  await waitFor(() => expect(screen.getByText(/frozen-2/)).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  fireEvent.click(submit);
  await waitFor(() => expect(submissions).toHaveLength(3));
  expect(submissions[2].body.expected_config_hash).toBe("frozen-2");
  expect(submissions[2].headers["Idempotency-Key"]).not.toBe(
    submissions[0].headers["Idempotency-Key"],
  );
  fireEvent.click(await screen.findByRole("button", { name: "关闭详情" }));
  fireEvent.change(screen.getByLabelText("整次评测 token 总预算"), {
    target: { value: "1000000" },
  });
  expect(submit.disabled).toBe(true);
});

it('filters RAG history and reopens details without submitting a job',async()=>{
 const calls:any[]=[];
 const run:any={id:'rag-one',kind:'rag',status:'complete',created_at:1,config:{name:'RAG 作答',question_key:'q1@rev',question:{prompt:'公开问题'},models:[{id:'glm',name:'GLM'}],retrieval:{selected_kb:{name:'知识库',version:'v'},provenance:[]}},result:{answer:{ranking:['A','B'],rationale:'历史解释',citations:[]},used_sources:[],unknown_citations:[]},records:[]};
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{calls.push(init?.method||'GET');return new Response(JSON.stringify(path==='/api/studio/runs'?{items:[run],total:1}:path.endsWith('/rag-one')?run:{items:[],total:0}));});
 render(<Runs version={0} act={async fn=>fn()} executionEnabled={false} onRun={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('运行类型筛选'),{target:{value:'rag'}});
 fireEvent.click(await screen.findByRole('button',{name:'查看运行 rag-one'}));expect(await screen.findByText('历史解释')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'关闭详情'}));fireEvent.click(screen.getByRole('button',{name:'查看运行 rag-one'}));await screen.findByText('历史解释');
 expect(calls.every(method=>method==='GET')).toBe(true);
});
