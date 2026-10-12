import {afterEach,expect,it} from 'vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import {RuleReasoning,ModelSources,SkippedRules} from './TaskReasoning';

afterEach(cleanup);
const A={id:'opaque-a',letter:'A'},B={id:'opaque-b',letter:'B'},C={id:'opaque-c',letter:'C'};
const rule={rule_id:'exec-c1-0',claim_ids:['C001'],revision:'rev-frozen',text:'适用条件下，较小学习率更好',validity_status:'proposed',source_status:'candidate',conditions:[{kind:'scope',label:'适用范围',expression:'family = regression 或 model_type = mlp',passed:true,facts:[{field:'family',operator:'eq',expected:'regression',winner_value:'regression',loser_value:'regression',winner_passed:true,loser_passed:true},{field:'model_type',operator:'eq',expected:'mlp',winner_value:'linear',loser_value:'linear',winner_passed:false,loser_passed:false}]}],prediction:{kind:'lower_better',label:'学习率更低的候选更好',fields:[{field:'lr',direction:'lower',winner_value:0.001,loser_value:0.01,min_ratio:2,ratio:10}]}};
it('shows the rule, observed candidate values, and the exact deduction path',()=>{
 render(<RuleReasoning value={{status:'answered',summary:'A 通过规则关系覆盖全部候选。',answer:A,edges:[{kb:{id:'k',name:'第 2 轮 KB'},winner:A,loser:B,rules:[rule]}],paths:[{kb_id:'k',candidates:[A,B,C],rule_refs:[{rule_id:'exec-c1-0',revision:'rev-frozen'}]}],conflicts:[],uncovered_pairs:[]}}/>);
 expect(screen.getByText('候选 A 优于候选 B')).toBeTruthy();expect(screen.getAllByText('C001').length).toBeGreaterThan(0);expect(screen.getByText('0.001')).toBeTruthy();expect(screen.getByText('0.01')).toBeTruthy();expect(screen.getByText('A → B → C')).toBeTruthy();expect(screen.getByText('family = regression 或 model_type = mlp')).toBeTruthy();
 expect(screen.getByText('来源标记：候选知识 · 待验证')).toBeTruthy();expect(screen.queryByText('所有条件均满足')).toBeNull();
});
it('keeps conflicts and missing comparisons visible when no answer is committed',()=>{
 render(<RuleReasoning value={{status:'conflict',summary:'规则支持相反结论，保留判断。',answer:null,edges:[],paths:[],conflicts:[{code:'opposite_rules',candidates:[A,B]}],uncovered_pairs:[[B,C]]}}/>);
 expect(screen.getByText('候选 A ↔ 候选 B')).toBeTruthy();expect(screen.getByText('候选 B / 候选 C')).toBeTruthy();expect(screen.getByText('规则支持相反结论，保留判断。')).toBeTruthy();
});
it('distinguishes actual model citations from only provided knowledge',()=>{
 const used={citation_id:'K1',text:'被模型引用的规则',source_claim_ids:['C001'],source_status:'candidate',rule:{scope:[],predict:{lower_better:'lr'}}},unused={citation_id:'K2',text:'提供但没有引用的规则',source_claim_ids:['C002']};
 render(<ModelSources result={{used_sources:[used],provided_sources:[used,unused]}}/>);
 const cited=screen.getByRole('region',{name:'模型明确引用的知识'});expect(within(cited).getByText('被模型引用的规则')).toBeTruthy();expect(within(cited).queryByText('提供但没有引用的规则')).toBeNull();
 expect(screen.getByText('提供给模型、未被引用的知识 · 1 条')).toBeTruthy();expect(screen.getByText('C001')).toBeTruthy();
});
it('explains why source claims were excluded from the selected KB',()=>{
 render(<SkippedRules value={{skipped_claims:[{claim_id:'C010',reason:'needs_revision'},{claim_id:'C011',reason:'invalid_rule',clause_index:2},{claim_id:'C012',reason:'source_retired'}]}}/>);
 expect(screen.getByText('未参与的规则 · 3 条')).toBeTruthy();expect(screen.getByText('C010')).toBeTruthy();expect(screen.getByText('待修订')).toBeTruthy();expect(screen.getByText('C011 · 第 2 条')).toBeTruthy();expect(screen.getByText('规则未通过校验')).toBeTruthy();expect(screen.getByText('已停用')).toBeTruthy();
});
it('presents clean numeric observations and original claim names along a path',()=>{
 render(<RuleReasoning value={{status:'answered',summary:'已确定答案',edges:[{kb:{id:'k',name:'KB'},winner:A,loser:B,rules:[{...rule,prediction:{...rule.prediction,fields:[{field:'lr',winner_value:0.010000000000000002,loser_value:0.030000000000000006,direction:'lower'}]}}]}],paths:[{kb_id:'k',candidates:[A,B],rule_refs:[{rule_id:'exec-c1-0',revision:'rev-frozen'}]}]}}/>);
 expect(screen.getByText('0.01')).toBeTruthy();expect(screen.getByText('0.03')).toBeTruthy();expect(screen.getAllByText('C001')).toHaveLength(2);
});
