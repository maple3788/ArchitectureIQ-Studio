import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import App from './App';
afterEach(()=>{cleanup();vi.unstubAllGlobals();location.hash='';});
it('question shortcut opens RAG with exact version key and leaves workflow storage intact',async()=>{
 location.hash='questions';localStorage.setItem('workflow-draft-test','preserve');
 vi.stubGlobal('fetch',async(path:string)=>{
  const value=path.endsWith('/bootstrap')?{service:{execution_enabled:false,host:'local'},stats:{questions:1},models:[]}:
   path.includes('/questions?')?{items:[{key:'q1@rev',id:'q1',family:'regression',type:'mixed',choices:2,ready:true,rag_ready:true,issues:[],model_types:[],source_count:1}],total:1}:
   path.endsWith('/sources')?{items:[],total:0}:{metadata:{key:'q1@rev',rag_ready:true},public:{id:'q1',family:'regression',prompt:'public',choices:[]}};
  return new Response(JSON.stringify(value));
 });
 render(<App/>);fireEvent.click(await screen.findByRole('button',{name:'打开 q1'}));
 fireEvent.click(await screen.findByRole('button',{name:'用 RAG 匹配 KB 作答'}));
 expect(await screen.findByRole('heading',{name:'RAG 作答'})).toBeTruthy();expect(screen.getAllByText('q1@rev').length).toBeGreaterThan(0);
 expect(location.hash).toBe('#rag');expect(localStorage.getItem('workflow-draft-test')).toBe('preserve');localStorage.removeItem('workflow-draft-test');
});
