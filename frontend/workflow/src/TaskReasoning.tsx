import type {Json} from './types';
import {ruleConditions,ruleField,sourceStatus} from './ruleKnowledgePresentation';
import './task-reasoning.css';

const rows=(value:unknown):Json[]=>Array.isArray(value)?value.filter(row=>row&&typeof row==='object'):[];
const candidate=(value:Json)=>value?.letter?`候选 ${value.letter}`:value?.id||'未记录候选';
const printable=(value:unknown):string=>value===undefined||value===null?'未记录':value===true?'是':value===false?'否':typeof value==='number'&&Number.isFinite(value)?String(Number.isInteger(value)?value:Number(value.toPrecision(12))):typeof value==='object'?JSON.stringify(value):String(value);
function qualification(value:Json){
 const status=value.source_status;
 if(status==='candidate')return '来源标记：候选知识 · 待验证';
 if(status==='verified')return '来源标记：已验证 · 按原适用范围使用';
 if(status==='suspect')return '来源标记：存疑';
 if(status==='retired')return '来源标记：已停用';
 return sourceStatus(value);
}

export function RuleReasoning({value}:{value:Json}){
 const edges=rows(value.edges),paths=rows(value.paths),conflicts=rows(value.conflicts),uncovered=rows(value.uncovered_pairs);
 const claimNames=new Map(edges.flatMap(edge=>rows(edge.rules).map(rule=>[`${rule.rule_id}@${rule.revision}`,Array.isArray(rule.claim_ids)&&rule.claim_ids.length?rule.claim_ids.join('、'):rule.rule_id] as [string,string])));
 return <section className="task-reasoning" aria-label="规则推导依据"><h4>答案如何得出</h4><p className="task-reasoning-summary">{value.summary}</p>
  {paths.length>0&&<div className="task-deduction-paths"><span>推导路径</span>{paths.map((path,index)=><div key={index}><strong>{rows(path.candidates).map(item=>item.letter||item.id).join(' → ')}</strong><small>{[...new Set(rows(path.rule_refs).map(ref=>claimNames.get(`${ref.rule_id}@${ref.revision}`)||ref.rule_id))].join(' · ')}</small></div>)}</div>}
  {conflicts.length>0&&<div className="task-reasoning-gap"><b>存在冲突</b>{conflicts.map((conflict,index)=><p key={index}>{rows(conflict.candidates).map(candidate).join(' ↔ ')}</p>)}</div>}
  {uncovered.length>0&&<div className="task-reasoning-gap"><b>尚未覆盖的比较</b>{uncovered.map((pair,index)=><p key={index}>{rows(pair).map(candidate).join(' / ')}</p>)}</div>}
  <div className="task-reasoning-edges">{edges.map((edge,index)=><section className="task-deduction-edge" key={index}><header><h5>{candidate(edge.winner)} 优于{candidate(edge.loser)}</h5><span>{edge.kb?.name}</span></header>{rows(edge.rules).map((rule,ruleIndex)=><article className="task-deduction-rule" key={`${rule.rule_id}:${ruleIndex}`}>
   <div className="task-rule-identity"><b>{Array.isArray(rule.claim_ids)&&rule.claim_ids.length?rule.claim_ids.join('、'):rule.rule_id}</b><small>{qualification(rule)}</small></div><p className="task-deduction-text">{rule.text}</p><p>{rule.prediction?.label}</p>
   {rows(rule.prediction?.fields).length>0&&<PairValues facts={rows(rule.prediction.fields)} winner={edge.winner} loser={edge.loser} prediction/>}
   {rows(rule.conditions).length>0&&<details className="task-disclosure"><summary>适用条件检查</summary><div className="task-condition-list">{rows(rule.conditions).map((condition,conditionIndex)=><section key={conditionIndex}><b>{condition.label}</b>{condition.expression&&<p>{condition.expression}</p>}{condition.field&&<p>{ruleField(condition.field)}{condition.expected!==undefined?` · 要求 ${printable(condition.expected)}`:''}</p>}{rows(condition.facts).length>0?<PairValues facts={rows(condition.facts)} winner={edge.winner} loser={edge.loser}/>:('winner_value' in condition||'loser_value' in condition)?<PairValues facts={[condition]} winner={edge.winner} loser={edge.loser}/>:null}{condition.ratio!=null&&<small>实际比值 {printable(condition.ratio)}</small>}</section>)}</div></details>}
   {(rule.prediction?.winner_condition||rule.prediction?.loser_condition)&&<div className="task-role-conditions">{[['winner_condition',edge.winner],['loser_condition',edge.loser]].map(([key,who])=>{const condition=rule.prediction[key as string];return condition?<section key={key as string}><b>{candidate(who as Json)} 的判定条件</b><p>{condition.expression}</p><dl>{rows(condition.facts).map((fact,i)=><div key={i}><dt>{ruleField(fact.field)}</dt><dd>{printable(fact.value)}</dd></div>)}</dl></section>:null;})}</div>}
   <details className="task-disclosure task-rule-record"><summary>原规则与来源记录</summary><p>执行条款：{rule.rule_id}{rule.clause_index!=null?` · 第 ${rule.clause_index} 条`:''}</p><p>规则记录：{rule.revision}</p><pre>{JSON.stringify({source_refs:rule.source_refs,source_revision:rule.source_revision,validated_scope:rule.validated_scope,conditions:rule.conditions,prediction:rule.prediction},null,2)}</pre></details>
  </article>)}</section>)}</div>
 </section>;
}
function PairValues({facts,winner,loser,prediction=false}:{facts:Json[];winner:Json;loser:Json;prediction?:boolean}){
 return <div className="task-evidence-table"><table><thead><tr><th>公开条件</th><th>{candidate(winner)}</th><th>{candidate(loser)}</th></tr></thead><tbody>{facts.map((fact,index)=><tr key={index}><th>{ruleField(fact.field||'参数量')}<small>{prediction?(fact.direction==='higher'?'数值更高':fact.direction==='lower'?'数值更低':''):fact.operator&&fact.expected!==undefined?`${({eq:'=',ne:'≠',lt:'<',le:'≤',gt:'>',ge:'≥',in:'属于',nin:'不属于'} as Record<string,string>)[fact.operator]||fact.operator} ${printable(fact.expected)}`:''}</small></th><td>{printable(fact.winner_value)}</td><td>{printable(fact.loser_value)}</td></tr>)}</tbody></table>{prediction&&facts.filter(fact=>fact.min_ratio>1).map((fact,index)=><p className="task-ratio" key={index}>{ruleField(fact.field)}：要求比值至少 {fact.min_ratio} 倍{fact.ratio!=null?`，实际 ${printable(fact.ratio)} 倍`:''}。</p>)}</div>;
}

