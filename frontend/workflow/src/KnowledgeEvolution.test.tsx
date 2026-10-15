import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,renderHook,screen,waitFor,within} from '@testing-library/react';
import {KnowledgeEvolution} from './KnowledgeEvolution';
import {evolutionPresentation,useKnowledgeEvolution,type EvolutionSnapshot} from './knowledgeEvolutionState';

vi.mock('./ResearchPathCanvas',()=>({ResearchPathCanvas:({nodes,onSelect,inspector,ariaLabel}:any)=><section aria-label={ariaLabel}>{nodes.map((node:any)=><button key={node.id} onClick={()=>onSelect(node.id)}>{node.label}<span>{node.status}</span></button>)}{inspector}</section>}));
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();});

const fixture=():EvolutionSnapshot=>({configured:true,name:'知识演化',sequence:8,sync:{status:'connected',last_success_at:1791756000},execution:{status:'running',alert:false,stop_requested:false},
 round:{index:2,completed_stages:['plan'],next_stage:'build',plan:{total:300,target:180,explore:120},build:{completed:110,ok:103,failed:7}},
 kb:{claims:1,candidate:1,verified:0,flagged:0,retired:0},evidence:{questions:30,verdicts:96},
 claims:[{id:'C0001',version:2,text:'满足公开条件时，模型 A 优于模型 B。',rules:[{when:{family:'continuous'},prefer:'A'}],status:'candidate',registered_round:1,needs_revision:false,revisions:1,stats:{lower_bound:null},evidence:{support:16,applicable:25,refute:9,conflicts:0}}],
 rounds:[{index:2,completed:false,completed_stages:['plan'],plan:{total:300,target:180,explore:120},build:{completed:110,ok:103,failed:7},report:null}],thresholds:{min_applicable:40},
});
class Source{
 static instances:Source[]=[];
 listeners:Record<string,(event:{data:string})=>void>={};
 onerror?:()=>void;
 close=vi.fn();
 constructor(public url:string){Source.instances.push(this);}
 addEventListener(name:string,fn:(event:{data:string})=>void){this.listeners[name]=fn;}
 emit(name:string,value:unknown){this.listeners[name]?.({data:JSON.stringify(value)});}
}
function install(snapshot=fixture()){
 Source.instances=[];vi.stubGlobal('EventSource',Source);
 const fetch=vi.fn(async()=>new Response(JSON.stringify(snapshot)));vi.stubGlobal('fetch',fetch);return fetch;
}
it('reads consistency audit details separately from source validation and causal hypotheses',async()=>{
 const snapshot=fixture();
 snapshot.claims![0].consistency_audit={status:'passed',issues:[],explanation:{text:'可能源于优化器的收敛行为',status:'hypothesis'}};
 install(snapshot);
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/claims/C0001')?{claim:snapshot.claims![0],history:[],evidence:[],evidence_total:0,evidence_truncated:false}:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));
 const audit=await screen.findByRole('region',{name:'文字与规则一致性审计'});
 expect(within(audit).getByText('一致性检查通过')).toBeTruthy();
 expect(within(audit).getByText(/不代表命题经过实证验证/)).toBeTruthy();
 expect(within(screen.getByRole('region',{name:'因果解释 · 待验证'})).getByText('可能源于优化器的收敛行为')).toBeTruthy();
 expect(screen.getAllByText('满足公开条件时，模型 A 优于模型 B。').length).toBeGreaterThan(0);
});

it('replays only newer snapshots, handles sync heartbeats and retains facts through disconnects',async()=>{
 install();const {result}=renderHook(()=>useKnowledgeEvolution());
 await waitFor(()=>expect(result.current.snapshot?.sequence).toBe(8));
 expect(Source.instances[0].url).toBe('/api/studio/kb-loop/stream?after=8');
 const newer={...fixture(),sequence:9,kb:{claims:2,candidate:2,verified:0,flagged:0,retired:0}};
 act(()=>Source.instances[0].emit('snapshot',newer));
 act(()=>Source.instances[0].emit('snapshot',fixture()));
 expect(result.current.snapshot?.kb?.claims).toBe(2);
 act(()=>Source.instances[0].emit('sync',{sync:{status:'disconnected',last_success_at:1791756000}}));
 expect(result.current.snapshot?.sync.status).toBe('disconnected');
 expect(result.current.snapshot?.round?.build?.completed).toBe(110);
 act(()=>Source.instances[0].onerror?.());
 expect(result.current.connection).toBe('disconnected');
 expect(result.current.snapshot?.sequence).toBe(9);
});

