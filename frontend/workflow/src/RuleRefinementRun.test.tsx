import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {render,screen,cleanup,fireEvent,waitFor,within} from '@testing-library/react';
import {RuleRefinementRun} from './RuleRefinementRun';
import {deriveRuleRefinementView,retainRuleRun} from './ruleRefinementView';
import type {Run} from './types';
beforeEach(()=>{
 vi.stubGlobal('ResizeObserver',class{
  pending=new Map<Element,ReturnType<typeof setTimeout>>();
  constructor(private callback:ResizeObserverCallback){}
  observe(target:Element){this.pending.set(target,setTimeout(()=>this.callback([{target,contentRect:{width:240,height:150}} as ResizeObserverEntry],this as unknown as ResizeObserver),0));}
  unobserve(target:Element){clearTimeout(this.pending.get(target));this.pending.delete(target);}
  disconnect(){for(const timer of this.pending.values())clearTimeout(timer);this.pending.clear();}
 });
 vi.stubGlobal('DOMMatrixReadOnly',class{m22=1;});
 Object.defineProperty(SVGElement.prototype,'getBBox',{configurable:true,value:()=>({x:0,y:0,width:100,height:16})});
 vi.spyOn(HTMLElement.prototype,'offsetWidth','get').mockReturnValue(240);
 vi.spyOn(HTMLElement.prototype,'offsetHeight','get').mockReturnValue(150);
});
afterEach(()=>{cleanup();Reflect.deleteProperty(SVGElement.prototype,'getBBox');vi.restoreAllMocks();vi.unstubAllGlobals();});
export const score={selected:3,scorable:3,unscorable:0,correct:3,answered:3,conflicts:0,wrong_assertions:0,all_pass:true,accuracy:1,answer_coverage:1,per_question:{},per_rule:{},problems:[]};
export const run:Run={id:'r',kind:'rule_refinement',status:'complete',created_at:1,config:{},transport:{stream:false},refinement:{revision:8,phase:'finish',kb_version:'kb1',pool_version:'pool1',fresh_passes:1},result:{outcome:'stopped',stop_reason:'budget_exhausted',score,fresh_batches:[{batch_id:'b1',index:1,actual:3,requested:3,batch_passed:false,first_score:{...score,correct:2,all_pass:false}},{batch_id:'b2',index:2,actual:3,requested:3,batch_passed:true,first_score:score}]},events:[]};
it('does_not_label_budget_stop_as_success',()=>{render(<RuleRefinementRun run={run} act={async f=>f()}/>);expect(screen.getByText('资源上限已达到')).toBeTruthy();expect(screen.queryByText('目标已达成')).toBeNull();expect(screen.getByText('累计研究池')).toBeTruthy();});
it('keeps_all_first_test_scores_after_later_success',()=>{render(<RuleRefinementRun run={{...run,result:{...run.result,outcome:'target_reached',stop_reason:'target_reached'}}} act={async f=>f()}/>);fireEvent.click(screen.getByRole('tab',{name:'首测历史'}));expect(screen.getByText('2 / 3')).toBeTruthy();expect(screen.getByText('3 / 3')).toBeTruthy();expect(screen.getAllByText(/原始首测/).length).toBeGreaterThan(0);});
it('does_not_invent_model_text_for_rule_execution',()=>{render(<RuleRefinementRun run={{...run,status:'running',result:undefined,refinement:{...run.refinement,phase:'baseline'}}} act={async f=>f()}/>);expect(screen.queryByLabelText('模型实时输出')).toBeNull();expect(screen.getByText('等待已封存的评分记录')).toBeTruthy();expect(deriveRuleRefinementView({...run,result:undefined,refinement:undefined,events:[]}).phase).toBe('等待运行记录');});
it('reconnect_deduplicates_events_without_starting_run',()=>{const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);const event={sequence:1,node_id:'verify'};const newer={...run,events:[event,event],refinement:{...run.refinement,revision:10}};const view=deriveRuleRefinementView(newer);expect(view.events).toHaveLength(1);expect(retainRuleRun(newer,{...run,refinement:{revision:9},status:'running'})).toBe(newer);render(<RuleRefinementRun run={newer} act={async f=>f()}/>);expect(fetcher).not.toHaveBeenCalled();});
it('reads rejected proposal evidence without selecting it as current KB',async()=>{vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({kind:'decision',value:{accepted:false,reason:'regression',regressed:['q1']}})));render(<RuleRefinementRun run={{...run,artifacts:[{id:'a1',kind:'decision',label:'版本验收'}]}} act={async f=>f()}/>);fireEvent.click(screen.getByRole('tab',{name:'版本与验收'}));fireEvent.click(screen.getByRole('button',{name:'版本验收'}));await waitFor(()=>expect(screen.getByText('已答对的题目退步')).toBeTruthy());expect(screen.queryByRole('button',{name:'接受此 KB'})).toBeNull();});
it('offers backend verification for an uncertain run without a final result',async()=>{
 const fetcher=vi.fn(async(_input:RequestInfo|URL,_init?:RequestInit)=>new Response(JSON.stringify({status:'queued'})));vi.stubGlobal('fetch',fetcher);
 const {rerender}=render(<RuleRefinementRun run={{...run,status:'uncertain',result:undefined,refinement:{...run.refinement,phase:'revise'}}} act={async f=>f()}/>);
 fireEvent.click(screen.getByRole('button',{name:'核验并恢复'}));
 await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
 expect(String(fetcher.mock.calls[0][0])).toContain('/rule-refinement/runs/r/recover');
 rerender(<RuleRefinementRun run={{...run,status:'uncertain'}} act={async f=>f()}/>);
 expect(screen.queryByRole('button',{name:'核验并恢复'})).toBeNull();
});

