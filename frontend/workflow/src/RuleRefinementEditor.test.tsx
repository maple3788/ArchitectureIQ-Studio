import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import {useState} from 'react';
import {RuleRefinementEditor} from './RuleRefinementEditor';
import fixture from './ruleWorkflowFixture.json';
import type {Workflow} from './types';
vi.mock('./RuleRefinementCanvas',()=>({RuleRefinementCanvas:()=> <div>材料画布</div>}));
vi.mock('./DatasetInputPicker',()=>({DatasetInputPicker:({onApply,selectionMode}:any)=><button onClick={()=>onApply({dataset_binding:{collection_id:'ds',revision:'rev',keys:['q1','q2'],hashes:['h1','h2'],selection:{},pair_keys:selectionMode==='pairs'?['p1']:[]}})}>应用整库</button>}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const bootstrap:any={service:{execution_enabled:true},models:[{id:'m',name:'修订服务',enabled:true}],capabilities:{profiles:[{name:'v1.4',budgets:[4096],families:[{name:'univariate_regression',form_schema:{editable_fields:[]}}]}]}};
function setup(complete=false,omitDefaults=false){
 const calls:any[]=[];
 vi.stubGlobal('fetch',async(path:string,init:any)=>{const body=init?.body&&JSON.parse(init.body);calls.push({path,body,headers:init?.headers});let value:any={};
 if(path.endsWith('/kb'))value={items:[{id:'kb',version:'v',name:'研究规则',kind:'research_rules'}]};
 if(path.endsWith('/match?offset=0&limit=25'))value={total:2,matched_count:2,items:[{status:'conflict',question_ref:{key:'q1'},edges:[],paths:[]},{status:'answered',answer_id:'a',question_ref:{key:'q2'},edges:[],paths:[]}],cases:[]};
 if(path.endsWith('/preview'))value={can_run:true,preview_hash:'hash',counts:{questions:2,pairs:0},cost:{candidate_seed_runs_per_batch:48},blockers:[]};
 if(path.endsWith('/runs'))value={id:'run'};
 return new Response(JSON.stringify(value));});
 const flow:Workflow=structuredClone(fixture);if(complete){Object.assign(flow.settings.limits,{max_model_calls:20,max_tokens:10000,max_candidate_seed_runs:500,wall_time_seconds:600});flow.nodes[0].config.dataset_binding={collection_id:'ds',revision:'rev',keys:['q1','q2'],hashes:[],selection:{},pair_keys:[]} as any;flow.nodes[1].config.source={id:'kb',version:'v'} as any;flow.nodes[3].config.model_id='m';}
 if(omitDefaults)flow.settings.limits={max_model_calls:20,max_tokens:10000,max_candidate_seed_runs:500,wall_time_seconds:600};
 const onStarted=vi.fn();function Harness(){const [workflow,onChange]=useState<Workflow>(flow);return <RuleRefinementEditor workflow={workflow} onChange={onChange} bootstrap={bootstrap} onStarted={onStarted}/>;}render(<Harness/>);return {calls,onStarted};
}
it('shows four configuration blocks, default stop limits and no answer model',async()=>{
 setup();await screen.findByRole('option',{name:/研究规则/});
 for(const name of ['研究 Dataset','初始规则 KB','修订模型与提示词','新题方案与限制'])expect(screen.getByRole('heading',{name})).toBeTruthy();
 expect(screen.queryByLabelText('作答模型')).toBeNull();expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('12');
 expect((screen.getByLabelText('连续新批次通过目标') as HTMLInputElement).value).toBe('2');expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('研究材料类型'),{target:{value:'pairs'}});fireEvent.click(screen.getByRole('button',{name:'选择 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用整库'}));expect(screen.getByText(/2 道题 · 1 对/)).toBeTruthy();expect(screen.getByText(/8 对 · 16 道/)).toBeTruthy();
});
it('matches a whole Dataset without selecting models and does not read feedback',async()=>{
 const {calls}=setup();await screen.findByRole('option',{name:/研究规则/});fireEvent.change(screen.getByLabelText('规则 KB'),{target:{value:'kb@v'}});fireEvent.click(screen.getByRole('button',{name:'选择 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用整库'}));fireEvent.click(screen.getByRole('button',{name:'匹配预览'}));await screen.findByText(/本页 2/);
 const match=calls.find(c=>c.path.includes('/match?'));expect(match.body).toEqual({dataset_ref:{collection_id:'ds',revision:'rev'},selection:{},kb_ref:{id:'kb',version:'v'}});expect(screen.getByText('规则冲突')).toBeTruthy();expect(calls.some(c=>c.path.endsWith('/runs'))).toBe(false);
});
it('freezes a preview and invalidates it on model or budget changes',async()=>{
 const {calls,onStarted}=setup(true);await screen.findByRole('option',{name:/研究规则/});fireEvent.click(screen.getByRole('button',{name:'检查运行配置'}));await waitFor(()=>expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(false));
 fireEvent.change(screen.getByLabelText('最大模型调用'),{target:{value:'21'}});expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'检查运行配置'}));await waitFor(()=>expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'开始研究'}));await waitFor(()=>expect(onStarted).toHaveBeenCalledWith('run'));expect(calls.find(c=>c.path.endsWith('/runs')).headers['Idempotency-Key']).toBeTruthy();
});

it('shows server default iteration limits for a valid imported draft with only resource caps',async()=>{setup(false,true);await screen.findByRole('option',{name:/研究规则/});expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('12');expect(screen.getByText(/每批 16 道/)).toBeTruthy();});