it('reconnects with the retained sequence, and closes the stream when leaving the page',async()=>{
 const fetch=install();const view=renderHook(()=>useKnowledgeEvolution());
 await waitFor(()=>expect(Source.instances).toHaveLength(1));
 vi.useFakeTimers();
 act(()=>Source.instances[0].emit('snapshot',{...fixture(),sequence:12}));
 act(()=>Source.instances[0].onerror?.());
 await act(async()=>{await vi.advanceTimersByTimeAsync(3000);});
 expect(fetch).toHaveBeenCalledTimes(2);
 expect(Source.instances[1].url).toContain('after=12');
 view.unmount();expect(Source.instances[1].close).toHaveBeenCalledOnce();
});

it('marks completion only from saved markers, and never infers a running process from the next stage',()=>{
 const snapshot=fixture();
 let graph=evolutionPresentation(snapshot);
 expect(graph.nodes.map(node=>node.id)).toEqual(['plan','build','score','judge','propose','register','report']);
 expect(graph.nodes.find(node=>node.id==='plan')?.status).toBe('complete');
 expect(graph.nodes.find(node=>node.id==='build')?.status).toBe('running');
 expect(graph.nodes.find(node=>node.id==='propose')?.status).toBeUndefined();
 snapshot.execution!.status='unknown';
 expect(evolutionPresentation(snapshot).nodes.find(node=>node.id==='build')?.status).toBe('待完成');
 snapshot.execution!.status='running';
 expect(evolutionPresentation(snapshot,false).nodes.find(node=>node.id==='build')?.status).toBe('待完成');
 expect(graph.edges.some(edge=>edge.source==='report'&&edge.target==='plan'&&edge.loop)).toBe(true);
});

it('shows real source evidence, leaves unknown lower bounds pending, and does not create jobs',async()=>{
 const snapshot=fixture(),requests:string[]=[];install(snapshot);
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  requests.push(init?.method??'GET');
  const data=url.endsWith('/claims/C0001')?{claim:snapshot.claims![0],history:[],evidence:[],evidence_total:0,evidence_truncated:false}:url.endsWith('/rounds/2')?{...snapshot.rounds![0],score:null,registration:null,proposals:null,judge_events:[],registered:[]}:snapshot;
  return new Response(JSON.stringify(data));
 }));
 render(<KnowledgeEvolution/>);
 await screen.findByRole('button',{name:'阅读命题 C0001'});
 expect(screen.getByText('统计下界 待判定')).toBeTruthy();
 expect(screen.getByRole('progressbar',{name:'本轮出题进度'}).getAttribute('value')).toBe('110');
 expect(screen.queryByText('我的流程')).toBeNull();
 expect(screen.queryByRole('button',{name:/启动|停止|发布/})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'阅读命题 C0001'}));
 await screen.findByText('16 / 25');
 expect(screen.getByText('待判定')).toBeTruthy();
 expect(screen.getByText(/仅包含当前修订登记之后的新题/)).toBeTruthy();
 expect(requests.every(method=>method==='GET')).toBe(true);
});

it('shows persisted stage details and pending reports without inventing output',async()=>{
 const snapshot=fixture();install(snapshot);
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/rounds/2')?{...snapshot.rounds![0],score:null,proposals:null,registration:null,judge_events:[],registered:[]}:snapshot)));
 render(<KnowledgeEvolution/>);
 await screen.findByRole('button',{name:'提出与修订'});
 fireEvent.click(screen.getByRole('button',{name:'提出与修订'}));
 expect(await screen.findByText('等待保存提案与检查记录。')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'关闭节点详情'}));
 fireEvent.click(screen.getByRole('button',{name:'规则验证'}));
 expect(screen.getByText('来源会跳过内部冲突的比较；仅有冲突、没有有效预测的题不计入适用题。这里沿用来源判定。')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'关闭节点详情'}));
 fireEvent.click(screen.getByRole('tab',{name:'轮次记录'}));
 fireEvent.click(await screen.findByRole('button',{name:'阅读第 2 轮'}));
 expect(await screen.findByText('本轮尚未归档，以下仅展示已保存的产物。')).toBeTruthy();
 expect(screen.getByText('本轮报告尚未保存。')).toBeTruthy();
 expect(screen.getByText('预注册记录尚未保存。')).toBeTruthy();
});

