import {useState} from 'react';
import {Tabs,Field,ErrorBox,Loading,useResource,JsonView} from './ui';
import {RuleCaseEvidence} from './RuleRefinementRun';
import type {KBRef} from './ruleRefinementTypes';
import type {Json} from './types';
import './rule-refinement.css';
export function RuleKnowledgeReader({kbRef,runId,onEvaluate,record}:{kbRef:KBRef;runId?:string;onEvaluate?:(ref:KBRef)=>void;record?:Json}){
 const inventory=useResource<{items:Json[]}>(record?null:'/kb');const kb=record??inventory.data?.items.find(k=>k.id===kbRef.id&&k.version===kbRef.version);
 const source=runId??kb?.sources?.find((s:Json)=>s.kind==='run')?.id;const resource=useResource<Json>(source?'/runs/'+encodeURIComponent(source):null);
 const score=resource.data?.refinement?.score??resource.data?.result?.score;
 const [tab,setTab]=useState('知识'),[rule,setRule]=useState('all'),[question,setQuestion]=useState('');const rules=kb?.snapshot?.rules||[];
 const rows: [string,Json][]=Object.entries(score?.per_question||{});const applicable=rows.filter(([key])=>rule==='all'?Object.values(score?.per_rule||{}).some((r:any)=>r.question_keys?.includes(key)):score?.per_rule?.[rule]?.question_keys?.includes(key));
 const selected=applicable.some(([key])=>key===question)?question:applicable[0]?.[0];
 return <section className="rr-knowledge"><ErrorBox error={inventory.error||resource.error}/>{!kb?(inventory.loading?<Loading/>:<p>此规则版本不可用。</p>):<><p className="rr-status-note">研究规则 · 仅说明在已记录条件和批次上的表现。</p><p className="rr-version">版本 {kbRef.version} · 父版本 {kb.snapshot.parent_version||'初始副本'}</p>{onEvaluate&&<button onClick={()=>onEvaluate(kbRef)}>在 Task 中检查此规则 KB</button>}<Tabs tabs={['知识','适用题目']} value={tab} onChange={setTab}/>
 {tab==='知识'?<div>{rules.map((r:Json)=>{const evidence=score?.per_rule?.[r.rule_id];return <article className="rr-rule" key={r.rule_id}><small>{r.rule_id} · <span>{r.state==='retired'?'已退役':!evidence?'等待评分证据':!evidence.applicable?'尚未检验':evidence.wrong?'有反例':'已有研究记录'}</span></small><h3>{r.text||'未命名规则'}</h3>{r.rationale&&<p>{r.rationale}</p>}<p className="rr-version">规则修订 {r.revision?.slice(0,12)}{r.parents?.length?` · 来自 ${r.parents.map((p:Json)=>p.rule_id).join('、')}`:''}</p>{evidence?.applicable>0&&<p>直接关系：支持 {evidence.correct} · 反例 {evidence.wrong} · 无法判定 {evidence.unknown} · 涉及 {evidence.question_keys?.length??0} 道题</p>}<details><summary>执行条件与结论</summary><JsonView value={r.rule}/></details></article>;})}{!rules.length&&<p>当前 KB 为空，尚未提出有效规则。</p>}</div>:<div><div className="form-grid"><Field label="按规则查看"><select value={rule} onChange={e=>setRule(e.target.value)}><option value="all">全部已命中规则</option>{rules.map((r:Json)=><option key={r.rule_id} value={r.rule_id}>{r.text||r.rule_id}</option>)}</select></Field><Field label="适用题目"><select value={selected||''} onChange={e=>setQuestion(e.target.value)}>{applicable.map(([key,row],i)=><option key={key} value={key}>{i+1}. {row.case?.question?.id||key}</option>)}</select></Field></div>{selected?<RuleCaseEvidence row={score.per_question[selected]}/>:<p>当前保存的评分中没有适用题目。</p>}</div>}</>}
 </section>;
}
