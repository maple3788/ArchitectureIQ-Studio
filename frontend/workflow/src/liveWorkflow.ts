import {deriveRunWorkflow, nodeLabel, type NodeStatus} from './runWorkflow';
import type {MethodDefinition,MethodStep,Run,StageId,Workflow} from './types';
export type Focus={stageId:StageId;stepId?:string;round?:number;invocationId?:string};
export type SyncState={error?:string;lastSyncedAt?:number};
export type LiveStep=MethodStep&{status:NodeStatus;events:any[]};
export type WorkflowViewModel={source:'draft'|'run';workflow?:Workflow;method?:MethodDefinition;legacy:boolean;round?:number;current?:Focus;syncState?:SyncState;stages:{id:StageId;nodeIds:string[];status:NodeStatus;steps:LiveStep[]}[]};
export const stageDefinitions:{id:StageId;title:string;description:string;nodeIds:string[]}[]=[
 {id:'data',title:'Data · 研究数据',description:'冻结本轮题目与公开材料',nodeIds:['input']},
 {id:'harness',title:'Harness · 研究策略',description:'按冻结方法处理题目与反馈',nodeIds:['solver','commit','reveal','discoverer','skeptic','experiment','confirmation','analyst','curator']},
 {id:'kb',title:'KB · 知识积累',description:'保存知识版本、经验与来源',nodeIds:['publish']},
 {id:'task',title:'Task · 新题解答与效果验证',description:'使用冻结版本解答独立新题',nodeIds:['evaluate']},
];
function aggregate(statuses:NodeStatus[]):NodeStatus {
 for(const s of ['failed','uncertain','interrupted','paused','running','pending','ready'] as NodeStatus[])if(statuses.includes(s))return s;
 if(statuses.length&&statuses.every(s=>s==='complete'||s==='skipped'))return statuses.every(s=>s==='skipped')?'skipped':'complete';
 return statuses.some(s=>s==='complete')?'ready':'not_run';
}
export function deriveLiveWorkflow({draft,run,methodDefinition,syncState}:{draft?:Workflow;run?:Run;methodDefinition?:MethodDefinition;syncState?:SyncState}):WorkflowViewModel {
 const graph=run?deriveRunWorkflow(run):undefined;
 const workflow=run?graph?.workflow:draft;
 // The catalog may evolve; history is described only by its persisted recipe.
 const method:MethodDefinition|undefined=run?run.config?.method:methodDefinition;
 const stageEvents=(run?.events??[]).filter(e=>e.type==='stage');
 const rounds=[...stageEvents.map(e=>e.round_index),run?.progress?.round_index].filter((r):r is number=>Number.isInteger(r)&&r>0&&r<1000);
 const round=rounds.length?Math.max(...rounds):undefined;
 const nodeStatus=(id:string):NodeStatus=>{
  const node=graph?.nodes.find(n=>n.id===id);if(!node)return 'not_run';
  if(id==='evaluate'||round===undefined)return node.status;
  const inv=node.invocations.filter(i=>!i.unbound&&i.round===round);
  return inv.length?aggregate(inv.map(i=>i.status)):node.status==='skipped'?'skipped':'not_run';
 };
 const stages=stageDefinitions.map(s=>{
  const configuredSteps=method?.steps.filter(step=>step.stage_id===s.id);
  const definitions=configuredSteps?.length?configuredSteps:s.nodeIds.filter(id=>workflow?.nodes.some(n=>n.id===id)).map(id=>({id,stage_id:s.id,label:nodeLabel(id),node_ids:[id]}));
  const steps:LiveStep[]=definitions.map(step=>{
   const events=stageEvents.filter(e=>method?e.step_id===step.id:step.node_ids.includes(e.node_id));
   const currentEvents=events.filter(e=>s.id==='task'||round===undefined||e.round_index===round);
   const current=run?.progress?.step_id===step.id&&run?.progress?.round_index===round?run.progress:undefined;
   const explicitStatus=(current??currentEvents.at(-1))?.state;
   const status:NodeStatus=explicitStatus==='completed'?'complete':explicitStatus&&['complete','failed','uncertain','interrupted','running','ready','pending','paused','skipped'].includes(explicitStatus)?explicitStatus:method?'not_run':aggregate(step.node_ids.map(nodeStatus));
   const terminalStatus:NodeStatus = ['running','ready','pending'].includes(status)&&run&&['failed','uncertain','interrupted','cancelled','paused'].includes(run.status) ? run.status==='cancelled'?'interrupted':run.status as NodeStatus : status;
   return {...step,status:terminalStatus,events};
  });
  const nodeIds=method?.steps.some(step=>step.stage_id===s.id)?[...new Set(method.steps.filter(step=>step.stage_id===s.id).flatMap(step=>step.node_ids))]:s.nodeIds;
  const statuses=nodeIds.map(nodeStatus);
  let status=run?aggregate(statuses):'ready' as NodeStatus;
  if(run&&s.id==='task'&&!workflow?.edges.some(e=>e.target==='evaluate'))status='skipped';
  if(run&&method&&steps.some(step=>step.events.length))status=aggregate(steps.map(step=>step.status));
  // A sealed publication attests stage completion even when no eligible
  // hypothesis scheduled optional experiment steps. Their own statuses stay honest.
  if(run&&(s.id==='harness'||s.id==='kb')&&nodeStatus('publish')==='complete'&&!['failed','uncertain','interrupted','running','pending','paused'].includes(status))status='complete';
  return {id:s.id,nodeIds,status,steps};
 });
 const nodeId=graph?.currentNodeId;
 const latest=stageEvents.at(-1);
 const stageId=(run?.progress?.stage_id??latest?.stage_id??stageDefinitions.find(s=>s.nodeIds.includes(nodeId??''))?.id) as StageId|undefined;
 const stepId=run?.progress?.step_id??latest?.step_id;
 return {source:run?'run':'draft',workflow,method,legacy:!!run&&!method,round,current:stageId?{stageId,stepId:method?.steps.some(step=>step.id===stepId)?stepId:undefined,round}:undefined,syncState,stages};
}
