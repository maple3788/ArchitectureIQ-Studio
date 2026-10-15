import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {ConsistencyAuditView} from './ConsistencyAudit';

afterEach(cleanup);
it('shows discrete configured budgets and steps without implying arbitrary combinations or ranges',()=>{
 render(<ConsistencyAuditView audit={{status:'passed',issues:[],budget_context:{status:'configured',profile:'research',config_hash:'fixed',budget_values:[4096,16384],steps_values:[16,128],combinations:[{budget:4096,steps:16},{budget:16384,steps:128}],rule_semantics:'完整 DSL 定义'}}}/>);
 fireEvent.click(screen.getByText('审计详情'));
 fireEvent.click(screen.getByText('真实预算上下文'));
 const budget=within(screen.getByRole('region',{name:'预算取值'}));
 expect(budget.getByText('4096、16384')).toBeTruthy();
 expect(budget.getByText('预算 · 累计样本呈现次数')).toBeTruthy();
 expect(budget.getByText('16、128')).toBeTruthy();
 expect(budget.getByText('research')).toBeTruthy();
 expect(budget.getByText('按配置组合，不代表任意组合。')).toBeTruthy();
 const raw=screen.getByText('完整配置与规则定义').closest('details')!;
 expect(raw.open).toBe(false);
 fireEvent.click(within(raw).getByText('完整配置与规则定义'));
 expect(raw.open).toBe(true);
 expect(raw.textContent).toContain('完整 DSL 定义');
});
