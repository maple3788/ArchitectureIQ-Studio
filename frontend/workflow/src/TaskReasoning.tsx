import type {Json} from './types';
import {ruleConditions,ruleField,sourceStatus} from './ruleKnowledgePresentation';
import {candidateParameterValue} from './candidateParameterValue';
import {readableName} from './displayNames';
import './task-reasoning.css';

const rows=(value:unknown):Json[]=>Array.isArray(value)?value.filter(row=>row&&typeof row==='object'):[];
const candidate=(value:Json)=>value?.letter?`候选 ${value.letter}`:value?.id||'未记录候选';
const printable=(value:unknown):string=>typeof value==='number'&&Number.isFinite(value)?String(Number.isInteger(value)?value:Number(value.toPrecision(12))):candidateParameterValue(value);
function qualification(value:Json){
 const status=value.source_status;
 if(status==='candidate')return '来源标记：候选知识 · 待验证';
 if(status==='verified')return '来源标记：已验证 · 按原适用范围使用';
 if(status==='suspect')return '来源标记：存疑';
 if(status==='retired')return '来源标记：已停用';
 return sourceStatus(value);
}

const object=(value:unknown):Json=>value&&typeof value==='object'&&!Array.isArray(value)?value as Json:{};
function parsed(value:unknown):Json{try{return typeof value==='string'?object(JSON.parse(value)):object(value);}catch{return {};}}
const kbIdentity=(kb:Json)=>kb?.id?`${kb.id}${kb.version?`@${kb.version}`:''}`:'KB 标识未记录';
const kbLabel=(kb:Json)=>readableName(kb?.name,'已保存的知识版本');
const ruleName=(rule:Json)=>Array.isArray(rule.claim_ids)&&rule.claim_ids.length?rule.claim_ids.join('、'):rule.rule_id;
function pathSource(path:Json,edges:Json[]){
 const matching=edges.filter(edge=>(!path.kb_id||edge.kb?.id===path.kb_id)&&(!path.kb_version||edge.kb?.version===path.kb_version));
 const identities=[...new Set(matching.map(edge=>kbIdentity(edge.kb)))];
 const names=rows(path.rule_refs).map(ref=>{
  const rules=matching.flatMap(edge=>rows(edge.rules)).filter(rule=>rule.rule_id===ref.rule_id&&rule.revision===ref.revision);
  // Older paths omit KB versions. Keep the stored rule id if more than one
  // version could own it, instead of joining unrelated claims under one name.
  return identities.length===1?[...new Set(rules.map(ruleName))].join('、')||ref.rule_id:ref.rule_id;
 });
 return {label:identities.length===1?kbLabel(matching[0]?.kb):path.kb_id?'KB 版本归属未记录':'KB 归属未记录',names:[...new Set(names)].join(' · ')};
}
function frozenChoice(reference:Json,question:Json):Json|undefined{
 const choices=rows((question.public??question).choices);
 const matches=reference?.id?choices.filter(choice=>choice.id===reference.id):reference?.letter?choices.filter(choice=>choice.letter===reference.letter):[];
 if(matches.length!==1)return undefined;
 const choice=matches[0];
 return reference.letter&&choice.letter&&reference.letter!==choice.letter?undefined:choice;
}
function candidateFacts(choice:Json):Array<[string,unknown]>{
 const view=object(choice.view),model=parsed(view.arch_key),optimizer=parsed(view.opt_key),loss=parsed(view.loss_key);
 const recorded=(source:Json,key:string,fallback:unknown)=>Object.hasOwn(source,key)?source[key]:fallback;
 const facts:Array<[string,unknown]>=[
  ['模型类型',recorded(model,'type',view.model_type)],['隐藏层深度',recorded(model,'depth',view.depth)],
  ['层数',recorded(model,'num_layers',view.num_layers)],['宽度',recorded(model,'width',view.width)],
  ['表示维度',recorded(model,'d_model',view.d_model)],['逐层归一化',recorded(model,'layer_norm',view.layer_norm)],
  ['残差连接',recorded(model,'residual',view.residual)],['优化器',recorded(optimizer,'type',view.opt)],
  ['学习率',recorded(optimizer,'lr',view.lr)],['动量',recorded(optimizer,'momentum',view.momentum)],['激活函数',recorded(model,'activation',view.activation)],
  ['损失函数',recorded(loss,'loss_id',loss.type)],['累计处理量',view.budget],['训练步数',view.steps],['批大小',view.batch_size],
 ];
 const scalar=(value:unknown)=>['string','number','boolean'].includes(typeof value);
 return facts.filter(([,value])=>scalar(value)||Array.isArray(value)&&value.every(scalar)).slice(0,9);
}
function FrozenCandidate({reference,question}:{reference:Json;question:Json}){
 const choice=frozenChoice(reference,question),facts=choice?candidateFacts(choice):[];
 return <section className="task-frozen-candidate" aria-label={`${candidate(reference)} 的冻结配置`}>
  <b>{candidate(reference)}</b>{choice?<>{facts.length?<dl>{facts.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{printable(value)}</dd></div>)}</dl>:<p>冻结公开题面未记录候选配置摘要。</p>}</>:<p>冻结题面中未找到一致的候选标识。</p>}
 </section>;
}
function ConditionResult({value,leaf=false}:{value:unknown;leaf?:boolean}){
 const text=leaf?(value===true?'子条件满足':value===false?'子条件不满足':'子条件判定未记录'):(value===true?'整体条件成立':value===false?'整体条件不成立':'整体判定未记录');
 return <span className={`task-condition-result ${value===true?'is-passed':value===false?'is-failed':'is-unknown'}`}>{text}</span>;
}
const operators:Record<string,string>={eq:'=',ne:'≠',lt:'<',le:'≤',gt:'>',ge:'≥',in:'属于',nin:'不属于'};
function expectedCheck(fact:Json){return fact.operator&&fact.expected!==undefined?`${operators[fact.operator]||fact.operator} ${printable(fact.expected)}`:'';}

