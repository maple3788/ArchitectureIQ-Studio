import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowUpRight,BookOpen,Check,ChevronRight,FlaskConical,Plus,Sparkles} from 'lucide-react';
import {api,ApiError} from './api';
import {ErrorBox,Field,Loading,useResource} from './ui';
import {TaskQuestionPicker} from './TaskQuestionPicker';
import {RuleReasoning,ModelSources,SkippedRules} from './TaskReasoning';
import {QuestionReader} from './QuestionReader';
import {TaskRunRecord} from './TaskRunRecord';
import {RagKnowledge} from './Rag';
import {formatTimestamp} from './time';
import {ruleConditions,sourceStatus} from './ruleKnowledgePresentation';
import {newTask,taskFields,taskSignature} from './taskTypes';
import type {TaskCard,TaskFields,TaskKB,TaskPrediction,TaskPreview,TaskRun,TaskSeed} from './taskTypes';
import type {Action} from './Questions';
import type {Json,ModelProfile} from './types';
import './tasks.css';

type Props={version:number;act:Action;models:ModelProfile[];executionEnabled:boolean;questionKey?:string;seed?:TaskSeed;onSeedConsumed?:()=>void;onQuestionConsumed?:()=>void;onRun:(id:string)=>void};
const kbKey=(kb:{id:string;version:string})=>`${kb.id}@${kb.version}`;
const kbName=(kb:TaskKB)=>kb.source_kind==='knowledge_evolution'?`知识演化 · ${kb.source_claim_id||`第 ${kb.round_index} 轮`} · 研究候选`:kb.name;
export function Tasks(props:Props){
 const [active,setActive]=useState<TaskCard|'new'|undefined>(()=>props.seed||props.questionKey?'new':undefined);
 const [refresh,setRefresh]=useState(0);
 const list=useResource<{items:TaskCard[];total:number}>('/tasks',props.version+refresh);
 const [questionSeed,setQuestionSeed]=useState(props.questionKey);
 const [taskSeed,setTaskSeed]=useState(props.seed);
 useEffect(()=>{if(props.seed){setTaskSeed(props.seed);setQuestionSeed(undefined);setActive('new');props.onSeedConsumed?.();}},[props.seed]);
 useEffect(()=>{if(props.questionKey){setTaskSeed(undefined);setQuestionSeed(props.questionKey);setActive('new');props.onQuestionConsumed?.();}},[props.questionKey]);
 const close=()=>{setActive(undefined);setQuestionSeed(undefined);setTaskSeed(undefined);setRefresh(value=>value+1);};
 if(active)return <TaskWorkspace key={active==='new'?`new:${JSON.stringify([questionSeed,taskSeed])}`:active.id} {...props} initial={active==='new'?undefined:active} questionSeed={active==='new'?questionSeed:undefined} seed={active==='new'?taskSeed:undefined} onClose={close} onSaved={card=>{setActive(card);setRefresh(value=>value+1);}}/>;
 const cards=list.data?.items||[];
 return <section className="tasks-page"><header className="tasks-heading"><div><span className="eyebrow">TASKS</span><h1>解答任务</h1><p>为每个问题选择模型与知识，保留独立的作答记录。</p></div><button className="primary" onClick={()=>setActive('new')}><Plus size={17}/>新建任务</button></header>
  <ErrorBox error={list.error}/>{list.loading?<Loading/>:!cards.length?<div className="tasks-empty"><FlaskConical size={30}/><h2>从一个问题开始</h2><p>模型结合 KB 作答，或让匹配到的规则直接给出结论。<br/>每个任务单独配置，结果留在各自的卡片里。</p></div>:<>
   <p className="tasks-count">{list.data?.total??cards.length} 个任务</p><div className="task-grid">{cards.map(card=><button key={card.id} className="task-card" aria-label={`打开任务 ${card.name}`} onClick={()=>setActive(card)}><span className={`task-card-icon ${card.mode==='rules'?'rules':''}`}>{card.mode==='rules'?<BookOpen size={22}/>:<Sparkles size={22}/>}</span><span className="task-card-mode">{card.mode==='rules'?'KB 直接解答':'LLM + KB'}</span><h2>{card.name}</h2><p>{card.question_key?card.question_key.startsWith('evolution_')?'知识演化题目':card.question_key.split('@')[0]:'待选择题目'}</p><div className="task-card-path"><span>{card.kb_selection.mode==='auto'?'自动匹配知识':'指定知识库'}</span>{card.mode==='llm'&&<><ChevronRight size={12}/><span>{props.models.find(model=>model.id===card.model_id)?.name||'待选择模型'}</span></>}</div><footer><span>更新于 {formatTimestamp(card.updated_at)}</span><ArrowUpRight size={17}/></footer></button>)}</div>
  </>}
 </section>;
}