it('reads conditions and stored comparisons without treating evidence aliases as answer letters',async()=>{
 const snapshot=fixture();install(snapshot);
 const claim={...snapshot.claims![0],rules:[
  {scope:['family','eq','continuous'],same:['opt','depth'],max_param_ratio:2,predict:{higher_better:'width'}},
  {unknown_source_predicate:{value:1}},
 ]};
 const evidence={question_id:'q-evidence-1',round:2,outcome:'refute',pairs:[['alpha','zeta',false],['beta','alpha',true]],conflicts:1,question:{family:'continuous',type:'architecture',purpose:'target',candidates:{zeta:{width:32},alpha:{width:16},beta:{width:64}}}};
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/claims/C0001')?{claim,history:[],evidence:[evidence],evidence_total:1,evidence_truncated:false}:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));
 expect(await screen.findByText('数据家族 = continuous')).toBeTruthy();
 expect(screen.getByText('优化器、深度')).toBeTruthy();
 expect(screen.getByText('两候选参数量之比不超过 2 倍')).toBeTruthy();
 expect(screen.getByText('宽度更高的候选更好')).toBeTruthy();
 expect(screen.getByText('这个执行分支暂未转换为阅读形式，可展开查看原始规则。')).toBeTruthy();
 for(const summary of screen.getAllByText('完整规则记录'))expect(summary.closest('details')?.hasAttribute('open')).toBe(false);
 fireEvent.click(screen.getByText('q-evidence-1').closest('summary')!);
 const rows=within(screen.getByRole('table')).getAllByRole('row');
 expect(rows).toHaveLength(3);
 expect(rows[1].textContent).toBe('模型未记录 · 宽度 16 优于 模型未记录 · 宽度 32模型未记录 · 宽度 32 优于 模型未记录 · 宽度 16反例');
 expect(rows[2].textContent).toBe('模型未记录 · 宽度 64 优于 模型未记录 · 宽度 16模型未记录 · 宽度 64 优于 模型未记录 · 宽度 16支持');
 expect(screen.getByText('按保存的候选配置比较；完整题目中可选择答案并检查训练结果。')).toBeTruthy();
 expect(screen.getByText('continuous · 比较 3 个训练方案')).toBeTruthy();
 expect(screen.getByText('模型未记录 · 宽度 16', {selector:'.evolution-candidate-briefs strong'})).toBeTruthy();
 expect(screen.getByText('另有 1 个内部冲突的比较被来源跳过，不参与这道题的支持或推翻判定。')).toBeTruthy();
 expect(screen.getByText('候选配置与完整证据').closest('details')?.hasAttribute('open')).toBe(false);
});

it('keeps the last visible counts and shows lost synchronization separately from execution',async()=>{
 install();render(<KnowledgeEvolution/>);
 await screen.findByRole('button',{name:'阅读命题 C0001'});
 act(()=>Source.instances[0].emit('sync',{sync:{status:'disconnected',last_success_at:1791756000}}));
 expect(screen.getByText('同步中断 · 显示上次记录')).toBeTruthy();
 expect(screen.getByText('等待同步确认')).toBeTruthy();
 expect(screen.getByRole('progressbar').getAttribute('value')).toBe('110');
 expect(screen.queryByText('进程已停止')).toBeNull();
});

it('offers an honest unconfigured state without placeholder measurements',async()=>{
 install({configured:false,sequence:0,sync:{status:'unconfigured'}});
 render(<KnowledgeEvolution/>);
 await screen.findByText('连接正在进行的研究');
 expect(screen.queryByRole('progressbar')).toBeNull();
 expect(screen.queryByRole('region',{name:'知识演化研究路径'})).toBeNull();
});

it('opens the saved complete question from claim evidence and returns to that claim',async()=>{
 const snapshot=fixture();install(snapshot);
 const requests:string[]=[];
 vi.stubGlobal('fetch',async(url:string)=>{
  requests.push(url);
  if(url.endsWith('/questions/applicable-knowledge'))return new Response(JSON.stringify({scope:'public_applicability',items:[],total:0,feedback_released:false}));
  if(url.endsWith('/questions/inspect'))return new Response(JSON.stringify({scope:'human_inspection',correct_answer:{id:'y',letter:'A'},feedback:{correct_letter:'A',reveal:{curves:[]}}}));
  const data=url.endsWith('/claims/C0001')?{claim:snapshot.claims![0],history:[],evidence:[{question_id:'q-saved',round:1,outcome:'support',pairs:[]}],evidence_total:1,evidence_truncated:false}
   :url.endsWith('/questions/q-saved')?{metadata:{id:'q-saved',family:'xor_classification'},public:{id:'q-saved',choices:[{id:'x',letter:'B',view:{width:32}},{id:'y',letter:'A',view:{width:16}}],prompt:'## Dataset\nSaved complete data rule.\n## Candidates\nSaved candidate code.'},observation:{content_hash:'abc',captured_at:1791756000}}:snapshot;
  return new Response(JSON.stringify(data));
 });
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));
 fireEvent.click((await screen.findByText('q-saved')).closest('summary')!);
 fireEvent.click(screen.getByRole('button',{name:'阅读完整题目 q-saved'}));
 expect(await screen.findByRole('dialog',{name:'完整题目'})).toBeTruthy();
 fireEvent.click(await screen.findByRole('tab',{name:'原始 Prompt'}));
 expect(screen.getByTestId('original-prompt').textContent).toContain('Saved complete data rule.');
 expect(requests.filter(url=>url.endsWith('/questions/q-saved'))).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'返回知识与证据'}));
 expect(screen.getByRole('dialog',{name:'知识与证据'})).toBeTruthy();
});

