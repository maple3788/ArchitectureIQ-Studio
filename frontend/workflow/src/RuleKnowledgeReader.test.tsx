import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,cleanup,fireEvent,waitFor} from '@testing-library/react';
import {RuleKnowledgeReader} from './RuleKnowledgeReader';
import {RuleEvaluation} from './RuleEvaluation';
const ref={id:'kb',version:'v'};
const record={...ref,kind:'research_rules',name:'KB',sources:[{kind:'run',id:'r'}],snapshot:{version:'v',rules:[{rule_id:'r1',revision:'v1',state:'active',text:'宽度越小在这些条件下越好',rationale:'研究条件',rule:{when:[],winner:{width:16},loser:{width:32}}},{rule_id:'r2',revision:'v2',state:'active',text:'另一条未命中规则',rule:{}}]}};
vi.mock('./DatasetInputPicker',()=>({DatasetInputPicker:({onApply}:any)=><button onClick={()=>onApply({dataset_binding:{collection_id:'ds',revision:'rev',selection:{},keys:['q'],pair_keys:[]}})}>应用评测题</button>}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('reads_knowledge_before_applicable_questions and distinguishes unknown evidence',async()=>{
 const starts:any[]=[];vi.stubGlobal('fetch',async(path:string,init:any)=>{if(init?.method==='POST')starts.push(path);return new Response(JSON.stringify(path.endsWith('/kb')?{items:[record]}:{id:'r',refinement:{score:{per_rule:{r1:{applicable:2,correct:1,wrong:0,unknown:1,question_keys:['q']},r2:{applicable:0}},per_question:{q:{case:{ref:{key:'q'},question:{id:'Q',choices:[{id:'a',letter:'A'},{id:'b',letter:'B'}]},candidate_specs:[],dataset_spec:{}},prediction:{status:'answered',answer_id:'a',edges:[],paths:[]},scorable:true,correct:true,feedback:{correct_letter:'A'}}}}}}));});
 render(<RuleKnowledgeReader kbRef={ref}/>);await screen.findByText('宽度越小在这些条件下越好');expect(screen.getByRole('tab',{name:'知识'}).getAttribute('aria-selected')).toBe('true');expect(await screen.findByText('尚未检验')).toBeTruthy();expect(await screen.findByText(/无法判定 1/)).toBeTruthy();
 fireEvent.click(screen.getByRole('tab',{name:'适用题目'}));await screen.findByLabelText('适用题目');expect(screen.getByRole('radiogroup',{name:'候选方案'})).toBeTruthy();expect(starts).toEqual([]);
});
it('starts local stored-rule Task checks without any model configuration',async()=>{
 const calls:any[]=[];vi.stubGlobal('fetch',async(path:string,init:any)=>{calls.push({path,body:init?.body&&JSON.parse(init.body)});return new Response(JSON.stringify(path.endsWith('/kb')?{items:[record]}:path.endsWith('/preview')?{can_run:true,preview_hash:'h',blockers:[],counts:{questions:1},independence:'unknown_prior_exposure'}:{id:'eval'}));});const onStarted=vi.fn();render(<RuleEvaluation kbRef={ref} onStarted={onStarted}/>);await screen.findByRole('option',{name:/KB/});fireEvent.click(screen.getByRole('button',{name:'选择评测 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用评测题'}));fireEvent.click(screen.getByRole('button',{name:'预览规则评测'}));await screen.findByText('此前接触情况未知');expect(screen.queryByLabelText('模型')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'开始规则评测'}));await waitFor(()=>expect(onStarted).toHaveBeenCalledWith('eval'));expect(calls.find(c=>c.path.endsWith('/evaluations')).body).toMatchObject({kb_ref:ref,phase:'final',dataset_ref:{collection_id:'ds',revision:'rev'}});
});
