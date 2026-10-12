import {useEffect,useState} from 'react';
import {BookOpen} from 'lucide-react';
import {api} from './api';
import type {HumanReviewSource} from './HumanQuestionPractice';
import type {Json} from './types';

type Props={source:HumanReviewSource;knowledgeRef?:{id:string;version:string}};
export function QuestionApplicableKnowledge(props:Props){
 return <ApplicableReading key={JSON.stringify([props.source,props.knowledgeRef])} {...props}/>;
}
function ApplicableReading({source,knowledgeRef}:Props){
 const [data,setData]=useState<Json>(),[error,setError]=useState('');
 const identity=JSON.stringify([source,knowledgeRef]);
 useEffect(()=>{
  let active=true;
  void api<Json>('/questions/applicable-knowledge',{source,...(knowledgeRef?{knowledge_ref:knowledgeRef}:{})}).then(value=>{if(active)setData(value);}).catch(caught=>{if(active)setError((caught as Error).message);});
  return()=>{active=false;};
 },[identity]);
 const matches:Array<{kb:Json;rules:Json[]}>=data?.items??[];
 return <section className="question-applicable-knowledge" aria-label="适用于本题的 KB">
  <header><BookOpen size={18}/><h3>适用于本题的 KB</h3>{data&&<span>{data.total??matches.length} 组</span>}</header>
  {!data&&!error&&<p className="question-reader-note" role="status">正在检查规则适用条件…</p>}
  {error&&<p className="question-reader-note" role="status">暂时无法读取适用知识：{error}</p>}
  {data?.notice&&<p className="question-reader-note">{data.notice}</p>}
  {data&&!matches.length&&!data.notice&&<p className="question-reader-note">当前没有满足条件的规则。</p>}
  {matches.map(item=><div className="question-applicable-group" key={`${item.kb.id}@${item.kb.version}`}>
   <div className="question-applicable-source"><span>{item.kb.name||'规则知识'}</span><small>{item.kb.source_kind==='knowledge_evolution'?'知识演化 · 研究候选':item.kb.verification==='per_rule_scope'?'范围内已验证':'研究假设 · 尚未独立验证'}</small></div>
   {item.rules.map((rule,index)=><details className="question-applicable-rule" key={`${rule.rule_id}:${rule.revision}:${index}`} open={index===0}>
    <summary><span>{rule.text||rule.rule_id}</span></summary>
    <div><h4>适用条件</h4>{rule.conditions?.map((condition:string,i:number)=><p key={i}>{condition}</p>)}
     {!!rule.matched_pairs?.length&&<><h4>本题为何匹配</h4>{rule.matched_pairs.map((pair:Json,i:number)=><div className="question-applicable-pair" key={i}><span>{pair.candidates?.map((candidate:Json)=>candidate.letter?`候选 ${candidate.letter}`:'来源候选').join('、')}</span><ul>{pair.reasons?.map((reason:string,j:number)=><li key={j}>{reason}</li>)}</ul></div>)}</>}
     <details className="question-reader-parameter-help"><summary>知识版本与规则标识</summary><p>{item.kb.version} · {rule.rule_id} · {rule.revision}</p></details>
    </div>
   </details>)}
  </div>)}
 </section>;
}
