import { expect, it } from 'vitest';
import { questionLabel, runLabel, readableName, familyLabel, questionListSummary } from './displayNames';

it('uses public question metadata and list positions while retaining opaque identities separately', () => {
  expect(questionLabel({id:'q_deadbeef',family:'multivariate_regression',type:'architecture_only'}, 4)).toBe('多元回归 · 架构对比 · 第 4 题');
  expect(questionLabel({id:'q_deadbeef'})).toBe('训练方案对比');
  expect(familyLabel('new_family')).toBe('new_family');
});
it('uses meaningful run names or method names, never generated run identities', () => {
  expect(runLabel({id:'run_deadbeef',kind:'workflow',config:{workflow:{name:'噪声条件研究'}}})).toBe('噪声条件研究');
  expect(runLabel({id:'run_deadbeef',kind:'workflow',config:{method:{id:'basic_learning'}}})).toBe('单题学习');
  expect(runLabel({id:'run_deadbeef',kind:'evaluation',name:'run_deadbeef'})).toBe('模型评测');
  expect(runLabel({kind:'workflow',created_at:1791601200})).toContain('2026');
});
it('keeps user titles but replaces auto-generated identity-only names', () => {
  expect(readableName('archive_5c90af39120a9893','历史材料')).toBe('历史材料');
  expect(readableName('kb_09da77727be484f4','知识版本')).toBe('知识版本');
  expect(readableName('单题学习 · q_01afe9','单题学习')).toBe('单题学习');
  expect(readableName('优化器经验 · 第一次整理','历史材料')).toBe('优化器经验 · 第一次整理');
});
it('builds question list summaries from public metadata instead of contradictory raw prompt text',()=>{
 const value=questionListSummary({id:'q_bcb233',family:'bigram_lm',type:'mixed',choices:3,model_types:['gru_lm','transformer_lm'],budget:{total_samples_seen:16384},metric:'test_ce',prompt:'## Dataset\nUnivariate regression\n'+ 'long code '.repeat(1000)});
 expect(value.title).toBe('二元序列建模 · 训练方案比较');expect(value.description).toBe('比较 3 个候选方案，按测试交叉熵评价表现。');expect(value.models).toEqual(['GRU','Transformer']);expect(value.facts).toEqual(['训练总量 16,384 样本']);
 expect(JSON.stringify(value)).not.toContain('Univariate regression');
});
it('keeps unknown metadata readable and avoids invented counts or budget units',()=>{
 const value=questionListSummary({family:'new_family',type:'new_intervention',model_types:['new_model','new_model'],metric:'custom_metric',budget:4096});
 expect(value.title).toBe('new_family · 其他题型 · new_intervention');expect(value.description).toBe('按 custom_metric 评价候选表现。');expect(value.models).toEqual(['new_model']);expect(value.facts).toEqual(['训练预算 4,096']);
 expect(questionListSummary({prompt:'do something'})).toEqual({title:'训练方案对比',description:'打开题目，查看公开条件与候选配置。',models:[],facts:[]});
});
