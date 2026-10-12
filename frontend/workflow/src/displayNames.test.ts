import { expect, it } from 'vitest';
import { questionLabel, runLabel, readableName, familyLabel, questionListSummary, candidateListSummary, questionPromptSummary } from './displayNames';

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
 expect(value.title).toBe('GRU vs Transformer');expect(value.description).toBe('按各候选的配置训练后，这 3 个方案中哪个的测试交叉熵最低？');expect(value.category).toBe('二元序列建模 · 混合对比');expect(value.shortId).toBe('q_bcb233');expect(value.candidates).toEqual([]);
 expect(JSON.stringify(value)).not.toContain('Univariate regression');
});
it('keeps unknown metadata readable and avoids invented counts or budget units',()=>{
 const value=questionListSummary({family:'new_family',type:'new_intervention',model_types:['new_model','new_model'],metric:'custom_metric',budget:4096});
 expect(value.title).toBe('new_model · 其他题型 · new_intervention');expect(value.category).toBe('new_family · 其他题型 · new_intervention');expect(value.description).toContain('custom_metric');expect(value.description).not.toMatch(/最高|最低/);expect(value.candidates).toEqual([]);
 expect(questionListSummary({prompt:'do something'})).toEqual({title:'训练方案对比',description:'按各候选的配置训练后，哪个方案表现最好？评价指标未记录。',category:'',candidates:[],shortId:''});
});
it('asks for the recorded test metric without claiming equal budgets or inferring a missing metric from family',()=>{
 expect(questionPromptSummary({metric:'test_mse',candidateCount:2})).toContain('测试均方误差最低');
 expect(questionPromptSummary({metric:'test_accuracy'})).toContain('测试准确率最高');
 expect(questionPromptSummary({metric:'test_loss'})).toContain('测试损失最低');
 expect(questionPromptSummary({metric:'future_metric'})).toContain('在 future_metric 指标上表现最好');
 for(const budgets of [[128,128],[128,256]]){
  const value=questionListSummary({family:'univariate_regression',metric:'test_mse',candidate_configs:budgets.map((budget,index)=>({letter:'AB'[index],budget:{total_samples_seen:budget},model:{type:'mlp'}}))});
  expect(value.description).toContain('测试均方误差最低');expect(value.description).not.toMatch(/相同|统一|同等/);
 }
 expect(questionListSummary({family:'bigram_lm'}).description).toContain('评价指标未记录');
 expect(questionPromptSummary({candidateCount:NaN})).not.toContain('NaN');
 expect(questionPromptSummary({candidateCount:1})).not.toContain('1 个');
});
it('names actual candidate differences and keeps each candidate separate when model types repeat',()=>{
 const configs=[2,4,8].map((depth,index)=>({letter:'ABC'[index],model:{type:'mlp',depth,width:64},optimizer:{type:'Adam',lr:0.001}}));
 const value=questionListSummary({id:'q_abcdef0123456789',family:'univariate_regression',type:'architecture_only',candidate_configs:configs});
 expect(value.title).toBe('MLP · 深度 2 / 4 / 8');
 expect(value.shortId).toBe('q_abcdef01');
 expect(value.candidates).toEqual([{letter:'A',label:'MLP · 深度 2'},{letter:'B',label:'MLP · 深度 4'},{letter:'C',label:'MLP · 深度 8'}]);
 expect(candidateListSummary(configs)).toEqual({title:value.title,candidates:value.candidates});
});
it('uses optimizer differences without mistaking missing values or zero for common settings',()=>{
 const configs=[{letter:'A',model:{type:'gru_lm'},optimizer:{type:'SGD',lr:0}},
  {letter:'B',model:{type:'gru_lm'},optimizer:{type:'Adam',lr:0.001}},
  {letter:'C',model:{type:'transformer_lm'},optimizer:{}}];
 const value=candidateListSummary(configs,'optimizer_only');
 expect(value.title).toContain('SGD / Adam / 未记录');
 expect(value.candidates[0].label).toContain('学习率 0');
 expect(value.candidates[2].label).toContain('优化器 未记录');
 expect(JSON.stringify(value)).not.toContain('undefined');
});
it('does not use results or raw prompts to name candidates and keeps compact labels bounded',()=>{
 const value=questionListSummary({id:'q_1',prompt:'SECRET_PROMPT',candidate_configs:[
 {letter:'A',model:{type:'x'.repeat(1000),depth:2,score:'SECRET_SCORE'},correct_letter:'SECRET_ANSWER'},
 {letter:'B',model:{type:'x'.repeat(1000),depth:3},optimizer:{answer:'SECRET_OPT'}}]});
 expect(value.title.length).toBeLessThan(130);
 expect(JSON.stringify(value)).not.toContain('SECRET_');
});
