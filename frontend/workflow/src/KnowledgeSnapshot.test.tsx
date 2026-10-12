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

it('groups source clauses into one claim without losing per-clause status and evidence',()=>{
 render(<KnowledgeSnapshot snapshot={{version:'v1',claims:[
  {id:'K1.clause-1',source_claim_id:'K1',text:'同一原始主张',status:'replicated_in_scope',enabled:true,evidence_ids:['e1'],rule:{scope:['width','ge',64]}},
  {id:'K1.clause-2',source_claim_id:'K1',text:'同一原始主张',status:'refuted',enabled:false,evidence_ids:['e2'],rule:{scope:['depth','lt',4]}},
  {id:'K2',text:'相同编号以外的独立主张',status:'proposed',enabled:false,evidence_ids:[]}
 ],evidence:[{id:'e1',outcome:'support'},{id:'e2',outcome:'refute'}]}}/>);
 expect(screen.getAllByRole('article')).toHaveLength(2);
 expect(screen.getAllByText('同一原始主张',{exact:true})).toHaveLength(1);
 expect(screen.getByText('2 条知识 · 3 个规则子项')).toBeTruthy();
 expect(screen.getByText('已在记录范围内验证')).toBeTruthy();
 expect(screen.getByText('已被反驳')).toBeTruthy();
 const first=screen.getAllByRole('article')[0];
 for(const summary of within(first).getAllByText('适用于什么条件 · 证据'))fireEvent.click(summary);
 expect(within(first).getByText('宽度 至少 64')).toBeTruthy();
 expect(within(first).getByText('层数 小于 4')).toBeTruthy();
 expect(within(first).getByText(/支持 1 · 反驳 0/)).toBeTruthy();
 expect(within(first).getByText(/支持 0 · 反驳 1/)).toBeTruthy();
});
it('keeps other clause statuses visible when a grouped claim matches a filter',()=>{
 render(<KnowledgeSnapshot snapshot={{claims:[
  {id:'K1-a',source_claim_id:'K1',text:'共有正文',status:'replicated_in_scope',enabled:true},
  {id:'K1-b',source_claim_id:'K1',text:'另一个分支解释',status:'refuted',enabled:false},
  {id:'K2',text:'无关待验证主张',status:'proposed',enabled:false}
 ]}}/>);
 fireEvent.change(screen.getByRole('combobox',{name:'知识使用状态'}),{target:{value:'usable'}});
 expect(screen.getAllByRole('article')).toHaveLength(1);
 expect(screen.getByText('共有正文')).toBeTruthy();
 expect(screen.getByText('另一个分支解释')).toBeTruthy();
 expect(screen.getByText('已被反驳')).toBeTruthy();
 expect(screen.queryByText('无关待验证主张')).toBeNull();
});
