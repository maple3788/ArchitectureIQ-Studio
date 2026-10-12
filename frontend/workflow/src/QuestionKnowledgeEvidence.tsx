import {useState} from 'react';
import {ArrowUpRight,BookOpen} from 'lucide-react';
import {ErrorBox,Loading,useResource} from './ui';
import {ruleConditions} from './ruleKnowledgePresentation';
import {claimStateLabels,type EvolutionClaim,type EvolutionTaskContext} from './knowledgeEvolutionState';
import type {Json} from './types';
import './question-knowledge-evidence.css';

type EvidenceClaim={claim:EvolutionClaim;relation:string;current_evidence:Json[];counterexamples:{items:Json[];total:number|null;truncated:boolean};evidence_total:number;evidence_truncated:boolean};
type EvidenceView={question_id:string;claims:EvidenceClaim[];notice?:string};
type Props={id:string;record:Json;context:EvolutionTaskContext;onQuestion?:(id:string,context:EvolutionTaskContext)=>void};
const rows=(value:unknown):Json[]=>Array.isArray(value)?value.filter(row=>row&&typeof row==='object'):[];

/** Research-only evidence. These stored outcomes never enter a Task seed or public question. */
export function QuestionKnowledgeEvidence(props:Props){
 const {id,context}=props;
 const query=new URLSearchParams({source_identity:context.observation.source_identity,sequence:String(context.observation.sequence)});
 if(context.claim_ref){query.set('claim_id',context.claim_ref.id);query.set('claim_version',String(context.claim_ref.version));}
 const path=`/kb-loop/questions/${encodeURIComponent(id)}/evidence?${query}`;
 return <EvidenceReader key={path} {...props} path={path}/>;
}

function EvidenceReader({id,record,context,onQuestion,path}:Props&{path:string}){
 const [retry,setRetry]=useState(0),[selected,setSelected]=useState('');
 const result=useResource<EvidenceView>(path,retry);
 const claims=rows(result.data?.claims).filter(entry=>entry.claim&&Array.isArray(entry.current_evidence)) as EvidenceClaim[];
 const selectedClaim=claims.find(entry=>entry.claim.id===selected)??claims[0];
 return <section className="question-knowledge" aria-label="KB 与题目对照">
  <header className="question-knowledge-heading"><BookOpen size={17}/><h3>KB 与题目对照</h3></header>
  <p className="question-knowledge-caption">同一份研究记录中的规则、验证结果与反例。</p>
  {result.loading?<Loading/>:result.error?<><ErrorBox error={result.error}/><button className="loop-show-more" onClick={()=>setRetry(value=>value+1)}>重新读取知识证据</button></>:<>
   {claims.length>1&&<label className="question-knowledge-select">对照知识<select aria-label="对照知识" value={selectedClaim?.claim.id??''} onChange={event=>setSelected(event.target.value)}>{claims.map(entry=><option key={entry.claim.id} value={entry.claim.id}>{entry.claim.id} · {claimStateLabels[entry.claim.status]??entry.claim.status}{entry.current_evidence.some(row=>row.outcome==='refute')?' · 本题有反例':''}</option>)}</select></label>}
   {selectedClaim?<KnowledgeComparison key={`${selectedClaim.claim.id}-${selectedClaim.claim.version}`} value={selectedClaim} id={id} record={record} onQuestion={onQuestion?questionId=>onQuestion(questionId,{observation:{...context.observation},claim_ref:{id:selectedClaim.claim.id,version:selectedClaim.claim.version}}):undefined}/>:<p className="question-knowledge-empty">这份记录尚未关联本题的 KB。完成验证后可从新记录中查看。</p>}
   {result.data?.notice&&<p className="question-knowledge-caption">{result.data.notice}</p>}
  </>}
 </section>;
}

