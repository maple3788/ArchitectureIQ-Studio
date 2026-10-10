import { it, expect } from "vitest";
import { runProgress } from "./progress";
it("shows completed evaluation work separately from a zero accuracy score", () => {
  expect(
    runProgress({
      kind: "evaluation",
      status: "complete",
      progress: { completed: 0, total: 1 },
      result: { calls: 1, scores: { model: { correct: 0, total: 1 } } },
    }),
  ).toEqual({ completed: 1, total: 1 });
});
it("retains incomplete evaluation and other workflow progress", () => {
  expect(
    runProgress({
      kind: "evaluation",
      status: "running",
      progress: { completed: 0, total: 1 },
    }),
  ).toEqual({ completed: 0, total: 1 });
  expect(
    runProgress({
      kind: "workflow",
      status: "complete",
      progress: { completed: 0, total: 1 },
    }),
  ).toEqual({ completed: 0, total: 1 });
});
it("uses actual calls when an old completed evaluation has no progress total", () => {
  expect(
    runProgress({
      kind: "evaluation",
      status: "complete",
      result: { calls: 3 },
    }),
  ).toEqual({ completed: 3, total: 3 });
});