it('opens live generation rows, refreshes saved outcomes, and never calls pending items running',async()=>{
 const snapshot=fixture();install(snapshot);
 let completed=false;
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/rounds/2')?{...snapshot.rounds![0],generation:{total:2,completed:completed?2:1,ok:completed?2:1,failed:0,pending:completed?0:1,items:[
  {item_id:'item-a',family:'xor_classification',question_type:'mixed',purpose:'explore',targets:[],status:'ok',question_id:'q-new',seconds:2},
  {item_id:'item-b',family:'bigram_lm',question_type:'optimizer_only',purpose:'target',targets:['C0001'],status:completed?'ok':'pending',...(completed?{question_id:'q-later'}:{})},
 ]}}:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:/生成新题/}));
 const panel=await screen.findByRole('dialog',{name:'本轮新题'});
 expect(await within(panel).findByRole('button',{name:'阅读完整题目 q-new'})).toBeTruthy();
 expect(within(panel).getByText('等待产出',{selector:'span'})).toBeTruthy();
 expect(within(panel).queryByText('执行中')).toBeNull();
 completed=true;
 act(()=>Source.instances[0].emit('snapshot',{...snapshot,sequence:9}));
 expect(await within(panel).findByRole('button',{name:'阅读完整题目 q-later'})).toBeTruthy();
 expect(within(panel).queryByText('等待产出',{selector:'span'})).toBeNull();
 act(()=>Source.instances[0].emit('sync',{sync:{status:'disconnected'}}));
 expect(within(panel).getByText('同步中断，保留最近记录')).toBeTruthy();
});

it('retains generation filters, expanded rows and reading position after reading a complete question',async()=>{
 const snapshot=fixture();install(snapshot);
 const items=Array.from({length:55},(_,index)=>({item_id:`i-${index}`,family:'xor_classification',question_type:'mixed',purpose:'explore',targets:[],status:'ok',question_id:`q_saved_${index}`}));
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/questions/applicable-knowledge')?{scope:'public_applicability',items:[],total:0,feedback_released:false}
  :url.endsWith('/rounds/2')?{...snapshot.rounds![0],generation:{total:55,completed:55,ok:55,failed:0,pending:0,items}}
  :url.includes('/questions/')?{metadata:{id:'q_saved_0'},public:{id:'q_saved_0',choices:[],prompt:'saved question'}}:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:/生成新题/}));
 fireEvent.change(await screen.findByRole('textbox',{name:'搜索生成记录'}),{target:{value:'异或'}});
 fireEvent.change(screen.getByRole('combobox',{name:'筛选生成状态'}),{target:{value:'ok'}});
 fireEvent.click(screen.getByRole('button',{name:/继续查看/}));
 fireEvent.click(screen.getByRole('button',{name:'阅读完整题目 q_saved_0'}));
 fireEvent.click(await screen.findByRole('button',{name:'返回生成记录'}));
 expect((screen.getByRole('textbox',{name:'搜索生成记录'}) as HTMLInputElement).value).toBe('异或');
 expect((screen.getByRole('combobox',{name:'筛选生成状态'}) as HTMLSelectElement).value).toBe('ok');
 expect(document.activeElement).toBe(screen.getByRole('button',{name:'阅读完整题目 q_saved_0'}));
 expect(screen.queryByRole('button',{name:/继续查看/})).toBeNull();
});

it('recovers a failed generation detail when synchronization returns without a new source sequence',async()=>{
 const snapshot=fixture();install(snapshot);let online=false;
 vi.stubGlobal('fetch',async(url:string)=>{
  if(url.endsWith('/rounds/2')){
   if(!online)throw new Error('offline');
   return new Response(JSON.stringify({...snapshot.rounds![0],generation:{total:0,completed:0,ok:0,failed:0,pending:0,items:[]}}));
  }
  return new Response(JSON.stringify(snapshot));
 });
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:/生成新题/}));
 await screen.findByText('详情暂时无法同步，请稍后重新打开。');
 act(()=>Source.instances[0].emit('sync',{sync:{status:'disconnected'}}));
 online=true;
 act(()=>Source.instances[0].emit('sync',{sync:{status:'connected'}}));
 expect(await screen.findByText('没有符合条件的生成记录')).toBeTruthy();
 expect(screen.queryByText('详情暂时无法同步，请稍后重新打开。')).toBeNull();
});

