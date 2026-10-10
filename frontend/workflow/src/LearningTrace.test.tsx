import { afterEach,expect,it } from 'vitest';
import { cleanup,render,screen } from '@testing-library/react';
import { LearningTrace } from './LearningTrace';
afterEach(cleanup);
it('shows provisional induction, independent transfer and revision with no claim of verified knowledge',()=>{
 const note={learning:{summary:'小样本偏好简单模型',conditions:['样本较少'],exceptions:[],interactions:['噪声与样本量'],changed_factors:['范围'],controlled_factors:['预算'],competing_explanation:'优化难度',next_test:'固定噪声重复'}};
 render(<LearningTrace trace={{pair_id:'pair-one',induction:note,transfer:{ranking:['B','A','C'],rationale:'迁移理由'},revision:{learning:{...note.learning,summary:'补充噪声条件'}}}}/>);
 expect(screen.getByText('小样本偏好简单模型')).toBeTruthy();
 expect(screen.getByText('补充噪声条件')).toBeTruthy();
 expect(screen.getByText(/预测排序：B → A → C/)).toBeTruthy();
 expect(screen.getByText(/待验证的研究记录/)).toBeTruthy();
});
