import {useEffect,useState} from 'react';
import {ChevronLeft,ChevronRight,Search} from 'lucide-react';
import {QuestionReader} from './QuestionReader';
import {questionListSummary} from './displayNames';
import {Empty,ErrorBox,Loading,useResource} from './ui';
import type {KBRef} from './ruleRefinementTypes';
import type {Json} from './types';
import './knowledge-questions.css';

type Relation='applicable'|'inapplicable'|'unknown';
type QuestionMatch={key:string;id:string;family?:string;type?:string;relation:Relation;reason:{code:string;message:string};prediction_status:string|null;matched_rules:number;matched_pairs:number};
type Matches={kb_ref:KBRef;claim_id:string;items:QuestionMatch[];counts:Record<Relation,number>;total:number;offset:number;limit:number;scope:string;notice:string};
type Props={kbRef:KBRef;claimId:string;relation:'applicable'|'inapplicable'};
const labels:Record<Relation,string>={applicable:'适用',inapplicable:'不适用',unknown:'待判断'};

export function KnowledgeQuestions(props:Props){
 return <QuestionQuery key={JSON.stringify([props.kbRef,props.claimId,props.relation])} {...props}/>;
}
function QuestionQuery({kbRef,claimId,relation}:Props){
 const [filter,setFilter]=useState<Relation>(relation),[draft,setDraft]=useState(''),[search,setSearch]=useState(''),[offset,setOffset]=useState(0);
 useEffect(()=>{if(draft.trim()===search)return;const timer=setTimeout(()=>{setSearch(draft.trim());setOffset(0);},250);return()=>clearTimeout(timer);},[draft,search]);
 const query=new URLSearchParams({kb_id:kbRef.id,kb_version:kbRef.version,claim_id:claimId,relation:filter,search,offset:String(offset),limit:'25'});
 const path=`/kb/questions?${query}`;
 return <div className="knowledge-questions">
  <div className="knowledge-questions-toolbar">
   <label className="knowledge-question-search"><Search size={16}/><input type="search" aria-label="搜索题目" placeholder="搜索题目 ID 或数据类型" value={draft} onChange={event=>setDraft(event.target.value)}/></label>
   <label className="knowledge-question-filter">题目状态<select aria-label="题目状态" value={filter} onChange={event=>{setFilter(event.target.value as Relation);setOffset(0);}}><option value={relation}>{labels[relation]}题目</option><option value="unknown">待判断</option></select></label>
  </div>
  <QuestionMatches key={path} path={path} filter={filter} offset={offset} onPage={setOffset}/>
 </div>;
}
function QuestionMatches({path,filter,offset,onPage}:{path:string;filter:Relation;offset:number;onPage:(offset:number)=>void}){
 const [retry,setRetry]=useState(0),[selected,setSelected]=useState('');
 const result=useResource<Matches>(path,retry);
 const data=result.data,rows=data?.items??[],current=rows.find(row=>row.key===selected)??rows[0];
 if(result.loading)return <Loading/>;
 if(result.error)return <><ErrorBox error={result.error}/><button className="secondary" onClick={()=>setRetry(value=>value+1)}>重新读取题目</button></>;
 return <>
  <div className="knowledge-question-counts" aria-label="题目判定数量">{(['applicable','inapplicable','unknown'] as Relation[]).map(relation=><span className={relation===filter?'is-current':''} key={relation}>{labels[relation]} <b>{data?.counts[relation]??'—'}</b></span>)}</div>
  <p className="knowledge-question-note">{data?.notice||'按公开条件检查规则适用性，不代表答案正确。'}{filter==='unknown'&&' 待判断题目单独保留，不计入不适用。'}</p>
  {!rows.length?<Empty title={`暂无${labels[filter]}题目`}>可以调整搜索，或查看其他题目状态。</Empty>:<div className="knowledge-question-workspace">
   <div className="knowledge-question-index"><nav aria-label={`${labels[filter]}题目列表`}>{rows.map(row=>{
    const summary=questionListSummary(row);
    return <button key={row.key} className={current?.key===row.key?'is-selected':''} aria-current={current?.key===row.key?'true':undefined} onClick={()=>setSelected(row.key)}><small>{row.id}</small><strong>{summary.title}</strong><span>{row.reason.message}</span></button>;
   })}</nav>
   {(data?.total??0)>25&&<div className="knowledge-question-pages"><button aria-label="上一页" disabled={offset===0} onClick={()=>onPage(Math.max(0,offset-25))}><ChevronLeft size={16}/></button><span>{Math.floor(offset/25)+1} / {Math.ceil((data?.total??0)/25)}</span><button aria-label="下一页" disabled={offset+25>=(data?.total??0)} onClick={()=>onPage(offset+25)}><ChevronRight size={16}/></button></div>}
   </div>
   {current&&<MatchedQuestion key={current.key} value={current}/>}
  </div>}
 </>;
}
function MatchedQuestion({value}:{value:QuestionMatch}){
 const [retry,setRetry]=useState(0);
 const record=useResource<Json>(`/tasks/questions/${encodeURIComponent(value.key)}`,retry);
 return <div className="knowledge-question-reading">
  <div className={`knowledge-question-reason is-${value.relation}`}><div><span>{value.id}</span><strong>{value.prediction_status==='conflict'?'规则冲突':`${labels[value.relation]}原因`}</strong></div><p>{value.reason.message}</p>{value.matched_rules>0&&<small>命中 {value.matched_rules} 条规则 · {value.matched_pairs} 组候选关系</small>}</div>
  {record.loading?<Loading/>:record.error?<><ErrorBox error={record.error}/><button className="secondary" onClick={()=>setRetry(number=>number+1)}>重新读取完整题目</button></>:record.data?<QuestionReader record={record.data} questionKey={value.key} reviewSource={{kind:'catalog',key:value.key}}/>:null}
 </div>;
}
