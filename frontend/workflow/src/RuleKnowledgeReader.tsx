import {useState} from 'react';
import {Tabs,Field,ErrorBox,Loading,useResource,JsonView} from './ui';
import {RuleCaseEvidence} from './RuleRefinementRun';
import {RuleVersionSummary} from './RuleVersionSummary';
import {ruleConditions,ruleField,ruleGroups,sourceStatus} from './ruleKnowledgePresentation';
import type {KBRef} from './ruleRefinementTypes';
import type {Json} from './types';
import './rule-refinement.css';

function RuleClause({rule,evidence,index,multiple}:{rule:Json;evidence?:Json;index:number;multiple:boolean}){
 const status=rule.state==='retired'?'已退役':!evidence?'等待评分证据':!evidence.applicable?'尚未检验':evidence.wrong?'有反例':'已有研究记录';
 return <section className="rr-rule-clause">
  <div className="rr-rule-clause-heading">{multiple&&<b>分支 {index+1}</b>}<small>{status}</small></div>
  <dl className="rr-condition-list">{ruleConditions(rule.rule).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  {evidence&&evidence.applicable>0&&<p>直接关系：支持 {evidence.correct} · 反例 {evidence.wrong} · 无法判定 {evidence.unknown} · 涉及 {evidence.question_keys?.length??0} 道题</p>}
  <details><summary>执行条件与结论 · 完整记录</summary><p className="rr-version">{rule.rule_id} · 修订 {rule.revision?.slice(0,12)||'未记录'}{rule.parents?.length?` · 来自 ${rule.parents.map((p:Json)=>p.rule_id).join('、')}`:''}</p><JsonView value={rule}/></details>
 </section>;
}
function ModelReferencePolicy({metadata,label}:{metadata:Json;label?:string}){
 const referenceExcluded=['exploratory','descriptive'].includes(metadata.role);
 return <div>{label&&<small>{label}</small>}<p>{metadata.inject===false?'不注入模型；仍可按程序条件验证。':referenceExcluded?'仅作探索或描述记录，不用于模型参考。':metadata.validity_status!=='replicated_in_scope'||metadata.validation_origin!=='source_reported'?'待独立确认，不作为已复现知识供模型参考。':'来源允许参考；可预览公开题目的参考匹配，不改变程序判定。'}</p>{metadata.inject!==false&&!referenceExcluded&&Array.isArray(metadata.inject_same)&&<p className="muted">{metadata.inject_same.length?`参考时仅要求相同：${metadata.inject_same.map(ruleField).join('、')}；程序执行仍保留原条件。`:'参考时不要求保持相同字段；程序执行仍保留原条件。'}</p>}{metadata.usage_note&&<p className="rr-usage-note">{metadata.usage_note}</p>}</div>;
}
function RuleClaim({id,rules,score}:{id:string;rules:Json[];score?:Json}){
 const active=rules.filter(r=>r.state!=='retired'),first=active[0]??rules[0],metadata=first.metadata,hasLocal=active.some(r=>score?.per_rule?.[r.rule_id]);
 const statuses=[...new Set((active.length?active:rules).filter(r=>r.metadata).map(r=>sourceStatus(r.metadata)))];
 const policies=[...new Map(active.filter(r=>r.metadata).map(r=>[JSON.stringify([r.metadata.inject,r.metadata.inject_same,r.metadata.validity_status,r.metadata.validation_origin,r.metadata.role,r.metadata.usage_note]),r])).values()];
 return <article className="rr-rule">
  <div className="rr-claim-heading"><small>{id}</small>{statuses.map(status=><span className="rr-source-state" key={status}>{status}</span>)}</div>
  <h3>{first.text||'未命名规则'}</h3>
  {metadata&&!hasLocal&&<p className="muted">本平台尚未重新验证。</p>}
  {first.rationale&&<p>{first.rationale}</p>}
  {metadata?.parents?.length>0&&<p className="rr-claim-lineage">来自 {metadata.parents.join('、')}{metadata.operation?` · ${metadata.operation}`:''}</p>}
  <div className="rr-strict-rules"><h4>程序执行条件</h4>{rules.map((r,index)=><RuleClause key={r.rule_id} rule={r} index={index} multiple={rules.length>1} evidence={score?.per_rule?.[r.rule_id]}/>)}</div>
  {metadata&&<div className="rr-injection-policy"><h4>模型参考策略</h4>{!active.length?<p>规则已退役，不用于模型参考。</p>:policies.map(r=><ModelReferencePolicy key={r.rule_id} metadata={r.metadata} label={policies.length>1?r.rule_id:undefined}/>)}</div>}
  {metadata?.dev_evidence&&<details className="rr-development"><summary>来源开发证据</summary><p>{metadata.dev_evidence}</p><p className="muted">这是来源文档记录的证据，不计作本平台的独立确认结果。</p></details>}
 </article>;
}
export function RuleKnowledgeReader({kbRef,runId,onEvaluate,record}:{kbRef:KBRef;runId?:string;onEvaluate?:(ref:KBRef)=>void;record?:Json}){
 const inventory=useResource<{items:Json[]}>(record?null:'/kb');const kb=record??inventory.data?.items.find(k=>k.id===kbRef.id&&k.version===kbRef.version);
 const source=runId??kb?.sources?.find((s:Json)=>s.kind==='run')?.id;const resource=useResource<Json>(source?'/runs/'+encodeURIComponent(source):null);
 const score=resource.data?.refinement?.score??resource.data?.result?.score;
 const [tab,setTab]=useState('知识'),[rule,setRule]=useState('all'),[question,setQuestion]=useState('');const rules:Json[]=kb?.snapshot?.rules||[];
 const rows: [string,Json][]=Object.entries(score?.per_question||{});const applicable=rows.filter(([key])=>rule==='all'?Object.values(score?.per_rule||{}).some((r:any)=>r.question_keys?.includes(key)):score?.per_rule?.[rule]?.question_keys?.includes(key));
 const selected=applicable.some(([key])=>key===question)?question:applicable[0]?.[0];
 return <section className="rr-knowledge"><ErrorBox error={inventory.error||resource.error}/>{!kb?(inventory.loading?<Loading/>:<p>此规则版本不可用。</p>):<>
  <p className="rr-status-note">研究规则 · 仅说明在已记录条件和批次上的表现。</p>
  <RuleVersionSummary snapshot={kb.snapshot}/>
  {!kb.snapshot.source_document&&<p className="rr-version">版本 {kbRef.version} · 父版本 {kb.snapshot.parent_version||'初始副本'}</p>}
  {onEvaluate&&<button onClick={()=>onEvaluate(kbRef)}>在 Task 中检查此规则 KB</button>}
  <Tabs tabs={['知识','适用题目']} value={tab} onChange={setTab}/>
  {tab==='知识'?<div>{ruleGroups(rules).map(group=><RuleClaim key={group.id} {...group} score={score}/>)}{!rules.length&&<p>当前 KB 为空，尚未提出有效规则。</p>}</div>:<div><div className="form-grid"><Field label="按规则查看"><select value={rule} onChange={e=>setRule(e.target.value)}><option value="all">全部已命中规则</option>{rules.map((r:Json)=><option key={r.rule_id} value={r.rule_id}>{r.text||r.rule_id}{r.metadata?.claim_id?` · ${r.metadata.claim_id} 分支 ${r.metadata.clause_index??1}`:''}</option>)}</select></Field><Field label="适用题目"><select value={selected||''} onChange={e=>setQuestion(e.target.value)}>{applicable.map(([key,row],i)=><option key={key} value={key}>{i+1}. {row.case?.question?.id||key}</option>)}</select></Field></div>{selected?<RuleCaseEvidence row={score.per_question[selected]}/>:<p>当前保存的评分中没有适用题目。</p>}</div>}
 </>}</section>;
}
