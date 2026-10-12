import {expect,it} from 'vitest';
import {evidenceQuestionSummary} from './evidenceQuestionSummary';
it('labels actual evidence candidates from public structure and optimizer configuration',()=>{
 const summary=evidenceQuestionSummary({family:'bigram_lm',type:'mixed',winner:'private',candidates:{
  original_b:{arch_key:JSON.stringify({type:'transformer_lm',num_layers:3,num_heads:4}),opt_key:JSON.stringify({type:'SGD',lr:0.0001}),test_ce:0.2},
  original_a:{arch_key:JSON.stringify({type:'transformer_lm',num_layers:2,num_heads:2}),opt:'AdamW',lr:0.0003,test_ce:0.3},
 }});
 expect(summary.description).toBe('二元序列建模 · 比较 2 个训练方案');
 expect(summary.alias('original_b')).toContain('Transformer · 层数 3 · 注意力头数 4 · SGD · 学习率 0.0001');
 expect(summary.alias('original_a')).toContain('AdamW');
 expect(JSON.stringify(summary)).not.toContain('test_ce');
 expect(summary.alias('absent')).toBe('未记录配置（absent）');
});
it('keeps source identities visible when saved configuration cannot distinguish candidates',()=>{
 const summary=evidenceQuestionSummary({candidates:{one:{model_type:'mlp'},two:{model_type:'mlp'}}});
 expect(summary.alias('one')).toBe('MLP（one）');
 expect(summary.alias('two')).toBe('MLP（two）');
});
