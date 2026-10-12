import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {Tasks} from './Tasks';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const card:any={id:'task1',name:'架构选择实验',revision:1,created_at:1,updated_at:1,question_key:'q1@rev',mode:'llm',model_id:'glm',kb_selection:{mode:'auto'},knowledge_limit:8};
const question={metadata:{key:'q1@rev'},public:{id:'q1',family:'regression',prompt:'完整公开题面',choices:[{id:'a',letter:'A',view:{}},{id:'b',letter:'B',view:{}}]}};
const kb={id:'kb1',version:'hash1',name:'架构规则',kind:'research_rules',summary:'3 条规则'};
const prediction={status:'answered',answer_id:'a',answer_letter:'A',matches:[{kb,prediction:{status:'answered',answer_id:'a',edges:[],paths:{}}}],issues:[]};
const rulePreview={task_id:'task1',task_revision:1,mode:'rules',preview_hash:'frozen',can_run:true,can_answer:true,question:question.public,selected_kbs:[kb],prediction,warnings:[]};
function setup(initial:any[]=[card],extra?:(path:string,init:RequestInit|undefined)=>Promise<Response|undefined>){
 let cards=initial.map(c=>({...c}));const calls:{path:string;body:any;method?:string}[]=[];
 const fetcher=async(path:string,init?:RequestInit)=>{
  const body=init?.body?JSON.parse(String(init.body)):undefined;calls.push({path,body,method:init?.method});
  const override=await extra?.(path,init);if(override)return override;
  let value:any={};
  if(path.endsWith('/questions/applicable-knowledge'))value={scope:'public_applicability',items:[],total:0,feedback_released:false};
  else if(path.endsWith('/tasks')&&init?.method==='POST'){value={...card,...body,id:'created',revision:1};cards.push(value);}
  else if(path.endsWith('/tasks'))value={items:cards,total:cards.length};
  else if(path.includes('/tasks/kbs'))value={items:[kb],total:1};
  else if(path.includes('/tasks/questions/'))value=question;
  else if(path.endsWith('/preview'))value={...rulePreview,mode:cards[0]?.mode||'rules',task_revision:cards[0]?.revision||1};
  else if(path.endsWith('/runs')&&init?.method==='POST')value={id:'receipt1',task_id:'task1',task_revision:cards[0].revision,mode:'rules',status:'completed',created_at:1,result:{prediction,selected_kbs:[kb],question:question.public}};
  else if(path.endsWith('/runs'))value={items:[],total:0};
  else if(path.includes('/tasks/')){const id=path.split('/').at(-1);const current=cards.find(c=>c.id===id);if(init?.method==='PUT'){value={...current,...body,revision:current.revision+1};cards=cards.map(c=>c.id===id?value:c);}else value=current;}
  else if(path.includes('/questions?'))value={items:[{key:'q1@rev',id:'q1',family:'regression',type:'mixed',choices:2,rag_ready:true,ready:true,issues:[],model_types:[],source_count:1}],total:1};
  else if(path.includes('/questions/'))value=question;
  return new Response(JSON.stringify(value));
 };
 vi.stubGlobal('fetch',fetcher);
 const props={version:0,act:async(fn:any)=>fn(),models:[{id:'glm',name:'GLM',enabled:true}] as any,executionEnabled:false,onRun:vi.fn()};
 const view=render(<Tasks {...props}/>);return {...view,props,calls};
}
it('loads persisted task cards and binds history to the selected card',async()=>{
 setup([card,{...card,id:'task2',name:'第二个实验'}],async path=>path.endsWith('/task1/runs')?new Response(JSON.stringify({items:[{id:'old-result',task_id:'task1',task_revision:1,mode:'rules',status:'completed',created_at:1,result:{prediction,question:question.public,selected_kbs:[kb]}}],total:1})):undefined);
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));
 expect(await screen.findByText('old-result')).toBeTruthy();expect(screen.getByRole('heading',{name:'候选 A',level:3})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'返回任务列表'}));fireEvent.click(await screen.findByRole('button',{name:'打开任务 第二个实验'}));
 expect(await screen.findByText('这个任务还没有作答记录。')).toBeTruthy();expect(screen.queryByText('old-result')).toBeNull();
});
it('switches to rules without a model and records the frozen result locally',async()=>{
 const c=setup();fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));
 await screen.findByLabelText('作答模型');fireEvent.click(screen.getByLabelText('KB 直接解答'));
 expect(screen.queryByLabelText('作答模型')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'保存任务'}));
 await waitFor(()=>expect(c.calls.some(v=>v.method==='PUT'&&v.body.mode==='rules'&&v.body.model_id===null)).toBe(true));
 fireEvent.click(await screen.findByRole('button',{name:'匹配并预览'}));await screen.findByText('规则匹配预览');
 const run=screen.getByRole('button',{name:'执行并记录'}) as HTMLButtonElement;expect(run.disabled).toBe(false);fireEvent.click(run);fireEvent.click(run);
 await waitFor(()=>expect(c.calls.filter(v=>v.path.endsWith('/runs')&&v.method==='POST').length).toBe(1));
 expect(c.calls.find(v=>v.path.endsWith('/runs')&&v.method==='POST')?.body).toEqual({expected_revision:2,preview_hash:'frozen'});
});
it('invalidates previews after edits and ignores late preview responses',async()=>{
 let resolve!:(r:Response)=>void;
 const c=setup([{...card,mode:'rules',model_id:null}],async path=>path.endsWith('/preview')?new Promise<Response>(r=>{resolve=r;}):undefined);
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');
 fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));await waitFor(()=>expect(resolve).toBeTruthy());
 fireEvent.change(screen.getByLabelText('任务名称'),{target:{value:'修改后'}});resolve(new Response(JSON.stringify(rulePreview)));
 await waitFor(()=>expect((screen.getByRole('button',{name:'保存任务'}) as HTMLButtonElement).disabled).toBe(false));
 expect(screen.queryByText('规则匹配预览')).toBeNull();expect(c.calls.filter(v=>v.path.endsWith('/runs')&&v.method==='POST')).toHaveLength(0);
});
it('keeps unsaved edits on a revision conflict',async()=>{
 setup([card],async(_path,init)=>init?.method==='PUT'?new Response(JSON.stringify({detail:'任务已被更新'}),{status:409}):undefined);
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');
 fireEvent.change(screen.getByLabelText('任务名称'),{target:{value:'我未保存的修改'}});fireEvent.click(screen.getByRole('button',{name:'保存任务'}));
 await screen.findByText('任务已被更新');expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe('我未保存的修改');
 expect(screen.getByText(/当前填写内容已保留/)).toBeTruthy();expect(screen.queryByText('规则匹配预览')).toBeNull();
});
it('creates a persistent task with selected question and manual KB',async()=>{
 const c=setup([]);fireEvent.click(await screen.findByRole('button',{name:'新建任务'}));
 fireEvent.change(screen.getByLabelText('任务名称'),{target:{value:'我的规则实验'}});fireEvent.click(screen.getByLabelText('KB 直接解答'));
 fireEvent.click(screen.getByRole('button',{name:'选择题目'}));fireEvent.click(await screen.findByLabelText('选择 q1'));
 fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));await screen.findByText('q1@rev');
 fireEvent.change(screen.getByLabelText('知识来源'),{target:{value:'manual'}});await screen.findByRole('option',{name:'架构规则'});
 fireEvent.change(screen.getByLabelText('指定 KB'),{target:{value:'kb1@hash1'}});fireEvent.click(screen.getByRole('button',{name:'保存任务'}));
 await waitFor(()=>expect(c.calls.find(v=>v.path.endsWith('/tasks')&&v.method==='POST')?.body).toMatchObject({name:'我的规则实验',question_key:'q1@rev',mode:'rules',model_id:null,kb_selection:{mode:'manual',ref:{id:'kb1',version:'hash1'}}}));
 fireEvent.click(await screen.findByRole('button',{name:'返回任务列表'}));expect(await screen.findByRole('button',{name:'打开任务 我的规则实验'})).toBeTruthy();
});
it('disables LLM execution locally after a valid preview',async()=>{
 setup();fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('作答模型');
 fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));await screen.findByText('作答预览');expect((screen.getByRole('button',{name:'开始作答'}) as HTMLButtonElement).disabled).toBe(true);
});
it('shows research qualifications and readable matched rule conditions',async()=>{
 const rule={rule_id:'r1',revision:'r1v',text:'小学习率规则',validity_status:'proposed',validation_origin:'research',rule:{scope:[['family','eq','regression']],predict:{lower_better:'lr'}}};
 setup([{...card,mode:'rules',model_id:null}],async path=>path.endsWith('/preview')?new Response(JSON.stringify({...rulePreview,selected_kbs:[{...kb,verification:'research_hypothesis'}],prediction:{...prediction,matches:[{kb,rules:[rule],prediction:prediction.matches[0].prediction}]}})):undefined);
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));
 expect(await screen.findByText('研究假设 · 待独立验证')).toBeTruthy();expect(screen.getByText('小学习率规则')).toBeTruthy();expect(screen.getByText('学习率更低的候选更好')).toBeTruthy();expect(screen.getByText('来源标记：待独立确认')).toBeTruthy();
});
it('reads the committed structured model answer in task history',async()=>{
 setup([card],async path=>path.endsWith('/task1/runs')?new Response(JSON.stringify({items:[{id:'model-run',task_id:'task1',task_revision:1,mode:'llm',status:'complete',created_at:1,job_id:'job1',result:{answer:{ranking:['A','B'],rationale:'候选 A 符合知识的条件',citations:['rule1']},unknown_citations:['unknown1']}}],total:1})):undefined);
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));expect(await screen.findByText('A → B')).toBeTruthy();expect(screen.getByText('候选 A 符合知识的条件')).toBeTruthy();expect(screen.getByText('未能对应到提供知识的引用：unknown1')).toBeTruthy();
});
it('requires a KB selection before saving manual mode',async()=>{
 const c=setup([card]);fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');
 fireEvent.change(screen.getByLabelText('知识来源'),{target:{value:'manual'}});
 expect((screen.getByRole('button',{name:'保存任务'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getByText('请先选择一个知识库，再保存任务。')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'保存任务'}));expect(c.calls.filter(call=>call.method==='PUT')).toHaveLength(0);
 await screen.findByRole('option',{name:'架构规则'});fireEvent.change(screen.getByLabelText('指定 KB'),{target:{value:'kb1@hash1'}});
 expect((screen.getByRole('button',{name:'保存任务'}) as HTMLButtonElement).disabled).toBe(false);
 expect(screen.queryByText('请先选择一个知识库，再保存任务。')).toBeNull();
});
it('connects generated questions and evolution KB snapshots to a saved task',async()=>{
 const evolutionKB={...kb,id:'loop-kb',version:'snapshot2',name:'知识演化',source_kind:'knowledge_evolution',round_index:2,verification:'research_hypothesis'};
 const c=setup([],async(path,init)=>{
  if(path.includes('/tasks/kbs'))return new Response(JSON.stringify({items:[evolutionKB],total:1}));
  if(path.includes('/tasks/evolution/questions?'))return new Response(JSON.stringify({items:[{id:'q_gen',family:'univariate_regression',question_type:'mixed',round_index:2}],total:1,source:{connected:true}}));
  if(path.endsWith('/tasks/evolution/questions/q_gen')&&init?.method==='POST')return new Response(JSON.stringify({key:'evolution:frozen:key',record:question}));
  if(path.includes('/tasks/questions/evolution%3Afrozen%3Akey'))return new Response(JSON.stringify({...question,metadata:{...question.metadata,source_kind:'knowledge_evolution',round_index:2},public:{...question.public,id:'q_gen'}}));
 });
 fireEvent.click(await screen.findByRole('button',{name:'新建任务'}));fireEvent.change(screen.getByLabelText('任务名称'),{target:{value:'演化知识解答'}});fireEvent.click(screen.getByLabelText('KB 直接解答'));fireEvent.click(screen.getByRole('button',{name:'选择题目'}));
 fireEvent.click(screen.getByRole('tab',{name:'知识演化'}));fireEvent.click(await screen.findByLabelText('选择 q_gen'));fireEvent.click(screen.getByRole('button',{name:'应用所选题目'}));await screen.findByText('来自知识演化 · 第 2 轮');
 fireEvent.change(screen.getByLabelText('知识来源'),{target:{value:'manual'}});await screen.findByRole('option',{name:'知识演化 · 第 2 轮 · 研究候选'});
 fireEvent.change(screen.getByLabelText('指定 KB'),{target:{value:'loop-kb@snapshot2'}});fireEvent.click(screen.getByRole('button',{name:'保存任务'}));
 await waitFor(()=>expect(c.calls.find(call=>call.method==='POST'&&call.path.endsWith('/tasks'))?.body).toMatchObject({question_key:'evolution:frozen:key',kb_selection:{mode:'manual',ref:{id:'loop-kb',version:'snapshot2'}}}));
});
it('renders rule explanations in preview and actual citations in persisted model history',async()=>{
 setup([{...card,mode:'rules',model_id:null}],async path=>{
  if(path.endsWith('/preview'))return new Response(JSON.stringify({...rulePreview,prediction:{...prediction,explanation:{status:'answered',summary:'规则 A 覆盖了其余候选',edges:[],paths:[],conflicts:[],uncovered_pairs:[]}}}));
  if(path.endsWith('/task1/runs'))return new Response(JSON.stringify({items:[{id:'cited',task_id:'task1',task_revision:1,mode:'llm',status:'complete',created_at:1,result:{answer:{ranking:['A','B'],rationale:'引用规则得出 A',citations:['K1']},used_sources:[{citation_id:'K1',text:'这条规则确实被引用',source_claim_ids:['C001']}],provided_sources:[]}}],total:1}));
 });
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));
 expect(await screen.findByText('规则 A 覆盖了其余候选')).toBeTruthy();expect(screen.getByText('这条规则确实被引用')).toBeTruthy();
});
it('allows rematching an expired preview when the saved task revision has not changed',async()=>{
 setup([{...card,mode:'rules',model_id:null}],async(path,init)=>path.endsWith('/runs')&&init?.method==='POST'?new Response(JSON.stringify({detail:'预览已失效，请重新预览'}),{status:409}):undefined);
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));
 fireEvent.click(await screen.findByRole('button',{name:'执行并记录'}));await screen.findByText('预览已失效，请重新预览');
 await waitFor(()=>expect((screen.getByRole('button',{name:'匹配并预览'}) as HTMLButtonElement).disabled).toBe(false));
 expect(screen.queryByRole('button',{name:'载入服务器版本'})).toBeNull();expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe(card.name);
 fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));expect(await screen.findByRole('button',{name:'执行并记录'})).toBeTruthy();
});
it('preserves the current fields and asks for explicit reload on a true run revision conflict',async()=>{
 let changed=false;
 setup([{...card,mode:'rules',model_id:null}],async(path,init)=>{
  if(path.endsWith('/runs')&&init?.method==='POST'){changed=true;return new Response(JSON.stringify({detail:'任务已在其他窗口更新，请重新加载并预览'}),{status:409});}
  if(changed&&path.endsWith('/tasks/task1'))return new Response(JSON.stringify({...card,mode:'rules',model_id:null,revision:2,name:'另一个窗口的修改'}));
 });
 fireEvent.click(await screen.findByRole('button',{name:'打开任务 架构选择实验'}));await screen.findByLabelText('任务名称');fireEvent.click(screen.getByRole('button',{name:'匹配并预览'}));fireEvent.click(await screen.findByRole('button',{name:'执行并记录'}));
 expect(await screen.findByRole('button',{name:'载入服务器版本'})).toBeTruthy();expect((screen.getByRole('button',{name:'匹配并预览'}) as HTMLButtonElement).disabled).toBe(true);expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe(card.name);
});
it('prefills both frozen evolution inputs without saving or running, and retains KB when choosing a model',async()=>{
 const evolved={...kb,id:'evolution_kb_source_C4',version:'frozen4',source_kind:'knowledge_evolution',source_claim_id:'C0004',round_index:2};
 const c=setup([],async path=>path.includes('/tasks/kbs')?new Response(JSON.stringify({items:[evolved]})):undefined);
 const seed={question_key:'evolution_question4',mode:'rules' as const,name:'知识演化 · C0004',kb_selection:{mode:'manual' as const,ref:{id:evolved.id,version:'frozen4'}},kb:evolved};
 const consumed=vi.fn();c.rerender(<Tasks {...c.props} seed={seed} onSeedConsumed={consumed}/>);
 await screen.findByRole('heading',{name:'新建解答任务'});
 expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe('知识演化 · C0004');
 expect((screen.getByLabelText('KB 直接解答') as HTMLInputElement).checked).toBe(true);
 await screen.findByRole('option',{name:'知识演化 · C0004 · 研究候选'});
 expect((screen.getByLabelText('指定 KB') as HTMLSelectElement).value).toBe('evolution_kb_source_C4@frozen4');
 expect(screen.getAllByText('evolution_question4').length).toBeGreaterThan(0);
 expect(c.calls.filter(call=>call.method==='POST'&&!call.path.endsWith('/questions/applicable-knowledge'))).toHaveLength(0);
 fireEvent.click(screen.getByLabelText('LLM + KB'));
 expect((screen.getByLabelText('指定 KB') as HTMLSelectElement).value).toBe('evolution_kb_source_C4@frozen4');
 fireEvent.change(screen.getByLabelText('作答模型'),{target:{value:'glm'}});
 fireEvent.click(screen.getByRole('button',{name:'保存任务'}));
 await waitFor(()=>expect(c.calls.find(call=>call.path.endsWith('/tasks')&&call.method==='POST')?.body).toMatchObject({question_key:'evolution_question4',mode:'llm',model_id:'glm',kb_selection:{mode:'manual',ref:{id:'evolution_kb_source_C4',version:'frozen4'}}}));
 expect(consumed).toHaveBeenCalledTimes(1);
});
it('opens a KB-only seed without selecting an arbitrary question and clears it when leaving the new task',async()=>{
 const c=setup([]);const seed={question_key:null,mode:'rules' as const,name:'知识演化 · C0004',kb_selection:{mode:'manual' as const,ref:{id:'kb1',version:'hash1'}}};
 c.rerender(<Tasks {...c.props} seed={seed}/>);
 await screen.findByRole('heading',{name:'新建解答任务'});await screen.findByRole('option',{name:'架构规则'});
 expect(screen.getByRole('button',{name:'选择题目'})).toBeTruthy();
 expect((screen.getByLabelText('指定 KB') as HTMLSelectElement).value).toBe('kb1@hash1');
 expect(c.calls.filter(call=>call.method==='POST'&&!call.path.endsWith('/questions/applicable-knowledge'))).toHaveLength(0);
 fireEvent.click(screen.getByRole('button',{name:'返回任务列表'}));fireEvent.click(await screen.findByRole('button',{name:'新建任务'}));
 expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe('');
 expect((screen.getByLabelText('知识来源') as HTMLSelectElement).value).toBe('auto');
});
