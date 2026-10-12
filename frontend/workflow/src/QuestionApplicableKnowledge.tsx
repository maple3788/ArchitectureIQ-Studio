import {useEffect,useState} from 'react';
import {BookOpen} from 'lucide-react';
import {api} from './api';
import type {HumanReviewSource} from './HumanQuestionPractice';
import type {Json} from './types';

type Props={source:HumanReviewSource;knowledgeRef?:{id:string;version:string}};
type ApplicableSource={kb:Json;rule:Json};
function groupedMatches(items:Array<{kb:Json;rules:Json[]}>){
 const groups=new Map<string,{rule:Json;sources:ApplicableSource[]}>();
 const stable=(value:unknown):string=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
 for(const item of items)for(const rule of item.rules){
  // Display descriptions cannot establish equivalent execution or candidate identity.
  const complete=typeof rule.text==='string'&&!!rule.text.trim()&&rule.rule&&typeof rule.rule==='object'&&!Array.isArray(rule.rule)&&Object.keys(rule.rule).length>0
   &&Array.isArray(rule.matched_pairs)&&rule.matched_pairs.length>0&&rule.matched_pairs.every((pair:Json)=>Array.isArray(pair.candidates)&&pair.candidates.length===2&&pair.candidates.every((candidate:Json)=>typeof candidate.id==='string'&&!!candidate.id)&&Array.isArray(pair.reasons));
  const key=complete?stable({text:rule.text.trim(),rule:rule.rule,conditions:rule.conditions,matched_pairs:rule.matched_pairs,validity_status:rule.validity_status,verification:item.kb.verification}):`unmerged:${groups.size}`;
  if(!groups.has(key))groups.set(key,{rule,sources:[]});
  groups.get(key)!.sources.push({kb:item.kb,rule});
 }
 return [...groups.values()];
}
function candidateSummary(rule:Json){
 const pairs:string[]=(rule.matched_pairs??[]).map((pair:Json)=>(pair.candidates??[]).map((candidate:Json)=>candidate.letter??'来源候选').join('、'));
 return pairs.length?`适用候选：${[...new Set(pairs)].join('；')}`:'适用候选见公开匹配记录';
}
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
 const groups=groupedMatches(matches);
 return <section className="question-applicable-knowledge" aria-label="适用于本题的 KB">
  <header><BookOpen size={18}/><h3>适用于本题的 KB</h3>{data&&<span>{groups.length} 条</span>}</header>
  {!data&&!error&&<p className="question-reader-note" role="status">正在检查规则适用条件…</p>}
  {error&&<p className="question-reader-note" role="status">暂时无法读取适用知识：{error}</p>}
  {data?.notice&&<p className="question-reader-note">{data.notice}</p>}
  {data&&!matches.length&&!data.notice&&<p className="question-reader-note">当前没有满足条件的规则。</p>}
  {groups.map(({rule,sources},index)=><div className="question-applicable-group" key={`${rule.rule_id}:${rule.revision}:${index}`}>
   <details className="question-applicable-rule">
    <summary><span>{rule.text||rule.rule_id}</span><small>{candidateSummary(rule)}</small></summary>
    <div><h4>适用条件</h4>{rule.conditions?.map((condition:string,i:number)=><p key={i}>{condition}</p>)}
     {!!rule.matched_pairs?.length&&<><h4>本题为何匹配</h4>{rule.matched_pairs.map((pair:Json,i:number)=><div className="question-applicable-pair" key={i}><span>{pair.candidates?.map((candidate:Json)=>candidate.letter?`候选 ${candidate.letter}`:'来源候选').join('、')}</span><ul>{pair.reasons?.map((reason:string,j:number)=><li key={j}>{reason}</li>)}</ul></div>)}</>}
     <h4>知识来源与版本</h4>{sources.map(({kb,rule:saved},sourceIndex)=><div key={`${kb.id}:${kb.version}:${saved.rule_id}:${sourceIndex}`}>
      <div className="question-applicable-source"><span>{kb.name||'规则知识'}</span><small>{kb.verification==='per_rule_scope'?'范围内已验证':'研究假设 · 尚未独立验证'}</small></div>
      {saved.source_status&&<p>演化来源状态：{saved.source_status}</p>}<p>{kb.version} · {saved.rule_id} · {saved.revision}</p>
     </div>)}
    </div>
   </details>
  </div>)}
 </section>;
}
