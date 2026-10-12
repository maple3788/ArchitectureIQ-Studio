import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { QuestionReader } from "./QuestionReader";
import { useLayoutEffect, useEffect } from "react";

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const candidateCard=(letter:string)=>within(screen.getByRole('group',{name:'候选参数对比'})).getByRole('article',{name:`候选 ${letter}`});
function parameterRow(letter:string,id:string){
  const row=Array.from(candidateCard(letter).querySelectorAll<HTMLDivElement>('.question-reader-option-row')).find(row=>row.dataset.parameter===id);
  expect(row,`候选 ${letter} 应展示参数 ${id}`).toBeTruthy();
  return row!;
}
const parameterValue=(letter:string,id:string)=>parameterRow(letter,id).querySelector('.parameter-value')?.textContent;
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

it('retains an immediate first tab selection instead of overwriting it in a delayed mount reset',()=>{
  function ImmediatelyReadPrompt(){
    // The controls are already committed. Select the tab at the earliest
    // possible interaction boundary, before passive effects are flushed.
    useLayoutEffect(()=>{screen.getByRole('tab',{name:'原始 Prompt'}).click();},[]);
    return <QuestionReader record={record}/>;
  }
  render(<ImmediatelyReadPrompt/>);
  expect(screen.getByRole('article',{name:'公开题面'}).textContent).toBe(record.detail.prompt);
});

it("compares effective candidate specs and highlights differences without assuming equal budgets", () => {
  render(<QuestionReader record={record}/>);
  expect(screen.getByRole("heading", {name:"选项"})).toBeTruthy();
  for(const letter of ['A','B']){
    const activation=parameterRow(letter,'model.activation');
    expect(activation.querySelector('.parameter-label')?.textContent).toBe('激活函数');
    expect(activation.classList.contains('is-different')).toBe(true);
    expect(parameterRow(letter,'model.width').classList.contains('is-different')).toBe(false);
    expect(parameterValue(letter,'model.width')).toBe('64');
    expect(parameterRow(letter,'budget.total_samples_seen').classList.contains('is-different')).toBe(true);
  }
  expect(['A','B'].map(letter=>parameterValue(letter,'model.activation'))).toEqual(['gelu','relu']);
  expect(['A','B'].map(letter=>parameterValue(letter,'budget.total_samples_seen'))).toEqual(['8192','4096']);
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
  expect(screen.getByRole("heading",{name:"future_family"})).toBeTruthy();
  expect(['W','X','Y','Z'].map(letter=>candidateCard(letter).getAttribute('aria-label'))).toEqual(['候选 W','候选 X','候选 Y','候选 Z']);
  expect(['W','X','Y','Z'].map(letter=>parameterValue(letter,'budget.total_samples_seen'))).toEqual(['100','200','未记录','未记录']);
  expect(screen.queryByText("训练集样本数")).toBeNull();
  fireEvent.click(screen.getByRole("tab",{name:"原始 Prompt"}));
  expect(screen.getByText("此记录未提供原始 Prompt。")).toBeTruthy();
});

