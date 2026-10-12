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
 expect(rows[1].textContent).toBe('候选 2 优于 候选 1候选 1 优于 候选 2反例');
 expect(rows[2].textContent).toBe('候选 3 优于 候选 2候选 3 优于 候选 2支持');
 expect(screen.getByText('候选编号按这份证据中的来源顺序排列，不代表原题选项字母。')).toBeTruthy();
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
 vi.stubGlobal('fetch',async(url:string)=>new Response(JSON.stringify(url.endsWith('/rounds/2')?{...snapshot.rounds![0],generation:{total:55,completed:55,ok:55,failed:0,pending:0,items}}
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
