import {useState} from 'react';
import {ReactFlow,Background,Controls,Handle,Position,MarkerType,type Connection} from '@xyflow/react';
import type {Workflow,WorkflowNode,Run} from './types';
import {ErrorBox,Field} from './ui';
import '@xyflow/react/dist/style.css';
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
function Stage({data,selected}:any){return <div className={`rr-node ${selected?'selected':''}`}><small>{data.node.type==='group_cases'?'材料整理':data.node.id==='initialize'||data.node.id==='revise'?'模型':'程序'}</small><b>{data.node.label}</b>{data.inputs.map((p:string,i:number)=><Handle key={'in'+p} type="target" id={p} position={Position.Left} style={{top:30+i*24}}/>)}{data.outputs.map((p:string,i:number)=><Handle key={'out'+p} type="source" id={p} position={Position.Right} style={{top:30+i*24}}/>)}<span>{data.description}</span></div>;}
const nodeTypes={stage:Stage};
const descriptions:Record<string,string>={input:'固定 Dataset 修订',initialize:'导入规则或模型提出',verify:'全批预测封存后评分',revise:'根据问题提出补丁',accept:'同池回归 · 保护历史正确题',challenge:'新题第一次成绩独立保留',save:'规则、成绩与未解问题'};
export function RuleRefinementCanvas({workflow,onChange,validation,run,onSelect}:{workflow:Workflow;onChange:(w:Workflow)=>void;validation?:{valid:boolean;errors:any[]};run?:Run;onSelect?:(node:WorkflowNode)=>void}){
 const [selected,setSelected]=useState('verify'),[error,setError]=useState('');const node=workflow.nodes.find(n=>n.id===selected);const order=groupOrder(workflow);
 const apply=(fn:()=>Workflow)=>{try{onChange(fn());setError('');}catch(e){setError((e as Error).message);}};
 const nodes=workflow.nodes.map(n=>({id:n.id,type:'stage',position:n.position,selected:n.id===selected,deletable:false,data:{node:n,description:descriptions[n.id]||'完整反馈 · 保留全部问题',inputs:[...new Set(workflow.edges.filter(e=>e.target===n.id).map(e=>e.target_handle))],outputs:[...new Set(workflow.edges.filter(e=>e.source===n.id).map(e=>e.source_handle))]}}));
 return <section className="rr-flow-section" aria-label="规则闭环画布"><div className="rr-flow-caption"><div><h3>规则修订 ↔ 新题挑战</h3><p>内环修订与回归；累计题池通过后进入外环。封存、验收和预算由程序保证。</p></div><Field label="添加问题分组"><select value="" disabled={!!run} onChange={e=>apply(()=>addGrouping(workflow,e.target.value))}><option value="">选择整理方式</option>{Object.entries(groupingNames).map(([k,v])=><option key={k} value={k} disabled={workflow.nodes.some(n=>n.config.strategy===k)}>{v}</option>)}</select></Field></div><ErrorBox error={error||(!validation?.valid?validation?.errors.join('；'):undefined)}/>
 <div className="rr-flow-body"><div className="rr-flow"><ReactFlow nodes={nodes} nodeTypes={nodeTypes} edges={workflow.edges.map(e=>({id:e.id,source:e.source,target:e.target,sourceHandle:e.source_handle,targetHandle:e.target_handle,label:materialNames[e.source_handle||''],type:'smoothstep',markerEnd:{type:MarkerType.ArrowClosed},deletable:false}))} fitView minZoom={0.3} maxZoom={1.3} nodesDraggable={!run} nodesConnectable={!run} deleteKeyCode={null} onNodeClick={(_,n)=>{setSelected(n.id);const value=workflow.nodes.find(x=>x.id===n.id);if(value)onSelect?.(value);}} onNodeDragStop={(_,n)=>onChange({...workflow,nodes:workflow.nodes.map(old=>old.id===n.id?{...old,position:n.position}:old)})} onConnect={c=>apply(()=>connectFeedback(workflow,c))}><Background/><Controls showInteractive={false}/></ReactFlow></div>
 <aside className="rr-node-panel"><small>节点详情</small><h3>{node?.label}</h3><p>{descriptions[selected]||'调整问题分组顺序，改变模型收到材料的组织方式。'}</p>{node?.type==='group_cases'&&<><Field label="分组位置"><select value={order.indexOf(selected)} disabled={!!run} onChange={e=>{const next=order.filter(id=>id!==selected);next.splice(Number(e.target.value),0,selected);onChange(route(workflow,next));}}>{order.map((id,i)=><option key={id} value={i}>{i+1}</option>)}</select></Field><button disabled={!!run} onClick={()=>apply(()=>removeGrouping(workflow,selected))}>移除此分组</button></>}{node&&<dl><dt>输入材料</dt><dd>{[...new Set(workflow.edges.filter(e=>e.target===selected).map(e=>materialNames[e.target_handle||'']))].join('、')||'所选 Dataset'}</dd><dt>输出材料</dt><dd>{[...new Set(workflow.edges.filter(e=>e.source===selected).map(e=>materialNames[e.source_handle||'']))].join('、')||'研究记录'}</dd></dl>}<p className="muted">拖动节点安排画布；拖动反馈端口可调整分组顺序。</p></aside></div></section>;
}
