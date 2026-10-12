import { useLayoutEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import { HumanQuestionPractice, type HumanReviewSource } from "./HumanQuestionPractice";
import { candidateListSummary } from "./displayNames";
import type { Json } from "./types";
import "./question-reader.css";

const labels: Record<string, string> = {
  type: "模型类型", model_type: "模型类型", depth: "隐藏层深度", width: "隐藏宽度",
  input_dim: "输入维度", output_dim: "输出维度", activation: "激活函数",
  residual: "残差连接", layer_norm: "逐层归一化", layer_residual: "逐层残差", leaky_relu_slope: "Leaky ReLU 负半轴斜率",
  num_layers: "层数", num_heads: "注意力头数", d_model: "表示维度", d_ff: "前馈层宽度",
  hidden_size: "隐藏状态维度", embedding_dim: "嵌入维度", vocab_size: "词表大小",
  context_length: "上下文长度", dropout: "Dropout", bidirectional: "双向结构",
  lr: "学习率", weight_decay: "权重衰减", betas: "一阶 / 二阶动量系数", momentum: "动量",
  eps: "数值稳定项", nesterov: "Nesterov 动量", loss_id: "损失函数", label_smoothing: "标签平滑",
  total_samples_seen: "累计处理量", training_steps: "训练步数", batch_size: "每批数量",
  train_size: "训练集样本数", test_size: "测试集样本数", num_classes: "类别数",
  rule_family: "数据规则", active_features: "活跃特征索引", n_active_features: "活跃特征数",
  spiral_turns: "螺旋圈数", instance_seed: "数据实例种子", noise_std: "噪声标准差",
  seq_len: "序列长度", sequence_length: "序列长度", task: "任务类型",
  expression: "目标函数", domain: "输入范围", alpha: "转移分布参数 α",
  trainable_parameter_count: "可训练参数量", params: "可训练参数量", device: "执行设备",
};
const families: Record<string, string> = {
  univariate_regression: "一元回归", multivariate_regression: "多元回归",
  spiral_classification: "螺旋分类", xor_classification: "异或分类",
  synthetic_tabular_classification: "合成表格分类", bigram_lm: "二元序列建模",
};
const types: Record<string, string> = {
  architecture_only: "架构对比", optimizer_only: "优化器对比", loss_only: "损失函数对比", mixed: "混合对比",
};
const sections = [{key:"model", title:"模型结构"}, {key:"optimizer", title:"优化器"},
  {key:"loss", title:"损失函数"}, {key:"budget", title:"训练预算"}, {key:"execution", title:"执行设置"},
  {key:"other", title:"其他公开参数"}];
const dataKeys = ["task", "input_dim", "output_dim", "num_classes", "train_size", "test_size",
  "rule_family", "active_features", "n_active_features", "spiral_turns", "noise_std", "vocab_size",
  "context_length", "seq_len", "sequence_length", "instance_seed", "expression", "domain", "alpha"];
function object(value: unknown): Json {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Json;
  return {};
}
function parsedObject(value: unknown): Json {
  if (typeof value === "string") { try { return object(JSON.parse(value)); } catch { return {}; } }
  return object(value);
}
function array(value: unknown): Json[] { return Array.isArray(value) ? value.filter(v=>v && typeof v === "object") : []; }
function present(value: unknown) { return value !== undefined && value !== null; }
// Public configuration stays inspectable; executed results and source GT are never rendered.
function clean(value: any): any {
  if (Array.isArray(value)) return value.map(clean);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !/^(correct(_letter|_answer)?|answer|winner|rank(ing)?|ground_truth|gt|results?|summary|curves|significance|provenance|source_candidate_spec|seed_results|final_.+|(?:mean|std)_(?:test|train).+|(?:test|train)_(?:ce|mse|loss|accuracy|acc))$/i.test(key.replace(/([a-z0-9])([A-Z])/g,"$1_$2")))
    .map(([key,v])=>[key,clean(v)]));
  return value;
}
function text(value: any): string {
  if (!present(value)) return "未记录";
  if (typeof value === "boolean") return value ? "开启" : "关闭";
  if (Array.isArray(value)) return value.length ? value.map(v=>text(v)).join(" / ") : "空列表";
  return typeof value === "object" ? JSON.stringify(clean(value)) : String(value);
}
function FullConfig({title,value}: {title:string;value:unknown}) {
  return <details className="question-reader-disclosure"><summary>{title}</summary>
    <pre className="question-reader-json">{JSON.stringify(clean(value), null, 2)}</pre></details>;
}
function CodeFiles({files,prefix}: {files:Json;prefix:string}) {
  return <>{Object.entries(files).filter(([name,source])=>name.endsWith(".py") && typeof source === "string").map(([name,source])=>
    <details className="question-reader-disclosure" key={name}><summary>{prefix} · {name}</summary>
      <pre className="question-reader-code"><code>{source as string}</code></pre></details>)}</>;
}
function datasetText(prompt?: string) {
  if (!prompt) return "";
  const lines = prompt.split(/\r?\n/), selected: string[] = [];
  let inside = false, fenced = false;
  for (const line of lines) {
    if (!inside) { if (/^##\s+Dataset\s*$/.test(line)) inside = true; continue; }
    if (/^```/.test(line)) fenced = !fenced;
    if (!fenced && /^##\s+/.test(line)) break;
    selected.push(line);
  }
  return selected.join("\n").trim();
}
function InlineText({value}: {value:string}) {
  return <>{value.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part,index)=>part.startsWith("`") && part.endsWith("`")
    ? <code key={index}>{part.slice(1,-1)}</code> : part.startsWith("**") && part.endsWith("**")
      ? <strong key={index}>{part.slice(2,-2)}</strong> : part)}</>;
}
const promptHeadings: Record<string,string> = {
  "Data-generating and classification rule":"数据生成与分类规则",
  "Data splits and training protocol":"数据划分与训练协议", "Synthesis (PyTorch)":"数据合成方法",
};
// A small text-only Markdown reader: no HTML execution or external links/resources.
function DatasetNarrative({value}: {value:string}) {
  const blocks: {kind:string;value:string[]}[] = [];
  let code: string[] | undefined;
  for (const line of value.split("\n")) {
    if (/^```/.test(line)) {
      if (code) { blocks.push({kind:"code",value:code}); code = undefined; } else code = [];
      continue;
    }
    if (code) { code.push(line); continue; }
    if (!line.trim()) { blocks.push({kind:"break",value:[]}); continue; }
    if (/^#{3,6}\s/.test(line)) { blocks.push({kind:"heading",value:[line.replace(/^#{3,6}\s+/,"")]}); continue; }
    const kind = /^[-*]\s/.test(line) ? "list" : "paragraph";
    const previous = blocks[blocks.length-1];
    const content = kind === "list" ? line.replace(/^[-*]\s+/,"") : line;
    if (previous?.kind === kind) previous.value.push(content); else blocks.push({kind,value:[content]});
  }
  if (code) blocks.push({kind:"code",value:code});
  return <div className="question-reader-narrative">{blocks.map((block,index)=> {
    if (block.kind === "break") return null;
    if (block.kind === "heading") return <h4 key={index}>{promptHeadings[block.value[0]] || block.value[0]}</h4>;
    if (block.kind === "code") return <details key={index} className="question-reader-disclosure"><summary>数据说明中的代码</summary><pre className="question-reader-code"><code>{block.value.join("\n")}</code></pre></details>;
    if (block.kind === "list") return <ul key={index}>{block.value.map((line,i)=><li key={i}><InlineText value={line}/></li>)}</ul>;
    return <p key={index}><InlineText value={block.value.join(" ")}/></p>;
  })}</div>;
}
function viewGroups(view: Json): Record<string, Json> {
  const model: Json = {...parsedObject(view.arch_key)};
  const modelKeys=["depth","width","input_dim","output_dim","activation","residual","layer_norm","layer_residual",
    "num_layers","num_heads","d_model","d_ff","hidden_size","embedding_dim","vocab_size","context_length","dropout","leaky_relu_slope"];
  for (const key of modelKeys)
    if (!present(model[key]) && present(view[key])) model[key] = view[key];
  if (!present(model.type) && present(view.model_type)) model.type = view.model_type;
  const optimizer: Json = {...parsedObject(view.opt_key)};
  if (!present(optimizer.type) && present(view.opt)) optimizer.type = view.opt;
  for (const key of ["lr","weight_decay","momentum"]) if (!present(optimizer[key]) && present(view[key])) optimizer[key] = view[key];
  const loss = parsedObject(view.loss_key);
  const budget = {total_samples_seen:view.budget, training_steps:view.steps, batch_size:view.batch_size};
  const grouped=new Set([...modelKeys,"arch_key","opt_key","loss_key","model_type","opt","lr","weight_decay","momentum","budget","steps","batch_size"]);
  const other=Object.fromEntries(Object.entries(view).filter(([key])=>!grouped.has(key)));
  return {model,optimizer,loss,budget,other};
}

type ReaderProps={record:Json;interactive?:boolean;questionKey?:string;evidence?:ReactNode;reviewSource?:HumanReviewSource};
export function QuestionReader(props:ReaderProps){
  return <QuestionReaderContent key={JSON.stringify([props.questionKey,props.reviewSource])} {...props}/>;
}
function QuestionReaderContent({record,questionKey,evidence:providedEvidence,reviewSource}:ReaderProps) {
  const [revealed,setRevealed]=useState(false);
  const evidence=reviewSource&&!revealed?undefined:providedEvidence;
  // Reset before the new question can be interacted with; a passive mount
  // effect could otherwise overwrite an immediate first tab selection.
  useLayoutEffect(()=>{setTab("structured");},[questionKey]);
  const [tab,setTab] = useState("structured");
  const readerId = useId();
  const detail = object(record.detail), pub = object(record.public), metadata = object(record.metadata);
  const detailed = array(detail.choices), publicChoices = array(pub.choices);
  const base = publicChoices.length ? publicChoices : detailed;
  const choices = base.map((item,index)=> {
    const source = detailed.find(candidate=>(present(item.letter) && candidate.letter === item.letter) ||
      (item.id && candidate.candidateId === item.id)) || (publicChoices.length ? {} : item);
    const files = object(source.files), spec = clean(parsedObject(files["candidate_spec.json"]));
    const fallback = viewGroups(clean(object(item.view)));
    const groups = Object.keys(spec).length ? {
      ...Object.fromEntries(sections.filter(section=>section.key!=="other").map(section=>[section.key,spec[section.key]])),
      other:Object.fromEntries(Object.entries(spec).filter(([key])=>!sections.some(section=>section.key!=="other"&&section.key===key))),
    }:fallback;
    return {identity:String(item.id ?? item.candidateId ?? source.candidateId ?? spec.candidate_id ?? ""),letter:String(item.letter ?? source.letter ?? index+1), files, spec, groups,
      full:Object.keys(spec).length ? spec : clean(object(item.view))};
  });
  const dataset = object(detail.dataset), datasetFiles = object(dataset.files);
  const datasetSpec = parsedObject(datasetFiles["dataset_spec.json"]);
  const view = object(publicChoices[0]?.view);
  const params = Object.keys(object(datasetSpec.params)).length ? object(datasetSpec.params)
    : Object.keys(object(dataset.params)).length ? object(dataset.params) : view;
  const family = datasetSpec.family ?? dataset.family ?? pub.family ?? metadata.family;
  const metric = datasetSpec.selection_metric ?? dataset.selectionMetric ?? metadata.metric ?? view.metric;
  const prompt = typeof detail.prompt === "string" ? detail.prompt : typeof pub.prompt === "string" ? pub.prompt : undefined;
  const narrative = datasetText(prompt);
  const profile = metadata.profile ?? choices.find(c=>c.spec.profile)?.spec.profile;
  const facts = dataKeys.filter(key=>present(params[key]));
  const rows = comparisonRows(choices);
  const briefs=candidateListSummary(choices.map(choice=>({...choice.groups,letter:choice.letter})),metadata.type).candidates;
  const title = [family ? families[family] || text(family) : "训练方案对比", metadata.type ? types[metadata.type] || text(metadata.type) : undefined].filter(Boolean).join(" · ");
  const dataFacts = facts.length ? <dl className="question-reader-facts">{facts.map(key=><div key={key} className={key==="expression" ? "question-reader-expression" : ""}><dt>{labels[key] || key}</dt><dd>{text(params[key])}</dd></div>)}</dl>
    : <p className="question-reader-note">此记录未提供结构化数据条件，请查阅数据规则或原始 Prompt。</p>;
  return <article className={`question-reader${evidence?' has-evidence':''}`}>
    <div className="question-reader-tabs" role="tablist" aria-label="题目阅读方式">
      {[{id:"structured",label:"题目概览"},{id:"data",label:"数据与规则"},{id:"original",label:"原始 Prompt"}].map(item=>
        <button key={item.id} role="tab" aria-selected={tab===item.id} aria-controls={`${readerId}-${item.id}`}
          id={`${readerId}-${item.id}-tab`} onClick={()=>setTab(item.id)}>{item.label}</button>)}
    </div>
    {tab === "original" ? <section role="tabpanel" id={`${readerId}-original`} aria-labelledby={`${readerId}-original-tab`}>
      <p className="question-reader-note">保留完整原文、代码与回答格式，可用于核对结构化阅读视图。</p>
      {prompt !== undefined ? <article aria-label="公开题面"><pre className="question-reader-original" data-testid="original-prompt">{prompt}</pre></article> : <p>此记录未提供原始 Prompt。</p>}
    </section> : tab === "data" ? <section role="tabpanel" id={`${readerId}-data`} aria-labelledby={`${readerId}-data-tab`}>
      <div className="question-reader-section"><h3>数据与规则</h3>{dataFacts}
        {narrative ? <><p className="question-reader-note">以下完整数据规则与训练协议保留题目原文，作为解题依据。</p><DatasetNarrative value={narrative}/></>
          : <p className="question-reader-note">此记录未提供独立的数据规则段，请查阅完整原始 Prompt。</p>}
        <FullConfig title="完整数据配置" value={Object.keys(datasetSpec).length ? datasetSpec : params}/>
        <CodeFiles files={datasetFiles} prefix="数据生成"/>
      </div>
    </section> : <div role="tabpanel" id={`${readerId}-structured`} aria-labelledby={`${readerId}-structured-tab`}>
      <header className="question-reader-intro"><span className="question-reader-kicker">题目任务</span>
        <h2>{title}</h2>
        <p>依据数据规则与训练预算，选择训练后表现最好的候选。{metric && <>评价指标：<strong>{text(metric)}</strong>。</>}</p>
        <div className="question-reader-tags">
          <span>{choices.length} 个候选</span>{profile && <span>Profile {text(profile)}</span>}
        </div>
      </header>
      <div className={`question-reader-comparison-workspace${evidence?' with-evidence':''}`}>
      <section className="question-reader-section"><div className="question-reader-section-title"><h3>候选对比</h3><span className="question-reader-legend">高亮行表示候选间存在差异</span></div>
        {rows.length ? <ComparisonTable choices={choices} rows={rows} label="候选参数对比"/> : <p className="question-reader-note">候选配置未记录，请查阅原始 Prompt。</p>}
        <p className="question-reader-note">预算按候选分别列出：累计处理量 = 训练步数 × 每批数量。{family==='bigram_lm'?'本题按序列窗口计数，重复使用同一窗口也重复计数':'按样本计数，重复使用同一样本也重复计数'}，不是训练集的去重大小。仅展示已记录的数值，不反推缺失步数；逐层开关按模型中的层顺序排列。</p>
      </section>
      {evidence&&<aside className="question-reader-evidence">{evidence}</aside>}
      </div>
    </div>}
    {reviewSource&&<HumanQuestionPractice source={reviewSource} question={{id:pub.id??metadata.id,family,prompt,choices:choices.map((choice,index)=>({id:choice.identity,letter:choice.letter,label:briefs[index]?.label}))}} onRevealed={()=>setRevealed(true)}/>}
    {tab==='structured'&&<div className="question-reader-details">
      <section className="question-reader-section"><h3>数据与条件</h3>
        {dataFacts}
        <div className="question-reader-rule-link"><p className="question-reader-note">此页用于快速比较；解题请阅读完整数据生成规则与训练协议。</p><button onClick={()=>setTab("data")}>查看完整数据规则</button></div>
      </section>
      <section className="question-reader-section"><h3>配置、代码与来源</h3><p className="question-reader-note">展开查看本题有效配置，以及模型、训练、优化器与损失文件。</p>
        {choices.map((choice,index)=><div className="question-reader-candidate" key={`${choice.letter}-${index}`}><h4>候选 {choice.letter}</h4>
          <FullConfig title={`${choice.letter} · 完整候选配置`} value={choice.full}/><CodeFiles files={choice.files} prefix={choice.letter}/>
        </div>)}
      </section>
      <details className="question-reader-disclosure question-reader-provenance"><summary>来源与记录标识</summary>
        <p className="question-reader-note">阅读视图使用本题有效配置；原始来源的配置不参与候选比较。</p>
        <dl className="question-reader-facts">{["id","key","dataset_id","pair_id","lineage_id","profile"].filter(key=>present(metadata[key] ?? pub[key])).map(key=>
          <div key={key}><dt>{key}</dt><dd>{text(metadata[key] ?? pub[key])}</dd></div>)}</dl>
        {array(record.sources).map((source,index)=><p className="question-reader-source" key={index}>{text(source.origin ?? source.source_id)}</p>)}
      </details>
    </div>}
  </article>;
}
type ComparisonRow = {id:string;label:string;title:string;values:any[];different:boolean};
function flattened(value:unknown, prefix="",keepEmptyRoot=false): [string,unknown][] {
  if(value===undefined)return [];
  if(Array.isArray(value)){
    if(value.some(item=>item!==null&&typeof item==='object'))return value.flatMap((item,index)=>flattened(item,`${prefix}[${index}]`));
    return [[prefix,value]];
  }
  if(value&&typeof value==='object'){
    const entries=Object.entries(value);
    if(!entries.length)return prefix||keepEmptyRoot?[[prefix,value]]:[];
    return entries.flatMap(([key,item])=>{
      const segment=key.replace(/[\\.\[\]]/g,"\\$&");
      return flattened(item,prefix?`${prefix}.${segment}`:segment);
    });
  }
  return [[prefix,value]];
}
function comparisonRows(choices:Json[]): ComparisonRow[] {
  const rows = sections.flatMap(section=>{
    const fields=choices.map(choice=>new Map(flattened(choice.groups[section.key],"",Object.prototype.hasOwnProperty.call(choice.spec,section.key))));
    const keys=Array.from(new Set(fields.flatMap(value=>[...value.keys()])));
    return keys.map(key=>({id:`${section.key}.${key}`, title:section.title,
      label:key==="type"&&section.key==="optimizer"?"优化器类型":labels[key]||key||section.title,
      values:fields.map(value=>value.get(key))}));
  });
  return rows.map(row=>({...row,different:new Set(row.values.map(value=>JSON.stringify(value??null))).size>1}));
}
function ComparisonTable({choices,rows,label}: {choices:Json[];rows:ComparisonRow[];label:string}) {
  return <div className="question-reader-table-wrap"><table className="question-reader-table" aria-label={label} style={choices.length>3?{minWidth:`${(choices.length+1)*115}px`}:undefined}><colgroup><col style={{width:'26%'}}/>{choices.map((choice,index)=><col key={`${choice.letter}-${index}`} style={{width:`${74/choices.length}%`}}/>)}</colgroup><thead><tr><th scope="col">比较项目</th>
    {choices.map((choice,index)=><th scope="col" key={`${choice.letter}-${index}`}>候选 {choice.letter}</th>)}</tr></thead>
    <tbody>{rows.map((row,index)=><tr key={row.id} className={row.different ? "is-different" : ""}>
      <th scope="row">{(index===0 || rows[index-1].title!==row.title) && <small className="question-reader-row-group">{row.title}</small>}{row.label}</th>
      {row.values.map((value,index)=><td key={index}>{text(value)}</td>)}</tr>)}</tbody>
  </table></div>;
}
