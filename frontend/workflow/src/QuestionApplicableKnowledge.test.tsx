import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import {QuestionApplicableKnowledge} from './QuestionApplicableKnowledge';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const source={kind:'catalog' as const,key:'q@one'};
it('shows public applicable rule content and conditions without rendering stored results',async()=>{
 const fetch=vi.fn(async(_path:string,_options?:RequestInit)=>new Response(JSON.stringify({scope:'public_applicability',feedback_released:false,items:[{kb:{id:'kb',version:'v1',name:'优化器规则',kind:'research_rules'},rules:[{rule_id:'C1',revision:1,text:'适应性优化器的步长规则',conditions:['适用范围：MLP'],matched_pairs:[{candidates:[{id:'a',letter:'A'},{id:'b',letter:'B'}],reasons:['model.type = mlp']}],correct_answer:'SECRET',evidence:[{winner:'SECRET'}]}]}],total:1})));
 vi.stubGlobal('fetch',fetch);
 render(<QuestionApplicableKnowledge source={source} knowledgeRef={{id:'kb',version:'v1'}}/>);
 expect(await screen.findByText('适应性优化器的步长规则')).toBeTruthy();
 expect(screen.getByText('适用范围：MLP')).toBeTruthy();
 expect(screen.getByText('model.type = mlp')).toBeTruthy();
 expect(document.body.textContent).not.toContain('SECRET');
 expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({source,knowledge_ref:{id:'kb',version:'v1'}});
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