it('opens retained first-test evidence and current feedback from the run canvas without starting work',async()=>{
 const fetched:{url:string;method:string;body:any}[]=[];vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{fetched.push({url,method:init?.method??'GET',body:init?.body?JSON.parse(String(init.body)):undefined});return new Response(JSON.stringify(url.endsWith('/questions/applicable-knowledge')?{scope:'public_applicability',items:[],total:0,feedback_released:false}:url.endsWith('/questions/inspect')?{scope:'human_inspection',correct_answer:{id:'b',letter:'B'},feedback:{correct_letter:'B',reveal:{curves:[]}}}:{}));});
 const row={scorable:true,correct:false,prediction:{status:'conflict',edges:[],paths:{}},case:{ref:{key:'q1',hash:'h1'},question:{id:'conflicting-case',prompt:'A retained research question',choices:[{id:'a',letter:'A'},{id:'b',letter:'B'}]},dataset_spec:{},candidate_specs:[]}};
 const current={...score,correct:2,conflicts:1,all_pass:false,per_question:{q1:row},problems:[{type:'conflict',question_ref:{key:'q1'}}]};
 render(<RuleRefinementRun run={{...run,result:{...run.result,score:current,fresh_batches:[{batch_id:'b1',index:1,actual:3,requested:3,batch_passed:false,first_score:current}]}}} act={async f=>f()}/>);
 const canvas=screen.getByRole('region',{name:'规则闭环画布'});
 fireEvent.click(await within(canvas).findByRole('button',{name:'新题挑战'}));
 expect(screen.getByRole('tab',{name:'首测历史'}).getAttribute('aria-selected')).toBe('true');
 fireEvent.click(screen.getByRole('button',{name:'阅读此批题目与证据'}));
 expect(screen.getByLabelText('查看题目').textContent).toContain('conflicting-case');
 fireEvent.click(within(canvas).getByRole('button',{name:'错题反馈'}));
 expect(screen.getByRole('tab',{name:'当前结果'}).getAttribute('aria-selected')).toBe('true');
 fireEvent.change(screen.getByLabelText('问题分类'),{target:{value:'conflict'}});
 expect(screen.getByLabelText('查看题目').textContent).toContain('conflicting-case');
 expect(screen.getByRole('heading',{name:'规则如何得出结论'})).toBeTruthy();
 await screen.findByText('正确答案');
 const inspections=fetched.filter(call=>call.url==='/api/studio/questions/inspect');
 expect(inspections.length).toBeGreaterThan(0);
 for(const call of inspections)expect(call).toEqual({url:'/api/studio/questions/inspect',method:'POST',body:{source:{kind:'catalog',key:'q1'}}});
 expect(fetched.filter(call=>!['/api/studio/questions/applicable-knowledge','/api/studio/questions/inspect'].includes(call.url))).toEqual([]);
 expect(screen.queryByRole('radio')).toBeNull();
});

it('opens revision calls and rejected acceptance evidence from their stages',async()=>{
 const requested: string[]=[];
 vi.stubGlobal('fetch',async(url:string)=>{requested.push(url);return new Response(JSON.stringify({id:'rejected',kind:'decision',label:'版本验收',value:{accepted:false,reason:'regression',regressed:['q1']}}));});
 render(<RuleRefinementRun run={{...run,events:[{sequence:1,node_id:'revise',phase:'revise',operation_key:'revise-2'},{sequence:2,node_id:'initialize',phase:'initialize',operation_key:'initialize-1'}],artifacts:[{id:'rejected',kind:'decision',label:'版本验收'},{id:'proposal',kind:'proposal',label:'候选规则提案'}]}} act={async f=>f()}/>);
 const canvas=screen.getByRole('region',{name:'规则闭环画布'});
 fireEvent.click(await within(canvas).findByRole('button',{name:'修订规则'}));
 expect((screen.getByLabelText('已保存模型调用') as HTMLSelectElement).value).toBe('revise-2');
 expect(screen.getByRole('button',{name:'候选规则提案'})).toBeTruthy();
 fireEvent.click(within(canvas).getByRole('button',{name:'不退步验收'}));
 fireEvent.click(screen.getByRole('button',{name:'版本验收'}));
 expect(await screen.findByText('已答对的题目退步')).toBeTruthy();
 expect(requested).toHaveLength(1);
 expect(requested[0]).toContain('/artifacts/rejected');
 expect(screen.queryByRole('button',{name:'接受此 KB'})).toBeNull();
});

it('keeps evaluation results outside the refinement controller canvas',()=>{
 render(<RuleRefinementRun run={{...run,kind:'rule_evaluation',refinement:undefined,result:{score,independence:'verified_first_use'}}} act={async f=>f()}/>);
 expect(screen.getByRole('heading',{name:'固定评测题集'})).toBeTruthy();
 expect(screen.queryByRole('region',{name:'规则闭环画布'})).toBeNull();
 expect(screen.queryByRole('tab',{name:'首测历史'})).toBeNull();
});