export function ModelSources({result}:{result:Json}){
 if(!Array.isArray(result.provided_sources)&&!Array.isArray(result.used_sources))return null;
 const used=rows(result.used_sources),ids=new Set(used.map(item=>item.citation_id)),provided=rows(result.provided_sources).filter(item=>!ids.has(item.citation_id));
 return <div className="task-model-sources"><section aria-label="模型明确引用的知识"><h4>模型明确引用的知识</h4>{used.length?<><p className="task-muted">以下引用来自已保存的模型回答；引用本身不等同于程序验证。</p>{used.map((source,index)=><ModelSource key={source.citation_id||index} value={source}/>)}</>:<p className="task-muted">当前记录尚无可对应到已提供知识的模型引用。</p>}</section>{provided.length>0&&<details className="task-disclosure"><summary>提供给模型、未被引用的知识 · {provided.length} 条</summary>{provided.map((source,index)=><ModelSource key={source.citation_id||index} value={source}/>)}</details>}</div>;
}
function ModelSource({value}:{value:Json}){
 let conditions:[string,string][]=[];try{conditions=ruleConditions(value.rule);}catch{/* The immutable source record stays available below. */}
 return <article className="task-model-source"><header><b>{value.citation_id}</b>{Array.isArray(value.source_claim_ids)&&value.source_claim_ids.length>0&&<strong>{value.source_claim_ids.join('、')}</strong>}{value.source_status&&<small>{qualification(value)}</small>}</header><p>{value.text}</p>{conditions.length>0&&<dl>{conditions.map(([name,text],index)=><div key={index}><dt>{name}</dt><dd>{text}</dd></div>)}</dl>}{Array.isArray(value.matched_pairs)&&value.matched_pairs.length>0&&<small>适用比较：{value.matched_pairs.join('、')}</small>}<details className="task-disclosure"><summary>知识来源</summary>{rows(value.source_refs).map((source,index)=><p key={index}>{source.name} · {source.record_id} · 记录 {source.version}</p>)}<pre>{JSON.stringify({rule_sources:value.rule_sources,source_refs:value.source_refs},null,2)}</pre></details></article>;
}
export function SkippedRules({value}:{value:Json}){
 const skipped=rows(value.skipped_claims);if(!skipped.length)return null;
 const reasons:Record<string,string>={needs_revision:'待修订',source_flagged:'存疑',source_retired:'已停用',retired:'已停用',invalid_rule:'规则未通过校验',uncompiled:'无可执行规则',invalid_identity:'来源标识不完整',unknown_status:'来源状态未明确'};
 return <details className="task-disclosure task-skipped-rules"><summary>未参与的规则 · {skipped.length} 条</summary><p>这些来源规则保留在知识演化中，本次未用于解答。</p><dl>{skipped.map((rule,index)=><div key={index}><dt>{rule.claim_id||'未命名规则'}{rule.clause_index!=null?` · 第 ${rule.clause_index} 条`:''}</dt><dd>{reasons[rule.reason]||'暂不满足执行要求'}</dd></div>)}</dl></details>;
}