const taskSeed={question_key:null,kb_selection:{mode:'manual',ref:{id:'evolution-kb',version:'frozen-kb'}},kb:{id:'evolution-kb',version:'frozen-kb',name:'C0001',kind:'research_rules'},name:'知识解答',mode:'rules'};
function taskEntryFixture(override?:(url:string,init?:RequestInit)=>Response|Promise<Response>|undefined){
 const snapshot={...fixture(),observation:{source_identity:'source-one',sequence:8}};install(snapshot);
 const requests:{url:string;method:string;body:any}[]=[];
 vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{
  requests.push({url,method:init?.method??'GET',body:init?.body?JSON.parse(String(init.body)):undefined});
  if(url.endsWith('/questions/applicable-knowledge'))return new Response(JSON.stringify({scope:'public_applicability',items:[],total:0,feedback_released:false}));
  const special=override?.(url,init);if(special)return special;
  const data=url.endsWith('/claims/C0001')?{observation:snapshot.observation,claim:snapshot.claims![0],history:[],evidence:[{question_id:'q_saved',round:1,outcome:'support',pairs:[]}],evidence_total:1,evidence_truncated:false}
   :url.endsWith('/rounds/2')?{...snapshot.rounds![0],observation:{source_identity:'source-one',sequence:7},generation:{total:1,completed:1,ok:1,failed:0,pending:0,items:[{item_id:'i1',question_id:'q_saved',family:'xor_classification',question_type:'mixed',purpose:'explore',targets:[],status:'ok'}]}}
   :url.endsWith('/questions/q_saved')?{metadata:{id:'q_saved'},public:{id:'q_saved',family:'xor_classification',prompt:'公开题面',choices:[]},observation:{content_hash:'question-frozen-hash',captured_at:1}}
   :url.endsWith('/tasks/evolution/selection')?taskSeed:snapshot;
  return new Response(JSON.stringify(data));
 });
 return {snapshot,requests};
}
it('carries only the currently read claim to Task after freezing its observed version',async()=>{
 const {requests}=taskEntryFixture(),onTask=vi.fn();render(<KnowledgeEvolution onTask={onTask}/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));fireEvent.click(await screen.findByRole('button',{name:'去 Task 解答'}));
 await waitFor(()=>expect(onTask).toHaveBeenCalledWith(taskSeed));
 expect(requests.filter(row=>row.method==='POST'&&!row.url.endsWith('/questions/applicable-knowledge'))).toEqual([{url:'/api/studio/tasks/evolution/selection',method:'POST',body:{observation:{source_identity:'source-one',sequence:8},claim_ref:{id:'C0001',version:2}}}]);
});
it('keeps the evidence parent claim and observation when newer snapshots arrive while reading its question',async()=>{
 let advanced=false;
 const {snapshot,requests}=taskEntryFixture(url=>advanced&&url.endsWith('/claims/C0001')?new Response(JSON.stringify({observation:{source_identity:'source-two',sequence:9},claim:{...fixture().claims![0],version:3},history:[],evidence:[],evidence_total:0,evidence_truncated:false})):undefined),onTask=vi.fn();render(<KnowledgeEvolution onTask={onTask}/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));fireEvent.click((await screen.findByText('q_saved')).closest('summary')!);fireEvent.click(screen.getByRole('button',{name:'阅读完整题目 q_saved'}));
 await screen.findByRole('tab',{name:'原始 Prompt'});
 advanced=true;act(()=>Source.instances[0].emit('snapshot',{...snapshot,sequence:9,observation:{source_identity:'source-two',sequence:9}}));
 await waitFor(()=>expect(requests.filter(row=>row.url.endsWith('/claims/C0001'))).toHaveLength(2));
 fireEvent.click(screen.getByRole('button',{name:'去 Task 解答'}));await waitFor(()=>expect(onTask).toHaveBeenCalledOnce());
 expect(requests.find(row=>row.method==='POST'&&!row.url.endsWith('/questions/applicable-knowledge'))?.body).toEqual({observation:{source_identity:'source-one',sequence:8},question_id:'q_saved',expected_question_hash:'question-frozen-hash',claim_ref:{id:'C0001',version:2}});
});
it('carries a generated question with the viewed round observation and without an unrelated claim',async()=>{
 const {requests}=taskEntryFixture(),onTask=vi.fn();render(<KnowledgeEvolution onTask={onTask}/>);
 fireEvent.click(await screen.findByRole('button',{name:/生成新题/}));fireEvent.click(await screen.findByRole('button',{name:'阅读完整题目 q_saved'}));
 fireEvent.click(await screen.findByRole('button',{name:'去 Task 解答'}));await waitFor(()=>expect(onTask).toHaveBeenCalledOnce());
 expect(requests.find(row=>row.method==='POST'&&!row.url.endsWith('/questions/applicable-knowledge'))?.body).toEqual({observation:{source_identity:'source-one',sequence:7},question_id:'q_saved',expected_question_hash:'question-frozen-hash'});
});
it('keeps selection failures in the current reader and allows retry',async()=>{
 taskEntryFixture(url=>url.endsWith('/tasks/evolution/selection')?new Response(JSON.stringify({detail:'这份知识快照暂不可使用'}),{status:409}):undefined);
 const onTask=vi.fn();render(<KnowledgeEvolution onTask={onTask}/>);fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));fireEvent.click(await screen.findByRole('button',{name:'去 Task 解答'}));
 expect(await screen.findByText('这份知识快照暂不可使用')).toBeTruthy();expect(screen.getByRole('dialog',{name:'知识与证据'})).toBeTruthy();expect((screen.getByRole('button',{name:'去 Task 解答'}) as HTMLButtonElement).disabled).toBe(false);expect(onTask).not.toHaveBeenCalled();
});
it('does not navigate after leaving a question while its Task selection is still pending',async()=>{
 let resolve!:(response:Response)=>void;
 const {requests}=taskEntryFixture(url=>url.endsWith('/tasks/evolution/selection')?new Promise<Response>(done=>{resolve=done;}):undefined),onTask=vi.fn();render(<KnowledgeEvolution onTask={onTask}/>);
 fireEvent.click(await screen.findByRole('button',{name:/生成新题/}));fireEvent.click(await screen.findByRole('button',{name:'阅读完整题目 q_saved'}));
 const button=await screen.findByRole('button',{name:'去 Task 解答'});fireEvent.click(button);fireEvent.click(button);await waitFor(()=>expect(resolve).toBeTruthy());expect(requests.filter(row=>row.method==='POST'&&!row.url.endsWith('/questions/applicable-knowledge'))).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'返回生成记录'}));await act(async()=>{resolve(new Response(JSON.stringify(taskSeed)));});expect(onTask).not.toHaveBeenCalled();expect(screen.getByRole('dialog',{name:'本轮新题'})).toBeTruthy();
});