it('explains recorded language-model training windows without inventing steps or dataset size',()=>{
 render(<QuestionReader record={{metadata:{family:'bigram_lm'},public:{choices:[
  {letter:'A',view:{model_type:'gru_lm',budget:16384}},
  {letter:'B',view:{model_type:'transformer_lm',budget:16384}},
 ]}}}/>);
 const note=screen.getByText(/重复使用同一窗口也重复计数/);
 expect(note.textContent).toContain('累计处理量 = 训练步数 × 每批数量');
 expect(note.textContent).toContain('不是训练集的去重大小');
 expect(screen.queryByText('训练集样本数')).toBeNull();
 expect(screen.getByRole('group',{name:'候选参数对比'}).querySelector('[data-parameter="budget.training_steps"]')).toBeNull();
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

it("keeps shared parameters alongside differences without a collapsed common-settings section",()=>{
  const a=choice("A","gelu",8192), b=choice("B","gelu",8192);
  Object.assign(b.files["candidate_spec.json"].model,a.files["candidate_spec.json"].model);
  b.files["candidate_spec.json"].optimizer.lr=0.01;
  render(<QuestionReader record={{detail:{choices:[a,b]}}}/>);
  expect(screen.getByRole("tab",{name:"题目概览"}).getAttribute("aria-selected")).toBe("true");
  for(const letter of ['A','B']){
    expect(parameterRow(letter,'optimizer.lr').querySelector('.parameter-label')?.textContent).toBe('学习率');
    expect(parameterRow(letter,'model.width').querySelector('.parameter-label')?.textContent).toBe('隐藏宽度');
    expect(parameterRow(letter,'model.width').closest('details')).toBeNull();
    expect(parameterRow(letter,'optimizer.lr').classList.contains('is-different')).toBe(true);
  }
  expect(screen.queryByText("共同设置")).toBeNull();
});

it("aligns public choices by candidate id when letters are absent and source order differs", () => {
  const first=choice("A","gelu",8192), second=choice("B","relu",4096);
  const {letter: _firstLetter,...a}=first, {letter: _secondLetter,...b}=second;
  render(<QuestionReader record={{detail:{choices:[b,a]},public:{choices:[{id:first.candidateId},{id:second.candidateId}]}}}/>);
  expect(['1','2'].map(letter=>parameterValue(letter,'model.activation'))).toEqual(['gelu','relu']);
});

it("preserves layer patterns, language model axes and explicit zero values in mixed comparisons", ()=>{
  const a=choice("A","leaky_relu",8192), b=choice("B","relu",4096);
  Object.assign(a.files["candidate_spec.json"].model,{layer_norm:[true,false,true],leaky_relu_slope:0.01,type:"gru_lm",layer_residual:false});
  Object.assign(b.files["candidate_spec.json"].model,{type:"transformer_lm",num_heads:4,d_ff:64});
  Object.assign(a.files["candidate_spec.json"].optimizer,{weight_decay:0,momentum:0});
  render(<QuestionReader record={{detail:{choices:[a,b]}}}/>);
  expect(parameterValue('A','model.layer_norm')).toBe('(yes, no, yes)');
  expect(parameterValue('A','model.leaky_relu_slope')).toBe('0.01');
  expect(parameterValue('A','model.layer_residual')).toBe('no');
  expect(parameterValue('B','model.num_heads')).toBe('4');
  expect(parameterValue('A','optimizer.weight_decay')).toBe('0');
  expect(parameterValue('A','optimizer.momentum')).toBe('0');
});

it('keeps two-layer switch tuples together and visible without expanding a configuration',()=>{
 const a=choice('A','gelu',8192),b=choice('B','gelu',8192);
 Object.assign(a.files['candidate_spec.json'].model,{depth:2,layer_norm:[true,false],layer_residual:[false,true]});
 Object.assign(b.files['candidate_spec.json'].model,{depth:2,layer_norm:[false,true],layer_residual:[false,true]});
 render(<QuestionReader record={{detail:{choices:[a,b]}}}/>);
 expect(parameterValue('A','model.layer_norm')).toBe('(yes, no)');
 expect(parameterValue('B','model.layer_norm')).toBe('(no, yes)');
 for(const letter of ['A','B']){
  expect(parameterValue(letter,'model.layer_residual')).toBe('(no, yes)');
  expect(parameterRow(letter,'model.layer_norm').classList.contains('is-different')).toBe(true);
  expect(parameterRow(letter,'model.layer_residual').classList.contains('is-different')).toBe(false);
  expect(parameterRow(letter,'model.layer_norm').closest('details')).toBeNull();
  expect(candidateCard(letter).querySelector('[data-parameter^="model.layer_norm["]')).toBeNull();
 }
});

it('compares every candidate immediately without answer selection or comparison checkboxes',()=>{
 const third=choice('C','tanh',2048);
 const value={...record,detail:{...record.detail,choices:[...record.detail.choices,third]}};
 const {rerender}=render(<QuestionReader record={value} interactive questionKey="q@v1"/>);
 const comparison=screen.getByRole('group',{name:'候选参数对比'});
 for(const letter of ['A','B','C'])expect(within(comparison).getByRole('article',{name:`候选 ${letter}`})).toBeTruthy();
 expect(screen.queryByRole('radio')).toBeNull();
 expect(screen.queryByRole('checkbox')).toBeNull();
 expect(comparison.textContent).toContain('tanh');
 expect(document.body.textContent).not.toMatch(/SECRET-WINNER|SECRET-METRIC|WRONG-SOURCE/);
 rerender(<QuestionReader record={value} interactive questionKey="q@v2"/>);
 expect(screen.getByRole('group',{name:'候选参数对比'})).toBeTruthy();
});

it('shows unknown nested public parameters, explicit empty values and missing values in the comparison',()=>{
 const a:any=choice('A','gelu',8192),b:any=choice('B','gelu',8192),c:any=choice('C','gelu',8192);
 for(const item of [a,b,c])Object.assign(item.files['candidate_spec.json'],{
  execution:{precision:'float32',scheduler:{phases:[{warmup:5},{decay:0.1}]}},
  future_config:{retained_zero:0,retained_false:false,empty_list:[],empty_object:{},retained_null:null},
  private_metrics:{correctLetter:'SECRET-CAMEL',seed_results:[{value:'SECRET-NESTED'}]},
 });
 b.files['candidate_spec.json'].execution.scheduler.phases[1].decay=0.2;
 delete c.files['candidate_spec.json'].future_config.retained_zero;
 delete c.files['candidate_spec.json'].future_config.retained_null;
 const {container}=render(<QuestionReader record={{detail:{choices:[a,b,c]}}}/>);
 expect(['A','B','C'].map(letter=>parameterValue(letter,'execution.scheduler.phases[1].decay'))).toEqual(['0.1','0.2','0.1']);
 expect(['A','B','C'].map(letter=>parameterValue(letter,'other.future_config.retained_zero'))).toEqual(['0','0','未记录']);
 expect(['A','B','C'].map(letter=>parameterValue(letter,'other.future_config.retained_null'))).toEqual(['null','null','未记录']);
 for(const letter of ['A','B','C']){
  expect(parameterValue(letter,'model.future_option')).toBe('retained-option');
  expect(parameterRow(letter,'execution.scheduler.phases[1].decay').classList.contains('is-different')).toBe(true);
  expect(parameterRow(letter,'other.future_config.retained_null').classList.contains('is-different')).toBe(true);
  expect(parameterValue(letter,'other.future_config.empty_list')).toBe('()');
  expect(parameterValue(letter,'other.future_config.empty_object')).toBe('{}');
  expect(parameterValue(letter,'other.future_config.retained_false')).toBe('no');
 }
 expect(container.textContent).not.toMatch(/SECRET-CAMEL|SECRET-NESTED/);
});

it('retains extra public-view fields without requiring a known feature label',()=>{
 render(<QuestionReader record={{public:{choices:[
  {id:'a',letter:'A',view:{model_type:'mlp',width:8,future_public_axis:3,custom:{shape:'linear'}}},
  {id:'b',letter:'B',view:{model_type:'mlp',width:16,future_public_axis:4,custom:{shape:'curved'}}},
 ]}}}/>);
 expect(['A','B'].map(letter=>parameterValue(letter,'other.future_public_axis'))).toEqual(['3','4']);
 expect(['A','B'].map(letter=>parameterValue(letter,'other.custom.shape'))).toEqual(['linear','curved']);
});

it('places supplied knowledge evidence immediately after the candidate comparison',()=>{
 render(<QuestionReader record={record} evidence={<section aria-label="本题知识依据">规则 C1 与真实反例</section>}/>);
 const comparison=screen.getByRole('group',{name:'候选参数对比'}),evidence=screen.getByRole('region',{name:'本题知识依据'});
 expect(comparison.compareDocumentPosition(evidence)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 const workspace=comparison.closest('.question-reader-comparison-workspace');
 expect(workspace?.contains(evidence)).toBe(true);
 expect(screen.getByRole('heading',{name:'数据与条件'}).compareDocumentPosition(comparison)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it('does not lose explicit empty sections or literal dotted keys when flattening candidate parameters',()=>{
 const a:any=choice('A','gelu',8192),b:any=choice('B','gelu',8192);
 a.files['candidate_spec.json'].execution={};
 for(const candidate of [a,b])candidate.files['candidate_spec.json'].future_config={'axis.width':7,axis:{width:9}};
 render(<QuestionReader record={{detail:{choices:[a,b]}}}/>);
 expect(['A','B'].map(letter=>parameterValue(letter,'other.future_config.axis\\.width'))).toEqual(['7','7']);
 expect(['A','B'].map(letter=>parameterValue(letter,'other.future_config.axis.width'))).toEqual(['9','9']);
 expect(['A','B'].map(letter=>parameterValue(letter,'execution.'))).toEqual(['{}','未记录']);
});


it('keeps human feedback and evidence unread until a choice has been committed, including after a question change',async()=>{
 const calls:string[]=[];
 const feedback={selected_answer:{id:'candidate-A',letter:'A'},correct_answer:{id:'candidate-B',letter:'B'},correct:false,feedback:{correct_letter:'B',reveal:{curves:[]}}};
 vi.stubGlobal('fetch',async(path:string)=>{calls.push(path);return new Response(JSON.stringify(path.endsWith('/review')?feedback:{}));});
 function Evidence(){useEffect(()=>{void fetch('/research-evidence');},[]);return <section aria-label="已提交后的知识证据">已有规则研究结果</section>;}
 const source={kind:'catalog' as const,key:'q@first'};
 const value={...record,public:{id:'q',choices:[{id:'candidate-A',letter:'A'},{id:'candidate-B',letter:'B'}]}};
 const view=render(<QuestionReader record={value} questionKey="q@first" reviewSource={source} evidence={<Evidence/>}/>);
 expect(calls.filter(path=>!path.endsWith('/applicable-knowledge'))).toEqual([]);expect(screen.queryByLabelText('已提交后的知识证据')).toBeNull();
 const practice=screen.getByRole('region',{name:'人工检查题目'}),data=screen.getByRole('heading',{name:'数据与条件'});
 expect(data.compareDocumentPosition(practice)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(screen.getByRole('radio',{name:'选择 A'}).closest('label')?.textContent).toContain('mlp');
 fireEvent.click(screen.getByRole('radio',{name:'选择 A'}));expect(calls.filter(path=>!path.endsWith('/applicable-knowledge'))).toEqual([]);
 fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 await screen.findByText('正确答案 B');
 await waitFor(()=>expect(calls.filter(path=>!path.endsWith('/applicable-knowledge'))).toEqual(['/api/studio/questions/review','/research-evidence']));
 expect(screen.getByLabelText('已提交后的知识证据')).toBeTruthy();
 fireEvent.click(screen.getByRole('tab',{name:'数据与规则'}));fireEvent.click(screen.getByRole('tab',{name:'题目概览'}));
 expect(screen.getByText('正确答案 B')).toBeTruthy();
 view.rerender(<QuestionReader record={value} questionKey="q@second" reviewSource={{kind:'catalog',key:'q@second'}} evidence={<Evidence/>}/>);
 expect(screen.queryByText('正确答案 B')).toBeNull();expect(screen.queryByLabelText('已提交后的知识证据')).toBeNull();
 expect(screen.getByRole('button',{name:'提交并查看结果'})).toBeTruthy();
});

it('presents the concrete problem and dataset conditions before selectable candidate configurations',()=>{
 const prompt='## Task\nPredict a scalar from five input features.\n\n## Choices\nCandidate configurations.';
 const value={...record,detail:{...record.detail,prompt},public:{id:'q',choices:[{id:'candidate-A',letter:'A'},{id:'candidate-B',letter:'B'}]}};
 render(<QuestionReader record={value} reviewSource={{kind:'catalog',key:'q@first'}}/>);
 const problem=screen.getByText(/^Predict a scalar from five input features\./);
 const data=screen.getByRole('heading',{name:'数据与条件'});
 const comparison=screen.getByRole('group',{name:'候选参数对比'});
 expect(problem.compareDocumentPosition(data)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(data.compareDocumentPosition(comparison)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(within(candidateCard('A')).getByRole('radio',{name:'选择 A'})).toBeTruthy();
 expect(screen.getAllByRole('radio')).toHaveLength(2);
 fireEvent.click(within(candidateCard('B')).getByRole('radio',{name:'选择 B'}));
 expect((screen.getByRole('button',{name:'提交并查看结果'}) as HTMLButtonElement).disabled).toBe(false);
 expect(document.querySelector('.human-practice-reveal')).toBeNull();
});
