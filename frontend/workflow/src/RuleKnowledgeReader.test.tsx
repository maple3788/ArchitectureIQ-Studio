import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,cleanup,fireEvent,waitFor,within} from '@testing-library/react';
import {RuleKnowledgeReader} from './RuleKnowledgeReader';
import {RuleEvaluation} from './RuleEvaluation';
const ref={id:'kb',version:'v'};
const record={...ref,kind:'research_rules',name:'KB',sources:[{kind:'run',id:'r'}],snapshot:{version:'v',rules:[{rule_id:'r1',revision:'v1',state:'active',text:'宽度越小在这些条件下越好',rationale:'研究条件',rule:{when:[],winner:{width:16},loser:{width:32}}},{rule_id:'r2',revision:'v2',state:'active',text:'另一条未命中规则',rule:{}}]}};
vi.mock('./DatasetInputPicker',()=>({DatasetInputPicker:({onApply}:any)=><button onClick={()=>onApply({dataset_binding:{collection_id:'ds',revision:'rev',selection:{},keys:['q'],pair_keys:[]}})}>应用评测题</button>}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('reads_knowledge_before_applicable_questions and distinguishes unknown evidence',async()=>{
 const starts:any[]=[];vi.stubGlobal('fetch',async(path:string,init:any)=>{if(init?.method==='POST')starts.push(path);return new Response(JSON.stringify(path.endsWith('/questions/applicable-knowledge')?{scope:'public_applicability',items:[],total:0,feedback_released:false}:path.endsWith('/kb')?{items:[record]}:{id:'r',refinement:{score:{per_rule:{r1:{applicable:2,correct:1,wrong:0,unknown:1,question_keys:['q']},r2:{applicable:0}},per_question:{q:{case:{ref:{key:'q'},question:{id:'Q',choices:[{id:'a',letter:'A'},{id:'b',letter:'B'}]},candidate_specs:[],dataset_spec:{}},prediction:{status:'answered',answer_id:'a',edges:[],paths:[]},scorable:true,correct:true,feedback:{correct_letter:'A'}}}}}}));});
 render(<RuleKnowledgeReader kbRef={ref}/>);await screen.findByText('宽度越小在这些条件下越好');expect(screen.getByRole('tab',{name:'知识'}).getAttribute('aria-selected')).toBe('true');expect(await screen.findByText('尚未检验')).toBeTruthy();expect(await screen.findByText(/无法判定 1/)).toBeTruthy();
 fireEvent.click(screen.getByRole('tab',{name:'适用题目'}));await screen.findByLabelText('适用题目');expect(screen.getByRole('heading',{name:'候选对比'})).toBeTruthy();expect(screen.getByText('2 个候选')).toBeTruthy();expect(starts.filter(path=>!path.endsWith('/questions/applicable-knowledge'))).toEqual([]);
});
it('starts local stored-rule Task checks without any model configuration',async()=>{
 const calls:any[]=[];vi.stubGlobal('fetch',async(path:string,init:any)=>{calls.push({path,body:init?.body&&JSON.parse(init.body)});return new Response(JSON.stringify(path.endsWith('/kb')?{items:[record]}:path.endsWith('/preview')?{can_run:true,preview_hash:'h',blockers:[],counts:{questions:1},independence:'unknown_prior_exposure'}:{id:'eval'}));});const onStarted=vi.fn();render(<RuleEvaluation kbRef={ref} onStarted={onStarted}/>);await screen.findByRole('option',{name:/KB/});fireEvent.click(screen.getByRole('button',{name:'选择评测 Dataset'}));fireEvent.click(screen.getByRole('button',{name:'应用评测题'}));fireEvent.click(screen.getByRole('button',{name:'预览规则评测'}));await screen.findByText('此前接触情况未知');expect(screen.queryByLabelText('模型')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'开始规则评测'}));await waitFor(()=>expect(onStarted).toHaveBeenCalledWith('eval'));expect(calls.find(c=>c.path.endsWith('/evaluations')).body).toMatchObject({kb_ref:ref,phase:'final',dataset_ref:{collection_id:'ds',revision:'rev'}});
});

