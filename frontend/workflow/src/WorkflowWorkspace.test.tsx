import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act as reactAct, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkflowWorkspace } from "./WorkflowWorkspace";
import { Workflow } from './Workflow';
import { SharedWorkflowDraftProvider, useWorkflowDraft } from './SharedWorkflowDraft';
import { useWorkflowRun } from "./LiveWorkflowCanvas";
function FrozenRun(){const {run}=useWorkflowRun();return run?<div data-testid="run-graph">{run.id} · {run.status} · {run.config.workflow.name}</div>:null;}

vi.mock("./RunWorkflowView", () => ({ RunWorkflowView: ({ run }: any) => <div data-testid="run-graph">{run.id} · {run.status} · {run.config.workflow.name}</div> }));
beforeEach(()=>{
 vi.stubGlobal('localStorage',{getItem:()=>null,removeItem:()=>{}});
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
afterEach(() => { cleanup(); Reflect.deleteProperty(SVGElement.prototype,'getBBox'); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const run = (id: string, status: string) => ({ id, kind: "workflow", status, created_at: 1791529737,
  config: { name: id, workflow: { name: "冻结版本 " + id, nodes: [], edges: [], settings: {} } }, events: [], records: [] });

it("opens the requested frozen run without submitting a job, and retains the editor across modes", async () => {
  const submitted: unknown[] = [];
  const one = run("run-one", "failed"), two = run("run-two", "complete");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") submitted.push(init);
    return new Response(JSON.stringify(url.endsWith("/runs") ? { items: [two, one], total: 2 } : url.endsWith("run-one") ? one : two));
  }));
  render(<WorkflowWorkspace selectedRun="run-one" version={0} act={async op=>op()}>
    <FrozenRun/><input aria-label="编辑中的草稿" defaultValue="未提交的设置" />
  </WorkflowWorkspace>);
  expect((await screen.findByTestId("run-graph")).textContent).toContain("run-one · failed · 冻结版本 run-one");
  expect(await screen.findByText(/连接正常/)).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "编辑工作流" }));
  fireEvent.change(screen.getByLabelText("编辑中的草稿"), { target: { value: "保留这一版" } });
  fireEvent.click(screen.getByRole("tab", { name: "运行追踪" }));
  await screen.findByTestId("run-graph");
  fireEvent.change(screen.getByLabelText("追踪的工作流运行"), { target: { value: "run-two" } });
  await waitFor(()=>expect(screen.getByTestId("run-graph").textContent).toContain("run-two · complete"));
  fireEvent.click(screen.getByRole("tab", { name: "编辑工作流" }));
  expect((screen.getByLabelText("编辑中的草稿") as HTMLInputElement).value).toBe("保留这一版");
  expect(submitted).toEqual([]);
});

it("explains an empty run history without fabricating progress", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }))));
  render(<WorkflowWorkspace version={0} act={async op=>op()}><FrozenRun/><span>草稿</span></WorkflowWorkspace>);
  fireEvent.click(screen.getByRole("tab", { name: "运行追踪" }));
  expect(await screen.findByText("还没有工作流运行")).toBeTruthy();
  expect(screen.queryByTestId("run-graph")).toBeNull();
});

it("keeps the current run pinned when a newly created run appears in the list", async () => {
  const one = run("run-one", "failed"), two = run("run-two", "running");
  let listed = [one];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.endsWith("/runs") ? { items: listed, total: listed.length } : url.endsWith("run-one") ? one : two))));
  const view = render(<WorkflowWorkspace version={0} act={async op=>op()}><FrozenRun/><span>草稿</span></WorkflowWorkspace>);
  fireEvent.click(screen.getByRole("tab", { name: "运行追踪" }));
  expect((await screen.findByTestId("run-graph")).textContent).toContain("run-one");
  listed = [two, one];
  view.rerender(<WorkflowWorkspace version={1} act={async op=>op()}><FrozenRun/><span>草稿</span></WorkflowWorkspace>);
  await screen.findByRole("option", { name: /run-two/ });
  expect((screen.getByLabelText("追踪的工作流运行") as HTMLSelectElement).value).toBe("run-one");
  expect(screen.getByTestId("run-graph").textContent).toContain("run-one");
});

it("preserves an edited draft while tracking a refinement and exposes one set of backend controls", async () => {
 const refinement={id:'refinement',kind:'rule_refinement',status:'running',created_at:1,config:{name:'保存的闭环'},transport:{stream:false},refinement:{phase:'candidate_check',revision:4,kb_version:'accepted-kb'},events:[]};
 const submitted:string[]=[];
 vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{if(init?.method&&init.method!=='GET')submitted.push(url);return new Response(JSON.stringify(url.endsWith('/runs')?{items:[refinement],total:1}:refinement));});
 render(<WorkflowWorkspace version={0} act={async op=>op()}><input aria-label="编辑中的草稿" defaultValue="下一次研究"/></WorkflowWorkspace>);
 fireEvent.change(screen.getByLabelText('编辑中的草稿'),{target:{value:'未提交的修订'}});
 fireEvent.click(screen.getByRole('tab',{name:'运行追踪'}));
 expect(await screen.findByRole('region',{name:'规则闭环画布'})).toBeTruthy();
 expect(screen.getAllByRole('button',{name:'暂停研究'})).toHaveLength(1);
 expect(screen.queryByRole('button',{name:'暂停'})).toBeNull();
 expect(screen.queryByRole('textbox',{name:'编辑中的草稿'})).toBeNull();
 fireEvent.click(screen.getByRole('tab',{name:'编辑工作流'}));
 expect((screen.getByLabelText('编辑中的草稿') as HTMLInputElement).value).toBe('未提交的修订');
 expect(submitted).toEqual([]);
});

