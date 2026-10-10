import { expect, it } from "vitest";
import {
  deriveRunWorkflow,
  parseSentContent,
  parseOutput,
} from "./runWorkflow";
import type { Run } from "./types";
const workflow = {
  schema_version: 1,
  name: "冻结图",
  settings: {},
  nodes: ["input", "solver", "discoverer", "end", "confirmation"].map(
    (id, index) => ({
      id,
      type: id === "solver" || id === "discoverer" ? "agent" : id,
      position: { x: 0, y: index * 100 },
      config: { role: id, prompt: "配置指导" },
    }),
  ),
  edges: [
    { id: "a", source: "input", target: "solver" },
    { id: "b", source: "solver", target: "discoverer" },
    { id: "c", source: "discoverer", target: "end" },
  ],
};
export const failedRun: Run = {
  id: "failed",
  kind: "workflow",
  status: "failed",
  created_at: 1,
  config: { workflow },
  error: "context budget",
  progress: { node_id: "discoverer", state: "running", round_index: 1 },
  events: [
    {
      type: "stage",
      node_id: "input",
      state: "complete",
      round_index: 1,
      time: 1,
    },
    {
      type: "stage",
      node_id: "solver",
      state: "running",
      round_index: 1,
      key: "q1",
      time: 2,
    },
    {
      type: "stage",
      node_id: "solver",
      state: "complete",
      round_index: 1,
      key: "q1",
      time: 4,
    },
    {
      type: "stage",
      node_id: "discoverer",
      state: "running",
      round_index: 1,
      key: "packet-0",
      time: 5,
    },
  ],
  records: [
    {
      inputs: { node_id: "solver" },
      sent_at: 3,
      actual_request: {
        payload: {
          messages: [
            {
              role: "user",
              content:
                'Protocol\n\nDATA:\n{"question":{"id":"q1","prompt":"Public question"},"knowledge":[],"enabled":false,"count":0}',
            },
          ],
        },
      },
      raw: {
        choices: [
          {
            message: { content: '{"ranking":["B","A"],"rationale":"because"}' },
            finish_reason: "stop",
          },
        ],
      },
      status: "complete",
    },
  ],
};
it("terminal failure overrides stale running progress without completing absent nodes", () => {
  const graph = deriveRunWorkflow(failedRun);
  expect(graph.nodes.find((n) => n.id === "discoverer")?.status).toBe("failed");
  expect(graph.nodes.find((n) => n.id === "solver")?.status).toBe("complete");
  expect(graph.nodes.find((n) => n.id === "end")?.status).toBe("not_run");
  expect(graph.nodes.find((n) => n.id === "confirmation")?.status).toBe(
    "skipped",
  );
  expect(
    graph.nodes.find((n) => n.id === "solver")?.invocations[0].records,
  ).toHaveLength(1);
});
it("keeps repeated questions and rounds separate and leaves undated wire receipts unbound", () => {
  const run = {
    ...failedRun,
    status: "running",
    progress: {},
    events: [
      ...failedRun.events!.slice(0, 3),
      {
        type: "stage",
        node_id: "solver",
        state: "running",
        round_index: 2,
        key: "q2",
        time: 8,
      },
    ],
    records: [
      ...failedRun.records!,
      {
        inputs: { node_id: "solver" },
        actual_request: { payload: { messages: [] } },
        status: "complete",
      },
    ],
  };
  const solver = deriveRunWorkflow(run).nodes.find((n) => n.id === "solver")!;
  expect(solver.invocations.map((i) => i.round)).toEqual([1, 2, undefined]);
  expect(solver.invocations.map((i) => i.status)).toEqual([
    "complete",
    "running",
    "unknown",
  ]);
  expect(solver.invocations[2].unbound).toBe(true);
});
it("does not convert stale running to complete merely because the job completed", () => {
  expect(
    deriveRunWorkflow({ ...failedRun, status: "complete" }).nodes.find(
      (n) => n.id === "discoverer",
    )?.status,
  ).toBe("unknown");
});
it("parses actual DATA safely and retains malformed content and false/zero", () => {
  const parsed = parseSentContent(
    'Instruction\n\nDATA:\n{"enabled":false,"count":0}',
  );
  expect(parsed.data).toEqual({ enabled: false, count: 0 });
  expect(parsed.instructions).toBe("Instruction");
  expect(
    parseSentContent("Instruction\n\nDATA:\nnot JSON").data,
  ).toBeUndefined();
  expect(parseSentContent("Instruction\n\nDATA:\nnot JSON").original).toContain(
    "not JSON",
  );
  expect(parseOutput('```json\n{"ranking":["B"]}\n```')).toEqual({
    ranking: ["B"],
  });
  expect(parseOutput("<script>unsafe</script>")).toBeUndefined();
});

