import {useState,type ReactNode} from 'react';
import type {Connection} from '@xyflow/react';
import {ResearchPathCanvas,type PathNode,type PathEdge} from './ResearchPathCanvas';
import type {Workflow,WorkflowNode,Run} from './types';
import {ErrorBox,Field} from './ui';
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
const descriptions:Record<string,string>={input:'固定 Dataset 修订',initialize:'导入规则或模型提出',verify:'全批预测封存后评分',revise:'根据错题与冲突提出补丁',accept:'同池回归 · 保护历史正确题',challenge:'生成新题 · 独立保留首次成绩',save:'规则、成绩与未解问题'};
const conditionNames:Record<string,string>={needs_revision:'错题与冲突',pool_passed:'题池通过',stopped:'达到停止条件',target_reached:'目标达成'};
export function RuleRefinementCanvas({workflow,onChange,validation,run,onSelect,renderConfig}:{workflow:Workflow;onChange:(w:Workflow)=>void;validation?:{valid:boolean;errors:any[]};run?:Run;onSelect?:(node:WorkflowNode)=>void;renderConfig?:(node:WorkflowNode)=>ReactNode}){
 const [selected,setSelected]=useState(renderConfig?'input':'verify'),[error,setError]=useState('');
 const node=workflow.nodes.find(n=>n.id===selected)||workflow.nodes[0],selectedId=node?.id||'',order=groupOrder(workflow);
 const apply=(fn:()=>Workflow)=>{try{onChange(fn());setError('');}catch(e){setError((e as Error).message);}};
 // Control-flow loops explain the runner; they are never written to the material DAG.
 const loops:PathEdge[]=[{id:'control-accept-verify',source:'accept',target:'verify',sourceHandle:'control_loop',targetHandle:'control_loop',label:'继续检查题池',loop:true},{id:'control-challenge-verify',source:'challenge',target:'verify',sourceHandle:'control_loop',targetHandle:'control_loop',label:'新题首测 → 纳入题池',loop:true}].filter(e=>workflow.nodes.some(n=>n.id===e.source)&&workflow.nodes.some(n=>n.id===e.target));
 const nodes:PathNode[]=workflow.nodes.map(n=>({id:n.id,label:n.label||n.id,position:n.position,stage:n.id==='input'?'data':n.id==='save'?'kb':'harness',kind:n.id==='revise'||n.id==='initialize'&&n.config.mode==='model'?'model':n.id==='accept'?'decision':'program',description:descriptions[n.id]||'整理完整反馈，保留全部问题',
  inputs:[...new Set([...workflow.edges.filter(e=>e.target===n.id).map(e=>e.target_handle).filter((p):p is string=>!!p),...loops.filter(e=>e.target===n.id).map(()=> 'control_loop')])],
  outputs:[...new Set([...workflow.edges.filter(e=>e.source===n.id).map(e=>e.source_handle).filter((p):p is string=>!!p),...loops.filter(e=>e.source===n.id).map(()=> 'control_loop')])]}));
 const edges:PathEdge[]=[...workflow.edges.map(e=>({id:e.id,source:e.source,target:e.target,sourceHandle:e.source_handle,targetHandle:e.target_handle,label:conditionNames[e.condition||'']||materialNames[e.source_handle||'']})),...loops];
 const materials=<dl><dt>输入材料</dt><dd>{[...new Set(workflow.edges.filter(e=>e.target===selectedId).map(e=>materialNames[e.target_handle||'']))].join('、')||'所选 Dataset'}</dd><dt>输出材料</dt><dd>{[...new Set(workflow.edges.filter(e=>e.source===selectedId).map(e=>materialNames[e.source_handle||'']))].join('、')||'研究记录'}</dd></dl>;
 const inspector=node&&<div className="rr-node-panel"><header><small>{node.id==='input'?'Data':node.id==='save'?'KB':'Harness'}</small><h3>{node.label}</h3><p>{descriptions[node.id]||'调整问题分组顺序，改变模型收到材料的组织方式。'}</p></header>{renderConfig?.(node)}
  {node.type==='group_cases'&&<><Field label="分组位置"><select value={order.indexOf(selectedId)} disabled={!!run} onChange={e=>{const next=order.filter(id=>id!==selectedId);next.splice(Number(e.target.value),0,selectedId);onChange(route(workflow,next));}}>{order.map((id,i)=><option key={id} value={i}>{i+1}</option>)}</select></Field><button disabled={!!run} onClick={()=>apply(()=>removeGrouping(workflow,selectedId))}>移除此分组</button></>}
  {renderConfig?<details className="rr-materials"><summary>输入与输出材料</summary>{materials}</details>:materials}</div>;
 return <section className="rr-flow-section"><ErrorBox error={error||(!validation?.valid?validation?.errors.join('；'):undefined)}/>
  <ResearchPathCanvas nodes={nodes} edges={edges} selectedId={selectedId} onSelect={id=>{setSelected(id);const value=workflow.nodes.find(n=>n.id===id);if(value)onSelect?.(value);}} inspector={inspector} ariaLabel="规则闭环画布"
   toolbar={<div className="rr-flow-toolbar"><span>规则修订与新题挑战</span><Field label="添加问题分组"><select value="" disabled={!!run} onChange={e=>apply(()=>addGrouping(workflow,e.target.value))}><option value="">选择整理方式</option>{Object.entries(groupingNames).map(([k,v])=><option key={k} value={k} disabled={workflow.nodes.some(n=>n.config.strategy===k)}>{v}</option>)}</select></Field></div>}
   footer={<p className="rr-flow-note">实线传递材料，虚线表示循环。点击节点配置；反馈分组支持连接与排序。</p>}
   onMove={run?undefined:(id,position)=>onChange({...workflow,nodes:workflow.nodes.map(old=>old.id===id?{...old,position}:old)})}
   onConnect={run?undefined:c=>apply(()=>connectFeedback(workflow,c))}/>
 </section>;
}
