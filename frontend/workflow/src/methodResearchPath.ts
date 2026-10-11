import {deriveRunWorkflow} from './runWorkflow';
import {deriveLiveWorkflow, type LiveStep, type SyncState} from './liveWorkflow';
import type {MethodDefinition,Run,Workflow} from './types';
import type {PathNode,PathEdge} from './ResearchPathCanvas';

export type MethodPathNode=PathNode&{step:LiveStep;arranged:boolean};
const descriptions:Record<string,string>={
 assemble:'冻结题目与公开材料', input:'冻结题目与公开材料',
 solve:'阅读公开题面与已有知识', solver:'阅读公开题面与已有知识',
 commit:'先封存回答，再揭示反馈', feedback:'核对已保存的真实训练结果', reveal:'核对已保存的真实训练结果',
 hypothesize:'从反馈提出可检验假说', discoverer:'从反馈提出可检验假说',
 pair_induction:'仅看正常题反馈，归纳规律', pair_transfer:'尚未揭示反事实反馈，先作预测',
 pair_revision:'揭示对照反馈，修订条件与例外',
 skeptic:'检查反例与可验证性', experiment:'有可验证假说时执行',
 confirmation:'探索结果满足条件时独立确认', analysis:'解释证据支持的范围', analyst:'解释证据支持的范围',
 experience_consolidate:'整理案例与规律，保留未验证状态',
 curate:'根据证据提出知识修改', curator:'根据证据提出知识修改',
 publish:'通过证据门槛后保存版本',
 loop:'按轮次、预算和停止条件决定',
 evaluate:'独立题集验证，反馈不回流',
};

/** A research-path projection only: it never edits the executable graph or frozen recipe. */
export function deriveMethodResearchPath({workflow,methodDefinition,run,syncState}:{workflow:Workflow;methodDefinition?:MethodDefinition;run?:Run;syncState?:SyncState}) {
 const view=deriveLiveWorkflow({draft:workflow,methodDefinition,run,syncState});
 const source=view.workflow;
 const liveSteps=view.stages.flatMap(stage=>stage.steps);
 // Recipes distinguish multiple uses of the same actor. Historical runs without
 // a recipe keep their recorded physical nodes instead of adopting today's catalog.
 const steps:LiveStep[]=view.method?view.method.steps.map(step=>liveSteps.find(live=>live.id===step.id)??{...step,status:'not_run',events:[]}):[...liveSteps];
 if(!view.method&&source?.nodes.some(node=>node.id==='loop')&&!steps.some(step=>step.id==='loop')) {
  const taskIndex=steps.findIndex(step=>step.stage_id==='task');
  const loop=run?deriveRunWorkflow(run).nodes.find(node=>node.id==='loop'):undefined;
  const status=view.round?loop?.invocations.filter(invocation=>!invocation.unbound&&invocation.round===view.round).at(-1)?.status:loop?.status;
  steps.splice(taskIndex<0?steps.length:taskIndex,0,{id:'loop',stage_id:'kb',label:'决定是否继续',node_ids:['loop'],status:status??'not_run',events:(run?.events??[]).filter(event=>event.type==='stage'&&event.node_id==='loop')});
 }
 const nodes:MethodPathNode[]=steps.map(step=>{
  const physical=step.node_ids[0];
  const optional=physical==='confirmation'||physical==='evaluate';
  const arranged=!optional||!!source?.edges.some(edge=>edge.target===physical);
  const kind:PathNode['kind']=physical==='loop'?'decision':step.node_ids.some(id=>source?.nodes.some(node=>node.id===id&&node.type==='agent'))?'model':'program';
  return {id:step.id,label:step.label,description:arranged?descriptions[step.id]??descriptions[physical]??'查看此步骤的配置与记录':'未安排 · 点击可配置',stage:step.stage_id,kind,status:arranged?(run?step.status:undefined):'未安排',step,arranged};
 });
 const edges:PathEdge[]=[];
 if(!view.method) {
  for(const edge of source?.edges??[])if(nodes.some(node=>node.id===edge.source)&&nodes.some(node=>node.id===edge.target)) {
   edges.push({id:edge.id,source:edge.source,target:edge.target,label:edge.condition,optional:edge.target==='confirmation'||edge.target==='evaluate',loop:edge.source==='loop'&&edge.target==='input'});
  }
 } else {
  const main=nodes.filter(node=>!node.step.node_ids.includes('confirmation')&&node.stage!=='task');
  for(let index=1;index<main.length;index++) {
   const previous=main[index-1],current=main[index];
   edges.push({id:`path-${previous.id}-${current.id}`,source:previous.id,target:current.id,label:current.step.node_ids.includes('experiment')?'通过假说审查时':undefined,optional:current.step.node_ids.includes('experiment')});
  }
  const confirmation=nodes.find(node=>node.step.node_ids.includes('confirmation'));
  const experiment=nodes.find(node=>node.step.node_ids.includes('experiment'));
  const analysis=nodes.find(node=>node.step.node_ids.includes('analyst'));
  if(confirmation?.arranged&&experiment) {
   edges.push({id:'path-confirmation',source:experiment.id,target:confirmation.id,label:'满足确认条件时',optional:true});
   if(analysis)edges.push({id:'path-confirmation-result',source:confirmation.id,target:analysis.id,label:'确认结果',optional:true});
  }
  const loop=nodes.find(node=>node.step.node_ids.includes('loop'));
  const input=nodes.find(node=>node.stage==='data');
  if(loop&&input&&Number(source?.settings.max_rounds??1)>1)edges.push({id:'path-next-round',source:loop.id,target:input.id,label:'有下一批且预算允许',loop:true});
  const task=nodes.find(node=>node.step.node_ids.includes('evaluate'));
  const last=loop??main.at(-1);
  if(task?.arranged&&last)edges.push({id:'path-task',source:last.id,target:task.id,label:'结束研究后 · 独立题集',optional:true});
 }
 return {view,nodes,edges};
}
