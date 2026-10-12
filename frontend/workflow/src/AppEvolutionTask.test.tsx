import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import App from './App';

afterEach(()=>{cleanup();vi.unstubAllGlobals();location.hash='';});
it.each([false,true])('carries viewed evolution knowledge to Task, with evidence question=%s, without starting a run',async(withQuestion)=>{
 location.hash='#workflow';
 vi.stubGlobal('localStorage',{getItem:()=>null,setItem:()=>{},removeItem:()=>{}});
 vi.stubGlobal('EventSource',class {addEventListener(){}close(){}});
 vi.stubGlobal('ResizeObserver',class {observe(){}unobserve(){}disconnect(){}});
 const observation={source_identity:'source_hash',sequence:7};
 const claim={id:'C0004',version:3,text:'优化器知识',rules:[],status:'candidate',registered_round:1,needs_revision:false,revisions:2,evidence:{support:2,applicable:2,refute:0,conflicts:0}};
 const kb={id:'evolution_kb_source_C4',version:'frozen4',name:'知识演化 · C0004',kind:'research_rules',source_kind:'knowledge_evolution',source_claim_id:'C0004',round_index:2};
 const record={metadata:{key:'evolution_q1',source_kind:'knowledge_evolution',round_index:2},public:{id:'q_generated',prompt:'完整公开题面',choices:[{id:'a',letter:'A',view:{}},{id:'b',letter:'B',view:{}}]},observation:{content_hash:'qhash'}};
 const calls:{path:string,method?:string,body?:any}[]=[];
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
  const body=init?.body?JSON.parse(String(init.body)):undefined;calls.push({path,method:init?.method,body});
  let value:unknown={items:[],total:0};
  if(path.endsWith('/bootstrap'))value={service:{execution_enabled:false,knowledge_loop_configured:true,host:'local'},stats:{},models:[]};
  else if(path.endsWith('/kb-loop'))value={configured:true,sequence:7,observation,sync:{status:'connected'},claims:[claim],rounds:[],kb:{claims:1,candidate:1,verified:0,flagged:0,retired:0}};
  else if(path.endsWith('/kb-loop/claims/C0004'))value={observation,claim,history:[],evidence:[{question_id:'q_generated',round:1,outcome:'support'}],evidence_total:1,evidence_truncated:false};
  else if(path.includes('/kb-loop/questions/'))value=record;
  else if(path.endsWith('/tasks/evolution/selection'))value={question_key:withQuestion?'evolution_q1':null,mode:'rules',name:'知识演化 · C0004',kb_selection:{mode:'manual',ref:{id:kb.id,version:kb.version}},kb};
  else if(path.includes('/tasks/kbs'))value={items:[kb]};
  else if(path.includes('/tasks/questions/'))value=record;
  return new Response(JSON.stringify(value));
 });
 render(<App/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读命题 C0004'}));
 if(withQuestion){fireEvent.click(await screen.findByText('q_generated'));fireEvent.click(await screen.findByRole('button',{name:'阅读完整题目 q_generated'}));}
 fireEvent.click(await screen.findByRole('button',{name:'去 Task 解答'}));
 await screen.findByRole('heading',{name:'新建解答任务'});
 await screen.findByRole('option',{name:'知识演化 · C0004 · 研究候选'});
 expect(location.hash).toBe('#rag');
 expect((screen.getByLabelText('指定 KB') as HTMLSelectElement).value).toBe('evolution_kb_source_C4@frozen4');
 expect((screen.getByLabelText('KB 直接解答') as HTMLInputElement).checked).toBe(true);
 if(withQuestion)expect((await screen.findAllByText('q_generated')).length).toBeGreaterThan(0);
 else expect(screen.getByRole('button',{name:'选择题目'})).toBeTruthy();
 const posts=calls.filter(call=>call.method==='POST');expect(posts).toHaveLength(1);
 expect(posts[0]).toMatchObject({path:'/api/studio/tasks/evolution/selection',body:{observation,claim_ref:{id:'C0004',version:3}}});
 if(withQuestion)expect(posts[0].body).toMatchObject({question_id:'q_generated',expected_question_hash:'qhash'});
 fireEvent.click(screen.getByRole('button',{name:'返回任务列表'}));
 fireEvent.click(screen.getByRole('button',{name:'Harness'}));await screen.findByRole('button',{name:'阅读命题 C0004'});
 fireEvent.click(screen.getByRole('button',{name:'Task'}));
 await waitFor(()=>expect(screen.queryByRole('heading',{name:'新建解答任务'})).toBeNull());
 expect(await screen.findByRole('heading',{name:'解答任务'})).toBeTruthy();
});