function KnowledgeComparison({value,id,record,onQuestion}:{value:EvidenceClaim;id:string;record:Json;onQuestion?:(id:string)=>void}){
 const {claim,counterexamples}=value;
 const [visible,setVisible]=useState(4);
 const evidence=rows(value.current_evidence),examples=rows(counterexamples?.items);
 // Bind only exact candidate IDs; evidence ordering is not the public answer order.
 const choices=rows(record.public?.choices);
 const aliases=new Map<string,string>();
 for(const choice of choices){
  const matching=choices.filter(other=>other.id===choice.id);
  if(choice.id&&choice.letter&&matching.length===1)aliases.set(String(choice.id),String(choice.letter));
 }
 const alias=(candidate:unknown)=>aliases.get(String(candidate))??`来源 ${String(candidate)}`;
 const pairs=evidence.flatMap(row=>(Array.isArray(row.pairs)?row.pairs:[]).filter((pair:unknown)=>Array.isArray(pair)&&pair.length>=2).map((pair:unknown[])=>({pair,round:row.round})));
 const unmapped=pairs.some(({pair})=>!aliases.has(String(pair[0]))||!aliases.has(String(pair[1])));
 const count=counterexamples?.total;
 const conflicts=evidence.reduce((sum,row)=>sum+(typeof row.conflicts==='number'?row.conflicts:0),0);
 return <article className="question-knowledge-claim">
  <div className="question-knowledge-identity"><strong>{claim.id}</strong><span className={`evolution-claim-status is-${claim.status}`}>{claimStateLabels[claim.status]??claim.status}</span></div>
  <p className="question-knowledge-text">{claim.text}</p>
  {(claim.needs_revision||claim.consistency?.consistent===false)&&<p className="question-knowledge-warning">{claim.needs_revision?'待修订。':'文字与规则需要复核。'}{claim.consistency?.issue}</p>}
  <div className="question-knowledge-rules">{rows(claim.rules).map((rule,index)=>{
   let conditions:[string,string][]=[];try{conditions=ruleConditions(rule);}catch{/* Keep the saved rule inspectable. */}
   return <section key={index} aria-label={`${claim.id} 执行分支 ${index+1}`}>
    {claim.rules.length>1&&<h4>执行分支 {index+1}</h4>}
    {conditions.length?<dl>{conditions.map(([label,text],i)=><div key={i}><dt>{label}</dt><dd>{text}</dd></div>)}</dl>:<p className="question-knowledge-caption">此规则尚未转换为阅读形式，请查看原规则。</p>}
    <details><summary>原规则</summary><pre>{JSON.stringify(rule,null,2)}</pre></details>
   </section>;
  })}</div>
  <section className="question-knowledge-verdict" aria-label={`${claim.id} 本题证据`}><h4>本题验证</h4>
   {evidence.length?<>
    <div className="question-knowledge-verdicts">{evidence.map((row,index)=><span className={row.outcome==='refute'?'is-refute':'is-neutral'} key={index}>第 {row.round} 轮 · {row.outcome==='refute'?'出现反例':row.outcome==='support'?'支持规则':'待判定'}</span>)}</div>
    {pairs.length>0&&<table aria-label={`${claim.id} 本题验证结果`}><thead><tr><th>规则预测</th><th>存储结果</th><th>检验</th></tr></thead><tbody>{pairs.map(({pair,round},index)=><tr key={index} className={pair[2]===false?'is-refute':''}><td>{pair[2]===true?`${alias(pair[0])} 优于 ${alias(pair[1])}`:pair[2]===false?`${alias(pair[1])} 优于 ${alias(pair[0])}`:'未记录'}</td><td>{alias(pair[0])} 优于 {alias(pair[1])}</td><td>{pair[2]===false?'反例':pair[2]===true?'支持':'待判定'}{evidence.length>1&&<small>第 {round} 轮</small>}</td></tr>)}</tbody></table>}
    {unmapped&&<p className="question-knowledge-caption">部分来源候选无法对应本题选项，保留来源标识。</p>}
    {conflicts>0&&<p className="question-knowledge-warning">{conflicts} 个内部冲突的比较已由来源跳过。</p>}
   </>:<p className="question-knowledge-empty">{value.relation==='target'?'本题为这条知识的定向检验题；':''}该快照尚无本题验证记录，不能据此判断规则是否适用。</p>}
  </section>
  <section className="question-knowledge-counterexamples" aria-label={`${claim.id} 反例`}><div><h4>反例</h4><span>{typeof count==='number'?`${count} 道题`:'数量待核实'}</span></div>
   {examples.length?<ul>{examples.slice(0,visible).map((row,index)=>{
    const failures=(Array.isArray(row.pairs)?row.pairs:[]).filter((pair:unknown)=>Array.isArray(pair)&&pair[2]===false).length;
    const content=<><span><strong>{row.question_id}{row.question_id===id?' · 本题':''}</strong><small>第 {row.round} 轮{failures?` · ${failures} 组比较与规则不符`:''}</small></span>{onQuestion&&row.question_id!==id&&<ArrowUpRight size={14}/>}</>;
    return <li key={`${row.question_id}-${row.round}-${index}`}>{onQuestion&&row.question_id!==id?<button aria-label={`阅读反例 ${row.question_id}`} onClick={()=>onQuestion(row.question_id)}>{content}</button>:<div>{content}</div>}</li>;
   })}</ul>:<p className="question-knowledge-empty">{counterexamples?.truncated?'反例记录不完整，暂时没有可展示的条目。':count===0?'这份记录中尚无反例。':'尚未保存可展示的反例记录。'}</p>}
   {examples.length>visible&&<button className="loop-show-more" onClick={()=>setVisible(number=>number+12)}>查看其余 {examples.length-visible} 条反例</button>}
   {counterexamples?.truncated&&examples.length>0&&<p className="question-knowledge-caption">仅列出已保存的 {examples.length} 条，反例记录不完整。</p>}
  </section>
 </article>;
}
