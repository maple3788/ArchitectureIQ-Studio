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
/** Compact list copy uses public metadata, never prompt excerpts or stored answers. */
export function questionListSummary(question?: Json):{title:string;description:string;models:string[];facts:string[]}{
  const q=question?.metadata??question?.public??question??{};
  const comparisons:Record<string,string>={architecture_only:'架构选择',architecture:'架构选择',optimizer_only:'优化器选择',optimizer:'优化器选择',loss_only:'损失函数选择',loss:'损失函数选择',mixed:'训练方案比较'};
  const title=[familyLabel(q.family),q.type?(comparisons[q.type]||typeLabel(q.type)):undefined].filter(Boolean).join(' · ');
  const modelNames:Record<string,string>={mlp:'MLP',linear:'线性模型',gru_lm:'GRU',transformer_lm:'Transformer',gru:'GRU',transformer:'Transformer',lstm:'LSTM',lstm_lm:'LSTM',cnn:'CNN',convnet:'ConvNet',resnet:'ResNet'};
  const models=[...new Set<string>((Array.isArray(q.model_types)?q.model_types:[]).filter((model:unknown):model is string=>typeof model==='string'&&!!model.trim()).map((model:string)=>modelNames[model]||model))];
  const metricNames:Record<string,string>={test_ce:'测试交叉熵',test_mse:'测试均方误差',test_acc:'测试准确率',test_accuracy:'测试准确率',test_loss:'测试损失',ce:'交叉熵',mse:'均方误差',accuracy:'准确率'};
  const metric=typeof q.metric==='string'&&q.metric.trim()?(metricNames[q.metric]||q.metric):undefined;
  const choices=Array.isArray(q.choices)?q.choices.length:q.choices;
  const count=Number.isInteger(choices)&&choices>0?choices:undefined;
  const description=count?`比较 ${count} 个候选方案${metric?`，按${metricNames[q.metric]?'':' '}${metric}${metricNames[q.metric]?'':' '}评价表现`:'的公开配置'}。`:metric?`按 ${metric} 评价候选表现。`:'打开题目，查看公开条件与候选配置。';
  const facts:string[]=[];
  const number=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value.toLocaleString('zh-CN',{maximumFractionDigits:6}):undefined;
  if(typeof q.budget==='number'){
    const amount=number(q.budget);if(amount!==undefined)facts.push(`训练预算 ${amount}`);
  }else if(q.budget&&typeof q.budget==='object'){
    const samples=number(q.budget.total_samples_seen),steps=number(q.budget.training_steps),batch=number(q.budget.batch_size);
    if(samples!==undefined)facts.push(`训练总量 ${samples} 样本`);
    if(steps!==undefined)facts.push(`训练 ${steps} 步`);
    if(batch!==undefined)facts.push(`每批 ${batch} 样本`);
  }
  return {title,description,models,facts};
}
export function runLabel(run?: Json): string {
  if (!run) return '运行记录';
  const config = run.config ?? {};
  const method = config.method?.id ?? config.method_id ?? config.workflow?.settings?.method_id;
  const fallback = method === 'basic_learning' ? '单题学习' : ({workflow:'KB 研究', evaluation:'模型评测', generation:'题目生成',rag:'RAG 作答',rule_refinement:'规则 KB 闭环',rule_evaluation:'规则评测'}[String(run.kind)] ?? '运行记录');
  const title = [run.name, config.name, config.workflow?.name, config.method?.name].map(name=>readableName(name, '')).find(Boolean) || fallback;
  return run.created_at ? `${title} · ${formatTimestamp(run.created_at)}` : title;
}
