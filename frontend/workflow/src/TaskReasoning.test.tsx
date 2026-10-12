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
it('connects each comparison to frozen public candidates by exact identity rather than array order',()=>{
 const question={choices:[{...B,view:{model_type:'gru_lm',num_layers:4,lr:0.01}},
  {...A,view:{model_type:'mlp',depth:2,arch_key:JSON.stringify({type:'mlp',layer_norm:[true,false]}),lr:0.001,
   answer:'SECRET_ANSWER',test_mse:'SECRET_GT'}}],feedback:{answer:'SECRET_FEEDBACK'}};
 render(<RuleReasoning question={question} value={{edges:[{kb:{id:'kb-frozen',version:'v2',name:'冻结 KB'},winner:A,loser:B,rules:[rule]}]}}/>);
 const first=screen.getByLabelText('候选 A 的冻结配置'),second=screen.getByLabelText('候选 B 的冻结配置');
 expect(within(first).getByText('mlp')).toBeTruthy();expect(within(first).getByText('2')).toBeTruthy();expect(within(first).getByText('(yes, no)')).toBeTruthy();
 expect(within(second).getByText('gru_lm')).toBeTruthy();expect(within(second).getByText('4')).toBeTruthy();
 expect(first.textContent).not.toContain('gru_lm');expect(screen.getByText('kb-frozen@v2').closest('details')).toBeTruthy();
 expect(document.body.textContent).not.toContain('SECRET_');
});
it('does not substitute a same-letter candidate when the frozen candidate id disagrees',()=>{
 render(<RuleReasoning question={{choices:[{id:'different-id',letter:'A',view:{model_type:'WRONG_MODEL'}},B]}} value={{edges:[{winner:A,loser:B,rules:[]}]}}/>);
 expect(screen.getByLabelText('候选 A 的冻结配置').textContent).toContain('冻结题面中未找到一致的候选标识');
 expect(document.body.textContent).not.toContain('WRONG_MODEL');
});
it('does not attach configuration when the saved id matches but the option letter disagrees',()=>{
 render(<RuleReasoning question={{public:{choices:[{...A,letter:'C',view:{model_type:'WRONG_LETTER_MODEL'}},B]}}} value={{edges:[{winner:A,loser:B,rules:[]}]}}/>);
 expect(screen.getByLabelText('候选 A 的冻结配置').textContent).toContain('冻结题面中未找到一致的候选标识');
 expect(document.body.textContent).not.toContain('WRONG_LETTER_MODEL');
});
it('keeps actual scope checks available on expansion and preserves OR truth without treating every leaf as passed',()=>{
 render(<RuleReasoning value={{edges:[{winner:A,loser:B,rules:[rule]}]}}/>);
 const expression=screen.getByText('family = regression 或 model_type = mlp');
 expect(expression.closest('details')?.open).toBe(false);
 expect(screen.getByText('整体条件成立')).toBeTruthy();
 expect(screen.getAllByText('子条件不满足')).toHaveLength(2);
 expect(screen.getAllByText('子条件满足')).toHaveLength(2);
 expect(screen.queryByText(/所有条件.*满足/)).toBeNull();
 expect(screen.getByText('原规则与来源记录').closest('details')?.open).toBe(false);
});
it('defaults to compact relations, merging equal execution semantics while retaining every frozen source',()=>{
 const edges=[{kb:{id:'kb-a',version:'v1',name:'学习率知识'},winner:A,loser:B,rules:[rule]},
  {kb:{id:'kb-b',version:'v2',name:'同一知识的另一来源'},winner:A,loser:B,rules:[{...rule,rule_id:'other-id',revision:'second-revision',claim_ids:['C009']}]}];
 const path={kb_id:'kb-a',candidates:[A,B],rule_refs:[{rule_id:rule.rule_id,revision:rule.revision}]};
 const {container}=render(<RuleReasoning embedded value={{status:'answered',edges,paths:[path,path]}}/>);
 const comparisons=container.querySelectorAll<HTMLDetailsElement>('.task-deduction-edge');
 expect(comparisons).toHaveLength(1);expect(comparisons[0].open).toBe(false);
 expect(comparisons[0].querySelector('summary')?.textContent).toContain('候选 A > 候选 B');
 expect(comparisons[0].querySelector('summary')?.textContent).toContain('因为 KB C001：学习率越低越优');
 expect(screen.getByText('kb-a@v1').closest('details')?.open).toBe(false);
 expect(screen.getByText('kb-b@v2').closest('details')?.open).toBe(false);
 expect(container.textContent).toContain('second-revision');
 expect(screen.getByText('A → B').closest('details')?.open).toBe(false);
 expect(screen.queryByRole('heading',{name:'答案如何得出'})).toBeNull();
});
it.each(['conditions','prediction','text','relation'])('does not merge reused identities when %s differs',changed=>{
 const altered={...rule,revision:'another-revision',...(changed==='text'?{text:'较高学习率更好'}:changed==='conditions'?{conditions:[{kind:'scope',passed:false}]}:changed==='prediction'?{prediction:{...rule.prediction,fields:[{field:'lr',winner_value:0.2,loser_value:0.3}]}}:{})};
 const {container}=render(<RuleReasoning value={{edges:[{kb:{id:'same-kb',version:'v1'},winner:A,loser:B,rules:[rule]},
  {kb:{id:'same-kb',version:'v2'},winner:changed==='relation'?B:A,loser:changed==='relation'?A:B,rules:[altered]}]}}/>);
 expect(container.querySelectorAll('.task-deduction-edge')).toHaveLength(2);
});
it('groups equivalent object key orders without changing the frozen execution records',()=>{
 const reversed=Object.fromEntries(Object.entries(rule.prediction).reverse());
 const value={edges:[{kb:{id:'k1',version:'v1'},winner:A,loser:B,rules:[rule]},
  {kb:{id:'k2',version:'v2'},winner:A,loser:B,rules:[{...rule,revision:'r2',prediction:reversed}]}]};
 const before=JSON.stringify(value),{container}=render(<RuleReasoning value={value}/>);
 expect(container.querySelectorAll('.task-deduction-edge')).toHaveLength(1);
 expect(JSON.stringify(value)).toBe(before);
});
it('does not claim equivalence when historical execution conditions are missing',()=>{
 const legacy={rule_id:'same-id',revision:'r1',text:'旧规则正文'};
 const {container}=render(<RuleReasoning value={{edges:[{winner:A,loser:B,rules:[legacy]},
  {winner:A,loser:B,rules:[{...legacy,revision:'r2'}]}]}}/>);
 expect(container.querySelectorAll('.task-deduction-edge')).toHaveLength(2);
});
it('merges equivalent model knowledge without turning unreferenced citations into referenced ones',()=>{
 const first={citation_id:'K1',record_id:'r1',revision:'v1',text:'同一条学习率知识',rule:{scope:[['model_type','eq','mlp']],predict:{lower_better:'lr'}},source_refs:[{id:'kb1',version:'v1'}]};
 const second={...first,citation_id:'K2',record_id:'r2',revision:'v2',source_refs:[{id:'kb2',version:'v2'}]};
 const {container}=render(<ModelSources result={{used_sources:[first],provided_sources:[first,second]}}/>);
 expect(container.querySelectorAll('.task-model-source')).toHaveLength(1);
 expect(screen.getByText('同一条学习率知识').closest('summary')).toBeTruthy();
 expect(screen.getByText('引用 K1')).toBeTruthy();
 expect(screen.queryByText('引用 K2')).toBeNull();
 expect(container.textContent).toContain('K2');expect(container.textContent).toContain('仅提供');
 expect(container.textContent).toContain('kb1');expect(container.textContent).toContain('kb2');
 expect((container.querySelector('.task-model-source') as HTMLDetailsElement).open).toBe(false);
});
it('keeps differing model rule predicates and unknown legacy revisions separate despite identical prose',()=>{
 const source={citation_id:'K1',record_id:'r',revision:'v1',text:'相同正文',rule:{scope:{any:[['width','eq',32],['width','eq',64]]},predict:{lower_better:'lr'}}};
 const {container}=render(<ModelSources result={{used_sources:[source,{...source,citation_id:'K2',revision:'v2',rule:{...source.rule,scope:{all:source.rule.scope.any}}},
  {citation_id:'K3',record_id:'legacy',revision:'v1',text:'旧正文'},{citation_id:'K4',record_id:'legacy',revision:'v2',text:'旧正文'}]}}/>);
 expect(container.querySelectorAll('.task-model-source')).toHaveLength(4);
});
it('keeps rule identity scoped to the saved KB along each deduction path',()=>{
 const edges=[{kb:{id:'kb-one',version:'v1',name:'第一份知识'},winner:A,loser:B,rules:[rule]},
  {kb:{id:'kb-two',version:'v9',name:'第二份知识'},winner:A,loser:C,rules:[{...rule,claim_ids:['C999']}]}];
 const paths=[{kb_id:'kb-one',candidates:[A,B],rule_refs:[{rule_id:rule.rule_id,revision:rule.revision}]},
  {kb_id:'kb-two',candidates:[A,C],rule_refs:[{rule_id:rule.rule_id,revision:rule.revision}]}];
 render(<RuleReasoning value={{edges,paths}}/>);
 const first=screen.getByText('A → B').parentElement!,second=screen.getByText('A → C').parentElement!;
 expect(first.textContent).toContain('C001');expect(first.textContent).not.toContain('C999');
 expect(second.textContent).toContain('C999');expect(second.textContent).not.toContain('C001');
 expect(first.textContent).toContain('第一份知识');expect(second.textContent).toContain('第二份知识');
 expect(first.textContent).not.toContain('kb-one@v1');expect(second.textContent).not.toContain('kb-two@v9');
 expect(screen.getByText('kb-one@v1').closest('details')).toBeTruthy();expect(screen.getByText('kb-two@v9').closest('details')).toBeTruthy();
});
it('shows stored negative and unknown predicate results without inferring truth from the values',()=>{
 const role={expression:'非（residual = true）',passed:true,facts:[{field:'residual',operator:'eq',expected:true,value:false,passed:false}]};
 render(<RuleReasoning value={{edges:[{winner:A,loser:B,rules:[{...rule,conditions:[{label:'历史条件',expression:'lr < 0',passed:false,facts:[{field:'lr',winner_value:0,loser_value:1}]}],prediction:{winner_condition:role}}]}]}}/>);
 expect(screen.getByText('整体条件不成立')).toBeTruthy();expect(screen.getByText('非（residual = true）')).toBeTruthy();
 expect(screen.getByText('子条件不满足')).toBeTruthy();expect(screen.getByText('no')).toBeTruthy();
 expect(screen.getAllByText('子条件判定未记录')).toHaveLength(2);
});
it('leaves ambiguous historical KB versions explicit instead of assigning a path to a claim from another version',()=>{
 const edges=[{kb:{id:'same-kb',version:'v1'},winner:A,loser:B,rules:[rule]},
  {kb:{id:'same-kb',version:'v2'},winner:A,loser:C,rules:[{...rule,claim_ids:['C999']}]}];
 render(<RuleReasoning value={{edges,paths:[{kb_id:'same-kb',candidates:[A,B],rule_refs:[{rule_id:rule.rule_id,revision:rule.revision}]}]}}/>);
 const path=screen.getByText('A → B').parentElement!;
 expect(path.textContent).toContain('KB 版本归属未记录');expect(path.textContent).toContain(rule.rule_id);
 expect(path.textContent).not.toContain('C001');expect(path.textContent).not.toContain('C999');
 expect(screen.getByText('same-kb@v1')).toBeTruthy();expect(screen.getByText('same-kb@v2')).toBeTruthy();
});
it('omits missing compact configuration values while preserving explicit zero momentum and false switches',()=>{
 const question={choices:[{...A,view:{model_type:'mlp',num_layers:null,d_model:null,layer_norm:[false,true],residual:false,opt_key:JSON.stringify({type:'SGD',momentum:0})}},B]};
 render(<RuleReasoning question={question} value={{edges:[{winner:A,loser:B,rules:[rule]}]}}/>);
 const summary=screen.getByLabelText('候选 A 的冻结配置');
 expect(within(summary).queryByText('层数')).toBeNull();expect(within(summary).queryByText('表示维度')).toBeNull();
 expect(within(summary).getByText('动量')).toBeTruthy();expect(within(summary).getByText('0')).toBeTruthy();
 expect(within(summary).getByText('no')).toBeTruthy();expect(within(summary).getByText('(no, yes)')).toBeTruthy();
});
