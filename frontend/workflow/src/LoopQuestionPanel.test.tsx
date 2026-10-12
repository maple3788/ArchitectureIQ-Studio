import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {LoopQuestionPanel} from './LoopQuestionPanel';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('commits against the viewed evolution snapshot before requesting saved comparisons',async()=>{
 const observation={source_identity:'a'.repeat(64),sequence:8},hash='b'.repeat(64),calls:{path:string;body?:any}[]=[];
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{calls.push({path,body:init?.body&&JSON.parse(init.body as string)});return new Response(JSON.stringify(path.endsWith('/review')?{selected_answer:{id:'from-source-A',letter:'C'},correct_answer:{id:'from-source-B',letter:'A'},correct:false,feedback:{reveal:{curves:[]}}}:path.includes('/evidence?')?{question_id:'q_123',claims:[],notice:'记录中的知识证据'}:{metadata:{id:'q_123'},observation:{content_hash:hash},public:{id:'q_123',choices:[{id:'from-source-A',letter:'C'},{id:'from-source-B',letter:'A'}]}}));});
 render(<LoopQuestionPanel id="q_123" backLabel="返回知识与证据" onBack={()=>{}} taskContext={{observation,claim_ref:{id:'C1',version:2}}}/>);
 fireEvent.click(await screen.findByRole('radio',{name:'选择 C'}));expect(calls.some(call=>call.path.includes('/evidence'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 await screen.findByText('正确答案 A');await waitFor(()=>expect(calls.some(call=>call.path.includes('/evidence?'))).toBe(true));
 expect(calls.find(call=>call.path.endsWith('/review'))?.body).toEqual({source:{kind:'knowledge_evolution',question_id:'q_123',observation,expected_question_hash:hash},answer_id:'from-source-A'});
 const query=new URL(calls.find(call=>call.path.includes('/evidence?'))!.path,'http://localhost').searchParams;
 expect(Object.fromEntries(query)).toMatchObject({...observation,sequence:'8',claim_id:'C1',claim_version:'2'});
});
