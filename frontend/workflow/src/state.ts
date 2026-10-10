import type { Workflow } from "./types";
export function toggleKeys(keys: string[], page: string[], checked: boolean) {
  return checked
    ? [...new Set([...keys, ...page])]
    : keys.filter((key) => !page.includes(key));
}
export function parseWorkflow(text: string): Workflow {
  const value = JSON.parse(text);
  if (
    value?.schema_version !== 1 ||
    typeof value.name !== "string" ||
    !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges) ||
    !value.settings ||
    typeof value.settings !== "object" ||
    Array.isArray(value.settings)
  )
    throw new Error("请选择 schema_version: 1 的 Workflow JSON。");
  if (
    !value.nodes.every(
      (node: any) =>
        node &&
        typeof node.id === "string" &&
        typeof node.type === "string" &&
        node.position &&
        Number.isFinite(node.position.x) &&
        Number.isFinite(node.position.y) &&
        node.config &&
        typeof node.config === "object" &&
        !Array.isArray(node.config),
    )
  )
    throw new Error("节点缺少合法的 ID、类型、位置或配置。");
  if (
    !value.edges.every(
      (edge: any) =>
        edge &&
        typeof edge.id === "string" &&
        typeof edge.source === "string" &&
        typeof edge.target === "string",
    )
  )
    throw new Error("连线缺少合法的 ID 或端点。");
  return value;
}
export function serializeWorkflow(value: unknown) {
  return JSON.stringify(value, null, 2);
}
export function updatePrompt<
  T extends { nodes: { id: string; config: Record<string, any> }[] },
>(value: T, id: string, prompt: string): T {
  return {
    ...value,
    nodes: value.nodes.map((node) =>
      node.id === id ? { ...node, config: { ...node.config, prompt } } : node,
    ),
  };
}
export function evaluationRequest(
  set: string,
  models: string[],
  prompt: string,
  calls: number,
  tokens: number,
) {
  if (!set || !models.length)
    throw new Error("请选择冻结题集和至少一个被测 LLM。");
  if (calls < 1 || tokens < 1) throw new Error("调用与 token 预算必须大于 0。");
  return {
    kind: "evaluation" as const,
    question_set_id: set,
    model_ids: [...models],
    prompt,
    max_calls: calls,
    max_tokens: tokens,
  };
}
export function modelReady(model: any, requireAttested = false) {
  return (
    !!model &&
    model.enabled !== false &&
    (model.health?.status === "verified" ||
      model.health?.verified === true ||
      (!requireAttested && model.health?.status === "reachable"))
  );
}
export function workflowModelReady(model: any, methodId?: string) {
  return modelReady(model, !(methodId === "basic_learning" && model?.connection_type === "api"));
}
export const draftKey = "architectureiq-studio-workflow-v1";

export function setOptionalRoute<
  T extends { edges: Workflow["edges"]; settings: Record<string, any> },
>(
  value: T,
  route: "confirmation" | "evaluation",
  enabled: boolean,
): T & { settings: Record<string, any> } {
  const edge = (source: string, target: string, condition = "always") => ({
    id: source + "-" + target,
    source,
    target,
    source_handle: "out",
    target_handle: "in",
    mapping: {},
    condition,
  });
  const excluded =
    route === "confirmation"
      ? new Set(["experiment", "confirmation"])
      : new Set(["evaluate"]);
  const edges = value.edges.filter(
    (e) =>
      !excluded.has(e.source) &&
      !(
        route === "evaluation" &&
        e.source === "loop" &&
        e.condition === "done"
      ),
  );
  edges.push(
    ...(route === "confirmation"
      ? enabled
        ? [edge("experiment", "confirmation"), edge("confirmation", "analyst")]
        : [edge("experiment", "analyst")]
      : enabled
        ? [edge("loop", "evaluate", "done"), edge("evaluate", "end")]
        : [edge("loop", "end", "done")]),
  );
  const settings = {
    ...value.settings,
    [route === "confirmation" ? "enable_confirmation" : "enable_evaluation"]:
      enabled,
  };
  if (route === "confirmation" && enabled)
    Object.assign(settings, {
      n_seeds: 10,
      confirmation_count: 48,
      max_candidate_seed_runs: Math.max(
        Number(settings.max_candidate_seed_runs) || 0,
        1600,
      ),
    });
  return { ...value, edges, settings };
}
