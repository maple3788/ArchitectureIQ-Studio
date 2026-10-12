import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react';
import {LoopQuestionPanel} from './LoopQuestionPanel';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('inspects the viewed evolution snapshot before requesting saved comparisons without committing an answer',async()=>{
 const observation={source_identity:'a'.repeat(64),sequence:8},hash='b'.repeat(64),calls:{path:string;method:string;body?:any}[]=[];
 let resolveInspection!:(response:Response)=>void;
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
  calls.push({path,method:init?.method??'GET',body:init?.body&&JSON.parse(init.body as string)});
  if(path.endsWith('/questions/inspect'))return new Promise<Response>(resolve=>{resolveInspection=resolve;});
  return new Response(JSON.stringify(path.endsWith('/applicable-knowledge')?{scope:'public_applicability',items:[],total:0,feedback_released:false}:path.includes('/evidence?')?{question_id:'q_123',claims:[],notice:'记录中的知识证据'}:{metadata:{id:'q_123'},observation:{content_hash:hash},public:{id:'q_123',choices:[{id:'from-source-A',letter:'C'},{id:'from-source-B',letter:'A'}]}}));
 });
 render(<LoopQuestionPanel id="q_123" backLabel="返回知识与证据" onBack={()=>{}} taskContext={{observation,claim_ref:{id:'C1',version:2}}}/>);
 await waitFor(()=>expect(resolveInspection).toBeDefined());
 expect(screen.queryByRole('radio')).toBeNull();expect(calls.some(call=>call.path.includes('/evidence'))).toBe(false);
 await act(async()=>resolveInspection(new Response(JSON.stringify({scope:'human_inspection',correct_answer:{id:'from-source-B',letter:'A'},feedback:{correct_letter:'A',reveal:{curves:[]}}}))));
 expect(await within(screen.getByRole('article',{name:'候选 A'})).findByText('正确答案')).toBeTruthy();
 await waitFor(()=>expect(calls.some(call=>call.path.includes('/evidence?'))).toBe(true));
 expect(calls.filter(call=>call.path.endsWith('/questions/inspect'))).toEqual([{path:'/api/studio/questions/inspect',method:'POST',body:{source:{kind:'knowledge_evolution',question_id:'q_123',observation,expected_question_hash:hash}}}]);
 expect(calls.filter(call=>call.method!=='GET'&&!['/api/studio/questions/inspect','/api/studio/questions/applicable-knowledge'].includes(call.path))).toEqual([]);
 const query=new URL(calls.find(call=>call.path.includes('/evidence?'))!.path,'http://localhost').searchParams;
 expect(Object.fromEntries(query)).toMatchObject({...observation,sequence:'8',claim_id:'C1',claim_version:'2'});
});
