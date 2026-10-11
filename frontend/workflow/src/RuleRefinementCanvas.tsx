import {useState,type ReactNode} from 'react';
import type {Connection} from '@xyflow/react';
import {ResearchPathCanvas,type PathNode,type PathEdge} from './ResearchPathCanvas';
import type {Workflow,WorkflowNode,Run} from './types';
import {ErrorBox,Field} from './ui';
import {ruleLoopPresentation,ruleLoopDescriptions} from './ruleLoopPresentation';
import './rule-loop-canvas.css';
import './rule-refinement.css';
const groupingNames:Record<string,string>={type:'按问题类型',rule:'按规则',family:'按数据家族'};
const materialNames:Record<string,string>={public_cases:'公开题目',rule_kb:'规则 KB',sealed_feedback:'已封存反馈',patch:'修订补丁',decision:'验收决定'};
export function groupOrder(workflow:Workflow):string[]{
 const groups=new Set(workflow.nodes.filter(n=>n.type==='group_cases').map(n=>n.id)),order:string[]=[];let source='verify';
 while(true){const next=workflow.edges.find(e=>e.source===source&&e.source_handle==='sealed_feedback'&&e.target!=='accept')?.target;if(!next||!groups.has(next)||order.includes(next))break;order.push(next);source=next;}
 return [...order,...[...groups].filter(id=>!order.includes(id))];
}
function route(workflow:Workflow,order:string[]):Workflow{
 const groups=new Set(workflow.nodes.filter(n=>n.type==='group_cases').map(n=>n.id));
 const edges=workflow.edges.filter(e=>!groups.has(e.source)&&!groups.has(e.target)&&!(e.source==='verify'&&e.target==='revise'));
 const chain=['verify',...order,'revise'];for(let i=0;i<chain.length-1;i++){const source=chain[i],target=chain[i+1];edges.push({id:`${source}-${target}-sealed_feedback`,source,target,source_handle:'sealed_feedback',target_handle:'sealed_feedback',mapping:{sealed_feedback:'sealed_feedback'},condition:source==='verify'?'needs_revision':'always'});}
 return {...workflow,edges};
}
export function addGrouping(workflow:Workflow,strategy:string){
 if(!groupingNames[strategy]||workflow.nodes.some(n=>n.type==='group_cases'&&n.config.strategy===strategy))return workflow;
 const order=groupOrder(workflow),id='group_'+strategy;
 return route({...workflow,nodes:[...workflow.nodes,{id,type:'group_cases',label:groupingNames[strategy],position:{x:270+order.length*260,y:530},config:{strategy}}]},[...order,id]);
}
export function removeGrouping(workflow:Workflow,id:string){
 if(!workflow.nodes.some(n=>n.id===id&&n.type==='group_cases'))throw Error('保护节点不能移除');
 const order=groupOrder(workflow).filter(x=>x!==id);
 return route({...workflow,nodes:workflow.nodes.filter(n=>n.id!==id),edges:workflow.edges.filter(e=>e.source!==id&&e.target!==id)},order);
}
export function connectFeedback(workflow:Workflow,c:Connection):Workflow{
 const order=groupOrder(workflow);
 if(c.sourceHandle!=='sealed_feedback'||c.targetHandle!=='sealed_feedback'||c.source===c.target||!(c.source==='verify'||order.includes(c.source))||!(c.target==='revise'||order.includes(c.target)))throw Error('仅可重排验证 → 问题分组 → 修订之间的反馈材料');
 let next=order.filter(id=>id!==c.target);
 if(c.target==='revise'){next=order.filter(id=>id!==c.source);if(c.source!=='verify')next.push(c.source);else if(order.length)throw Error('请先移除分组节点，再直连修订');}
 else next.splice(c.source==='verify'?0:next.indexOf(c.source)+1,0,c.target);
 return route(workflow,next);
}
const materialDescriptions:Record<string,string>={input:'固定 Dataset 修订',initialize:'导入规则或模型提出',verify:'全批预测封存后评分',revise:'根据错题与冲突提出补丁',accept:'同池回归 · 保护历史正确题',challenge:'生成新题 · 独立保留首次成绩',save:'规则、成绩与未解问题'};
const conditionNames:Record<string,string>={needs_revision:'错题与冲突',pool_passed:'题池通过',stopped:'达到停止条件',target_reached:'目标达成'};
export function RuleRefinementCanvas({workflow,onChange,validation,run,onSelect,renderConfig,selectedId:controlledSelection}:{workflow?:Workflow;onChange?:(w:Workflow)=>void;validation?:{valid:boolean;errors:any[]};run?:Run;onSelect?:(node:WorkflowNode)=>void;renderConfig?:(node:WorkflowNode)=>ReactNode;selectedId?:string}){
 const [selected,setSelected]=useState(''),[inspectorOpen,setInspectorOpen]=useState(false),[materialView,setMaterialView]=useState(false),[error,setError]=useState('');
 const selectedId=controlledSelection??selected,editable=!!workflow&&!!onChange&&!run,showMaterials=materialView&&!!workflow&&!run;
 const overview=ruleLoopPresentation({workflow,run});
 const displayNode=overview.nodes.find(n=>n.id===selectedId);
 // A persisted run uses only the controller overview, never the current editing draft.
 const node=(!run?workflow?.nodes.find(n=>n.id===selectedId):undefined)??(displayNode?{id:displayNode.id,type:'controller_view',label:displayNode.label,position:displayNode.position!,config:{}}:undefined);
 const order=workflow&&!run?groupOrder(workflow):[];
 const apply=(fn:()=>Workflow)=>{if(!editable)return;try{onChange!(fn());setError('');}catch(e){setError((e as Error).message);}};
 const loops:PathEdge[]=workflow?[{id:'control-accept-verify',source:'accept',target:'verify',sourceHandle:'control_loop',targetHandle:'control_loop',label:'继续检查题池',loop:true},{id:'control-challenge-verify',source:'challenge',target:'verify',sourceHandle:'control_loop',targetHandle:'control_loop',label:'新题首测 → 纳入题池',loop:true}].filter(e=>workflow.nodes.some(n=>n.id===e.source)&&workflow.nodes.some(n=>n.id===e.target)):[];
 const materialNodes:PathNode[]=showMaterials?workflow!.nodes.map(n=>({id:n.id,label:n.label||n.id,position:n.position,stage:n.id==='input'?'data':n.id==='save'?'kb':'harness',kind:n.id==='revise'||n.id==='initialize'&&n.config.mode==='model'?'model':n.id==='accept'?'decision':'program',description:materialDescriptions[n.id]||'整理完整反馈，保留全部问题',
  inputs:[...new Set([...workflow!.edges.filter(e=>e.target===n.id).map(e=>e.target_handle).filter((p):p is string=>!!p),...loops.filter(e=>e.target===n.id).map(()=> 'control_loop')])],
  outputs:[...new Set([...workflow!.edges.filter(e=>e.source===n.id).map(e=>e.source_handle).filter((p):p is string=>!!p),...loops.filter(e=>e.source===n.id).map(()=> 'control_loop')])]})):[];
 const materialEdges:PathEdge[]=showMaterials?[...workflow!.edges.map(e=>({id:e.id,source:e.source,target:e.target,sourceHandle:e.source_handle,targetHandle:e.target_handle,label:conditionNames[e.condition||'']||materialNames[e.source_handle||'']})),...loops]:[];
 const select=(id:string)=>{setSelected(id);setInspectorOpen(true);const current=(!run?workflow?.nodes.find(n=>n.id===id):undefined),item=overview.nodes.find(n=>n.id===id);if(current)onSelect?.(current);else if(item)onSelect?.({id,type:'controller_view',label:item.label,position:item.position!,config:{}});};
 const groupControls=editable&&workflow&&<div className="rule-loop-grouping"><Field label="添加问题分组"><select value="" onChange={e=>apply(()=>addGrouping(workflow,e.target.value))}><option value="">选择整理方式</option>{Object.entries(groupingNames).map(([k,v])=><option key={k} value={k} disabled={workflow.nodes.some(n=>n.type==='group_cases'&&n.config.strategy===k)}>{v}</option>)}</select></Field>{order.map((id,index)=>{const group=workflow.nodes.find(n=>n.id===id)!;return <div className="rule-loop-group-row" key={id}><span>{groupingNames[group.config.strategy]||group.label}</span><select aria-label={`${group.label}的位置`} value={index} onChange={e=>apply(()=>{const next=order.filter(value=>value!==id);next.splice(Number(e.target.value),0,id);return route(workflow,next);})}>{order.map((_,i)=><option key={i} value={i}>{i+1}</option>)}</select><button onClick={()=>apply(()=>removeGrouping(workflow,id))}>移除</button></div>;})}</div>;
 const materials=workflow&&!run&&<dl><dt>输入材料</dt><dd>{[...new Set(workflow.edges.filter(e=>e.target===selectedId).map(e=>materialNames[e.target_handle||'']))].join('、')||'所选 Dataset'}</dd><dt>输出材料</dt><dd>{[...new Set(workflow.edges.filter(e=>e.source===selectedId).map(e=>materialNames[e.source_handle||'']))].join('、')||'研究记录'}</dd></dl>;
 const inspector=inspectorOpen&&node&&<div className="rr-node-panel"><header><div className="rule-loop-inspector-heading"><small>{node.id==='input'?'Data':node.id==='save'?'KB':'Harness'}</small><button type="button" aria-label="关闭节点详情" onClick={()=>setInspectorOpen(false)}>×</button></div><h3>{node.label}</h3><p>{ruleLoopDescriptions[node.id as keyof typeof ruleLoopDescriptions]||'调整问题分组顺序，保留完整反馈。'}</p></header>
  {node.id==='feedback'?<><p>错答、规则冲突、未覆盖题和规则反例共同进入修订。冲突保留为问题，不强行选择答案。</p>{groupControls}</>:!run?renderConfig?.(node):<p className="muted">运行记录与证据显示在画布下方；状态来自已保存的后台事件。</p>}
  {node.type==='group_cases'&&groupControls}
  {showMaterials&&<details className="rr-materials"><summary>输入与输出材料</summary>{materials}</details>}
 </div>;
 return <section className={`rr-flow-section rule-loop-canvas ${showMaterials?'is-material-view':'is-loop-view'}`}><ErrorBox error={error||(validation?.valid===false?validation.errors.join('；'):undefined)}/>
  <ResearchPathCanvas nodes={showMaterials?materialNodes:overview.nodes} edges={showMaterials?materialEdges:overview.edges} selectedId={selectedId} onSelect={select} inspector={inspector} inspectorPresentation="overlay" ariaLabel="规则闭环画布"
   toolbar={<div className="rule-loop-toolbar"><span>{showMaterials?'材料连线':'研究路径'}</span>{workflow&&!run&&<button type="button" className="rule-loop-view-switch" aria-pressed={showMaterials} onClick={()=>{setMaterialView(!showMaterials);setInspectorOpen(false);}}>{showMaterials?'返回研究路径':'材料连线'}</button>}</div>}
   footer={<p className="rr-flow-note">{showMaterials?'实线传递材料，虚线解释循环。原有节点位置与反馈分组可在此调整。':'题池通过后再出题，首测留档后整批入池；修订须通过不退步验收。达到目标或停止上限时保留已验收 KB。'}</p>}
   onMove={showMaterials&&editable?(id,position)=>apply(()=>({...workflow!,nodes:workflow!.nodes.map(old=>old.id===id?{...old,position}:old)})):undefined}
   onConnect={showMaterials&&editable?c=>apply(()=>connectFeedback(workflow!,c)):undefined}/>
 </section>;
}
