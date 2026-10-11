import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,cleanup,fireEvent,waitFor} from '@testing-library/react';
import {Workflow} from './Workflow';
import {SharedWorkflowDraftProvider} from './SharedWorkflowDraft';
import {WorkflowWorkspace} from './WorkflowWorkspace';
import {KB} from './KB';
import {Runs} from './Runs';
import fixture from './ruleWorkflowFixture.json';
vi.mock('./ResearchPathCanvas',()=>({ResearchPathCanvas:({nodes,onSelect,inspector}:any)=><section><nav>{nodes.map((node:any)=><button key={node.id} onClick={()=>onSelect(node.id)}>{node.label}</button>)}</nav>{inspector}</section>}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const act=async(fn:()=>Promise<any>)=>fn();
it('loads a v2 shared draft, survives refresh, and switches through server templates',async()=>{
 let draft:any={workflow:structuredClone(fixture),advanced_backup:null,revision:1,updated_at:1};const writes:any[]=[];const gets:string[]=[];
 const basic={schema_version:1,name:'单题学习',nodes:[],edges:[],settings:{method_id:'basic_learning',question_set_id:'saved'}};
 vi.stubGlobal('fetch',async(path:string,init:any)=>{const url=new URL(path,'http://test');let result:any={items:[],total:0};gets.push(path);
 if(url.pathname.endsWith('/workflow/draft')){if(init?.method==='PUT'){const b=JSON.parse(init.body);writes.push(b);draft={...b,revision:draft.revision+1,updated_at:2};}result=draft;}
 else if(url.pathname.endsWith('/workflow/default'))result=url.searchParams.get('method_id')==='basic_learning'?basic:fixture;
 else if(url.pathname.endsWith('/methods'))result={items:[{id:'rule_refinement',name:'规则 KB 闭环',status:'available',learning_protocol:'rule_refinement_v1',data_modes:['single','pairs']},{id:'basic_learning',name:'单题学习',status:'available',learning_protocol:'basic_learning'}]};
 return new Response(JSON.stringify(result));});
 function App(){return <SharedWorkflowDraftProvider><Workflow version={0} act={act} executionEnabled={false} onRun={()=>{}}/></SharedWorkflowDraftProvider>;}
 const view=render(<App/>);await screen.findByRole('heading',{name:'研究题池'});fireEvent.click(screen.getByRole('button',{name:'新题挑战'}));fireEvent.change(screen.getByLabelText('最大修订尝试'),{target:{value:'9'}});await waitFor(()=>expect(writes.length).toBeGreaterThan(0));expect(draft.workflow.settings.limits.max_revision_attempts).toBe(9);
 view.unmount();render(<App/>);await screen.findByRole('heading',{name:'研究题池'});fireEvent.click(screen.getByRole('button',{name:'新题挑战'}));expect((screen.getByLabelText('最大修订尝试') as HTMLInputElement).value).toBe('9');
 fireEvent.change(screen.getByLabelText('切换学习方法'),{target:{value:'basic_learning'}});await waitFor(()=>expect(gets).toContain('/api/studio/workflow/default?method_id=basic_learning'));expect(writes.every(w=>w.workflow.settings.method_id!=='rule_refinement'||!('question_set_id' in w.workflow.settings))).toBe(true);
});
it('opens a persisted rule run through Harness and never starts on reconnect',async()=>{
 const posts:any[]=[];const run={id:'r',kind:'rule_refinement',status:'complete',config:{name:'规则研究'},created_at:1,refinement:{revision:10,phase:'finish'},result:{outcome:'stopped',stop_reason:'resource_limit',fresh_batches:[]},events:[]};
 vi.stubGlobal('fetch',async(path:string,init:any)=>{if(init?.method==='POST')posts.push(path);return new Response(JSON.stringify(path.endsWith('/runs')?{items:[run],total:1}:run));});
 render(<WorkflowWorkspace selectedRun="r" version={0} act={act}><p>编辑草稿</p></WorkflowWorkspace>);await screen.findByText('资源上限已达到');expect(screen.queryByText('目标已达成')).toBeNull();fireEvent.click(screen.getByRole('tab',{name:'编辑工作流'}));fireEvent.click(screen.getByRole('tab',{name:'运行追踪'}));await screen.findByText('资源上限已达到');expect(posts).toEqual([]);
});
it('carries a frozen rule KB from knowledge reading into a model-free Task',async()=>{
 const record={id:'kb',version:'v',kind:'research_rules',name:'我的研究规则',snapshot:{version:'v',rules:[]},sources:[]};vi.stubGlobal('fetch',async(path:string)=>new Response(JSON.stringify(path.endsWith('/kb')?{items:[record]}:{items:[],total:0})));
 const onEvaluate=vi.fn();const view=render(<KB version={0} onEvaluate={onEvaluate}/>);fireEvent.click(await screen.findByRole('button',{name:'阅读 我的研究规则'}));fireEvent.click(await screen.findByRole('button',{name:'在 Task 中检查此规则 KB'}));expect(onEvaluate).toHaveBeenCalledWith({id:'kb',version:'v'});view.unmount();
 render(<Runs version={0} act={act} executionEnabled={false} ruleKB={{id:'kb',version:'v'}} onRun={()=>{}}/>);await screen.findByLabelText('待评测规则 KB');expect(screen.queryByRole('button',{name:'提交模型评测'})).toBeNull();expect(screen.getByRole('button',{name:'开始规则评测'})).toBeTruthy();
});
