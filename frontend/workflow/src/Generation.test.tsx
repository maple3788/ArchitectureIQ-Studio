import { afterEach, it, expect, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { Generation } from "./Generation";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const capabilities = {
  profiles: [
    {
      name: "v1.5",
      budgets: [64],
      n_seeds: 10,
      num_choices: 3,
      families: [
        {
          name: "test-family",
          model_types: ["mlp"],
          options: [],
          losses: ["mse"],
          config: {},
        },
      ],
      pools: { optimizers: ["adam"] },
    },
  ],
};
const act = async (operation: () => Promise<any>) => operation();
it("uses server preflight full batch cost and invalidates it when settings change", async () => {
  const requests: { path: string; body: any; headers: any }[] = [];
  vi.stubGlobal("fetch", async (path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : null;
    requests.push({ path, body, headers: init?.headers });
    if (path.endsWith("/runs")) return new Response('{"items":[],"total":0}');
    if (path.endsWith("/generations/preview"))
      return new Response(
        JSON.stringify({
          ...body,
          dataset_count: 3,
          candidate_seed_runs: 180,
          total_samples_seen: 11520,
          profile_hash: "verified-profile-hash",
          dataset_plan: [
            { seed: 1, num_questions: 1 },
            { seed: 2, num_questions: 1 },
            { seed: 3, num_questions: 1 },
          ],
        }),
      );
    return new Response('{"id":"new-generation"}');
  });
  let runId = "";
  render(
    <Generation
      capabilities={capabilities}
      version={0}
      act={act}
      executionEnabled
      onRun={(id) => (runId = id)}
    />,
  );
  const submit = screen.getByRole("button", {
    name: "提交生成任务",
  }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "冻结 spec 预览" }));
  await waitFor(() => expect(screen.getByText("180")).toBeTruthy());
  expect(
    requests.some((r) => r.path === "/api/studio/generations/preview"),
  ).toBe(true);
  expect(screen.getByText("3 个数据实例")).toBeTruthy();
  expect(screen.getByText("11,520")).toBeTruthy();
  expect(submit.disabled).toBe(false);
  fireEvent.click(submit);
  await waitFor(() => expect(runId).toBe("new-generation"));
  expect(
    requests.find((r) => r.path === "/api/studio/generations")?.body,
  ).toMatchObject({
    dataset_count: 3,
    candidate_seed_runs: 180,
    profile_hash: "verified-profile-hash",
  });
  const firstKey = requests.find((r) => r.path === "/api/studio/generations")
    ?.headers["Idempotency-Key"];
  expect(firstKey).toBeTruthy();
  fireEvent.click(submit);
  await waitFor(() =>
    expect(
      requests.filter((r) => r.path === "/api/studio/generations"),
    ).toHaveLength(2),
  );
  expect(
    requests.filter((r) => r.path === "/api/studio/generations")[1].headers[
      "Idempotency-Key"
    ],
  ).toBe(firstKey);
  fireEvent.click(screen.getByRole("button", { name: "冻结 spec 预览" }));
  await waitFor(() => expect(submit.disabled).toBe(false));
  fireEvent.click(submit);
  await waitFor(() =>
    expect(
      requests.filter((r) => r.path === "/api/studio/generations"),
    ).toHaveLength(3),
  );
  expect(
    requests.filter((r) => r.path === "/api/studio/generations")[2].headers[
      "Idempotency-Key"
    ],
  ).not.toBe(firstKey);
  fireEvent.change(screen.getByLabelText("请求题目数量"), {
    target: { value: "4" },
  });
  await waitFor(() => expect(submit.disabled).toBe(true));
});
it("prefers available v1.5 once and preserves a later user Profile choice on refresh", async () => {
  vi.stubGlobal("fetch", async () => new Response('{"items":[],"total":0}'));
  const current = capabilities.profiles[0];
  const other = { ...current, name: "v0" };
  const data = { profiles: [other, current] };
  const view = render(
    <Generation
      capabilities={data}
      version={0}
      act={act}
      executionEnabled
      onRun={() => {}}
    />,
  );
  await waitFor(() =>
    expect((screen.getByLabelText("Profile") as HTMLSelectElement).value).toBe(
      "v1.5",
    ),
  );
  fireEvent.change(screen.getByLabelText("Profile"), {
    target: { value: "v0" },
  });
  view.rerender(
    <Generation
      capabilities={{ profiles: [{ ...other }, { ...current }] }}
      version={1}
      act={act}
      executionEnabled
      onRun={() => {}}
    />,
  );
  expect((screen.getByLabelText("Profile") as HTMLSelectElement).value).toBe(
    "v0",
  );
});
it('freezes controlled pair settings and invalidates preflight on factor changes', async()=>{
 const bodies:any[]=[];
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
  if(path.endsWith('/runs'))return new Response('{"items":[],"total":0}');
  const body=JSON.parse(String(init?.body));bodies.push(body);return new Response(JSON.stringify({...body,pair_count:3,requested_question_count:6,dataset_count:6,candidate_seed_runs:36}));
 });
 const cap=structuredClone(capabilities) as any;
 cap.profiles[0].families[0].data_interventions=[{factor:'alpha',type:'number',original_value:1,counterfactual_value:2}];
 render(<Generation capabilities={cap} version={0} act={act} executionEnabled onRun={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('生成单位'),{target:{value:'paired'}});
 fireEvent.change(screen.getByLabelText('题目用途'),{target:{value:'final'}});
 fireEvent.click(screen.getByRole('button',{name:'冻结 spec 预览'}));
 await waitFor(()=>expect(bodies.length).toBe(1));
 expect(bodies[0]).toMatchObject({mode:'paired',split:'final',intervention:{factor:'alpha',original_value:1,counterfactual_value:2}});
 const submit=screen.getByRole('button',{name:'提交生成任务'}) as HTMLButtonElement;
 await waitFor(()=>expect(submit.disabled).toBe(false));
 fireEvent.change(screen.getByLabelText('DataFlip 因素值'),{target:{value:'3'}});
 expect(submit.disabled).toBe(true);
});