it('opens round knowledge at its saved version and returns through question, knowledge and round',async()=>{
 const snapshot=fixture();install(snapshot);
 const observation={source_identity:'a'.repeat(64),sequence:8};
 const requests:string[]=[];
 const writes:{url:string;method:string;body:any}[]=[];
 const detail={...snapshot.rounds![0],observation,judge_events:[{claim_id:'C0001',version:1,from:'candidate',to:'verified',support:15,applicable:18,lower_bound:.6}],registered:[{id:'C0002',version:1,text:'本轮新登记的规则'}]};
 vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{
  requests.push(url);
  if(init?.method&&init.method!=='GET')writes.push({url,method:init.method,body:init.body?JSON.parse(String(init.body)):undefined});
  if(url.endsWith('/questions/applicable-knowledge'))return new Response(JSON.stringify({scope:'public_applicability',items:[],total:0,feedback_released:false}));
  const data=url.includes('/rounds/2/claims/')?{observation,reading_round:2,claim:{...snapshot.claims![0],version:1,text:'本轮封存的知识内容'},history:[],evidence:[{question_id:'q_round',round:2,outcome:'support',pairs:[]}],evidence_total:1,evidence_truncated:false}
   :url.endsWith('/rounds/2')?detail
   :url.endsWith('/questions/q_round')?{metadata:{id:'q_round'},public:{id:'q_round',prompt:'本轮完整题面',choices:[{id:'candidate-a',letter:'A'},{id:'candidate-b',letter:'B'}]},observation:{content_hash:'hash'}}
   :url.endsWith('/questions/inspect')?{scope:'human_inspection',correct_answer:{id:'candidate-b',letter:'B'},feedback:{correct_letter:'B',reveal:{curves:[]}}}:snapshot;
  return new Response(JSON.stringify(data));
 });
 render(<KnowledgeEvolution onTask={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('tab',{name:'轮次记录'}));
 fireEvent.click(screen.getByRole('button',{name:'阅读第 2 轮'}));
 fireEvent.click(await screen.findByRole('button',{name:'查看第 2 轮知识 C0001'}));
 expect(await screen.findByText('本轮封存的知识内容')).toBeTruthy();
 expect(screen.queryByRole('dialog',{name:'第 2 轮研究'})).toBeNull();
 expect(screen.queryByRole('button',{name:'去 Task 解答'})).toBeNull();
 expect(requests).toContain(`/api/studio/kb-loop/rounds/2/claims/C0001?version=1&source_identity=${observation.source_identity}&sequence=8`);
 act(()=>Source.instances[0].emit('snapshot',{...snapshot,sequence:9}));
 expect(requests.some(url=>url.includes('/rounds/2/claims/')&&url.includes('sequence=9'))).toBe(false);
 fireEvent.click(screen.getByText('q_round').closest('summary')!);
 fireEvent.click(screen.getByRole('button',{name:'阅读完整题目 q_round'}));
 expect(await screen.findByRole('dialog',{name:'完整题目'})).toBeTruthy();
 await screen.findByText('正确答案');
 expect(within(screen.getByRole('article',{name:'候选 B'})).getByText('正确答案')).toBeTruthy();
 expect(screen.queryByRole('radio')).toBeNull();
 expect(writes.filter(call=>call.url.endsWith('/questions/inspect'))).toEqual([{url:'/api/studio/questions/inspect',method:'POST',body:{source:{kind:'knowledge_evolution',question_id:'q_round',observation,expected_question_hash:'hash'}}}]);
 expect(writes.filter(call=>!['/api/studio/questions/applicable-knowledge','/api/studio/questions/inspect'].includes(call.url))).toEqual([]);
 expect(screen.queryByRole('button',{name:'去 Task 解答'})).toBeNull();
 expect(requests.some(url=>url.includes('/evidence'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'返回知识与证据'}));
 fireEvent.click(await screen.findByRole('button',{name:'返回第 2 轮研究'}));
 expect(await screen.findByRole('dialog',{name:'第 2 轮研究'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'查看第 2 轮知识 C0002'}));
 await waitFor(()=>expect(requests.some(url=>url.includes('/rounds/2/claims/C0002?version=1'))).toBe(true));
});

