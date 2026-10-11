import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {Field,Status,ErrorBox,JsonView} from './ui';
import {RolePrompt} from './RolePrompt';
import {RoundDecisionControls,useWorkflowRun} from './LiveWorkflowCanvas';
import {RunStreamProvider} from './LiveOutput';
import {RunWorkflowView} from './RunWorkflowView';
import {RunFailure} from './RunFailure';
import {KnowledgeSnapshot} from './KnowledgeSnapshot';
import {ResearchPathCanvas} from './ResearchPathCanvas';
import {deriveMethodResearchPath,type MethodPathNode} from './methodResearchPath';
import type {MethodDefinition,ModelProfile,QuestionSet,Run,Workflow} from './types';
import './workflow-stages.css';

const emptyRun:Run={id:'draft',kind:'workflow',status:'draft',created_at:0,config:{}};
const count=(set?:QuestionSet)=>set?.count??set?.keys?.length??set?.questions?.length;
const budgetFields:[string,string][]=[['max_calls_per_round','每轮调用上限（次）'],['max_tokens_per_round','每轮文本预算（token）'],['max_candidate_seed_runs','训练执行上限（候选 × 种子）']];

export function WorkflowStages({workflow,models,researchSet,taskSet,rolePrompts,onResearch,onTask,onDataset,onTaskDataset,onResearchPairs,onResearchSingles,onTaskPairs,onTaskSingles,onSetting,onPhase,onRoute,onPrompt,children,methods=[]}:{
 workflow:Workflow;models:ModelProfile[];researchSet?:QuestionSet;taskSet?:QuestionSet;rolePrompts?:Record<string,string>;
 onResearch:()=>void;onTask:()=>void;onDataset?:()=>void;onTaskDataset?:()=>void;
 onResearchPairs?:()=>void;onResearchSingles?:()=>void;onTaskPairs?:()=>void;onTaskSingles?:()=>void;
 onSetting:(key:string,value:any)=>void;onPhase:(phase:string)=>void;onRoute:(route:'confirmation'|'evaluation',enabled:boolean)=>void;onPrompt:(id:string,prompt:string)=>void;
 children:ReactNode;methods?:MethodDefinition[];onMethod?:(method:MethodDefinition)=>void;
}) {
 const live=useWorkflowRun(),run=live.run;
 const method=methods.find(item=>item.id===workflow.settings.method_id);
 const path=useMemo(()=>deriveMethodResearchPath({workflow,methodDefinition:method,run,syncState:live.syncState}),[workflow,method,run,live.syncState]);
 const {view,nodes,edges}=path;
 const [selectedId,setSelectedId]=useState(nodes[0]?.id??''),[round,setRound]=useState<number|undefined>(),[following,setFollowing]=useState(true),[recordsOpen,setRecordsOpen]=useState(false);
 const currentId=view.current?.stepId??nodes.find(node=>node.step.node_ids.includes(run?.progress?.node_id??''))?.id??nodes.find(node=>node.stage===view.current?.stageId)?.id;
 const identity=`${run?.id??'draft'}:${view.method?.id??'legacy'}`;
 const previousIdentity=useRef(identity);
 useEffect(()=>{if(previousIdentity.current!==identity){setSelectedId(currentId??nodes[0]?.id??'');setRound(view.round);setFollowing(true);previousIdentity.current=identity;}},[identity,currentId,nodes,view.round]);
 useEffect(()=>{if(run&&following){if(currentId)setSelectedId(currentId);setRound(view.round);}},[run?.id,following,currentId,view.round]);
 const selected=nodes.find(node=>node.id===selectedId)??nodes[0];
 const select=(id:string)=>{setSelectedId(id);setFollowing(false);if(round===undefined)setRound(view.round);};
 const model=models.find(item=>item.id===workflow.settings.model_id);
 const evaluating=workflow.edges.some(edge=>edge.source==='loop'&&edge.target==='evaluate');
 const confirming=workflow.edges.some(edge=>edge.source==='experiment'&&edge.target==='confirmation');
 const phase=workflow.nodes.find(node=>node.id==='evaluate')?.config.phase||'final';
 const selectedCount=count(researchSet),taskCount=count(taskSet);

 const budgetSettings=()=><details className="workflow-stage-disclosure"><summary>研究预算</summary>{budgetFields.map(([key,label])=><Field key={key} label={label}><input type="number" min={1} value={workflow.settings[key]??''} onChange={event=>onSetting(key,event.target.value===''?undefined:Number(event.target.value))}/></Field>)}<p className="workflow-stage-note">调用、文本与训练预算在开始前冻结；更多分批与实验设置见内部高级配置。</p></details>;
 const loopSettings=()=><>
  <Field label="研究轮数" hint="各轮按冻结顺序继续取题。"><input type="number" min={1} max={3} value={workflow.settings.max_rounds??1} onChange={event=>onSetting('max_rounds',Number(event.target.value))}/></Field>
  <Field label="循环方式" hint="手动模式每轮封存后等待决定；自动模式受冻结预算与停止条件约束。"><select value={workflow.settings.loop_mode||'automatic'} onChange={event=>onSetting('loop_mode',event.target.value)}><option value="manual">每轮等待决定</option><option value="automatic">自动继续</option></select></Field>
  <Field label="连续无变化停止轮数" hint="正式知识与经验均无更新时停止，最多 3 轮；未设置时不启用。"><input type="number" min={1} max={3} placeholder="未设置" value={workflow.settings.stop_after_no_change_rounds??''} onChange={event=>onSetting('stop_after_no_change_rounds',event.target.value===''?undefined:Number(event.target.value))}/></Field>
  <p className="workflow-stage-note">下一轮使用冻结题集的下一批与刚保存的版本；无下一批、预算不足或达到停止条件时结束。</p>{budgetSettings()}
 </>;
 const dataSettings=()=><>
  <strong>{researchSet?.name||(workflow.settings.question_set_id?'已保存研究题集':'尚未选择研究题目')}</strong>
  <p>{selectedCount===undefined?'选择后保存为固定题集':researchSet?.selection_mode==='pairs'?`${researchSet.pair_count??Number(selectedCount)/2} 对 · ${selectedCount} 题 · 正常题与 DataFlip 成对研究`:`${selectedCount} 题 · 按冻结顺序研究`}</p>
  <div className="actions">{onDataset&&<button onClick={onDataset}>从 Dataset 选择</button>}<button onClick={onResearch}>{workflow.settings.question_set_id?'调整研究题目':'选择研究题目'}</button></div>
  <details className="workflow-stage-disclosure"><summary>题目选择与分批</summary>
   {onResearchPairs&&<button onClick={onResearchPairs}>选择研究题目对 · 正常题 + DataFlip</button>}
   {researchSet?.selection_mode==='pairs'&&onResearchSingles&&<button onClick={onResearchSingles}>改为单题选择</button>}
   <Field label="每轮题数（题）" hint="研究反馈用于学习；Task 使用独立评测题集。"><input type="number" min={1} value={workflow.settings.discovery_per_round??1} onChange={event=>onSetting('discovery_per_round',Number(event.target.value))}/></Field>
   {!workflow.settings.method_id&&<Field label="学习方式" hint="模型权重保持固定，观察知识与推理上下文随反馈变化。"><select value={workflow.settings.learning_protocol||'single'} onChange={event=>onSetting('learning_protocol',event.target.value)}><option value="single" disabled={researchSet?.selection_mode==='pairs'}>普通题目研究</option><option value="paired_contrastive" disabled={researchSet?.selection_mode!=='pairs'}>题对对照 · 解释变化与不变</option><option value="paired_progressive" disabled={researchSet?.selection_mode!=='pairs'}>渐进学习 · 归纳 → 迁移 → 修订</option></select></Field>}
  </details>
  {!nodes.some(node=>node.step.node_ids.includes('loop'))&&<details className="workflow-stage-disclosure"><summary>轮次与预算</summary>{loopSettings()}</details>}
 </>;
 const modelSettings=(node:MethodPathNode)=><>
  <Field label="研究模型" hint="研究角色与 Task 各组评测共用一个固定模型。"><select value={workflow.settings.model_id||''} onChange={event=>onSetting('model_id',event.target.value)}><option value="">选择已登记模型</option>{models.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
  {model&&<p><Status value={model.health?.status||'unchecked'}/> · 单次回答上限 {model.parameters?.max_tokens??'未登记'} tokens</p>}
  {node.id==='pair_induction'&&<p>仅使用正常题反馈归纳初步规律；反事实反馈保留到预测完成后揭示。</p>}
  {node.id==='pair_transfer'&&<p>用初步规律预测反事实结果，保存答案后才揭示对应反馈。</p>}
  {node.id==='pair_revision'&&<p>对照两题已保存的反馈，修订适用条件、例外与交互。</p>}
  {node.id==='experience_consolidate'&&<p>跨题经验单独保存为未验证版本，不会自动启用正式科学 KB 规则。</p>}
  {node.id==='experience_consolidate'?<details><summary>默认经验整理指令</summary><p>此经验步骤使用固定整理协议；补充指令按服务端方法配置提供。</p><JsonView value={rolePrompts?.experience_curator}/></details>:node.step.node_ids.filter(id=>workflow.nodes.some(physical=>physical.id===id&&physical.type==='agent')).map(id=>{
   const role=id==='discoverer'&&(view.method?.learning_protocol??workflow.settings.learning_protocol)?.startsWith('paired_')?'pair_researcher':id;
   return <RolePrompt key={`${node.id}:${id}`} role={role} template={rolePrompts?.[role]} guidance={workflow.nodes.find(physical=>physical.id===id)?.config.prompt||''} onGuidance={prompt=>onPrompt(id,prompt)}/>;
  })}
 </>;
 const experimentSettings=()=><>
  <label className="checkbox-label"><input type="checkbox" checked={confirming} onChange={event=>onRoute('confirmation',event.target.checked)}/>探索后独立确认</label>
  <p className="workflow-stage-note">开启独立确认使用 48 个独立数据集、10 个训练种子，并将训练执行预算至少设为 1600 次。关闭后保留已设预算。</p>
  <p>程序执行生成的训练代码并保存证据；没有满足条件的假说时，不会强行安排实验或确认。</p>
  {budgetSettings()}
 </>;
 const knowledgeSettings=()=><>
  <p>只有通过发布检查的更新才写入正式知识版本；没有通过检查的假说不能当作已验证知识。</p>
  {view.method?.experience_mode==='expel_inspired'&&<p>经验记忆单独保存为未验证版本；不会自动启用正式科学 KB 规则。</p>}
  <Field label="初始知识文件" hint="服务器上的已有知识文件。导入记录保留来源，不因导入就称已验证。"><input value={workflow.settings.kb_path||''} placeholder="留空从默认初始知识开始" onChange={event=>onSetting('kb_path',event.target.value)}/></Field>
  <Field label="知识规则文件" hint="用于解释初始知识，按实际服务端配置校验。"><input value={workflow.settings.rules_path||''} onChange={event=>onSetting('rules_path',event.target.value)}/></Field>
 </>;
 const taskSettings=()=><>
  <label className="workflow-task-toggle"><input aria-label="安排独立评测" type="checkbox" checked={evaluating} onChange={event=>onRoute('evaluation',event.target.checked)}/><strong>研究结束后安排独立评测</strong></label>
  <p>同一固定模型、同一评测题集比较无 KB、初始 KB、本轮 KB。评测答案不参与知识发现。</p>
  {view.method?.experience_mode==='expel_inspired'&&<p>额外比较经验案例、经验规律、两者组合三组；均标记为未验证经验。</p>}
  {!evaluating&&<p className="workflow-task-off">本次未安排独立评测。已选择的评测题集会保留，关闭不会把它并入研究题集。</p>}
  <Field label="独立评测阶段" hint="只选用题目原有 development 或 final 分区，不修改原分区。"><select value={phase} onChange={event=>onPhase(event.target.value)}><option value="final">最终盲测</option><option value="development">开发集评测</option></select></Field>
  <strong>{taskSet?.name||(workflow.settings.task_question_set_id?'已保存独立评测题集':'尚未选择独立评测题目')}</strong>
  <p>{taskCount===undefined?'独立选择，与研究题集分开冻结':`已选 ${taskCount} 题 · 目标：${phase==='final'?'最终盲测':'开发评测'}，分区以预览核对为准`}</p>
  <div className="actions">{onTaskDataset&&<button onClick={onTaskDataset}>从 Dataset 选择独立评测</button>}<button onClick={onTask}>{workflow.settings.task_question_set_id?'调整独立评测题目':'选择独立评测题目'}</button></div>
  {(onTaskPairs||onTaskSingles)&&<details className="workflow-stage-disclosure"><summary>评测题对选择</summary>{onTaskPairs&&<button onClick={onTaskPairs}>选择独立评测题目对</button>}{taskSet?.selection_mode==='pairs'&&onTaskSingles&&<button onClick={onTaskSingles}>独立评测改为单题选择</button>}</details>}
  <p className="workflow-stage-note">更换评测分区后核对题目原分区。与研究集重复的题目、数据实例或谱系会在预览时拒绝。</p>
 </>;
 const configuration=(node:MethodPathNode):ReactNode=>{
  const physical=node.step.node_ids[0];
  if(physical==='input')return dataSettings();
  if(physical==='evaluate')return taskSettings();
  if(physical==='loop')return loopSettings();
  if(physical==='experiment'||physical==='confirmation')return experimentSettings();
  if(node.kind==='model')return <>{modelSettings(node)}{physical==='curator'&&<p>模型提出修改建议，下一步由程序验证证据与发布条件。</p>}</>;
  if(node.stage==='kb')return knowledgeSettings();
  return <p>{physical==='commit'?'程序先保存模型的原始回答，确保揭示标准答案后不会修改已提交答案。':physical==='reveal'?'读取真实训练结果核对已提交回答，再把反馈交给研究步骤；标准答案不会提前提供给 Solver。':'此步骤由程序按冻结流程执行，无需配置模型。'}</p>;
 };
 const savedKnowledge=run?.node_observations?.filter((observation:any)=>observation.node_id==='publish'&&observation.availability==='available').find((observation:any)=>observation.round_index===(round??view.round));
 const savedExperience=run?.node_observations?.find((observation:any)=>observation.node_id==='loop'&&observation.round_index===(round??view.round)&&observation.output?.experience)?.output?.experience;
 const inspector=selected?<>
  <span className="eyebrow">{selected.stage==='data'?'Data':selected.stage==='kb'?'KB':selected.stage==='task'?'Task':'Harness'}</span>
  <h2>{selected.label}</h2><p className="workflow-stage-note">{selected.description}</p>
  {run?<>
   {view.round&&selected.stage!=='task'&&<Field label="查看研究轮次"><input type="number" min={1} max={view.round} value={round??view.round} onChange={event=>{setFollowing(false);setRound(Math.max(1,Math.min(view.round!,Number(event.target.value))));}}/></Field>}
   {selected.stage==='kb'&&savedKnowledge?.output?.claims&&<details><summary>本轮已保存的正式 KB</summary><KnowledgeSnapshot snapshot={savedKnowledge.output}/><JsonView value={{patch:savedKnowledge.input?.patch,source:savedKnowledge.source}}/></details>}
   {selected.stage==='kb'&&savedExperience&&<details><summary>本轮经验与来源 · 未验证</summary><JsonView value={savedExperience}/></details>}
   {!selected.arranged?<p>本次冻结运行未安排此步骤。</p>:view.method&&!selected.step.events.some(event=>selected.stage==='task'||round===undefined||event.round_index===round)?<p>此方法步骤尚无可绑定的实际记录；不将其他步骤的输出归到这里。</p>:<RunWorkflowView key={`${run.id}:${selected.id}`} run={run} nodeIds={selected.step.node_ids} compact syncError={live.syncState?.error} fixedRound={selected.stage==='task'?undefined:round??view.round} stepId={view.method?selected.id:undefined}/>}
  </>:configuration(selected)}
 </>:<p>此流程没有可展示的研究步骤。</p>;
 return <RunStreamProvider run={run??emptyRun}><ResearchPathCanvas nodes={nodes} edges={edges} selectedId={selected?.id??''} onSelect={select} inspector={inspector}
  ariaLabel="方法研究路径"
  toolbar={<><span>{run?'本次冻结运行':'下一次运行草稿'}{view.method?` · ${view.method.name}`:''}{run&&view.round?` · 第 ${view.round} 轮`:''}</span>{run&&<button aria-pressed={following} onClick={()=>{setFollowing(true);if(currentId)setSelectedId(currentId);setRound(view.round);}}>跟随当前步骤</button>}</>}
  footer={<>
   {run?<><ErrorBox error={live.syncState?.error}/><RunFailure run={run} nodeId={run.progress?.node_id}/>{view.legacy&&<p>此历史运行未保存方法配方，仅展示已记录的程序节点。</p>}{run.status==='waiting_round'&&run.round_decision&&<RoundDecisionControls run={run} act={live.act}/>}<details className="workflow-stage-disclosure" onToggle={event=>setRecordsOpen(event.currentTarget.open)}><summary>完整执行记录</summary>{recordsOpen&&<RunWorkflowView run={run} syncError={live.syncState?.error}/>}</details></>:children}
  </>}
 /></RunStreamProvider>;
}
