import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import {useState} from 'react';
import {RuleRefinementEditor} from './RuleRefinementEditor';
import fixture from './ruleWorkflowFixture.json';
import type {Workflow} from './types';
vi.mock('./ResearchPathCanvas',()=>({ResearchPathCanvas:({nodes,onSelect,inspector}:any)=><section aria-label="研究路径画布"><nav>{nodes.map((node:any)=><button key={node.id} onClick={()=>onSelect(node.id)}>{node.label}</button>)}</nav><aside>{inspector}</aside></section>}));
vi.mock('./DatasetInputPicker',()=>({DatasetInputPicker:({onApply,selectionMode}:any)=><button onClick={()=>onApply({dataset_binding:{collection_id:'ds',revision:'rev',keys:['q1','q2'],hashes:['h1','h2'],selection:{},pair_keys:selectionMode==='pairs'?['p1']:[]}})}>应用整库</button>}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const bootstrap:any={service:{execution_enabled:true},models:[{id:'m',name:'修订服务',enabled:true}],capabilities:{profiles:[{name:'v1.4',budgets:[4096],families:[{name:'univariate_regression',form_schema:{editable_fields:[]}}]}]}};
it('keeps matching inside verification and resource limits inside acceptance',async()=>{
 const {calls}=setup(true);
 expect(screen.queryByRole('button',{name:'匹配预览'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'程序验证'}));
 fireEvent.click(screen.getByRole('button',{name:'匹配预览'}));
 await screen.findByText(/本页 2/);
 expect(calls.some(c=>c.path.endsWith('/runs'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'不退步验收'}));
 expect((screen.getByLabelText('最大模型调用') as HTMLInputElement).value).toBe('20');
 expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('12');
 fireEvent.click(screen.getByRole('button',{name:'新题挑战'}));
 expect(screen.getByLabelText('新题类型')).toBeTruthy();
 expect(screen.queryByLabelText('最大模型调用')).toBeNull();
});
function setup(complete=false,omitDefaults=false,kbItems?:any[],source?:{id:string;version:string}){
 const calls:any[]=[];
 vi.stubGlobal('fetch',async(path:string,init:any)=>{const body=init?.body&&JSON.parse(init.body);calls.push({path,body,headers:init?.headers});let value:any={};
 if(path.endsWith('/kb'))value={items:kbItems??[{id:'kb',version:'v',name:'研究规则',kind:'research_rules'}]};
 if(path.endsWith('/match?offset=0&limit=25'))value={total:2,matched_count:2,items:[{status:'conflict',question_ref:{key:'q1'},edges:[],paths:[]},{status:'answered',answer_id:'a',question_ref:{key:'q2'},edges:[],paths:[]}],cases:[],context_matches:[{question_ref:{key:'q1'},status:'matched',claim_ids:['R1'],rule_ids:['R1:0'],matches:[{rule_id:'R1:0',claim_id:'R1',winner:'a',loser:'b'}]},{question_ref:{key:'q2'},status:'uncovered',claim_ids:[],rule_ids:[],matches:[]}]};
 if(path.endsWith('/preview'))value={can_run:true,preview_hash:'hash',counts:{questions:2,pairs:0},cost:{candidate_seed_runs_per_batch:48},blockers:[]};
 if(path.endsWith('/runs'))value={id:'run'};
 return new Response(JSON.stringify(value));});
 const flow:Workflow=structuredClone(fixture);if(complete){Object.assign(flow.settings.limits,{max_model_calls:20,max_tokens:10000,max_candidate_seed_runs:500,wall_time_seconds:600});flow.nodes[0].config.dataset_binding={collection_id:'ds',revision:'rev',keys:['q1','q2'],hashes:[],selection:{},pair_keys:[]} as any;flow.nodes[1].config.source={id:'kb',version:'v'} as any;flow.nodes[3].config.model_id='m';}
 if(omitDefaults)flow.settings.limits={max_model_calls:20,max_tokens:10000,max_candidate_seed_runs:500,wall_time_seconds:600};
 if(source)flow.nodes[1].config.source=source;
 const onStarted=vi.fn();function Harness(){const [workflow,onChange]=useState<Workflow>(flow);return <RuleRefinementEditor workflow={workflow} onChange={onChange} bootstrap={bootstrap} onStarted={onStarted}/>;}render(<Harness/>);return {calls,onStarted};
}
it('opens one node configuration at a time and preserves Dataset and stop-limit edits',async()=>{
 setup();
 expect(screen.queryByRole('heading',{name:'研究题池'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'研究题池'}));
 expect(screen.getByRole('heading',{name:'研究题池'})).toBeTruthy();
 expect(screen.queryByLabelText('修订模型')).toBeNull();expect(screen.queryByLabelText('最大修订尝试')).toBeNull();
 expect(screen.queryByLabelText('作答模型')).toBeNull();expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('研究材料类型'),{target:{value:'pairs'}});fireEvent.click(screen.getByRole('button',{name:'选择 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用整库'}));expect(screen.getByText(/2 道题 · 1 对/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'修订规则'}));expect(screen.getByLabelText('修订模型')).toBeTruthy();expect(screen.queryByLabelText('研究材料类型')).toBeNull();
 fireEvent.change(screen.getByLabelText('修订模型'),{target:{value:'m'}});
 fireEvent.click(screen.getByRole('button',{name:'不退步验收'}));expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('12');expect((screen.getByLabelText('连续新批次通过目标') as HTMLInputElement).value).toBe('2');expect(screen.getByText(/8 对 · 16 道/)).toBeTruthy();
 fireEvent.change(screen.getByLabelText('最大修订尝试'),{target:{value:'9'}});
 fireEvent.click(screen.getByRole('button',{name:'研究题池'}));expect(screen.getByText(/2 道题 · 1 对/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'修订规则'}));expect((screen.getByLabelText('修订模型') as HTMLSelectElement).value).toBe('m');
 fireEvent.click(screen.getByRole('button',{name:'不退步验收'}));expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('9');
});
it('matches a whole Dataset without selecting models and does not read feedback',async()=>{
 const {calls}=setup();fireEvent.click(screen.getByRole('button',{name:'初始规则'}));await screen.findByRole('option',{name:/研究规则/});fireEvent.change(screen.getByLabelText('规则 KB'),{target:{value:'kb@v'}});fireEvent.click(screen.getByRole('button',{name:'研究题池'}));fireEvent.click(screen.getByRole('button',{name:'选择 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用整库'}));fireEvent.click(screen.getByRole('button',{name:'程序验证'}));fireEvent.click(screen.getByRole('button',{name:'匹配预览'}));await screen.findByText(/本页 2/);
 const match=calls.find(c=>c.path.includes('/match?'));expect(match.body).toEqual({dataset_ref:{collection_id:'ds',revision:'rev'},selection:{},kb_ref:{id:'kb',version:'v'}});expect(screen.getByText('规则冲突')).toBeTruthy();expect(calls.some(c=>c.path.endsWith('/runs'))).toBe(false);
});
it('freezes a preview and invalidates it on model or budget changes',async()=>{
 const {calls,onStarted}=setup(true);fireEvent.click(screen.getByRole('button',{name:'不退步验收'}));fireEvent.click(screen.getByRole('button',{name:'检查运行配置'}));await waitFor(()=>expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(false));
 fireEvent.change(screen.getByLabelText('最大模型调用'),{target:{value:'21'}});expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'检查运行配置'}));await waitFor(()=>expect((screen.getByRole('button',{name:'开始研究'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'开始研究'}));await waitFor(()=>expect(onStarted).toHaveBeenCalledWith('run'));expect(calls.find(c=>c.path.endsWith('/runs')).headers['Idempotency-Key']).toBeTruthy();
});

