import { describe, it, expect } from "vitest";
import {
  toggleKeys,
  parseWorkflow,
  serializeWorkflow,
  updatePrompt,
  evaluationRequest,
} from "./state";
const workflow = {
  schema_version: 1,
  name: "研究",
  nodes: [
    {
      id: "solver",
      type: "agent",
      label: "Solver",
      position: { x: 10, y: 20 },
      config: { role: "solver", prompt: "完整指令" },
    },
  ],
  edges: [
    {
      id: "e",
      source: "input",
      target: "solver",
      source_handle: "out",
      target_handle: "in",
      mapping: {},
      condition: "always",
    },
  ],
  settings: { kb_path: "/server/kb", model_id: "m1" },
};
describe("frozen selection", () => {
  it("retains selected keys from earlier pages and removes only requested keys", () => {
    expect(toggleKeys(["page1", "page2"], ["page3"], true)).toEqual([
      "page1",
      "page2",
      "page3",
    ]);
    expect(toggleKeys(["page1", "page2", "page3"], ["page2"], false)).toEqual([
      "page1",
      "page3",
    ]);
  });
  it("deduplicates keys without changing the chosen order", () =>
    expect(toggleKeys(["a"], ["b", "a", "b"], true)).toEqual(["a", "b"]));
});
describe("workflow draft", () => {
  it("preserves full prompt, coordinates, mapping and server paths through export/import", () =>
    expect(parseWorkflow(serializeWorkflow(workflow))).toEqual(workflow));
  it("rejects an unrelated JSON file", () =>
    expect(() => parseWorkflow('{"items":[]}')).toThrow());
  it("changes only selected agent instructions", () => {
    const next = updatePrompt(workflow, "solver", "新指令");
    expect(next.nodes[0].config.prompt).toBe("新指令");
    expect(workflow.nodes[0].config.prompt).toBe("完整指令");
    expect(next.settings).toEqual(workflow.settings);
  });
});
describe("evaluation submission", () => {
  it("keeps model multi-selection and the exact edited prompt", () =>
    expect(
      evaluationRequest("set1", ["m1", "m2"], "  完整 prompt\n", 10, 2048),
    ).toEqual({
      kind: "evaluation",
      question_set_id: "set1",
      model_ids: ["m1", "m2"],
      prompt: "  完整 prompt\n",
      max_calls: 10,
      max_tokens: 2048,
    }));
  it("blocks evaluation without a fixed set or selected model", () => {
    expect(() => evaluationRequest("", ["m1"], "", 10, 100)).toThrow();
    expect(() => evaluationRequest("set", [], "", 10, 100)).toThrow();
  });
});
import { modelReady, setOptionalRoute } from "./state";
describe("verified service selection", () => {
  it("does not mark an absent or merely enabled model runnable", () => {
    expect(modelReady(undefined)).toBe(false);
    expect(modelReady({ enabled: true, health: { status: "unchecked" } })).toBe(
      false,
    );
  });
  it("requires an enabled verified identity", () => {
    expect(modelReady({ enabled: true, health: { status: "verified" } })).toBe(
      true,
    );
    expect(modelReady({ enabled: false, health: { verified: true } })).toBe(
      false,
    );
  });
});
describe("optional scientific routes", () => {
  const source = {
    ...workflow,
    edges: [
      {
        id: "explore-analyze",
        source: "experiment",
        target: "analyst",
        source_handle: "out",
        target_handle: "in",
        condition: "always",
        mapping: {},
      },
      {
        id: "loop-end",
        source: "loop",
        target: "end",
        source_handle: "out",
        target_handle: "in",
        condition: "done",
        mapping: {},
      },
    ],
    settings: {
      enable_confirmation: false,
      n_seeds: 2,
      max_candidate_seed_runs: 40,
      confirmation_count: 48,
    },
  };
  it("enables independent confirmation with protocol requirements and preserves unrelated routes", () => {
    const next = setOptionalRoute(source, "confirmation", true);
    expect(next.edges.map((e) => [e.source, e.target])).toEqual([
      ["loop", "end"],
      ["experiment", "confirmation"],
      ["confirmation", "analyst"],
    ]);
    expect(next.settings).toMatchObject({
      enable_confirmation: true,
      n_seeds: 10,
      confirmation_count: 48,
      max_candidate_seed_runs: 1600,
    });
    expect(source.settings.n_seeds).toBe(2);
  });
  it("bypasses confirmation without discarding an edited training budget", () => {
    const enabled = setOptionalRoute(source, "confirmation", true);
    enabled.settings.max_candidate_seed_runs = 1900;
    const next = setOptionalRoute(enabled, "confirmation", false);
    expect(next.settings).toMatchObject({
      enable_confirmation: false,
      max_candidate_seed_runs: 1900,
    });
    expect(
      next.edges.some(
        (e) => e.source === "experiment" && e.target === "analyst",
      ),
    ).toBe(true);
  });
  it("routes a done round through evaluation and does not change round continuation", () => {
    const next = setOptionalRoute(source, "evaluation", true);
    expect(next.edges.map((e) => [e.source, e.target, e.condition])).toEqual([
      ["experiment", "analyst", "always"],
      ["loop", "evaluate", "done"],
      ["evaluate", "end", "always"],
    ]);
    expect(next.settings.enable_evaluation).toBe(true);
  });
});
describe("import shape safety", () => {
  it("rejects nodes that cannot be drawn rather than crashing the canvas", () => {
    expect(() =>
      parseWorkflow(
        JSON.stringify({
          ...workflow,
          nodes: [
            { id: "solver", type: "agent", config: null, position: { x: 10 } },
          ],
        }),
      ),
    ).toThrow("节点");
  });
  it("rejects array settings and non-object edge records", () => {
    expect(() =>
      parseWorkflow(JSON.stringify({ ...workflow, settings: [] })),
    ).toThrow();
    expect(() =>
      parseWorkflow(JSON.stringify({ ...workflow, edges: [null] })),
    ).toThrow("连线");
  });
});

it("allows reachable API services for independent evaluation but requires attestation for KB research", () => {
  const reachable = { enabled: true, health: { status: "reachable" } };
  expect(modelReady(reachable)).toBe(true);
  expect(modelReady(reachable, true)).toBe(false);
  expect(
    modelReady({ enabled: true, health: { status: "verified" } }, true),
  ).toBe(true);
});