it('does not substitute current knowledge when round reference is missing',async()=>{
 const snapshot=fixture();install(snapshot);
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/rounds/2')?{...snapshot.rounds![0],judge_events:[{claim_id:'C0001',from:'candidate',to:'verified'}]}:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('tab',{name:'轮次记录'}));
 fireEvent.click(screen.getByRole('button',{name:'阅读第 2 轮'}));
 expect((await screen.findByRole('button',{name:'查看第 2 轮知识 C0001'}) as HTMLButtonElement).disabled).toBe(true);
});

it('reads saved original wording and changes from claim history without relabeling current evidence',async()=>{
 const snapshot=fixture();install(snapshot);
 const original={...snapshot.claims![0],version:1,text:'最初登记的知识原文',registered_round:0,rules:[]};
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/claims/C0001')?{
  claim:snapshot.claims![0],history:[original,snapshot.claims![0]],evidence:[],evidence_total:0,evidence_truncated:false,
 }:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));
 fireEvent.click(await screen.findByText('登记与修订记录'));
 const history=await screen.findByRole('region',{name:'知识修订历史'});
 expect(within(history).getByText('第一版原文')).toBeTruthy();
 expect(within(history).getByText('最初登记的知识原文')).toBeTruthy();
 expect(within(history).getByText('较 C0001 · 第 1 版：正文、执行规则已调整。')).toBeTruthy();
 expect(within(history).queryByText(/支持|适用题/)).toBeNull();
});

it('separates the leaf-first design from observed source settings and keeps unexecuted stages pending',async()=>{
 const snapshot=fixture();
 Object.assign(snapshot,{configuration:{scope:'current_source',proposer:{model:'recorded-model',splits_per_claim:3},checks:{new_min_rate:0.85,min_history_applicable:1},questions:{target_fraction:0.6},evidence:{min_relative_gap:0.1}}});
 install(snapshot);render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByText('研究策略'));
 const strategy=screen.getByRole('region',{name:'研究策略说明'});
 expect(within(strategy).getByText('来源当前配置')).toBeTruthy();
 expect(within(strategy).getByText('recorded-model')).toBeTruthy();
 expect(within(strategy).getByText('85.0%')).toBeTruthy();
 expect(within(strategy).getByText(/最新设计.*第 7 轮起/)).toBeTruthy();
 expect(within(strategy).getByText(/95%/)).toBeTruthy();
 expect(within(strategy).getByText(/不能据此认定当前轮已经执行/)).toBeTruthy();
 expect(within(screen.getByRole('region',{name:'知识演化研究路径'})).queryByText('已完成')).toBeNull();
 expect(screen.queryByText('Qwen3.5-27B')).toBeNull();
});

it('shows joint answering separately for all questions and random exploration using saved report values',async()=>{
 const snapshot=fixture();install(snapshot);
 const detail={...snapshot.rounds![0],report:{model:'saved-round-model',build:{steered:18,target_hit:12},splits:{parents:4,registered:7},ensemble:{questions:30,claims:2,answered:20,correct:18,coverage:2/3,accuracy:.9,overall:.6},ensemble_explore:{questions:12,claims:2,answered:0,correct:0,coverage:0,accuracy:null,overall:0}}};
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/rounds/2')?detail:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('tab',{name:'轮次记录'}));
 fireEvent.click(screen.getByRole('button',{name:'阅读第 2 轮'}));
 const report=await screen.findByRole('region',{name:'KB 联合答题'});
 expect(within(report).getByText('本轮全部题（含定向）')).toBeTruthy();
 expect(within(report).getByText('随机探索题')).toBeTruthy();
 expect(within(report).getByText('90.0%')).toBeTruthy();
 expect(within(report).getByText('未作答')).toBeTruthy();
 expect(within(report).getByText(/候选不参与/)).toBeTruthy();
 expect(await screen.findByText('12 / 18')).toBeTruthy();
 expect(screen.getByText('7')).toBeTruthy();
 expect(screen.getByText('saved-round-model')).toBeTruthy();
});

