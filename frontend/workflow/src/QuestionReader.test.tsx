import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QuestionReader } from "./QuestionReader";

afterEach(cleanup);
const choice = (letter: string, activation: string, budget: number) => ({
  letter,
  candidateId: `candidate-${letter}`,
  files: {
    "candidate_spec.json": {
      model: { type: "mlp", width: 64, activation, residual: letter === "A", future_option: "retained-option" },
      optimizer: { type: "AdamW", lr: 0.001 },
      loss: { loss_id: "cross_entropy" },
      budget: { total_samples_seen: budget, batch_size: 32, training_steps: budget / 32 },
      correct_letter: "SECRET-WINNER",
      results: { test_ce: "SECRET-METRIC" },
    },
    "model.py": '<script>alert("unsafe")</script>\nclass Model: pass',
    "results/summary.json": { final_test_ce: "SECRET-SUMMARY" },
  },
  provenance: { source_candidate_spec: { model: { activation: "WRONG-SOURCE" } } },
});
const record = {
  metadata: { family: "spiral_classification", type: "architecture_only", correct_letter: "SECRET-WINNER" },
  detail: {
    dataset: { params: { input_dim: 2, train_size: 1024, test_size: 2048 }, selectionMetric: "test_ce" },
    choices: [choice("A", "gelu", 8192), choice("B", "relu", 4096)],
    prompt: 'Exact\n\n<answer>A</answer>\n<script>not executed</script>',
  },
};

it("compares effective candidate specs and highlights differences without assuming equal budgets", () => {
  render(<QuestionReader record={record}/>);
  expect(screen.getByRole("heading", {name:"候选对比"})).toBeTruthy();
  const activation = screen.getByText("激活函数").closest("tr")!;
  expect(activation.classList.contains("is-different")).toBe(true);
  expect(activation.textContent).toContain("gelu");
  expect(activation.textContent).toContain("relu");
  const width = screen.getByText("隐藏宽度").closest("tr")!;
  expect(width.classList.contains("is-different")).toBe(false);
  const budget = screen.getByText("总训练样本量").closest("tr")!;
  expect(budget.classList.contains("is-different")).toBe(true);
  expect(budget.textContent).toContain("8192");
  expect(budget.textContent).toContain("4096");
  expect(screen.queryByText(/WRONG-SOURCE/)).toBeNull();
});

it("keeps code collapsed, escapes HTML, and provides the exact original prompt separately", () => {
  const {container} = render(<QuestionReader record={record}/>);
  const code = screen.getByText("A · model.py").closest("details")!;
  expect(code.open).toBe(false);
  expect(container.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("tab", {name:"原始 Prompt"}));
  expect(screen.getByTestId("original-prompt").textContent).toBe(record.detail.prompt);
  expect(container.querySelector("script")).toBeNull();
});

it("retains unknown public options in full configuration while excluding GT and source specs", () => {
  const {container} = render(<QuestionReader record={record}/>);
  expect(screen.getAllByText(/retained-option/).length).toBeGreaterThan(0);
  expect(container.textContent).not.toMatch(/SECRET-WINNER|SECRET-METRIC|SECRET-SUMMARY|WRONG-SOURCE/);
});

it("uses public views when files are unavailable, supports arbitrary choices, and leaves missing facts unspecified", () => {
  render(<QuestionReader record={{metadata:{family:"future_family"},public:{choices:[
    {letter:"W",view:{model_type:"custom-model",width:12,budget:100}},
    {letter:"X",view:{model_type:"custom-model",width:24,budget:200}},
    {letter:"Y",view:{model_type:"custom-model",width:48}},
    {letter:"Z",view:{model_type:"custom-model",width:96}},
  ]}}}/>);
  expect(screen.getByText("future_family")).toBeTruthy();
  expect(within(screen.getByRole("table",{name:"候选差异"})).getByRole("columnheader",{name:"候选 Z"})).toBeTruthy();
  expect(screen.getByText("总训练样本量").closest("tr")!.textContent).toContain("未记录");
  expect(screen.queryByText("训练集样本数")).toBeNull();
  fireEvent.click(screen.getByRole("tab",{name:"原始 Prompt"}));
  expect(screen.getByText("此记录未提供原始 Prompt。")).toBeTruthy();
});

it("opens complete authoritative dataset rules from the overview with safe formatting", () => {
  const prompt = '## Dataset\nA classification problem.\n\n### Data-generating and classification rule\n- Score: `s(x) = 0.8*x_0 - 0.4*x_1`.\n- Threshold: **0.25**; balance: 50%.\n- <img src=x onerror=alert(1)>\n\n### Synthesis (PyTorch)\n```python\nprint("exact code")\n```\n\n## Choices\nSECRET-AFTER-DATASET';
  const {container} = render(<QuestionReader record={{...record,detail:{...record.detail,prompt}}}/>);
  fireEvent.click(screen.getByRole("button",{name:"查看完整数据规则"}));
  expect(screen.getByText('s(x) = 0.8*x_0 - 0.4*x_1')).toBeTruthy();
  expect(screen.getByText('0.25')).toBeTruthy();
  expect(container.textContent).toContain('balance: 50%');
  expect(container.textContent).not.toContain('SECRET-AFTER-DATASET');
  expect(container.querySelector('img')).toBeNull();
  expect(screen.getByText('数据说明中的代码').closest('details')!.open).toBe(false);
});