it('shows server default iteration limits for a valid imported draft with only resource caps',async()=>{setup(false,true);fireEvent.click(screen.getByRole('button',{name:'不退步验收'}));expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('12');expect(screen.getByText(/每批 16 道/)).toBeTruthy();});

it('retains the selected built-in rule version and its status when moving between nodes',async()=>{
 const kbItems=['v9','v10'].map(v=>({id:'builtin:kb-'+v,version:'hash-'+v,name:'KB '+v,kind:'research_rules',library:{id:'builtin:architecture-rules',name:'架构与优化器规则',version_order:Number(v.slice(1))},snapshot:{parent_version:'parent',source_document:{version_label:v,filename:'kb_'+v+'_revision.json'},rules:[{rule_id:'R1:0',state:'active',metadata:{claim_id:'R1',validity_status:'proposed',validation_origin:'source_reported'},rule:{predict:{higher_better:'width'}}}]}}));
 const {calls}=setup(false,false,kbItems);
 fireEvent.click(screen.getByRole('button',{name:'初始规则'}));await screen.findByRole('option',{name:'架构与优化器规则'});
 expect(screen.getAllByRole('option',{name:'架构与优化器规则'})).toHaveLength(1);
 expect(screen.queryByRole('option',{name:/KB v9|KB v10|hash-/})).toBeNull();
 fireEvent.change(screen.getByLabelText('规则 KB'),{target:{value:'builtin:kb-v10@hash-v10'}});
 expect(screen.getByText(/1 条待独立确认/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'研究题池'}));fireEvent.click(screen.getByRole('button',{name:'选择 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用整库'}));
 fireEvent.click(screen.getByRole('button',{name:'初始规则'}));expect((screen.getByLabelText('规则 KB') as HTMLSelectElement).value).toBe('builtin:kb-v10@hash-v10');
 fireEvent.click(screen.getByRole('button',{name:'程序验证'}));fireEvent.click(screen.getByRole('button',{name:'匹配预览'}));await screen.findByText(/本页 2/);
 expect(calls.find(c=>c.path.includes('/match?')).body.kb_ref).toEqual({id:'builtin:kb-v10',version:'hash-v10'});
 expect(screen.getByText('模型参考匹配：1 条主张 · R1')).toBeTruthy();
 expect(screen.getByText('规则冲突')).toBeTruthy();
 expect(screen.getByText(/参考匹配不代表程序答案/)).toBeTruthy();
});

it('keeps an older saved KB binding without silently upgrading it to the current library',async()=>{
 const source={id:'builtin:kb-v9',version:'hash-v9'};
 const kbItems=[9,10].map(order=>({id:`builtin:kb-v${order}`,version:`hash-v${order}`,name:`KB v${order}`,kind:'research_rules',library:{id:'arch',name:'架构与优化器规则',version_order:order}}));
 const {calls}=setup(true,false,kbItems,source);
 fireEvent.click(screen.getByRole('button',{name:'初始规则'}));
 await screen.findByRole('option',{name:'架构与优化器规则'});
 expect((screen.getByLabelText('规则 KB') as HTMLSelectElement).value).toBe('builtin:kb-v9@hash-v9');
 expect(screen.getAllByRole('option',{name:'架构与优化器规则'})).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'程序验证'}));fireEvent.click(screen.getByRole('button',{name:'匹配预览'}));
 await screen.findByText(/本页 2/);
 expect(calls.find(c=>c.path.includes('/match?')).body.kb_ref).toEqual(source);
});