it('keeps checked split proposals separate from registered knowledge and does not infer an answer report',async()=>{
 const snapshot=fixture();install(snapshot);
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/rounds/2')?{...snapshot.rounds![0],proposals:{new_count:5,revision_count:0,split_count:3,split_parent_count:2,split_attempt_count:6}}:snapshot)));
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('tab',{name:'轮次记录'}));
 fireEvent.click(screen.getByRole('button',{name:'阅读第 2 轮'}));
 expect(await screen.findByText('通过检查的拆分提案')).toBeTruthy();
 expect(screen.queryByText('新登记的窄知识')).toBeNull();
 expect(screen.getByText('尝试拆分的原知识').nextElementSibling?.textContent).toBe('6');
 expect(screen.getByText('通过检查的原知识').nextElementSibling?.textContent).toBe('2');
 expect(screen.getByText('这轮尚无保存的联合答题报告。')).toBeTruthy();
 expect(screen.queryByText('0.0%')).toBeNull();
});

it('preserves the exact parent reference while explicitly navigating to the current parent record',async()=>{
 const snapshot=fixture();install(snapshot);const requests:string[]=[];
 vi.stubGlobal('fetch',async(url:string)=>{
  requests.push(url);
  return new Response(JSON.stringify(url.endsWith('/claims/C0001')?{claim:{...snapshot.claims![0],parent:{id:'C0000',version:1},lineage_kind:'split'},history:[],children:[{id:'C0002',version:1,text:'更窄的子知识',registered_round:2}],evidence:[],evidence_total:0,evidence_truncated:false}:url.endsWith('/claims/C0000')?{claim:{...snapshot.claims![0],id:'C0000',version:3,text:'父节点当前正文'},history:[],evidence:[],evidence_total:0,evidence_truncated:false}:snapshot));
 });
 render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));
 const lineage=await screen.findByRole('region',{name:'知识谱系'});
 expect(within(lineage).getByText('C0000 · 第 1 版')).toBeTruthy();
 expect(within(lineage).getByText('拆分来源 · 原知识保留为父节点')).toBeTruthy();
 expect(within(lineage).getByText('更窄的子知识')).toBeTruthy();
 fireEvent.click(within(lineage).getByRole('button',{name:'查看父节点当前记录'}));
 expect(await screen.findByText('父节点当前正文')).toBeTruthy();
 expect(requests).toContain('/api/studio/kb-loop/claims/C0000');
});

it('reads the exact split parent wording and rules without replacing them with current parent facts',async()=>{
 const snapshot=fixture();install(snapshot);
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/claims/C0001')?{
  claim:{...snapshot.claims![0],parent:{id:'C0000',version:1},lineage_kind:'split'},history:[],
  parent_claim:{id:'C0000',version:1,text:'拆分时保留的父知识原文',rules:[{when:{family:'continuous'},prefer:'A'}],registered_round:0},evidence:[],evidence_total:0,evidence_truncated:false,
 }:snapshot)));
 render(<KnowledgeEvolution/>);fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0001'}));
 fireEvent.click(await screen.findByText('拆分时的父规则'));
 const source=await screen.findByRole('region',{name:'父知识原始版本'});
 expect(within(source).getByText('拆分时保留的父知识原文')).toBeTruthy();
 expect(within(source).getByText('C0000 · 第 1 版')).toBeTruthy();
 expect(within(source).queryByText(/支持.*适用题/)).toBeNull();
});

it('explains directed generation steps using only saved source attempt limits',async()=>{
 const snapshot=fixture();Object.assign(snapshot,{configuration:{scope:'current_source',questions:{target_probe_tries:12,target_set_probe_tries:7,target_draws:2}}});
 install(snapshot);render(<KnowledgeEvolution/>);
 fireEvent.click(await screen.findByRole('button',{name:/研究计划/}));
 expect(screen.getByText('数据集条件')).toBeTruthy();
 expect(screen.getByText('训练前候选对适用性')).toBeTruthy();
 expect(screen.getByText('合格三选一')).toBeTruthy();
 expect(screen.getByText('最多 12 个种子')).toBeTruthy();
 expect(screen.getByText('最多 7 次采样')).toBeTruthy();
 expect(screen.getByText('最多 2 次抽取')).toBeTruthy();
 expect(screen.queryByText(/最多 40|最多 30|最多 6/)).toBeNull();
});