function TaskWorkspace({initial,questionSeed,seed,onClose,onSaved,...props}:Props&{initial?:TaskCard;questionSeed?:string;onClose:()=>void;onSaved:(card:TaskCard)=>void}){
 const [base,setBase]=useState(initial),[form,setForm]=useState<TaskFields>(()=>initial?taskFields(initial):newTask(questionSeed,seed));
 const [picker,setPicker]=useState(false),[error,setError]=useState(''),[conflict,setConflict]=useState(false),[busy,setBusy]=useState<'save'|'preview'|'run'|'reload'|undefined>();
 const [preview,setPreview]=useState<{data:TaskPreview;signature:string;key:string}>();
 const [historyRefresh,setHistoryRefresh]=useState(0),[recentRun,setRecentRun]=useState<TaskRun>();
 const mounted=useRef(true),request=useRef(0),lock=useRef(false);
 const server=useResource<TaskCard>(initial?`/tasks/${encodeURIComponent(initial.id)}`:null,props.version);
 const history=useResource<{items:TaskRun[];total:number}>(base?`/tasks/${encodeURIComponent(base.id)}/runs`:null,props.version+historyRefresh,base?5000:0);
 const kbQuery=new URLSearchParams({mode:form.mode,...(form.kb_selection.mode==='manual'&&form.kb_selection.ref?{kb_id:form.kb_selection.ref.id,kb_version:form.kb_selection.ref.version}:{})});
 const kbs=useResource<{items:TaskKB[];total:number}>(`/tasks/kbs?${kbQuery}`,props.version);
 const question=useResource<Json>(form.question_key?`/tasks/questions/${encodeURIComponent(form.question_key)}`:null,props.version);
 const signature=taskSignature(form),dirty=!base||signature!==taskSignature(base),latest=useRef(signature);latest.current=signature;
 const baseRef=useRef(base);baseRef.current=base;const formRef=useRef(form);formRef.current=form;
 const loaded=useRef(!initial),[initialized,setInitialized]=useState(!initial);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current++;};},[]);
 useEffect(()=>{
  if(!server.data)return;
  const current=baseRef.current;
  if(!loaded.current){setBase(server.data);setForm(taskFields(server.data));loaded.current=true;setInitialized(true);}
  else if(current&&server.data.revision>current.revision){
   if(taskSignature(formRef.current)!==taskSignature(current))setConflict(true);
   else {setBase(server.data);setForm(taskFields(server.data));}
   setPreview(undefined);
  }
 },[server.data]);
 useEffect(()=>{request.current++;setPreview(undefined);},[signature,base?.revision,props.version]);
 const current=preview?.signature===signature&&!dirty&&preview.data.task_revision===base?.revision?preview:undefined;
 const missingManualKB=form.kb_selection.mode==='manual'&&!form.kb_selection.ref;
 const valid=!missingManualKB&&!!form.name.trim()&&form.name.length<=120&&Number.isInteger(form.knowledge_limit)&&form.knowledge_limit>=1&&form.knowledge_limit<=12;
 const ready=!!form.question_key&&(form.mode==='rules'||!!form.model_id)&&(form.kb_selection.mode==='auto'||!!form.kb_selection.ref);
 const frozen=busy==='save'||busy==='run'||busy==='reload';
 const update=(patch:Partial<TaskFields>)=>{setForm(value=>({...value,...patch}));setError('');};
 const fail=async(caught:unknown,operation:'save'|'preview'|'run'|'reload')=>{
  setError((caught as Error).message);
  if(!(caught instanceof ApiError&&caught.status===409))return;
  setPreview(undefined);
  if(operation==='save'){setConflict(true);return;}
  const original=baseRef.current;
  if(!original)return;
  try{
   const current=await api<TaskCard>(`/tasks/${encodeURIComponent(original.id)}`);
   if(mounted.current&&baseRef.current?.id===current.id)setConflict(current.revision>baseRef.current.revision);
  }catch{/* Keep the original error and allow a fresh preview; the server still enforces the revision. */}
 };
 const save=async()=>{
  if(lock.current||!valid)return;lock.current=true;setBusy('save');setError('');
  try{const card=await api<TaskCard>(base?`/tasks/${encodeURIComponent(base.id)}`:'/tasks',{...taskFields(form),...(base?{expected_revision:base.revision}:{})},base?'PUT':'POST');if(mounted.current){setBase(card);setForm(taskFields(card));setConflict(false);setPreview(undefined);onSaved(card);}}
  catch(caught){if(mounted.current)await fail(caught,'save');}finally{lock.current=false;if(mounted.current)setBusy(undefined);}
 };
 const match=async()=>{
  if(lock.current||!base||dirty||!ready)return;lock.current=true;setBusy('preview');setError('');setPreview(undefined);
  const serial=++request.current,captured=signature;
  try{const data=await api<TaskPreview>(`/tasks/${encodeURIComponent(base.id)}/preview`,{expected_revision:base.revision});if(mounted.current&&serial===request.current&&latest.current===captured)setPreview({data,signature:captured,key:crypto.randomUUID()});}
  catch(caught){if(mounted.current&&serial===request.current)await fail(caught,'preview');}finally{lock.current=false;if(mounted.current)setBusy(undefined);}
 };
 const run=async()=>{
  if(lock.current||!base||!current?.data.can_run||(form.mode==='llm'&&!props.executionEnabled))return;lock.current=true;setBusy('run');setError('');
  try{const result=await api<TaskRun>(`/tasks/${encodeURIComponent(base.id)}/runs`,{expected_revision:base.revision,preview_hash:current.data.preview_hash},undefined,{'Idempotency-Key':current.key});if(mounted.current){setRecentRun(result);setHistoryRefresh(value=>value+1);setPreview(undefined);}}
  catch(caught){if(mounted.current)await fail(caught,'run');}finally{lock.current=false;if(mounted.current)setBusy(undefined);}
 };
 const reload=async()=>{
  if(lock.current||!base)return;lock.current=true;setBusy('reload');setError('');
  try{const card=await api<TaskCard>(`/tasks/${encodeURIComponent(base.id)}`);if(mounted.current){setBase(card);setForm(taskFields(card));setConflict(false);setPreview(undefined);}}
  catch(caught){if(mounted.current)await fail(caught,'reload');}finally{lock.current=false;if(mounted.current)setBusy(undefined);}
 };
 const records=[...(history.data?.items||[])];if(recentRun&&!records.some(run=>run.id===recentRun.id))records.unshift(recentRun);
 const switchedSelection=form.kb_selection.mode==='manual'&&form.kb_selection.ref?.id.startsWith('evolution_kb_')?form.kb_selection:{mode:'auto' as const};
 const selectedKB=form.kb_selection.ref,options=kbs.data?.items||[],activeKB=options.find(kb=>selectedKB&&kbKey(kb)===kbKey(selectedKB)),hasOption=!!activeKB;
 return <section className="tasks-page task-workspace">
  <button className="task-back" aria-label="返回任务列表" disabled={!!busy} onClick={onClose}><ArrowLeft size={17}/>全部任务</button>
  <header className="tasks-heading"><div><span className="eyebrow">TASK</span><h1>{base?.name||'新建解答任务'}</h1><p>{base?'题目、知识与每次作答，保存在同一个任务中。':'选择一道题，定义你希望怎样解答。'}</p></div>{base&&<span className="task-save-state">{dirty?'有未保存的修改':<><Check size={14}/>已保存</>}</span>}</header>
  <ErrorBox error={server.error}/>{!initialized?<Loading/>:<>
  <div className="task-config"><div className="task-config-main"><Field label="任务名称"><input value={form.name} maxLength={120} placeholder="例如：比较小样本下的架构选择" disabled={frozen} onChange={event=>update({name:event.target.value})}/></Field>
   <section className="task-question"><div><span className="task-section-index">01</span><h2>研究问题</h2></div>{form.question_key?<><div className="task-question-choice"><span className="task-selected-question">{question.data?.metadata?.source_kind==='knowledge_evolution'?<>{question.data.public?.id}<small>来自知识演化 · 第 {question.data.metadata.round_index} 轮</small></>:form.question_key}</span><button className="task-text-action" disabled={frozen} onClick={()=>setPicker(true)}>更换题目</button></div><details className="task-disclosure"><summary>阅读完整题目</summary>{question.loading?<Loading/>:question.data?<><QuestionReader record={question.data} questionKey={form.question_key} knowledgeRef={form.kb_selection.mode==='manual'?form.kb_selection.ref:undefined}/>{question.data.metadata?.source_kind==='knowledge_evolution'&&<details className="task-disclosure"><summary>题目固定记录</summary><code>{form.question_key}</code></details>}</>:<ErrorBox error={question.error}/>}</details></>:<button className="task-question-empty" aria-label="选择题目" disabled={frozen} onClick={()=>setPicker(true)}><Plus size={18}/>选择题目<span>从题库或知识演化中选择</span></button>}</section>
   <section className="task-method"><div className="task-section-heading"><span className="task-section-index">02</span><h2>解答方式</h2></div><fieldset className="task-mode"><legend className="sr-only">解答方式</legend><label className={form.mode==='llm'?'selected':''}><input type="radio" name="task-mode" value="llm" aria-label="LLM + KB" checked={form.mode==='llm'} disabled={frozen} onChange={()=>update({mode:'llm',kb_selection:switchedSelection})}/><Sparkles size={19}/><span><strong>LLM + KB</strong><small>匹配知识，交给模型作答</small></span></label><label className={form.mode==='rules'?'selected':''}><input type="radio" name="task-mode" value="rules" aria-label="KB 直接解答" checked={form.mode==='rules'} disabled={frozen} onChange={()=>update({mode:'rules',model_id:null,kb_selection:switchedSelection})}/><BookOpen size={19}/><span><strong>KB 直接解答</strong><small>程序执行规则，无需模型</small></span></label></fieldset>
    {form.mode==='llm'&&<Field label="作答模型"><select value={form.model_id||''} disabled={frozen} onChange={event=>update({model_id:event.target.value||null})}><option value="">选择模型</option>{props.models.filter(model=>model.enabled).map(model=><option key={model.id} value={model.id}>{model.name}</option>)}{form.model_id&&!props.models.some(model=>model.enabled&&model.id===form.model_id)&&<option value={form.model_id}>原模型暂不可用</option>}</select></Field>}
    <div className="task-kb-fields"><Field label="知识来源"><select value={form.kb_selection.mode} disabled={frozen} onChange={event=>update({kb_selection:{mode:event.target.value as 'auto'|'manual'}})}><option value="auto">自动匹配 KB</option><option value="manual">指定 KB</option></select></Field>{form.kb_selection.mode==='manual'&&<Field label="指定 KB"><select disabled={frozen||kbs.loading} value={selectedKB?kbKey(selectedKB):''} onChange={event=>{const kb=options.find(item=>kbKey(item)===event.target.value);update({kb_selection:{mode:'manual',...(kb?{ref:{id:kb.id,version:kb.version}}:{})}});}}><option value="">选择知识库</option>{options.map(kb=><option key={kbKey(kb)} value={kbKey(kb)}>{kbName(kb)}</option>)}{selectedKB&&!hasOption&&<option value={kbKey(selectedKB)}>原知识库暂不可用</option>}</select></Field>}</div><ErrorBox error={kbs.error}/>{missingManualKB&&<p className="task-explanation" role="status">请先选择一个知识库，再保存任务。</p>}
    <p className="task-explanation">{form.mode==='rules'?'检查规则的适用条件；冲突或未覆盖时保留原因，不强行选答案。':'模型接收公开题面与匹配知识，回答与引用一并保存。'}</p>{form.mode==='llm'&&<details className="task-disclosure task-advanced"><summary>更多设置</summary><Field label="知识条数"><input type="number" min={1} max={12} disabled={frozen} value={form.knowledge_limit} onChange={event=>update({knowledge_limit:Number(event.target.value)})}/></Field></details>}
   </section>
  </div><aside className="task-route"><span className="eyebrow">本次路径</span><ol><li><span>1</span><div><b>公开题面</b><small>{form.question_key?'已选择 1 道题':'待选择'}</small></div></li><li><span>2</span><div><b>{form.kb_selection.mode==='auto'?'自动匹配知识':'指定知识库'}</b><small>{form.kb_selection.mode==='auto'?'按题目检查适用性':activeKB?kbName(activeKB):'待选择'}</small></div></li><li><span>3</span><div><b>{form.mode==='rules'?'执行 KB 规则':'模型作答'}</b><small>{form.mode==='rules'?'程序给出结论或保留判断':props.models.find(model=>model.id===form.model_id)?.name||'待选择模型'}</small></div></li><li><span>4</span><div><b>保存解答</b><small>记录当时的题目与知识</small></div></li></ol></aside></div>
  <div className="task-action-bar"><div><p>{dirty?'保存配置后，即可匹配知识并预览。':current?'已固定本次题目与知识，修改配置需重新预览。':'先查看知识匹配结果，再执行并保留记录。'}</p>{form.mode==='llm'&&!props.executionEnabled&&<small>本地可预览；模型作答需在授权服务器执行。</small>}</div><div className="task-actions">{dirty?<button className="primary" disabled={!!busy||!valid} onClick={()=>void save()}>{busy==='save'?'正在保存…':'保存任务'}</button>:<><button className={current?'secondary':'primary'} disabled={!!busy||!ready||conflict} onClick={()=>void match()}>{busy==='preview'?'正在匹配…':current?'重新匹配':'匹配并预览'}</button>{current&&<button className="primary" disabled={!!busy||!current.data.can_run||(form.mode==='llm'&&!props.executionEnabled)} onClick={()=>void run()}>{busy==='run'?'正在提交…':form.mode==='rules'?'执行并记录':'开始作答'}</button>}</>}</div></div>
  <ErrorBox error={error}/>{conflict&&<div className="task-conflict"><p>服务器记录已有变化，当前填写内容已保留。载入服务器版本会替换当前填写内容。</p><button className="secondary" disabled={!!busy} onClick={()=>void reload()}>载入服务器版本</button></div>}
  {current&&<Preview data={current.data}/>}
  {base&&<section className="task-history"><header><span className="task-section-index">03</span><h2>作答记录</h2>{history.data&&<small>{Math.max(history.data.total,records.length)} 次</small>}</header><ErrorBox error={history.error}/>{history.loading&&!records.length?<Loading/>:!records.length?<p className="task-muted">这个任务还没有作答记录。</p>:records.map((record,index)=><TaskRunRecord key={record.id} record={record} initialOpen={index===0} onRun={props.onRun} renderAnswer={(result,question)=><>{result?.prediction&&<Prediction value={result.prediction} question={question}/>}<RunAnswer result={result}/>{result&&<ModelSources result={result}/>}</>}/>)}</section>}
  </>}{picker&&<TaskQuestionPicker version={props.version} onSelectQuestion={key=>{update({question_key:key});setPicker(false);}} onClose={()=>setPicker(false)}/>}
 </section>;
}
function Prediction({value,question}:{value:TaskPrediction;question?:Json}){
 const label=value.status==='answered'?(value.answer_letter?`候选 ${value.answer_letter}`:value.answer_id||'已解答'):({conflict:'规则结论冲突',uncovered:'规则尚未覆盖',invalid:'规则暂不可执行'} as Record<string,string>)[value.status]||'尚无结论';
 return <div className={`task-prediction ${value.status}`}><span className="eyebrow">规则结论</span><h3>{label}</h3>{value.status!=='answered'&&<p>保留判断，等待补充适用规则或处理冲突。</p>}{value.issues?.map((issue,index)=><p key={index}>{issue.message}</p>)}{value.explanation&&<RuleReasoning value={value.explanation} question={question}/>} {!!value.matches?.length&&<details className="task-disclosure"><summary>匹配检查 · {value.matches.length} 个 KB</summary>{value.matches.map((match,index)=><div className="task-rule-match" key={`${kbKey(match.kb)}:${index}`}><b>{match.kb.name}</b><p>{match.kb.summary||'保留来源的规则适用条件与验证状态。'}</p>{match.rules?.map((rule,index)=><RuleMatch key={`${rule.rule_id}:${index}`} rule={rule}/>)}<details className="task-disclosure"><summary>完整规则执行记录</summary><pre>{JSON.stringify(match.prediction,null,2)}</pre></details></div>)}</details>}</div>;
}
function RuleMatch({rule}:{rule:Json}){
 let conditions:[string,string][]=[];try{conditions=ruleConditions(rule.rule);}catch{/* Preserve unfamiliar source rules in the full record. */}
 return <article className="task-matched-rule"><p className="task-rule-text">{rule.text}</p><small>{sourceStatus(rule)}</small>{conditions.length>0&&<dl>{conditions.map(([name,value],index)=><div key={index}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>}<details className="task-disclosure"><summary>规则来源与完整记录</summary><pre>{JSON.stringify(rule,null,2)}</pre></details></article>;
}
function RunAnswer({result}:{result?:Json}){
 if(!result||result.prediction)return null;
 const committed=result.answer;
 const ranking=Array.isArray(committed?.ranking)?committed.ranking.filter((value:unknown)=>typeof value==='string'):undefined;
 const answer=ranking?.length?ranking.join(' → '):result.answer_letter?`候选 ${result.answer_letter}`:typeof committed==='string'?committed:typeof result.answer_id==='string'?result.answer_id:undefined;
 const explanation=typeof committed?.rationale==='string'?committed.rationale:typeof result.explanation==='string'?result.explanation:typeof result.text==='string'?result.text:undefined;
 return answer||explanation?<div className="task-run-answer">{answer&&<h3>{answer}</h3>}{explanation&&<p>{explanation}</p>}{Array.isArray(committed?.citations)&&committed.citations.length>0&&<small>引用知识：{committed.citations.join('、')}</small>}{Array.isArray(result.unknown_citations)&&result.unknown_citations.length>0&&<p className="task-preview-warning">未能对应到提供知识的引用：{result.unknown_citations.join('、')}</p>}</div>:null;
}
function Preview({data}:{data:TaskPreview}){
 return <section className="task-preview"><header><span className="eyebrow">PREVIEW</span><h2>{data.mode==='rules'?'规则匹配预览':'作答预览'}</h2><p>仅使用公开题面，未进行评分。</p></header>{data.prediction&&<Prediction value={data.prediction} question={data.question}/>}
  {!data.can_answer&&!data.prediction&&<p className="task-muted">没有可用于本次作答的匹配知识。请检查知识来源及适用条件。</p>}
  {!!data.selected_kbs?.length&&<section className="task-selected-knowledge"><h3>{data.mode==='rules'?'检查的知识库':'将提供给模型的知识'}</h3>{data.selected_kbs.map(kb=><div key={kbKey(kb)}><BookOpen size={18}/><span><b>{kbName(kb)}</b>{kb.summary&&<small>{kb.summary}</small>}<small>{kb.verification==='research_hypothesis'||kb.kind==='research_rules'?'研究假设 · 待独立验证':kb.kind==='formal'?'正式规则 · 按各规则验证范围使用':'学习经验 · 待验证'}</small><small>记录 {kb.version.slice(0,12)}</small><SkippedRules value={kb}/></span></div>)}</section>}
  {!!data.retrieval?.provenance?.length&&<RagKnowledge hits={data.retrieval.provenance} anchors={false}/>}
  {data.warnings?.map((warning,index)=><p className="task-preview-warning" key={index}>{warning.message}</p>)}
  {data.request&&<details className="task-disclosure"><summary>实际模型请求 · 尚未发送{data.reserved_tokens?` · 预留 ${data.reserved_tokens} tokens`:''}</summary>{data.request.payload.messages?.map((message:Json,index:number)=><pre key={index}>{typeof message.content==='string'?message.content:JSON.stringify(message.content,null,2)}</pre>)}</details>}
 </section>;
}
