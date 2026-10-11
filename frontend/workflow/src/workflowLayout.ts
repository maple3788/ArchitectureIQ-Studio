import type { Workflow } from './types';

// Display positions only: routes, role instructions and run settings keep their
// existing identity. Empty optional branch rows remain available when toggled.
const rows: Record<string, number> = {
  input: 0, solver: 1, commit: 2, reveal: 3, discoverer: 4, skeptic: 5,
  experiment: 6, confirmation: 7, analyst: 8, curator: 9, publish: 10,
  loop: 11, evaluate: 12, end: 13,
};
const main = ['input','solver','commit','reveal','discoverer','skeptic','experiment','analyst','curator','publish','loop','end'];
export const stageWidth = 236;

export function migrateWorkflowLayout(workflow: Workflow): Workflow {
  if (workflow.schema_version === 2) return workflow;
  const core = main.flatMap(id => {
    const node = workflow.nodes.find(n => n.id === id);
    return node ? [node] : [];
  });
  let horizontal = 0, vertical = 0;
  for (let i = 1; i < core.length; i++) {
    const dx = Math.abs(core[i].position.x - core[i - 1].position.x);
    const dy = Math.abs(core[i].position.y - core[i - 1].position.y);
    if (dx > dy) horizontal++;
    else if (dy > dx) vertical++;
  }
  // Preserve user-arranged vertical drafts, even when optional branches are wide.
  if (vertical > horizontal || core.length < 2) return workflow;
  return {
    ...workflow,
    nodes: workflow.nodes.map((node, index) => ({
      ...node,
      position: {
        x: node.id === 'confirmation' || node.id === 'evaluate' ? 354 : 54,
        y: 48 + (rows[node.id] ?? 14 + index) * 150,
      },
    })),
  };
}
