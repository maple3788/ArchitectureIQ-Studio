import { expect, it } from 'vitest';
import { questionLabel, runLabel, readableName, familyLabel } from './displayNames';

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
