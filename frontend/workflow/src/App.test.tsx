import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import App from './App';
afterEach(()=>{cleanup();vi.unstubAllGlobals();location.hash='';});
it('question shortcut opens RAG with exact version key and leaves workflow storage intact',async()=>{
 const storage=new Map<string,string>();vi.stubGlobal('localStorage',{setItem:(key:string,value:string)=>storage.set(key,value),getItem:(key:string)=>storage.get(key)||null,removeItem:(key:string)=>storage.delete(key)});
 location.hash='questions';localStorage.setItem('workflow-draft-test','preserve');
 vi.stubGlobal('fetch',async(path:string)=>{
  const value=path.endsWith('/bootstrap')?{service:{execution_enabled:false,host:'local'},stats:{questions:1},models:[]}:
   path.includes('/questions?')?{items:[{key:'q1@rev',id:'q1',family:'regression',type:'mixed',choices:2,ready:true,rag_ready:true,issues:[],model_types:[],source_count:1}],total:1}:
   path.endsWith('/sources')?{items:[],total:0}:{metadata:{key:'q1@rev',rag_ready:true},public:{id:'q1',family:'regression',prompt:'public',choices:[]}};
  return new Response(JSON.stringify(value));
 });
 render(<App/>);
 const modules=within(screen.getByRole('navigation',{name:'核心模块'}));
 expect(modules.getAllByRole('button').map(button=>button.textContent)).toEqual(['Data','Harness','KB','Task']);
 expect(modules.getByRole('button',{name:'Data'}).getAttribute('aria-current')).toBe('page');
 fireEvent.click(await screen.findByRole('button',{name:'打开 q1'}));
 fireEvent.click(await screen.findByRole('button',{name:'用 RAG 匹配 KB 作答'}));
 expect(await screen.findByRole('heading',{name:'RAG 作答'})).toBeTruthy();expect(screen.getAllByText('q1@rev').length).toBeGreaterThan(0);
 expect(location.hash).toBe('#rag');expect(localStorage.getItem('workflow-draft-test')).toBe('preserve');localStorage.removeItem('workflow-draft-test');
 expect(modules.getByRole('button',{name:'Task'}).getAttribute('aria-current')).toBe('page');
});
it('opens Data by default while preserving existing named routes',async()=>{
 location.hash='';
 vi.stubGlobal('fetch',async(path:string)=>new Response(JSON.stringify(path.endsWith('/bootstrap')?{service:{execution_enabled:false,host:'local'},stats:{},capabilities:{}}:{items:[],total:0})));
 render(<App/>);
 expect(await screen.findByRole('heading',{name:'我的 Datasets'})).toBeTruthy();
 const dataNav=within(screen.getByRole('navigation',{name:'Data 工作空间'}));
 fireEvent.click(dataNav.getByText('更多'));
 fireEvent.click(dataNav.getByRole('button',{name:'生成任务'}));
 expect(await screen.findByRole('heading',{name:'构建研究题目'})).toBeTruthy();
 expect(location.hash).toBe('#generation');
 fireEvent.click(dataNav.getByText('更多'));
 fireEvent.click(dataNav.getByRole('button',{name:'题源管理'}));
 expect(await screen.findByRole('button',{name:'管理题源'})).toBeTruthy();
 expect(location.hash).toBe('#questions');
 fireEvent.click(dataNav.getByRole('button',{name:'总题库'}));
 expect(await screen.findByRole('heading',{name:'总题库'})).toBeTruthy();
 expect(location.hash).toBe('#data');
});
it('keeps model deep links inside Harness and follows browser hash navigation',async()=>{
 location.hash='#models';
 vi.stubGlobal('fetch',async(path:string)=>new Response(JSON.stringify(path.endsWith('/bootstrap')?{service:{execution_enabled:false,host:'local'},stats:{},models:[]}:{items:[],total:0})));
 render(<App/>);
 expect(await screen.findByRole('heading',{name:'配置模型接入。'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'Harness'}).getAttribute('aria-current')).toBe('page');
 fireEvent.click(screen.getByRole('button',{name:'Task'}));
 expect(await screen.findByRole('heading',{name:'RAG 作答'})).toBeTruthy();
 location.hash='#rag_one';
 fireEvent(window,new HashChangeEvent('hashchange'));
 expect(screen.getByRole('heading',{name:'RAG 作答'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'Task'}).getAttribute('aria-current')).toBe('page');
 location.hash='#models';
 fireEvent(window,new HashChangeEvent('hashchange'));
 expect(await screen.findByRole('heading',{name:'配置模型接入。'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'模型配置'}).getAttribute('aria-current')).toBe('page');
});
