import {createContext,useContext,useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {api} from './api';
import {deriveLiveWorkflow,stageDefinitions,type Focus,type SyncState,type WorkflowViewModel} from './liveWorkflow';
import {RunStreamProvider} from './LiveOutput';
import {RunWorkflowView} from './RunWorkflowView';
import {KnowledgeSnapshot} from './KnowledgeSnapshot';
import {RunFailure} from './RunFailure';
import {nodeStatusLabel} from './runWorkflow';
import {ErrorBox,JsonView} from './ui';
import type {Action} from './Questions';
import type {MethodDefinition,RoundDecision,Run,StageId,Workflow} from './types';
import './live-workflow.css';
export type LiveRunContextValue={run?:Run;syncState?:SyncState;act?:Action};
export const LiveRunContext=createContext<LiveRunContextValue>({});
export const useWorkflowRun=()=>useContext(LiveRunContext);
const CanvasContext=createContext<{view:WorkflowViewModel;run?:Run;focus?:Focus;select:(f:Focus)=>void;act?:Action}|null>(null);
function VersionTag({value,label='已保存版本'}:{value:any;label?:string}){return <span title={typeof value==='string'?value:undefined}>{value?label:'版本未提供'}</span>;}
const emptyRun:Run={id:'draft',kind:'workflow',status:'draft',created_at:0,config:{}};
export function LiveWorkflowCanvas({draft,run,methodDefinition,syncState,act,children}:{draft?:Workflow;run?:Run;methodDefinition?:MethodDefinition;syncState?:SyncState;act?:Action;children?:ReactNode}) {
 const view=useMemo(()=>deriveLiveWorkflow({draft,run,methodDefinition,syncState}),[draft,run,methodDefinition,syncState]);
 const [focus,setFocus]=useState<Focus>(),[following,setFollowing]=useState(true),[advanced,setAdvanced]=useState(false);
 useEffect(()=>{if(following&&view.current)setFocus(view.current);},[following,view.current?.stageId,view.current?.stepId,view.current?.round,run?.id]);
 // Only a deliberate run switch resets reading; polling and draft edits do not.
 const priorRun=useRef(run?.id);
 useEffect(()=>{if(priorRun.current&&priorRun.current!==run?.id){setFocus(view.current);setFollowing(true);}priorRun.current=run?.id;},[run?.id]);
 const select=(f:Focus)=>{setFollowing(false);setFocus(f);};
 return <RunStreamProvider run={run??emptyRun}><CanvasContext.Provider value={{view,run,focus,select,act}}>
  <div className="live-workflow-canvas workflow-stage-stack" data-testid="live-workflow-canvas" aria-label="Data → Harness → KB，同图工作流">
   <header className="live-canvas-toolbar"><div><strong>{run?'本次冻结运行':'下一次运行草稿'}</strong><p>{view.method?`${view.method.name} · v${view.method.version}`:run?'历史运行 · 未保存方法配方':''}{view.round?` · 第 ${view.round} 轮`:''}</p></div>{run&&<button onClick={()=>{setFollowing(true);setFocus(view.current);}} aria-pressed={following}>跟随当前步骤</button>}</header>
   {run&&<><p className="live-transport-note">阶段记录每 2.5 秒同步；模型正文通过独立 SSE 输出流显示。</p>{view.legacy&&<p>历史记录没有方法步骤身份，仅展示已记录的程序节点。</p>}<ErrorBox error={syncState?.error}/><RunFailure run={run} nodeId={run.progress?.node_id}/></>}
   {children??stageDefinitions.map((s,i)=><LiveWorkflowStage key={s.id} stageId={s.id} title={s.title} number={String(i+1)} description={s.description} icon={null}/>) }
   {run&&<details className="workflow-stage-disclosure" onToggle={e=>setAdvanced(e.currentTarget.open)}><summary>高级记录：完整执行图、路由与控制节点</summary>{advanced&&<RunWorkflowView run={run} syncError={syncState?.error}/>}</details>}
  </div>
 </CanvasContext.Provider></RunStreamProvider>;
}
export function LiveWorkflowStage({stageId,title,number,description,icon,children}:{stageId:StageId;title:string;number:string;description:string;icon:ReactNode;children?:ReactNode}) {
 const ctx=useContext(CanvasContext);if(!ctx)throw new Error('LiveWorkflowStage requires LiveWorkflowCanvas');
 const {view,run,focus,select,act}=ctx,stage=view.stages.find(s=>s.id===stageId)!;
 const selected=focus?.stageId===stageId,step=stage.steps.find(s=>s.id===focus?.stepId);
 const observations=run?.node_observations??[];
 const published=observations.filter((o:any)=>o.node_id==='publish'&&o.availability==='available');
 const snapshot=published.find((o:any)=>o.round_index===focus?.round)??published.at(-1);
 const loops=observations.filter((o:any)=>o.node_id==='loop'&&o.availability!=='unavailable'&&o.output);
 const previousSnapshot=published.find((o:any)=>o.output?.version===snapshot?.output?.parent_version)?.output??run?.config.kb_snapshot;
 const experience=loops.find((o:any)=>o.round_index===focus?.round)?.output?.experience??loops.at(-1)?.output?.experience;
 const latestEvent=stage.steps.flatMap(s=>s.events).filter(e=>e.event_id&&e.state==='complete').sort((a,b)=>(a.sequence??0)-(b.sequence??0)).at(-1);
 const [handoff,setHandoff]=useState(false),seen=useRef<string | undefined>(latestEvent?.event_id);
 useEffect(()=>{if(!latestEvent?.event_id||seen.current===latestEvent.event_id)return;seen.current=latestEvent.event_id;setHandoff(true);const timer=setTimeout(()=>setHandoff(false),550);return()=>clearTimeout(timer);},[latestEvent?.event_id]);
 const round=focus?.round??view.round;
 return <section className={`workflow-stage-card live-stage live-${stageId} ${selected?'is-selected':''} ${handoff?'observed-handoff':''}`} data-testid={`live-stage-${stageId}`} aria-label={title}>
  <header className="workflow-stage-heading"><span className="workflow-stage-icon">{icon}</span><div><span className="eyebrow">{stageId==='task'?'独立下游出口':`STAGE ${number}`}</span><h2>{title}</h2><p>{description}</p></div>{run&&<span className={`live-status rw-${stage.status}`}>{stage.status==='skipped'?'本次未安排':nodeStatusLabel[stage.status]}</span>}</header>
  <div className="workflow-stage-body">
   {run?<>
    <p>{stageId==='data'?`${run.config.question_set?.name??'冻结研究题集'} · ${run.config.question_set?.question_count??run.config.question_set?.keys?.length??'数量见记录'} 题`:stageId==='harness'?`${view.method?.description??'按历史冻结流程执行'} · ${run.config.models?.[0]?.name??'冻结模型'}`:stageId==='kb'?'正式知识与未验证经验分别保存；零更新也会保留记录。':'独立 Task 使用冻结版本；最终测试反馈不回流学习。'}</p>
    <button onClick={()=>select({stageId,round:view.round})} aria-expanded={selected} aria-label={`查看 ${title}`}>查看阶段输入与输出</button>
    {stage.steps.length>0&&<div className="live-method-steps" aria-label={`${stageId} 方法步骤`}>{stage.steps.map(s=><button key={s.id} className={`live-step rw-${s.status}`} aria-pressed={selected&&focus?.stepId===s.id} onClick={()=>select({stageId,stepId:s.id,round:view.round})}><strong>{s.label}</strong><small>{nodeStatusLabel[s.status]}</small></button>)}</div>}
    {selected&&<div className="live-inspector"><p className="live-inspector-purpose">{step?.label??title} · 查看实际提交材料、模型返回与封存结果</p>{view.round&&stageId!=='task'&&<label>查看研究轮次 <input aria-label="查看研究轮次" type="number" min={1} max={Math.max(view.round,round??1)} value={round??view.round} onChange={e=>select({...focus!,round:Number(e.target.value)})}/></label>}
      {stageId==='kb'&&snapshot?.output?.claims&&<><p>正式 KB · <VersionTag label="更新前" value={snapshot.output?.parent_version??snapshot.input?.kb_version??snapshot.input?.patch?.parent_version}/> → <VersionTag label="本轮保存" value={snapshot.output.version}/></p><KnowledgeSnapshot snapshot={snapshot.output}/>{snapshot.input?.patch?.operations?.length===0&&<p>该轮没有正式知识变更</p>}<KnowledgeChanges snapshot={snapshot} previous={previousSnapshot}/></>}
      {stageId==='kb'&&experience&&<ExperienceChanges value={experience}/>}
      {stageId==='task'&&stage.status==='skipped'?<p>此运行没有执行 Task，尚不能判断知识是否帮助独立新题解答。</p>:step&&view.method&&!step.events.some(e=>stageId==='task'||round===undefined||e.round_index===round)?<p>此方法步骤尚无可绑定的实际记录；不将其他步骤的输出归到这里。</p>:<RunWorkflowView run={run} nodeIds={step?.node_ids??stage.nodeIds} compact syncError={view.syncState?.error} fixedRound={stageId==='task'?undefined:round} stepId={view.method?step?.id:undefined}/>} 
    </div>}
    {stageId==='kb'&&run.status==='waiting_round'&&run.round_decision&&<RoundDecisionControls run={run} act={act}/>}
    {children&&<details className="workflow-stage-disclosure live-draft-settings"><summary>下一次运行草稿设置 · 不修改本次冻结运行</summary>{children}</details>}
   </>:<>{stage.steps.length>0&&view.method&&<ol className="live-draft-steps">{stage.steps.map(s=><li key={s.id}>{s.label}</li>)}</ol>}{children}</>}
  </div>
 </section>;
}
function KnowledgeChanges({snapshot,previous}:{snapshot:any;previous:any}) {
 const operations=snapshot.input?.patch?.operations??[];
 return <details><summary>逐项知识修改与来源</summary>{operations.map((op:any,index:number)=>{
  const id=op.claim?.id??op.id,old=previous?.claims?.find((c:any)=>c.id===id),next=snapshot.output?.claims?.find((c:any)=>c.id===id);
  return <article className="live-change" key={index}><h4 title={id}>知识修改 {index+1} · {op.op==='retire'?'停用':old?'修订':'新增'}</h4><dl><dt>旧文本</dt><dd>{old?.text??(op.op==='upsert'&&op.claim?.revision===1?'此前没有此记录':'当前视图未保存旧文本')}</dd><dt>新文本</dt><dd>{next?.text??'未提供'}</dd><dt>修改原因</dt><dd>{op.reason??'未记录'}</dd><dt>验证状态</dt><dd>{next?.status??'未提供'}</dd></dl>{(next?.evidence_ids??[]).map((id:string)=><details key={id}><summary title={id}>查看关联证据</summary><JsonView value={snapshot.output?.evidence?.find((e:any)=>e.id===id)??{id,notice:'此视图只有引用'}}/></details>)}</article>;
 })}<details><summary>完整 patch 与产物来源</summary><JsonView value={{patch:snapshot.input?.patch,source:snapshot.source}}/></details></details>;
}
function ExperienceChanges({value}:{value:any}) {
 const lessons=value.after_snapshot?.lessons??[];
 return <section className="live-experience"><h3>经验记忆 · 未验证</h3><p><VersionTag label="更新前" value={value.before}/> → <VersionTag label="本轮保存" value={value.after}/></p>{value.operations?.length===0&&<p>该轮没有经验规则更新</p>}{lessons.map((lesson:any,index:number)=><article key={lesson.id}><h4 title={lesson.id}>经验 {index+1} · 修订 {lesson.revision??'见记录'} · {lesson.status==='retired'?'已停用':'经验规则'}</h4><p>{lesson.text}</p><dl><dt>适用条件</dt><dd>{lesson.conditions?.join('；')||'未声明'}</dd><dt>例外</dt><dd>{lesson.exceptions?.join('；')||'未声明'}</dd><dt>修改原因</dt><dd>{lesson.reason??'见原始记录'}</dd></dl><p>关联 {lesson.source_episode_ids?.length??0} 次作答记录</p>{(lesson.source_episode_ids??[]).map((id:string,index:number)=><details key={id}><summary title={id}>查看作答来源 {index+1}</summary>{value.episode_provenance?.[id]?<><p title={value.episode_provenance[id].question_id}>第 {value.episode_provenance[id].round} 轮作答</p><JsonView value={value.episode_provenance[id].source_refs}/></>:<p>此历史记录只保存来源 ID；未提供可读取的来源路径。</p>}</details>)}</article>)}<details><summary>经验修改、检索与来源记录</summary><JsonView value={value}/></details></section>;
}
export function RoundDecisionControls({run,act}:{run:Run;act?:Action}) {
 const decision=run.round_decision as RoundDecision;
 const basic=(run.config.method?.id??run.config.workflow?.settings?.method_id)==='basic_learning';
 const experienceVersion=run.node_observations?.find((o:any)=>o.node_id==='experience_save'&&o.round_index===decision.round_index&&o.availability==='available')?.output?.version;
 const repeatLabel=run.config.workflow?.settings?.use_previous_experience===false?'同题再练':'带着经验再试一次';
 const [pending,setPending]=useState(false),[submitted,setSubmitted]=useState(false),[error,setError]=useState('');const inFlight=useRef(false);
 useEffect(()=>{setSubmitted(false);setError('');},[run.id,decision.round_index]);
 const choose=async(action:string)=>{if(inFlight.current||submitted)return;inFlight.current=true;setPending(true);setError('');try{const operation=()=>api(`/runs/${encodeURIComponent(run.id)}/round-decision`,{round_index:decision.round_index,action});const result=act?await act(operation):await operation();if(result)setSubmitted(true);else setError('提交未获确认；请核对服务器状态后重试相同决定。');}catch(e){setError(e instanceof Error?e.message:String(e));}finally{inFlight.current=false;setPending(false);}};
 return <section className="live-round-decision" aria-label="轮末决定"><h3>第 {decision.round_index} 轮已封存 · 等待决定</h3><p>{basic?'当前经验版本：':'当前正式 KB：'}<VersionTag label={`第 ${decision.round_index} 轮保存`} value={basic?experienceVersion:decision.kb_version}/></p><p>{decision.next_round_available?(basic?`下一轮 ${decision.next_round_index} · 同一道题复盘`:`下一轮 ${decision.next_round_index} · 冻结下一批 ${decision.next_question_ids?.length??0} 题`):(basic&&decision.next_round_reason==='round_cap'?'已达到最多学习轮数，请结束本次学习':`没有下一批：${decision.next_round_reason??'服务未提供原因'}`)}</p>{decision.next_round_available&&<details><summary>下一批题目清单与完整版本</summary><JsonView value={{question_ids:decision.next_question_ids,kb_version:decision.kb_version}}/></details>}<div className="actions">{decision.available_actions.map(action=><button key={action} disabled={pending||submitted||decision.status!=='waiting'} onClick={()=>void choose(action)}>{action==='continue'?(basic?repeatLabel:'继续下一轮'):action==='evaluate'?'验证效果':'结束研究'}</button>)}</div>{submitted&&<p role="status">决定已提交，等待服务器同步</p>}<ErrorBox error={error}/></section>;
}