it('keeps source validation, model-reference policy and strict program conditions distinct',()=>{
 const version={id:'builtin:kb-v10',version:'hash10',kind:'research_rules',snapshot:{parent_version:'hash9',source_document:{version_label:'v10',filename:'kb_v10_revision.json',file_sha256:'source10'},rules:[{rule_id:'R2:0',revision:'r2rev',state:'active',text:'固定深度与训练配置时更宽更好',metadata:{claim_id:'R2',clause_index:0,validity_status:'replicated_in_scope',validation_origin:'source_reported',inject:false,parents:['v9 R2'],usage_note:'参数量受限时宽度和深度同时变化，使用 R6。'},rule:{scope:[['model_type','eq','mlp']],same:['depth','opt_key'],predict:{higher_better:'width'}}}]}};
 render(<RuleKnowledgeReader kbRef={{id:version.id,version:version.version}} record={version}/>);
 expect(screen.getByText(/来源标记：范围内复现/)).toBeTruthy();
 expect(screen.getByText(/本平台尚未重新验证/)).toBeTruthy();
 expect(screen.getByText(/不注入模型；仍可按程序条件验证/)).toBeTruthy();
 expect(screen.getByText('参数量受限时宽度和深度同时变化，使用 R6。')).toBeTruthy();
 expect(screen.getByText('深度、优化器完整配置')).toBeTruthy();
 expect(screen.getByText('来自 v9 R2')).toBeTruthy();
 expect(screen.queryByText('已验证且启用')).toBeNull();
});

it('groups clauses under their original claim and retains bounds and confirmation protocol',()=>{
 const metadata={claim_id:'R6',validity_status:'proposed',validation_origin:'source_reported',inject:true,inject_same:[],parents:['K0056'],operation:'broaden + split'};
 const rule=(id:string,clause_index:number,depth:string)=>({rule_id:id,revision:id+'rev',state:'active',text:'深度与宽度权衡',metadata:{...metadata,clause_index},rule:{scope:[['model_type','eq','mlp']],same:['opt_key'],differ:['depth','width'],max_param_ratio:2,predict:{dominates:[['depth',depth],['width',depth==='higher'?'lower':'higher']]}}});
 const version={id:'builtin:kb-v10',version:'hash10',snapshot:{source_document:{version_label:'v10',filename:'kb_v10_revision.json',legacy_disposition:{K0056:'split into R6'}},rules:[rule('R6:0',0,'higher'),rule('R6:1',1,'lower')],confirmation_protocol:{unit:'dataset instance (lineage)',decision_rule:{confirmatory:['R6'],REPLICATED:'determined lineages >= 16 AND success rate >= 0.75',REFUTED:'success rate < 0.5'},downstream:'Only replicated claims enter the next use.'}}};
 render(<RuleKnowledgeReader kbRef={{id:version.id,version:version.version}} record={version}/>);
 expect(screen.getAllByRole('heading',{name:'深度与宽度权衡'})).toHaveLength(1);
 const article=screen.getByRole('article');
 expect(within(article).getByText(/来源标记：待独立确认/)).toBeTruthy();
 expect(within(article).getByText('分支 1')).toBeTruthy();expect(within(article).getByText('分支 2')).toBeTruthy();
 expect(within(article).getAllByText('两候选参数量之比不超过 2 倍')).toHaveLength(2);
 expect(within(article).getByText(/不要求保持相同字段；程序执行仍保留原条件/)).toBeTruthy();
 expect(screen.getByText('determined lineages >= 16 AND success rate >= 0.75')).toBeTruthy();
 expect(screen.getByText(/协议不代表确认结果/)).toBeTruthy();
});

