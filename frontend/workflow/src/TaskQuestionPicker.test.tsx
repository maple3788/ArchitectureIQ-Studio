import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TaskQuestionPicker} from './TaskQuestionPicker';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const record={metadata:{id:'q_generated',family:'univariate_regression'},public:{id:'q_generated',family:'univariate_regression',prompt:'这是一道真实生成题',choices:[{id:'ca',letter:'A',view:{}},{id:'cb',letter:'B',view:{}}]}};
function setup(extra?:(path:string,init?:RequestInit)=>Response|undefined){
 const calls:{path:string;method?:string}[]=[],onSelect=vi.fn(),onClose=vi.fn();
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
  calls.push({path,method:init?.method});const override=extra?.(path,init);if(override)return override;
  let data:unknown={};
  if(path.includes('/tasks/evolution/questions/'))data={key:'evolution:frozen:abc',record};
  else if(path.includes('/tasks/evolution/questions?'))data={items:[{id:'q_generated',family:'univariate_regression',question_type:'architecture_only',round_index:2,purpose:'target'}],total:26,source:{connected:true}};
  else if(path.includes('/questions?'))data={items:[{key:'q_catalog@old',id:'q_catalog',family:'bigram_lm',type:'mixed',rag_ready:true}],total:1};
  else if(path.includes('/tasks/questions/'))data=record;
  return new Response(JSON.stringify(data));
 });
 render(<TaskQuestionPicker version={0} onSelectQuestion={onSelect} onClose={onClose}/>);return {calls,onSelect,onClose};
}
it('selects a generated question through a persisted immutable record',async()=>{
 const c=setup();fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));
 fireEvent.click(await screen.findByLabelText('选择 q_generated'));fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 await waitFor(()=>expect(c.onSelect).toHaveBeenCalledWith('evolution:frozen:abc'));
 expect(c.calls.some(call=>call.path.endsWith('/tasks/evolution/questions/q_generated')&&call.method==='POST')).toBe(true);
});
it('searches and pages within the selected question source',async()=>{
 const c=setup();fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));await screen.findByLabelText('选择 q_generated');
 fireEvent.click(screen.getByRole('button',{name:'下一页'}));await waitFor(()=>expect(c.calls.some(call=>call.path.includes('offset=25'))).toBe(true));
 fireEvent.change(screen.getByLabelText('搜索题目'),{target:{value:'q_generated'}});
 await waitFor(()=>expect(c.calls.some(call=>call.path.includes('search=q_generated')&&call.path.includes('offset=0'))).toBe(true));
 fireEvent.click(screen.getByRole('tab',{name:'题库'}));expect(await screen.findByLabelText('选择 q_catalog')).toBeTruthy();
});
it('shows the public original question while preserving source selection',async()=>{
 const c=setup();fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));
 fireEvent.click(await screen.findByLabelText('选择 q_generated'));fireEvent.click(screen.getByRole('button',{name:'阅读题目 q_generated'}));
 fireEvent.click(await screen.findByRole('tab',{name:'原始 Prompt'}));expect(screen.getByText('这是一道真实生成题')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'返回题目列表'}));
 expect((screen.getByLabelText('选择 q_generated') as HTMLInputElement).checked).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));await waitFor(()=>expect(c.onSelect).toHaveBeenCalledWith('evolution:frozen:abc'));
});
it('keeps selection and explains unavailable snapshots without accepting a question ID',async()=>{
 const c=setup(path=>path.endsWith('/tasks/evolution/questions/q_generated')?new Response(JSON.stringify({detail:'来源题目暂不可读取'}),{status:503}):undefined);
 fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));fireEvent.click(await screen.findByLabelText('选择 q_generated'));fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 expect(await screen.findByText('来源题目暂不可读取')).toBeTruthy();expect(c.onSelect).not.toHaveBeenCalled();expect((screen.getByLabelText('选择 q_generated') as HTMLInputElement).checked).toBe(true);
});
