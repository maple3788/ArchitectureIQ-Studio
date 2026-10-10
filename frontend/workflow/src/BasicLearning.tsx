import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowDown,BookOpen,Check,Database,GitCompareArrows,Lightbulb,MessageSquare,RotateCcw} from 'lucide-react';
import {RunStreamProvider} from './LiveOutput';
import {RoundDecisionControls} from './LiveWorkflowCanvas';
import {RunNodeIO} from './RunWorkflowView';
import {deriveRunWorkflow,nodeStatusLabel,type NodeStatus} from './runWorkflow';
import {QuestionReader} from './QuestionReader';
import {RolePrompt} from './RolePrompt';
import {InitialKBField,FrozenInitialKB} from './InitialKBField';
import {ErrorBox,Field,JsonView,useResource} from './ui';
import {RunFailure} from './RunFailure';
import type {Action} from './Questions';
import type {ModelProfile,QuestionSet,Run,Workflow} from './types';
import './basic-learning.css';

const nodes=[
 {id:'input',step:'assemble',title:'题目',area:'Data · 研究材料',purpose:'选择一道真实题目，组装公开题面。',hint:'同一道题，逐轮复盘',icon:Database},
 {id:'solver',step:'solve',title:'作答',area:'Harness · 模型调用',purpose:'阅读公开题面与已有经验，对候选方案排序并解释理由。回答保存后才会揭示本轮反馈。',hint:'公开题面 + 可选已有经验',icon:MessageSquare},
 {id:'reveal',step:'feedback',title:'对照结果',area:'Harness · 程序步骤',purpose:'将已保存的回答与题目的真实训练结果对照，供经验提炼使用。',hint:'保存回答后，揭示真实反馈',icon:GitCompareArrows},
 {id:'experience_curator',step:'experience_consolidate',title:'提炼经验',area:'Harness · 模型调用',purpose:'从本轮回答与反馈中提炼经验，修订适用条件和例外。',hint:'回答 + 反馈 → 经验草稿',icon:Lightbulb},
 {id:'experience_save',step:'experience_save',title:'知识库 · KB',area:'KB · 经验版本',purpose:'校验经验的来源与结构，保存可追溯的新版本。单题经验保持待验证状态。',hint:'保存经验、来源与版本',icon:BookOpen},
 {id:'loop',step:'loop',title:'是否继续',area:'Loop · 手动决定',purpose:'本轮封存后等待你的决定。下一轮使用同一道题，并按配置读取上一版经验。',hint:'带着经验，回到作答',icon:RotateCcw},
] as const;
const emptyRun:Run={id:'draft',kind:'workflow',created_at:0,status:'draft',config:{}};
export function BasicLearning({workflow,models,researchSet,onResearch,onSetting,onPrompt,rolePrompts,version,run,syncError,act}: {
 workflow:Workflow;models:ModelProfile[];researchSet?:QuestionSet;onResearch:()=>void;
 onSetting:(key:string,value:any)=>void;onPrompt:(id:string,value:string)=>void;rolePrompts?:Record<string,string>;
 version:number;run?:Run;syncError?:string;act?:Action;
}) {
 const inspector=useRef<HTMLElement>(null);
 const [selected,setSelected]=useState<string>('input'),[tab,setTab]=useState<'config'|'input'|'output'>('config');
 const [following,setFollowing]=useState(true),[selectedRound,setSelectedRound]=useState<number>();
 const graph=useMemo(()=>run?deriveRunWorkflow(run):undefined,[run]);
 const latestRound=graph?.rounds.filter(r=>r<1000).at(-1)??1;
 const round=selectedRound??latestRound;
 const actual=run?.config.workflow??workflow;
 const current=run?.progress?.node_id==='commit'?'solver':run?.progress?.node_id;
 useEffect(()=>{if(following&&nodes.some(n=>n.id===current)){setSelected(current!);setTab('output');setSelectedRound(undefined);}},[following,current,latestRound,run?.id]);
 useEffect(()=>{setSelectedRound(undefined);setFollowing(true);},[run?.id]);
 const selectedNode=nodes.find(n=>n.id===selected)??nodes[0];
 const frozenSet=run?.config.question_set;
 const setId=workflow.settings.question_set_id;
 const loadedSet=useResource<QuestionSet>(!run&&setId&&!researchSet?.keys?`/question-sets/${encodeURIComponent(setId)}`:null,version);
 const set=frozenSet??researchSet??loadedSet.data;
 const questionKey=set?.keys?.[0]??loadedSet.data?.keys?.[0]??set?.questions?.[0]?.key;
 const detail=useResource<any>(!run&&questionKey?`/questions/${encodeURIComponent(questionKey)}`:null,version);
 const choose=(id:string)=>{setSelected(id);setFollowing(false);setTab(run?'output':'config');if(window.matchMedia?.('(max-width: 560px)').matches)requestAnimationFrame(()=>inspector.current?.scrollIntoView({block:'start',behavior:'smooth'}));};
 const status=(id:string):NodeStatus=>{
  const node=graph?.nodes.find(n=>n.id===id);
  return node?.invocations.filter(i=>!i.unbound&&i.round===round).at(-1)?.status??'not_run';
 };
 const frozenModel=run?.config.models?.[0]??models.find(m=>m.id===workflow.settings.model_id);
 const draftQuestion=<><strong>{set?.name??'尚未选择题目'}</strong><p className="basic-muted">{questionKey?.split('@')[0]??(set?'已保存 1 道真实题目':'从题库选入一道资料完整的发现题。')}</p><button onClick={onResearch}>更换题目</button>{detail.data&&<details className="basic-question"><summary>阅读完整公开题面</summary><QuestionReader record={detail.data}/></details>}<ErrorBox error={detail.error||loadedSet.error}/></>;
 const config=()=>{
  if(run){
    const nodeConfig=actual.nodes.find((n:any)=>n.id===selected)?.config;
    const bool=(value:any,yes:string,no:string)=>value===true?yes:value===false?no:'未记录';
    return <><p className="basic-muted">本次配置已冻结；编辑工作流用于下一次运行。</p><dl className="basic-values">
      {selected==='input'&&<><dt>研究题目</dt><dd>{run.config.question_set?.name??'冻结题目'}</dd><dt>使用方式</dt><dd>同一道题逐轮复盘</dd></>}
      {selected==='solver'&&<><dt>作答模型</dt><dd>{frozenModel?.name??'未记录'}</dd>{frozenModel?.connection_type==='api'&&<><dt>服务身份</dt><dd>API 服务，权重身份未验证</dd></>}<dt>起始知识</dt><dd><FrozenInitialKB item={run.config.initial_kb} selection={actual.settings.initial_kb}/></dd><dt>后续轮次</dt><dd>{bool(actual.settings.use_previous_experience,'叠加本次学习的经验','每轮仅使用起始 KB，不叠加本次学习的经验')}</dd></>}
      {selected==='reveal'&&<><dt>揭示时机</dt><dd>本轮回答保存之后</dd><dt>反馈来源</dt><dd>题目封存的真实训练结果</dd></>}
      {selected==='experience_curator'&&<><dt>提炼模型</dt><dd>{frozenModel?.name??'未记录'}</dd><dt>经验边界</dt><dd>{bool(actual.settings.record_conditions,'记录适用条件与例外','本次不记录条件与例外')}</dd><dt>更新方式</dt><dd>从已揭示的回答与反馈提炼、修订经验。</dd></>}
      {selected==='experience_save'&&<><dt>保存方式</dt><dd>校验来源与结构，保存新版本</dd><dt>经验状态</dt><dd>待验证</dd></>}
      {selected==='loop'&&<><dt>循环方式</dt><dd>每轮封存后等待你的决定</dd><dt>最多轮数</dt><dd>{actual.settings.max_rounds??'未记录'} 轮</dd><dt>下一轮材料</dt><dd>同一道题；是否读取经验以作答配置为准</dd></>}
    </dl>{['solver','experience_curator'].includes(selected)&&<details><summary>冻结的附加 Prompt</summary>{nodeConfig?.prompt?<pre>{nodeConfig.prompt}</pre>:<p className="basic-muted">没有附加指令。完整实际 Prompt 可在该轮「输入」中查看。</p>}</details>}<details><summary>高级详情：冻结配置</summary><JsonView value={{...nodeConfig,...(selected==='solver'?{initial_kb:actual.settings.initial_kb,use_previous_experience:actual.settings.use_previous_experience}:selected==='experience_curator'?{record_conditions:actual.settings.record_conditions}:selected==='loop'?{max_rounds:actual.settings.max_rounds,loop_mode:actual.settings.loop_mode}:{})}}/></details></>;
  }
  if(selected==='input')return draftQuestion;
  if(selected==='solver')return <><Field label="作答模型"><select aria-label="作答模型" value={workflow.settings.model_id??''} onChange={e=>onSetting('model_id',e.target.value)}><option value="">选择模型</option>{models.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>{frozenModel?.connection_type==='api'&&<p className="basic-muted">API 服务，权重身份未验证；运行时冻结服务地址、模型名与请求参数。</p>}<InitialKBField value={workflow.settings.initial_kb} onChange={value=>onSetting('initial_kb',value)} version={version}/><label className="basic-check"><input type="checkbox" checked={workflow.settings.use_previous_experience!==false} onChange={e=>onSetting('use_previous_experience',e.target.checked)}/>后续轮次叠加本次学习的经验</label><p className="basic-muted">起始 KB 每轮都可使用；开启后，第二轮起还会读取本次学习积累的经验。再次作答属于接触反馈后的同题复盘。</p><details><summary>作答提示词</summary><RolePrompt role="solver" template={rolePrompts?.solver} guidance={workflow.nodes.find(n=>n.id==='solver')?.config.prompt??''} onGuidance={v=>onPrompt('solver',v)}/></details></>;
  if(selected==='reveal')return <dl className="basic-values"><dt>揭示时机</dt><dd>本轮回答已保存之后</dd><dt>反馈来源</dt><dd>题目封存的真实训练结果</dd></dl>;
  if(selected==='experience_curator')return <><label className="basic-check"><input type="checkbox" checked={workflow.settings.record_conditions!==false} onChange={e=>onSetting('record_conditions',e.target.checked)}/>记录适用条件与例外</label><p className="basic-muted">经验保留回答与反馈来源，后续复盘可修订已有条目。</p><details><summary>经验提炼提示词</summary><RolePrompt role="experience_curator" template={rolePrompts?.experience_curator} guidance={workflow.nodes.find(n=>n.id==='experience_curator')?.config.prompt??''} onGuidance={v=>onPrompt('experience_curator',v)}/></details></>;
  if(selected==='experience_save')return <dl className="basic-values"><dt>更新方式</dt><dd>校验来源，保存新版本</dd><dt>经验状态</dt><dd>待验证 · 同题反馈不能证明独立能力提升</dd></dl>;
  return <><Field label="最多学习轮数"><select value={workflow.settings.max_rounds??2} onChange={e=>onSetting('max_rounds',Number(e.target.value))}>{[1,2,3].map(n=><option value={n} key={n}>{n} 轮</option>)}</select></Field><p>每轮结束后由你决定是否继续。</p><p className="basic-muted">下一轮复用同一道题与起始 KB；是否叠加本次学习的经验由作答配置决定。研究模型与其他配置在开始时冻结。</p></>;
 };
 const nodeButton=(id:string,index:string)=>{const n=nodes.find(n=>n.id===id)!,Icon=n.icon,state=status(id);return <button key={id} className={`basic-node basic-state-${state} ${selected===id?'is-selected':''}`} aria-label={n.title} aria-pressed={selected===id} onClick={()=>choose(id)}><span className="basic-node-icon">{state==='complete'?<Check size={18}/>:<Icon size={18}/>}</span><span className="basic-node-copy"><strong>{n.title}</strong><small>{id==='input'?(set?'1 道真实题目':'尚未选题'):n.hint}</small></span><span className="basic-node-state">{run?nodeStatusLabel[state]:index}</span></button>;};
 const edge=(label:string)=><div className="basic-edge"><ArrowDown size={15}/><span>{label}</span></div>;
 return <RunStreamProvider run={run??emptyRun}><section className="basic-learning" aria-label="单题学习工作流">
  <div className="basic-overview"><div><span className="eyebrow">DATA → HARNESS → KB</span><h2>从一道题，积累一条经验</h2><p>{run?`第 ${round} 轮 · ${run.status==='waiting_round'?'本轮已封存，等待决定':frozenModel?.name??'冻结运行'}`:`${set?'1 道题':'未选题'} · ${frozenModel?.name??'待选择模型'} · 最多 ${workflow.settings.max_rounds??2} 轮`}</p></div><span className="basic-badge">手动循环</span></div>
  {run&&<><ErrorBox error={syncError}/><RunFailure run={run} nodeId={current}/></>}
  <div className="basic-workspace"><div className="basic-graph" aria-label="学习节点图">
   <div className="basic-group-label">DATA</div>{nodeButton('input','D')}{edge('公开题面')}
   <div className="basic-harness"><div className="basic-group-label">HARNESS <span>单题学习 · 2 次模型调用 / 轮</span></div>{nodeButton('solver','1')}{edge('保存回答')}{nodeButton('reveal','2')}{edge('真实反馈')}{nodeButton('experience_curator','3')}</div>
   {edge('经验草稿')}{nodeButton('experience_save','K')}{edge('保存新版本')}{nodeButton('loop','↻')}
   <p className="basic-loop-return">↳ 同题复盘 → 补充经验的条件与例外</p>
   {run&&<label className="basic-follow"><input type="checkbox" checked={following} onChange={e=>setFollowing(e.target.checked)}/>跟随当前节点</label>}
  </div><section ref={inspector} className="basic-inspector" aria-label="节点详情">
   <header><span className="eyebrow">{selectedNode.area}</span><h3>{selectedNode.title}</h3><p>{selectedNode.purpose}</p></header>
   {run&&<label className="basic-round">查看轮次<select aria-label="查看学习轮次" value={round} onChange={e=>{setFollowing(false);setSelectedRound(Number(e.target.value));}}>{(graph?.rounds.filter(r=>r<1000).length?graph.rounds.filter(r=>r<1000):[1]).map(r=><option key={r} value={r}>第 {r} 轮</option>)}</select></label>}
   <div className="basic-tabs" role="tablist" aria-label="配置与输入输出">{(['config','input','output'] as const).map((t,i)=><button key={t} role="tab" id={`basic-tab-${t}`} aria-controls="basic-panel" aria-selected={tab===t} onClick={()=>setTab(t)}>{['配置','输入','输出'][i]}</button>)}</div>
   <div className="basic-panel" role="tabpanel" id="basic-panel" aria-labelledby={`basic-tab-${tab}`}>{tab==='config'?config():run?<RunNodeIO key={`${run.id}:${selected}:${round}`} run={run} nodeId={selected} stepId={selectedNode.step} round={round} direction={tab}/>:tab==='input'&&selected==='input'?draftQuestion:tab==='input'?<p className="basic-muted">开始后可查看此节点实际收到的材料与 Prompt。当前是待运行的配置。</p>:<p className="basic-muted">运行到此节点后，在这里查看真实输出。模型调用支持逐段显示。</p>}</div>
  </section></div>
  {run?.status==='waiting_round'&&run.round_decision&&<RoundDecisionControls run={run} act={act}/>}
  <p className="basic-footnote">同题复盘已接触先前反馈，产生的经验需要独立新题或受控实验验证。</p>
 </section></RunStreamProvider>;
}
