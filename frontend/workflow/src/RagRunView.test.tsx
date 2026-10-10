import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render,screen} from '@testing-library/react';
import {RagRunView} from './RagRunView';
import {ragRun,ragHit} from './ragTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('shows only arriving persisted content then sealed answer and separates provided and used sources',()=>{
 let source:any;class Source{listeners:any={};constructor(){source=this;}addEventListener(name:string,f:any){this.listeners[name]=f;}close(){}onerror:any;}
 vi.stubGlobal('EventSource',Source);
 const v=render(<RagRunView run={ragRun}/>);expect(screen.queryByText('真实增量正文')).toBeNull();
 act(()=>source.listeners.chunk({data:JSON.stringify({seq:1,wire_key:'wire',node_id:'solver',round_index:0,operation_key:'rag:q1@rev:glm',kind:'chunk',chunk:{choices:[{index:0,delta:{content:'真实增量正文'}}]}})}));
 expect(screen.getByText('真实增量正文')).toBeTruthy();
 v.rerender(<RagRunView run={{...ragRun,status:'complete',result:{answer:{ranking:['B','A'],rationale:'封存的解释',citations:['rag_one','unknown'],invalid_citations:true},used_sources:[ragHit],unknown_citations:['unknown']}}}/>);
 expect(screen.getByText('封存的解释')).toBeTruthy();expect(screen.getByText('B → A')).toBeTruthy();
 expect(screen.getByRole('heading',{name:'提供给模型的知识'})).toBeTruthy();expect(screen.getByRole('heading',{name:'模型实际引用'})).toBeTruthy();
 expect(screen.getByRole('link',{name:'引用知识 1'}).getAttribute('href')).toBe('#rag_one');
 expect(screen.queryByRole('link',{name:'unknown'})).toBeNull();expect(screen.getByText(/未知引用/)).toBeTruthy();expect(screen.getByText(/另一来源/)).toBeTruthy();
 expect(screen.queryByText(/accuracy|GT|正确率/)).toBeNull();
});
it('uncertain preserves received text and receipt status without generating a replacement answer',()=>{
 vi.stubGlobal('EventSource',undefined);
 render(<RagRunView run={{...ragRun,status:'uncertain',error:'timeout',records:[{status:'uncertain',actual_request:{},raw:null}]}}/>);
 expect(screen.getByText(/不会自动重试/)).toBeTruthy();expect(screen.getAllByText(/uncertain/).length).toBeGreaterThan(0);expect(screen.queryByText('封存的解释')).toBeNull();
});
