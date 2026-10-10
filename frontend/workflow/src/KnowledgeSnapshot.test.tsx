import { afterEach, it, expect } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  within,
} from "@testing-library/react";
import { KnowledgeSnapshot } from "./KnowledgeSnapshot";
afterEach(cleanup);
function show(scope: any, extras: any = {}) {
  render(
    <KnowledgeSnapshot
      snapshot={{
        version: "v1",
        claims: [
          {
            id: "K1",
            text: "候选条件",
            status: "proposed",
            enabled: false,
            evidence_ids: [],
            rule: { scope, ...extras },
          },
        ],
        evidence: [],
      }}
    />,
  );
  fireEvent.click(screen.getByText("适用于什么条件 · 证据"));
  return screen.getByRole("article");
}
it("reads a single predicate as one condition and retains false and zero literals", () => {
  const card = show(["target_oscillatory", "eq", false]);
  expect(within(card).getByText("目标是否振荡 等于 否")).toBeTruthy();
  cleanup();
  expect(
    within(show(["budget", "ge", 0])).getByText("训练样本预算 至少 0"),
  ).toBeTruthy();
});
it("preserves all/any/not logic and negative membership with control conditions", () => {
  const card = show(
    {
      all: [
        ["family", "eq", "regression"],
        {
          any: [
            ["depth", "lt", 4],
            ["width", "ge", 64],
          ],
        },
        { not: ["activation", "in", ["relu", "gelu"]] },
        ["model_type", "nin", ["transformer"]],
      ],
    },
    { same: ["opt_key", "loss_key", "batch_size"], differ: ["arch_key"] },
  );
  expect(
    within(card).getByText(
      /同时满足.*数据类型 等于 regression.*至少满足一项.*层数 小于 4.*宽度 至少 64.*不满足.*激活函数 属于 relu、gelu.*模型类型 不属于 transformer/,
    ),
  ).toBeTruthy();
  expect(
    within(card).getByText(/保持相同.*优化器配置.*损失函数配置.*批大小/),
  ).toBeTruthy();
  expect(within(card).getByText(/需要不同.*模型结构配置/)).toBeTruthy();
  expect(within(card).queryByText("未提供机器可检验的适用条件。")).toBeNull();
});
it("distinguishes missing scope from an existing condition that cannot be summarized", () => {
  const card = show({ unexpected: [["family", "eq", "regression"]] });
  expect(
    within(card).getByText(/已记录适用条件，简明视图暂不能解释/),
  ).toBeTruthy();
  expect(within(card).queryByText("未提供机器可检验的适用条件。")).toBeNull();
  cleanup();
  expect(
    within(show(undefined)).getByText(/未记录额外的题目条件/),
  ).toBeTruthy();
});
