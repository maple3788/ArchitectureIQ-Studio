import { afterEach, it, expect } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ResultSummary } from "./ResultSummary";
afterEach(cleanup);
it("renders backend model scores and resolves an output to its exact receipt", () => {
  let index = -1;
  const result = {
    scores: {
      m1: {
        correct: 1,
        total: 2,
        invalid: 1,
        pairwise_accuracy: null,
        pair_joint_correct: 0,
        pair_total: 1,
        covered_questions: 0,
      },
    },
    outputs: { m1: { q1: { ranking: ["B", "A"], valid: true } } },
    calls: 2,
    charged_tokens: 340,
    elapsed_seconds: 1.5,
  };
  const records = [
    {
      inputs: { model_id: "m1", question_key: "q1" },
      correct: false,
      status: "complete",
    },
  ];
  render(
    <ResultSummary
      result={result}
      records={records}
      onRecord={(i) => (index = i)}
    />,
  );
  expect(screen.getByText("1 / 2")).toBeTruthy();
  expect(screen.getByText("B → A")).toBeTruthy();
  expect(screen.getByText("错误")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看逐题收据 q1 m1" }));
  expect(index).toBe(0);
});
it("does not infer correctness when the server did not provide scoring", () => {
  render(
    <ResultSummary
      result={{ outputs: { m1: { q1: { ranking: ["A"], valid: true } } } }}
      records={[]}
    />,
  );
  expect(screen.getByText("未提供评分")).toBeTruthy();
});