it('does not carry a source validation badge onto a rule modified in Studio',()=>{
 const version={id:'edited',version:'h',snapshot:{rules:[{rule_id:'R1',state:'active',text:'已修改条件',metadata:{claim_id:'R1',validity_status:'replicated_in_scope',validation_origin:'modified_in_studio'},rule:{same:['width'],predict:{higher_better:'depth'}}}]}};
 render(<RuleKnowledgeReader kbRef={{id:version.id,version:version.version}} record={version}/>);
 expect(screen.getByText(/本平台已修订 · 待重新验证/)).toBeTruthy();
 expect(screen.queryByText(/^来源标记：范围内复现/)).toBeNull();
});

it('uses active revisions for a split claim rather than its retired source policy',()=>{
 const base={rule_id:'R1-old',revision:'old',state:'retired',text:'旧规则',metadata:{claim_id:'R1',clause_index:1,validity_status:'replicated_in_scope',validation_origin:'source_reported',inject:true,inject_same:[]},rule:{predict:{higher_better:'depth'}}};
 const version={id:'split',version:'split-hash',snapshot:{source_document:{version_label:'KB v10'},rules:[base,{...base,rule_id:'R1-new',state:'active',text:'已缩小范围的规则',metadata:{...base.metadata,validity_status:'proposed',validation_origin:'modified_in_studio'}}]}};
 render(<RuleKnowledgeReader kbRef={{id:version.id,version:version.version}} record={version}/>);
 expect(screen.getByRole('heading',{name:'已缩小范围的规则'})).toBeTruthy();
 expect(screen.getByText('规则知识')).toBeTruthy();
 expect(screen.queryByText('KB v10')).toBeNull();
 expect(screen.getByText(/待独立确认，不作为已复现知识供模型参考/)).toBeTruthy();
 expect(screen.queryByText(/来源允许参考/)).toBeNull();
 expect(screen.getByText('已退役')).toBeTruthy();
});

it.each(['exploratory','descriptive'])('does not enable model reference for a %s role with a replicated source label',role=>{
 const version={id:'roles',version:'h',snapshot:{rules:[{rule_id:'R1',state:'active',text:'仅记录的主张',metadata:{claim_id:'R1',role,validity_status:'replicated_in_scope',validation_origin:'source_reported',inject:true,inject_same:[]},rule:{predict:{higher_better:'depth'}}}]}};
 render(<RuleKnowledgeReader kbRef={{id:version.id,version:version.version}} record={version}/>);
 expect(screen.getByText('来源标记：范围内复现')).toBeTruthy();
 expect(screen.getByText(/仅作探索或描述记录，不用于模型参考/)).toBeTruthy();
 expect(screen.queryByText(/来源允许参考/)).toBeNull();
});

it('focuses a single claim on content and never shows sibling rules or the whole-KB selector',()=>{
 const rule=(id:string,claim:string,text:string)=>({rule_id:id,revision:'rev-'+id,state:'active',text,metadata:{claim_id:claim,validity_status:'proposed',validation_origin:'source_reported'},rule:{same:['depth'],predict:{higher_better:'width'}}});
 const single={id:'research',version:'frozen',snapshot:{rules:[rule('r1','C1','在相同深度下比较宽度'),rule('r2','C2','另一条知识不能混入')]}};
 render(<RuleKnowledgeReader kbRef={{id:'research',version:'frozen'}} record={single} claimId="C1"/>);
 expect(screen.getByRole('tab',{name:'知识内容'}).getAttribute('aria-selected')).toBe('true');
 expect(screen.getByRole('heading',{name:'在相同深度下比较宽度'})).toBeTruthy();
 expect(screen.queryByText('另一条知识不能混入')).toBeNull();
 expect(screen.queryByLabelText('按规则查看')).toBeNull();
 expect(screen.getByRole('tab',{name:'不适用题目'})).toBeTruthy();
});

it('does not substitute another claim when an exact selected claim is absent',()=>{
 render(<RuleKnowledgeReader kbRef={ref} record={record} claimId="missing"/>);
 expect(screen.queryByText('宽度越小在这些条件下越好')).toBeNull();
 expect(screen.getByText(/这条知识在当前记录中暂不可用/)).toBeTruthy();
});