it("uncertain terminal state stops active stages and ignores candidate inner completion", () => {
  const run = {
    ...failedRun,
    status: "uncertain",
    events: [
      ...failedRun.events!,
      {
        type: "stage",
        node_id: "end",
        state: "running",
        round_index: 1,
        time: 6,
      },
      {
        type: "stage",
        node_id: "experiment",
        state: "complete",
        candidate_id: "candidate",
        round_index: 1,
        time: 7,
      },
    ],
  };
  expect(
    deriveRunWorkflow(run).nodes.find((n) => n.id === "discoverer")?.status,
  ).toBe("uncertain");
});
it("does not mark a whole experimental step complete for one candidate", () => {
  const w = {
    ...workflow,
    nodes: [
      ...workflow.nodes,
      {
        id: "experiment",
        type: "experiment",
        position: { x: 0, y: 600 },
        config: {},
      },
    ],
    edges: [
      ...workflow.edges,
      { id: "d", source: "discoverer", target: "experiment" },
    ],
  };
  const graph = deriveRunWorkflow({
    ...failedRun,
    status: "running",
    config: { workflow: w },
    events: [
      {
        type: "stage",
        node_id: "experiment",
        state: "running",
        round_index: 1,
        key: "claim",
        time: 1,
      },
      {
        type: "stage",
        node_id: "experiment",
        state: "complete",
        round_index: 1,
        candidate_id: "candidate",
        time: 2,
      },
    ],
  });
  expect(graph.nodes.find((n) => n.id === "experiment")?.status).toBe(
    "running",
  );
});

it("binds same-round receipts only to a unique stage time interval", () => {
  const events = [
    {
      type: "stage",
      node_id: "solver",
      state: "running",
      round_index: 1,
      key: "q1",
      time: 1,
    },
    {
      type: "stage",
      node_id: "solver",
      state: "complete",
      round_index: 1,
      key: "q1",
      time: 3,
    },
    {
      type: "stage",
      node_id: "solver",
      state: "running",
      round_index: 1,
      key: "q2",
      time: 4,
    },
    {
      type: "stage",
      node_id: "solver",
      state: "complete",
      round_index: 1,
      key: "q2",
      time: 6,
    },
  ];
  const records = [
    {
      inputs: { node_id: "solver", round_index: 1 },
      sent_at: 5,
      status: "complete",
    },
    { inputs: { node_id: "solver" }, status: "complete" },
  ];
  const solver = deriveRunWorkflow({
    ...failedRun,
    status: "complete",
    progress: {},
    events,
    records,
  }).nodes.find((n) => n.id === "solver")!;
  expect(solver.invocations[0].records).toHaveLength(0);
  expect(solver.invocations[1].records).toHaveLength(1);
  expect(solver.invocations[2].unbound).toBe(true);
});
it("uses an exact sealed logical-prompt match only when unique and suppresses unavailable round zero", () => {
  const observation = {
    node_id: "solver",
    round_index: 1,
    key: "q1",
    input: { prompt: "exact input" },
    output: { result: { ranking: ["A"] } },
    availability: "available",
    source: ["calls/sealed.json"],
  };
  const graph = deriveRunWorkflow({
    ...failedRun,
    records: [
      {
        inputs: { node_id: "solver" },
        actual_request: {
          payload: { messages: [{ role: "user", content: "exact input" }] },
        },
        status: "complete",
      },
    ],
    node_observations: [
      observation,
      {
        node_id: "end",
        round_index: 0,
        availability: "unavailable",
        source: [],
      },
    ],
  });
  const solver = graph.nodes.find((n) => n.id === "solver")!;
  expect(solver.invocations).toHaveLength(1);
  expect(solver.invocations[0].records).toHaveLength(1);
  expect(solver.invocations[0].observation).toEqual(observation);
  expect(graph.rounds).toEqual([1]);
  expect(graph.nodes.find((n) => n.id === "end")?.status).toBe("not_run");
});

it('keeps distinct method steps separate when they share node, round and item identity', () => {
 const run:any={id:'r',status:'running',config:{workflow:{schema_version:1,name:'paired',settings:{},nodes:[{id:'discoverer',type:'agent',position:{x:0,y:0},config:{}}],edges:[]}},events:[{type:'stage',node_id:'discoverer',step_id:'pair_induction',round_index:1,key:'pair',state:'complete'},{type:'stage',node_id:'discoverer',step_id:'experience_consolidate',round_index:1,key:'pair',state:'running'}],records:[{node_id:'discoverer',inputs:{node_id:'discoverer',round_index:1,question_key:'pair',step_id:'pair_induction'},status:'complete'}]};
 const graph=deriveRunWorkflow(run);expect(graph.nodes[0].invocations).toHaveLength(2);expect(graph.nodes[0].invocations[0].status).toBe('complete');
});
it('binds sealed observations to explicit method steps sharing the same node and item',()=>{
 const graph=deriveRunWorkflow({id:'r',kind:'workflow',created_at:1,status:'complete',config:{workflow:{schema_version:1,name:'paired',settings:{},nodes:[{id:'discoverer',type:'agent',position:{x:0,y:0},config:{}}],edges:[]}},events:[{type:'stage',node_id:'discoverer',step_id:'pair_induction',round_index:1,key:'pair',state:'complete'},{type:'stage',node_id:'discoverer',step_id:'experience_consolidate',round_index:1,key:'pair',state:'complete'}],node_observations:[{node_id:'discoverer',step_id:'pair_induction',round_index:1,key:'pair',availability:'available',output:{text:'induction'}},{node_id:'discoverer',step_id:'experience_consolidate',round_index:1,key:'pair',availability:'available',output:{text:'memory'}}]});
 expect(graph.nodes[0].invocations).toHaveLength(2);expect(graph.nodes[0].invocations[0].observation?.output.text).toBe('induction');expect(graph.nodes[0].invocations[1].observation?.output.text).toBe('memory');
});