export function RuleReasoning({value,question}:{value:Json;question?:Json}){
 const edges=rows(value.edges),paths=rows(value.paths),conflicts=rows(value.conflicts),uncovered=rows(value.uncovered_pairs);
 return <section className="task-reasoning" aria-label="规则推导依据"><h4>答案如何得出</h4><p className="task-reasoning-summary">{value.summary}</p>
  {paths.length>0&&<div className="task-deduction-paths"><span>推导路径</span>{paths.map((path,index)=>{const source=pathSource(path,edges);return <div key={index}><strong>{rows(path.candidates).map(item=>item.letter||item.id).join(' → ')}</strong><small><span>{source.names}</span><span>{source.label}</span></small></div>;})}</div>}
  {conflicts.length>0&&<div className="task-reasoning-gap"><b>存在冲突</b>{conflicts.map((conflict,index)=><p key={index}>{rows(conflict.candidates).map(candidate).join(' ↔ ')}</p>)}</div>}
  {uncovered.length>0&&<div className="task-reasoning-gap"><b>尚未覆盖的比较</b>{uncovered.map((pair,index)=><p key={index}>{rows(pair).map(candidate).join(' / ')}</p>)}</div>}
  <div className="task-reasoning-edges">{edges.map((edge,index)=><section className="task-deduction-edge" key={index}>
   <header><div><span className="task-comparison-number">比较 {index+1}</span><h5>{candidate(edge.winner)} 优于{candidate(edge.loser)}</h5></div><div className="task-comparison-kb"><span>{kbLabel(edge.kb)}</span></div></header>
   {question&&<div className="task-comparison-candidates"><FrozenCandidate reference={edge.winner} question={question}/><FrozenCandidate reference={edge.loser} question={question}/></div>}
   {rows(edge.rules).map((rule,ruleIndex)=><article className="task-deduction-rule" key={`${rule.rule_id}:${ruleIndex}`}>
    <section className="task-rule-step"><h6>1 · 采用这条知识</h6><div className="task-rule-identity"><b>{ruleName(rule)}</b><small>{qualification(rule)}</small></div><p className="task-deduction-text">{rule.text}</p></section>
    <section className="task-rule-step"><h6>2 · 检查适用条件</h6>{rows(rule.conditions).length>0?<div className="task-condition-list">{rows(rule.conditions).map((condition,conditionIndex)=><section key={conditionIndex}>
     <div className="task-condition-heading"><b>{condition.label}</b><ConditionResult value={condition.passed}/></div>{condition.expression&&<p>{condition.expression}</p>}
     {condition.field&&<p>{ruleField(condition.field)}{condition.expected!==undefined?` · 要求 ${expectedCheck(condition)||printable(condition.expected)}`:''}</p>}
     {rows(condition.facts).length>0?<><p className="task-condition-note">整体结果以完整表达式为准；以下分别列出子条件结果。</p><PairValues facts={rows(condition.facts)} winner={edge.winner} loser={edge.loser} leafChecks/></>:('winner_value' in condition||'loser_value' in condition)?<PairValues facts={[condition]} winner={edge.winner} loser={edge.loser}/>:null}
     {condition.ratio!=null&&<small>实际比值 {printable(condition.ratio)}</small>}
    </section>)}</div>:<p className="task-condition-note">这份执行记录未保存适用条件明细。</p>}</section>
    <section className="task-rule-step"><h6>3 · 应用规则比较候选</h6><p>{rule.prediction?.label}</p>
     {rows(rule.prediction?.fields).length>0&&<PairValues facts={rows(rule.prediction.fields)} winner={edge.winner} loser={edge.loser} prediction/>}
     {(rule.prediction?.winner_condition||rule.prediction?.loser_condition)&&<div className="task-role-conditions">{[['winner_condition',edge.winner],['loser_condition',edge.loser]].map(([key,who])=>{const condition=rule.prediction[key as string];return condition?<section key={key as string}>
      <div className="task-condition-heading"><b>{candidate(who as Json)} 的判定条件</b><ConditionResult value={condition.passed}/></div><p>{condition.expression}</p><dl>{rows(condition.facts).map((fact,i)=><div key={i}><dt>{ruleField(fact.field)}<small>{expectedCheck(fact)}</small></dt><dd><span>{printable(fact.value)}</span><ConditionResult value={fact.passed} leaf/></dd></div>)}</dl>
     </section>:null;})}</div>}
    </section>
    <details className="task-disclosure task-rule-record"><summary>原规则与来源记录</summary><p>知识库记录：<code>{kbIdentity(edge.kb)}</code></p><p>执行条款：{rule.rule_id}{rule.clause_index!=null?` · 第 ${rule.clause_index} 条`:''}</p><p>规则记录：{rule.revision}</p><pre>{JSON.stringify({source_refs:rule.source_refs,source_revision:rule.source_revision,validated_scope:rule.validated_scope,conditions:rule.conditions,prediction:rule.prediction},null,2)}</pre></details>
   </article>)}
  </section>)}</div>
 </section>;
}
function PairValues({facts,winner,loser,prediction=false,leafChecks=false}:{facts:Json[];winner:Json;loser:Json;prediction?:boolean;leafChecks?:boolean}){
 return <div className="task-evidence-table"><table><thead><tr><th>公开条件</th><th>{candidate(winner)}</th><th>{candidate(loser)}</th></tr></thead><tbody>{facts.map((fact,index)=><tr key={index}><th>{ruleField(fact.field||'参数量')}<small>{prediction?(fact.direction==='higher'?'数值更高':fact.direction==='lower'?'数值更低':''):expectedCheck(fact)}</small></th><td><span>{printable(fact.winner_value)}</span>{leafChecks&&<ConditionResult value={fact.winner_passed} leaf/>}</td><td><span>{printable(fact.loser_value)}</span>{leafChecks&&<ConditionResult value={fact.loser_passed} leaf/>}</td></tr>)}</tbody></table>{prediction&&facts.filter(fact=>fact.min_ratio>1).map((fact,index)=><p className="task-ratio" key={index}>{ruleField(fact.field)}：要求比值至少 {fact.min_ratio} 倍{fact.ratio!=null?`，实际 ${printable(fact.ratio)} 倍`:''}。</p>)}</div>;
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
