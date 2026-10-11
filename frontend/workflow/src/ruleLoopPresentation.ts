import type {PathNode,PathEdge,PathPortSide} from './ResearchPathCanvas';
import type {Run,Workflow} from './types';
export type RuleLoopStage='input'|'initialize'|'verify'|'feedback'|'revise'|'accept'|'challenge'|'save';
export const ruleLoopLabels:Record<RuleLoopStage,string>={input:'研究题池',initialize:'初始规则',verify:'程序验证',feedback:'错题反馈',revise:'修订规则',accept:'不退步验收',challenge:'新题挑战',save:'保存最好 KB'};
export const ruleLoopDescriptions:Record<RuleLoopStage,string>={
 input:'选择 Dataset · 固定题目版本',initialize:'导入 KB，或由模型提出',
 verify:'程序作答 · 封存后评分',feedback:'错题、冲突、未覆盖与规则反例',
 revise:'模型根据完整反馈提出补丁',accept:'同池回归 · 保护历史正确题',
 challenge:'出题并保留首测 · 整批加入题池',save:'已验收 KB、未解问题与停止原因',
};
const phases:Record<string,RuleLoopStage>={baseline:'verify',ready:'verify',candidate_check:'verify',first_test:'verify',initialize:'initialize',revise:'revise',accept:'accept',challenge:'challenge',promote:'input',finish:'save'};
export function rulePhaseStage(phase?:string):RuleLoopStage|undefined{return phase?phases[phase]:undefined;}

/** This is a controller overview. It never becomes the frozen material DAG. */
export function ruleLoopPresentation({workflow,run}:{workflow?:Workflow;run?:Run}):{nodes:PathNode[];edges:PathEdge[]}{
 const positions:Record<RuleLoopStage,{x:number;y:number}>={input:{x:0,y:0},initialize:{x:270,y:0},verify:{x:0,y:160},feedback:{x:270,y:160},revise:{x:540,y:160},accept:{x:540,y:320},challenge:{x:0,y:320},save:{x:270,y:320}};
 const nodes:PathNode[]=(Object.keys(ruleLoopLabels) as RuleLoopStage[]).map(id=>({
  id,label:ruleLoopLabels[id],description:ruleLoopDescriptions[id],position:positions[id],
  stage:id==='input'?'data':id==='save'?'kb':'harness',
  kind:id==='revise'||id==='initialize'&&!run&&workflow?.nodes.find(n=>n.id===id)?.config.mode==='model'?'model':id==='accept'?'decision':'program',
  inputs:[],outputs:[],inputSides:{},outputSides:{},
 }));
 const edges:PathEdge[]=[];
 const connect=(source:RuleLoopStage,target:RuleLoopStage,label:string,sourceSide:PathPortSide,targetSide:PathPortSide,loop=false)=>{
  const id=`overview-${source}-${target}`,out=id+'-out',input=id+'-in';
  const from=nodes.find(n=>n.id===source)!,to=nodes.find(n=>n.id===target)!;
  from.outputs!.push(out);from.outputSides![out]=sourceSide;to.inputs!.push(input);to.inputSides![input]=targetSide;
  edges.push({id,source,target,label,sourceHandle:out,targetHandle:input,loop});
 };
 connect('input','verify','公开题目','bottom','top');
 connect('initialize','verify','当前规则','left','right');
 connect('verify','feedback','需要修订','right','left');
 connect('feedback','revise','完整反馈','right','left');
 connect('revise','accept','候选 KB','bottom','top');
 connect('accept','verify','通过更新 · 拒绝保留','bottom','left',true);
 connect('verify','challenge','题池通过再出题','bottom','top');
 connect('challenge','verify','入池','left','left',true);
 connect('accept','save','停止','left','right');
 connect('challenge','save','新批达标','right','left');
 if(run){
  const events=[...(run.events||[])].sort((a,b)=>(a.sequence??0)-(b.sequence??0));
  const phase=run.refinement?.phase??[...events].reverse().find(event=>event.phase)?.phase;
  const current=rulePhaseStage(phase);
  const active=nodes.find(node=>node.id===current);
  if(active){
   if(run.result)active.status=run.result.outcome==='target_reached'?'complete':['failed','uncertain'].includes(run.status)?run.status:'已停止';
   else if(['running','paused','failed','uncertain','interrupted','starting','queued','stopping','cancelled'].includes(run.status))active.status=({starting:'准备中',queued:'排队中',stopping:'正在停止',cancelled:'已取消'} as Record<string,string>)[run.status]??run.status;
  }
 }
 return {nodes,edges};
}
