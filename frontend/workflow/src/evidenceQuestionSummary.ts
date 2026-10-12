import {candidateListSummary,familyLabel} from './displayNames';
import type {Json} from './types';
const object=(value:unknown):Json=>{if(typeof value==='string'){try{return object(JSON.parse(value));}catch{return {};}}return value&&typeof value==='object'&&!Array.isArray(value)?value as Json:{};};
/** Reconstruct a brief only from recorded public features, never winner/GT fields. */
export function evidenceQuestionSummary(question:Json={}){
 const entries=Object.entries(object(question.candidates));
 const configs=entries.map(([id,raw])=>{
  const view=object(raw),model={...object(view.arch_key),...object(view.model)},optimizer={...object(view.opt_key),...object(view.optimizer)},loss={...object(view.loss_key),...object(view.loss)};
  for(const field of ['depth','width','num_layers','d_model','hidden_size','num_heads','activation','residual','layer_norm'])if(view[field]!==undefined&&model[field]===undefined)model[field]=view[field];
  if(model.type===undefined)model.type=view.model_type;
  if(optimizer.type===undefined)optimizer.type=view.opt;
  for(const field of ['lr','weight_decay','momentum','betas'])if(view[field]!==undefined&&optimizer[field]===undefined)optimizer[field]=view[field];
  return {letter:id,model,optimizer,loss};
 });
 const brief=candidateListSummary(configs,question.type);
 const candidates=brief.candidates.map((candidate,index)=>{
  const optimizer=configs[index].optimizer,extras:string[]=[];
  if(optimizer.type&&!candidate.label.includes(String(optimizer.type)))extras.push(String(optimizer.type));
  if(typeof optimizer.lr==='number'&&!candidate.label.includes('学习率'))extras.push(`学习率 ${optimizer.lr}`);
  return {id:candidate.letter,label:[candidate.label,...extras].join(' · ')};
 });
 const aliases=new Map(candidates.map(candidate=>[candidate.id,candidates.filter(other=>other.label===candidate.label).length>1?`${candidate.label}（${candidate.id}）`:candidate.label]));
 return {title:brief.title||familyLabel(question.family),description:`${familyLabel(question.family)} · 比较 ${entries.length} 个训练方案`,candidates,alias:(id:unknown)=>aliases.get(String(id))??`未记录配置（${String(id)}）`};
}
