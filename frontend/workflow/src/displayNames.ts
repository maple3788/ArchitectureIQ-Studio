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
export function runLabel(run?: Json): string {
  if (!run) return '运行记录';
  const config = run.config ?? {};
  const method = config.method?.id ?? config.method_id ?? config.workflow?.settings?.method_id;
  const fallback = method === 'basic_learning' ? '单题学习' : ({workflow:'KB 研究', evaluation:'模型评测', generation:'题目生成',rag:'RAG 作答',rule_refinement:'规则 KB 闭环',rule_evaluation:'规则评测'}[String(run.kind)] ?? '运行记录');
  const title = [run.name, config.name, config.workflow?.name, config.method?.name].map(name=>readableName(name, '')).find(Boolean) || fallback;
  return run.created_at ? `${title} · ${formatTimestamp(run.created_at)}` : title;
}