it("shows optimizer differences first when model settings are shared, with common settings collapsed",()=>{
  const a=choice("A","gelu",8192), b=choice("B","gelu",8192);
  Object.assign(b.files["candidate_spec.json"].model,a.files["candidate_spec.json"].model);
  b.files["candidate_spec.json"].optimizer.lr=0.01;
  render(<QuestionReader record={{detail:{choices:[a,b]}}}/>);
  expect(screen.getByRole("tab",{name:"题目概览"}).getAttribute("aria-selected")).toBe("true");
  const table=screen.getByRole("table",{name:"候选差异"});
  expect(table.querySelector("tbody tr")!.textContent).toContain("学习率");
  expect(table.textContent).not.toContain("隐藏宽度");
  const common=screen.getByText("共同设置").closest("details")!;
  expect(common.open).toBe(false);
  expect(common.textContent).toContain("隐藏宽度");
});

it("aligns public choices by candidate id when letters are absent and source order differs", () => {
  const first=choice("A","gelu",8192), second=choice("B","relu",4096);
  const {letter: _firstLetter,...a}=first, {letter: _secondLetter,...b}=second;
  render(<QuestionReader record={{detail:{choices:[b,a]},public:{choices:[{id:first.candidateId},{id:second.candidateId}]}}}/>);
  const row=screen.getByText("激活函数").closest("tr")!;
  expect(Array.from(row.querySelectorAll("td")).map(cell=>cell.textContent)).toEqual(["gelu","relu"]);
});

it("preserves layer patterns, language model axes and explicit zero values in mixed comparisons", ()=>{
  const a=choice("A","leaky_relu",8192), b=choice("B","relu",4096);
  Object.assign(a.files["candidate_spec.json"].model,{layer_norm:[true,false,true],leaky_relu_slope:0.01,type:"gru_lm",layer_residual:false});
  Object.assign(b.files["candidate_spec.json"].model,{type:"transformer_lm",num_heads:4,d_ff:64});
  Object.assign(a.files["candidate_spec.json"].optimizer,{weight_decay:0,momentum:0});
  render(<QuestionReader record={{detail:{choices:[a,b]}}}/>);
  expect(screen.getByText("逐层归一化").closest("tr")!.textContent).toContain("开启 / 关闭 / 开启");
  expect(screen.getByText("Leaky ReLU 负半轴斜率").closest("tr")!.textContent).toContain("0.01");
  expect(screen.getByText("逐层残差").closest("tr")!.textContent).toContain("关闭");
  expect(screen.getByText("注意力头数").closest("tr")!.textContent).toContain("4");
  expect(screen.getByText("权重衰减").closest("tr")!.querySelector("td")!.textContent).toBe("0");
  expect(screen.getByText("动量").closest("tr")!.querySelector("td")!.textContent).toBe("0");
});

it('selects and compares candidates locally, supports keyboard movement and resets for a new exact question',()=>{
 const network=vi.fn();vi.stubGlobal('fetch',network);
 const third=choice('C','tanh',2048);
 const value={...record,detail:{...record.detail,choices:[...record.detail.choices,third]}};
 const {rerender}=render(<QuestionReader record={value} interactive questionKey="q@v1"/>);
 fireEvent.click(screen.getByRole('radio',{name:'候选 A'}));
 fireEvent.keyDown(screen.getByRole('radio',{name:'候选 A'}),{key:'ArrowRight'});
 expect((screen.getByRole('radio',{name:'候选 B'}) as HTMLInputElement).checked).toBe(true);
 fireEvent.click(screen.getByRole('checkbox',{name:'对比候选 A'}));fireEvent.click(screen.getByRole('checkbox',{name:'对比候选 C'}));
 const comparison=screen.getByRole('table',{name:'候选差异'});
 expect(within(comparison).queryByRole('columnheader',{name:'候选 B'})).toBeNull();
 expect(comparison.textContent).toContain('tanh');expect(network).not.toHaveBeenCalled();
 expect(document.body.textContent).not.toMatch(/SECRET-WINNER|SECRET-METRIC|WRONG-SOURCE/);
 rerender(<QuestionReader record={value} interactive questionKey="q@v2"/>);
 expect(screen.getAllByRole('radio').some(input=>(input as HTMLInputElement).checked)).toBe(false);
 vi.unstubAllGlobals();
});
