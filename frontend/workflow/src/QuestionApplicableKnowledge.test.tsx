import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {QuestionApplicableKnowledge} from './QuestionApplicableKnowledge';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const source={kind:'catalog' as const,key:'q@one'};
it('shows public applicable rule content and conditions without rendering stored results',async()=>{
 const fetch=vi.fn(async(_path:string,_options?:RequestInit)=>new Response(JSON.stringify({scope:'public_applicability',feedback_released:false,items:[{kb:{id:'kb',version:'v1',name:'优化器规则',kind:'research_rules'},rules:[{rule_id:'C1',revision:1,text:'适应性优化器的步长规则',conditions:['适用范围：MLP'],matched_pairs:[{candidates:[{id:'a',letter:'A'},{id:'b',letter:'B'}],reasons:['model.type = mlp']}],correct_answer:'SECRET',evidence:[{winner:'SECRET'}]}]}],total:1})));
 vi.stubGlobal('fetch',fetch);
 render(<QuestionApplicableKnowledge source={source} knowledgeRef={{id:'kb',version:'v1'}}/>);
 expect(await screen.findByText('适应性优化器的步长规则')).toBeTruthy();
 const details=screen.getByText('适应性优化器的步长规则').closest('details')!;
 expect(details.open).toBe(false);
 expect(within(details).getByText('适用候选：A、B')).toBeTruthy();
 fireEvent.click(within(details).getByText('适应性优化器的步长规则'));
 expect(screen.getByText('适用范围：MLP')).toBeTruthy();
 expect(screen.getByText('model.type = mlp')).toBeTruthy();
 expect(document.body.textContent).not.toContain('SECRET');
 expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({source,knowledge_ref:{id:'kb',version:'v1'}});
});

it('folds only proven equivalent public rules and matching candidate reasons, with every source inside the closed details',async()=>{
 const rule={rule_id:'O1',revision:'r1',text:'同正文规则',rule:{scope:[['opt','eq','Adam']],predict:{higher_better:'lr'}},validity_status:'proposed',conditions:['优化器相同'],matched_pairs:[{candidates:[{id:'a',letter:'A'},{id:'b',letter:'B'}],reasons:['满足公开比较条件']} ]};
 const copy={...rule,rule_id:'C1',revision:'r2',rule:{predict:{higher_better:'lr'},scope:[['opt','eq','Adam']]}};
 const items=[{kb:{id:'imported',version:'v10',name:'导入来源'},rules:[rule]},{kb:{id:'evolution',version:'ev3',name:'演化来源'},rules:[copy]}];
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items,total:2,scope:'public_applicability',feedback_released:false})));
 render(<QuestionApplicableKnowledge source={source}/>);
 await screen.findByText('同正文规则');
 expect(screen.getByText('1 条')).toBeTruthy();
 expect(screen.getAllByText('同正文规则')).toHaveLength(1);
 const details=screen.getByText('同正文规则').closest('details')!;
 expect(details.open).toBe(false);
 expect(within(details).getByText('适用候选：A、B')).toBeTruthy();
 expect(within(details).getByText('导入来源')).toBeTruthy();
 expect(within(details).getByText('演化来源')).toBeTruthy();
 expect(within(details).getByText('v10 · O1 · r1')).toBeTruthy();
 expect(within(details).getByText('ev3 · C1 · r2')).toBeTruthy();
 expect(document.body.textContent).not.toMatch(/A\s*[>＞]\s*B/);
});

it.each(['missing_rule','changed_rule','changed_reasons','changed_candidate_identity'])('keeps %s applicability records separate',async(change)=>{
 const first={rule_id:'R1',revision:'r1',text:'同正文规则',rule:{predict:{higher_better:'lr'}},conditions:['显示条件'],matched_pairs:[{candidates:[{id:'a',letter:'A'},{id:'b',letter:'B'}],reasons:['公开条件']} ]};
 const second:any=JSON.parse(JSON.stringify(first));second.rule_id='R2';
 if(change==='missing_rule')delete second.rule;
 if(change==='changed_rule')second.rule.predict.higher_better='depth';
 if(change==='changed_reasons')second.matched_pairs[0].reasons=['不同匹配原因'];
 if(change==='changed_candidate_identity')second.matched_pairs[0].candidates[0].id='other';
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[{kb:{id:'kb',version:'v1'},rules:[first,second]}],total:1})));
 render(<QuestionApplicableKnowledge source={source}/>);
 expect(await screen.findAllByText('同正文规则')).toHaveLength(2);
 expect(screen.getByText('2 条')).toBeTruthy();
});
it('ignores a stale response when the public question changes',async()=>{
 let finish:(value:Response)=>void=()=>{};
 vi.stubGlobal('fetch',vi.fn().mockImplementationOnce(()=>new Promise<Response>(resolve=>{finish=resolve;})).mockImplementationOnce(async()=>new Response(JSON.stringify({items:[],total:0,notice:'当前没有满足条件的规则。'}))));
 const view=render(<QuestionApplicableKnowledge source={source}/>);
 view.rerender(<QuestionApplicableKnowledge source={{kind:'catalog',key:'q@two'}}/>);
 expect(await screen.findByText('当前没有满足条件的规则。')).toBeTruthy();
 finish(new Response(JSON.stringify({items:[{kb:{id:'old',version:'1'},rules:[{text:'旧题目的规则'}]}],total:1})));
 await waitFor(()=>expect(screen.queryByText('旧题目的规则')).toBeNull());
});
it('reuses the match when the parent rerenders the same source and version',async()=>{
 const fetch=vi.fn(async()=>new Response(JSON.stringify({items:[],total:0})));vi.stubGlobal('fetch',fetch);
 const view=render(<QuestionApplicableKnowledge source={source} knowledgeRef={{id:'kb',version:'v1'}}/>);
 await screen.findByText('当前没有满足条件的规则。');
 view.rerender(<QuestionApplicableKnowledge source={{...source}} knowledgeRef={{id:'kb',version:'v1'}}/>);
 expect(fetch).toHaveBeenCalledTimes(1);
});
