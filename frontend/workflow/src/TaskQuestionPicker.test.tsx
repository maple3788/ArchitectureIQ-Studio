import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TaskQuestionPicker} from './TaskQuestionPicker';
import {readFileSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const record={metadata:{id:'q_generated',family:'univariate_regression'},public:{id:'q_generated',family:'univariate_regression',prompt:'这是一道真实生成题',choices:[{id:'ca',letter:'A',view:{}},{id:'cb',letter:'B',view:{}}]}};
const candidates=[{letter:'A',model:{type:'mlp',depth:2}},{letter:'B',model:{type:'mlp',depth:4}}];
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
it.each(['题库','知识演化'])('shows public question and candidate summaries in %s without resolving individual records',async(source)=>{
 const c=setup(path=>path.includes('/questions?')?new Response(JSON.stringify({items:[{
  key:'q_options@exact',id:'q_options',family:'univariate_regression',question_type:'architecture_only',round_index:7,
  candidate_configs:candidates,answer:'SECRET_ANSWER',evaluation:{curves:'SECRET_CURVES'},prompt:'SECRET_PROMPT',
 }],total:1})):undefined);
 if(source==='知识演化')fireEvent.click(screen.getByRole('tab',{name:source}));
 expect(await screen.findByText('MLP · 深度 2 / 4')).toBeTruthy();
 expect(screen.getByText('比较以下 2 个候选方案，选择表现最好的一个。')).toBeTruthy();
 expect(screen.getByText('一元回归 · 架构对比')).toBeTruthy();
 expect(screen.getByText('MLP · 深度 2')).toBeTruthy();
 expect(screen.getByText('MLP · 深度 4')).toBeTruthy();
 expect(screen.getByRole('list',{name:'q_options 的公开候选'}).children).toHaveLength(2);
 expect(document.body.textContent).not.toContain('SECRET_');
 expect(c.calls.every(call=>call.path.includes('/questions?'))).toBe(true);
 expect(c.onSelect).not.toHaveBeenCalled();
});
it('keeps the selection radio compact despite the global full-width form styles',async()=>{
 const style=document.createElement('style');
 style.textContent=['styles.css','task-question-picker.css'].map(file=>readFileSync(join(dirname(fileURLToPath(import.meta.url)),file),'utf8')).join('\n');
 document.head.append(style);
 try{
  setup();const radio=await screen.findByLabelText('选择 q_catalog');
  const computed=window.getComputedStyle(radio);
  expect(computed.width).toMatch(/^\d+(\.\d+)?px$/);
  expect(parseFloat(computed.width)).toBeLessThanOrEqual(24);
  expect(computed.flexShrink).toBe('0');
 }finally{style.remove();}
});
it('keeps the exact catalogue key when the other source has the same question ID',async()=>{
 const c=setup(path=>path.includes('/tasks/evolution/questions?')?new Response(JSON.stringify({items:[{id:'q_catalog',key:'evolution_other',family:'bigram_lm',question_type:'mixed',round_index:2}],total:1})):undefined);
 fireEvent.click(await screen.findByLabelText('选择 q_catalog'));
 fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));
 await screen.findByText('q_catalog · 第 2 轮');
 expect((screen.getByLabelText('选择 q_catalog') as HTMLInputElement).checked).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 await waitFor(()=>expect(c.onSelect).toHaveBeenCalledWith('q_catalog@old'));
 expect(c.calls.some(call=>call.path.endsWith('/tasks/questions/q_catalog%40old'))).toBe(true);
 expect(c.calls.some(call=>call.method==='POST')).toBe(false);
});
it('keeps unavailable public inputs unselectable even when candidate metadata is present',async()=>{
 const c=setup(path=>path.includes('/questions?')?new Response(JSON.stringify({items:[{key:'q_missing@old',id:'q_missing',family:'univariate_regression',rag_ready:false,candidate_configs:candidates}],total:1})):undefined);
 const radio=await screen.findByLabelText('选择 q_missing');
 expect((radio as HTMLInputElement).disabled).toBe(true);
 expect((screen.getByRole('button',{name:'应用所选题目'}) as HTMLButtonElement).disabled).toBe(true);
 expect(c.onSelect).not.toHaveBeenCalled();
});
it('shows source candidate configurations without inventing their shuffled option letters',async()=>{
 setup(path=>path.includes('/tasks/evolution/questions?')?new Response(JSON.stringify({items:[{
  id:'q_source',family:'univariate_regression',question_type:'architecture_only',round_index:3,
  candidate_configs:[{candidate_id:'candidate_z',model:{type:'mlp',width:32}},{candidate_id:'candidate_a',model:{type:'mlp',width:16}}],
 }],total:1})):undefined);
 fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));
 const options=await screen.findByRole('list',{name:'q_source 的公开候选'});
 expect(options.textContent).toContain('MLP · 宽度 32');
 expect(options.textContent).toContain('MLP · 宽度 16');
 expect(options.textContent).not.toContain('?');
 expect([...options.querySelectorAll('b')].map(b=>b.textContent)).not.toContain('A');
 expect(screen.getByText('选项字母以完整题面为准。')).toBeTruthy();
});
it('rejects a changed evolution source instead of applying a different question snapshot',async()=>{
 const c=setup(path=>path.includes('/tasks/evolution/questions?')?new Response(JSON.stringify({items:[{
  id:'q_generated',key:'evolution_original_source',family:'univariate_regression',round_index:2,
 }],total:1})):undefined);
 fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));
 fireEvent.click(await screen.findByLabelText('选择 q_generated'));
 fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));
 expect(await screen.findByText('题目来源已变化，请重新打开选择器后重试。')).toBeTruthy();
 expect(c.onSelect).not.toHaveBeenCalled();
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