it('leaves the draft editor unmounted when opening a refinement history directly',async()=>{
 const refinement={id:'history',kind:'rule_refinement',status:'complete',created_at:1,config:{name:'保存的研究'},transport:{stream:false},refinement:{phase:'finish',revision:3},result:{outcome:'stopped',stop_reason:'user_stop'},events:[]};
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/runs')?{items:[refinement],total:1}:refinement)));
 render(<WorkflowWorkspace selectedRun="history" version={0} act={async op=>op()}><input aria-label="编辑中的草稿" defaultValue="尚未打开的草稿"/></WorkflowWorkspace>);
 expect(screen.queryByLabelText('编辑中的草稿')).toBeNull();
 await screen.findByRole('region',{name:'规则闭环画布'});
 expect(screen.queryByLabelText('编辑中的草稿')).toBeNull();
 fireEvent.click(screen.getByRole('tab',{name:'编辑工作流'}));
 expect((screen.getByLabelText('编辑中的草稿') as HTMLInputElement).value).toBe('尚未打开的草稿');
});

it('opens the configured loop without mounting the editor and preserves a visited draft between panes',async()=>{
 const requests:string[]=[];
 vi.stubGlobal('EventSource',class{addEventListener(){}close(){}onerror:any;});
 vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{
  requests.push(`${init?.method??'GET'} ${url}`);
  return new Response(JSON.stringify(url.endsWith('/kb-loop')?{configured:false,sequence:0,sync:{status:'unconfigured'}}:{items:[],total:0}));
 });
 render(<WorkflowWorkspace loopEnabled version={0} act={async op=>op()}><input aria-label="编辑中的草稿" defaultValue="保留设置"/></WorkflowWorkspace>);
 expect(screen.getByRole('tab',{name:'知识演化'}).getAttribute('aria-selected')).toBe('true');
 expect(screen.queryByLabelText('编辑中的草稿')).toBeNull();
 await screen.findByText('连接正在进行的研究');
 fireEvent.click(screen.getByRole('tab',{name:'编辑工作流'}));
 fireEvent.change(screen.getByLabelText('编辑中的草稿'),{target:{value:'未提交修改'}});
 fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));
 expect(screen.queryByRole('textbox',{name:'编辑中的草稿'})).toBeNull();
 fireEvent.click(screen.getByRole('tab',{name:'编辑工作流'}));
 expect((screen.getByLabelText('编辑中的草稿') as HTMLInputElement).value).toBe('未提交修改');
 expect(requests.every(request=>request.startsWith('GET'))).toBe(true);
});

it('cancels pending automatic question and model selection while the real editor is hidden for history',async()=>{
 const workflow={schema_version:1,name:'未完成的单题配置',nodes:[],edges:[],settings:{method_id:'basic_learning',method_version:'1',loop_mode:'manual',max_rounds:2}};
 let draft={workflow,advanced_backup:null,revision:1,updated_at:1};
 const refinement={id:'history',kind:'rule_refinement',status:'complete',created_at:1,config:{name:'保存的研究'},transport:{stream:false},refinement:{phase:'finish',revision:3},result:{outcome:'stopped',stop_reason:'user_stop'},events:[]};
 const mutations:string[]=[];
 let releaseQuestions!:(value:Response)=>void,releaseModels!:(value:Response)=>void;
 const questions=new Promise<Response>(resolve=>{releaseQuestions=resolve;}),models=new Promise<Response>(resolve=>{releaseModels=resolve;});
 let questionsRequested=false;
 const respond=(value:unknown)=>new Response(JSON.stringify(value));
 function DraftSettings(){const shared=useWorkflowDraft();return <output data-testid="pending-draft-settings">{JSON.stringify(shared.workflow?.settings)}</output>;}
 vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{
  if(init?.method&&init.method!=='GET')mutations.push(url);
  if(url==='/api/studio/workflow/draft'){
   if(init?.method==='PUT')draft={...draft,...JSON.parse(String(init.body)),revision:draft.revision+1};
   return respond(draft);
  }
  if(url.startsWith('/api/studio/questions?')){questionsRequested=true;return questions;}
  if(url==='/api/studio/models')return models;
  if(url==='/api/studio/workflow/default')return respond(workflow);
  if(url==='/api/studio/runs')return respond({items:[refinement],total:1});
  if(url==='/api/studio/runs/history')return respond(refinement);
  if(url==='/api/studio/question-sets'&&init?.method==='POST')return respond({id:'automatic-set',name:'自动选题',keys:['q1'],count:1});
  return respond({items:[],total:0});
 });
 render(<SharedWorkflowDraftProvider><DraftSettings/><WorkflowWorkspace version={0} act={async op=>op()}><Workflow version={0} act={async op=>op()} executionEnabled={false} onRun={()=>{}}/></WorkflowWorkspace></SharedWorkflowDraftProvider>);
 await waitFor(()=>expect(questionsRequested).toBe(true));
 fireEvent.click(screen.getByRole('tab',{name:'运行追踪'}));
 await screen.findByRole('region',{name:'规则闭环画布'});
 await reactAct(async()=>{
  releaseQuestions(respond({items:[{key:'q1',id:'q1',ready:true,kb_ready:true,split:'discovery'}],total:1}));
  releaseModels(respond({items:[{id:'model1',name:'Ready model',enabled:true,health:{status:'verified'},parameters:{max_tokens:2048}}],total:1}));
 });
 expect(mutations).toEqual([]);
 expect(JSON.parse(screen.getByTestId('pending-draft-settings').textContent!)).toEqual({method_id:'basic_learning',method_version:'1',loop_mode:'manual',max_rounds:2});
 expect(draft.workflow.settings).toEqual({method_id:'basic_learning',method_version:'1',loop_mode:'manual',max_rounds:2});
});
