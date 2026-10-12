import { formatTimestamp } from './time';
import type { Json } from './types';

const families: Record<string, string> = {
  univariate_regression: '一元回归', multivariate_regression: '多元回归',
  spiral_classification: '螺旋分类', xor_classification: '异或分类',
  synthetic_tabular_classification: '合成表格分类', bigram_lm: '二元序列建模',
};
const types: Record<string, string> = {
  architecture_only: '架构对比', optimizer_only: '优化器对比', loss_only: '损失函数对比', mixed: '混合对比',
};
export const familyLabel = (family?: string) => family ? families[family] || family : '训练方案对比';
export const typeLabel = (type?: string) => type ? types[type] || `其他题型 · ${type}` : '题型未记录';
/** Display aliases only: opaque identifiers remain unchanged in requests and provenance. */
export function readableName(name: unknown, fallback: string): string {
  if (typeof name !== 'string' || !name.trim()) return fallback;
  const clean = name.replace(/(?:^|\s*[·：:]\s*)(?:(?:archive|run|q|pair|kb|exp|experience|set|snapshot|claim|wf)_[a-z0-9_-]+(?:@[a-z0-9]+)?|[a-f0-9]{16,})(?=\s*$)/i, '').trim();
  return clean || fallback;
}
export function questionLabel(question?: Json, ordinal?: number): string {
  const q = question?.metadata ?? question?.public ?? question ?? {};
  const name = [familyLabel(q.family), q.type ? typeLabel(q.type) : undefined].filter(Boolean).join(' · ');
  return ordinal === undefined ? name : `${name} · 第 ${ordinal} 题`;
}
const modelNames:Record<string,string>={mlp:'MLP',linear:'线性模型',gru_lm:'GRU',transformer_lm:'Transformer',gru:'GRU',transformer:'Transformer',lstm:'LSTM',lstm_lm:'LSTM',cnn:'CNN',convnet:'ConvNet',resnet:'ResNet'};
const compact=(value:string,max=32)=>value.length>max?value.slice(0,max-1)+'…':value;
const displayValue=(value:unknown):string=>value==null?'未记录':typeof value==='boolean'?value?'开启':'关闭':
  Array.isArray(value)?compact(value.map(displayValue).join('/')):typeof value==='number'&&Number.isFinite(value)?String(value):
  typeof value==='string'?compact(value):'未记录';
const modelName=(value:unknown)=>typeof value==='string'&&value?modelNames[value.toLowerCase()]||compact(value):'模型未记录';
type CandidateBrief={letter:string;label:string};
const comparisonFields=[
  ['model','depth','深度'],['model','num_layers','层数'],['model','width','宽度'],['model','d_model','表示维度'],
  ['optimizer','type','优化器'],['optimizer','lr','学习率'],['model','activation','激活'],['model','num_heads','注意力头数'],
  ['model','residual','残差'],['model','layer_norm','归一化'],['optimizer','weight_decay','权重衰减'],
  ['optimizer','momentum','动量'],['optimizer','betas','动量系数'],['loss','loss_id','损失'],['loss','type','损失'],['loss','lambda','损失系数'],
] as const;
/** Names only recorded public differences; no answer, prompt, or result is consulted. */
export function candidateListSummary(input:unknown,type?:string):{title:string;candidates:CandidateBrief[]}{
  const configs:Json[]=Array.isArray(input)?input.filter(value=>value&&typeof value==='object'&&!Array.isArray(value)):[];
  if(!configs.length)return {title:'',candidates:[]};
  const models=[...new Set(configs.map(config=>modelName(config.model?.type)))];
  const ordered=[...comparisonFields].sort((a,b)=>{
    const group=type?.startsWith('optimizer')?'optimizer':type?.startsWith('loss')?'loss':'model';
    return Number(b[0]===group)-Number(a[0]===group);
  });
  const changed=ordered.filter(([group,key])=>new Set(configs.map(config=>JSON.stringify(config[group]?.[key]??null))).size>1).slice(0,2);
  const series=(values:string[],separator=' / ')=>{const unique=[...new Set(values)];return unique.slice(0,4).join(separator)+(unique.length>4?` 等 ${unique.length} 种`:'');};
  const differences=changed.map(([group,key,label])=>`${label} ${series(configs.map(config=>displayValue(config[group]?.[key])))}`);
  const title=compact([series(models,' vs '),...differences].join(' · '),128);
  const candidates=configs.map(config=>({letter:typeof config.letter==='string'?config.letter:'?',
    label:[modelName(config.model?.type),...changed.map(([group,key,label])=>`${label} ${displayValue(config[group]?.[key])}`)].join(' · ')}));
  return {title,candidates};
}
/** Compact list copy uses public metadata, never prompt excerpts or stored answers. */
export function questionListSummary(question?:Json):{title:string;description:string;candidates:CandidateBrief[];shortId:string}{
  const q=question?.metadata??question?.public??question??{};
  const comparisons:Record<string,string>={architecture_only:'架构选择',architecture:'架构选择',optimizer_only:'优化器选择',optimizer:'优化器选择',loss_only:'损失函数选择',loss:'损失函数选择',mixed:'训练方案比较'};
  const kind=q.type?(comparisons[q.type]||typeLabel(q.type)):'';
  const description=[q.family?familyLabel(q.family):'',kind].filter(Boolean).join(' · ');
  const actual=candidateListSummary(q.candidate_configs,q.type);
  const models=[...new Set<string>((Array.isArray(q.model_types)?q.model_types:[]).filter((value:unknown)=>typeof value==='string'&&value).map(modelName))];
  const fallback=models.length>1?models.join(' vs '):[models[0]||familyLabel(q.family),kind].filter(Boolean).join(' · ');
  const id=typeof q.id==='string'?q.id.split('@')[0].split('/').pop()||'':'';
  const shortId=id.startsWith('q_')?id.slice(0,10):compact(id,14);
  return {title:actual.title||fallback,description,candidates:actual.candidates,shortId};
}
export function datasetTypeDistribution(counts?:Record<string,number>):string[]{
  return Object.entries(counts??{}).filter(([,count])=>Number.isInteger(count)&&count>0)
    .sort(([a],[b])=>a.localeCompare(b)).map(([type,count])=>`${typeLabel(type)} ${count} 题`);
}
export function runLabel(run?: Json): string {
  if (!run) return '运行记录';
  const config = run.config ?? {};
  const method = config.method?.id ?? config.method_id ?? config.workflow?.settings?.method_id;
  const fallback = method === 'basic_learning' ? '单题学习' : ({workflow:'KB 研究', evaluation:'模型评测', generation:'题目生成',rag:'RAG 作答',rule_refinement:'规则 KB 闭环',rule_evaluation:'规则评测'}[String(run.kind)] ?? '运行记录');
  const title = [run.name, config.name, config.workflow?.name, config.method?.name].map(name=>readableName(name, '')).find(Boolean) || fallback;
  return run.created_at ? `${title} · ${formatTimestamp(run.created_at)}` : title;
}
