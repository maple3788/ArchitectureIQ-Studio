import {useState} from 'react';
import {Search,ChevronLeft,ChevronRight} from 'lucide-react';
import {useResource,ErrorBox,Loading} from './ui';
import {familyLabel} from './displayNames';
import {questionTypeLabel} from './QuestionPicker';
import type {BankItem,Page,QuestionFilters} from './dataTypes';

export function GlobalQuestionBank({version,onRead,selected,onSelect,filters:initialFilters={},offset:initialOffset=0,onLocation}: {
 version:number;onRead?:(key:string)=>void;selected?:string[];onSelect?:(keys:string[])=>void;
 filters?:QuestionFilters;offset?:number;onLocation?:(filters:QuestionFilters,offset:number)=>void;
}) {
 const [filters,setFilters]=useState(initialFilters),[offset,setOffset]=useState(initialOffset),[retry,setRetry]=useState(0);
 const query=new URLSearchParams({...filters,offset:String(offset),limit:'25'});
 const data=useResource<Page<BankItem>>('/question-bank?'+query,version+retry);
 const navigate=(next:QuestionFilters,page=0)=>{setFilters(next);setOffset(page);onLocation?.(next,page);};
 return <section className="data-bank" aria-label="总题库">
  <div className="data-toolbar"><label className="data-search"><Search size={17}/><input aria-label="搜索总题库" placeholder="搜索题目、类型或公开题面" value={filters.search||''} onChange={e=>navigate({...filters,search:e.target.value})}/></label><span>{data.data?`${data.data.total} 道去重题目`:'读取题库…'}</span></div>
  <ErrorBox error={data.error}/>{data.error&&<button onClick={()=>setRetry(v=>v+1)}>重试读取题库</button>}
  {data.loading&&<Loading/>}
  {data.data?.items.map(item=><article className="data-question" key={item.equivalence_id}>
   {onSelect&&<input type="checkbox" aria-label={item.summary.id} checked={item.keys.some(k=>selected?.includes(k))} onChange={e=>onSelect(e.target.checked?[...selected||[],item.representative_key]:(selected||[]).filter(k=>!item.keys.includes(k)))}/>}
   <div className="data-question-body"><div className="data-question-meta"><span>{familyLabel(item.summary.family)}</span><span>{questionTypeLabel(item.summary.type)}</span>{!item.summary.ready&&<span>资料待补充</span>}</div>
    {onRead?<button className="data-title-button" aria-label={`阅读 ${item.summary.id}`} onClick={()=>onRead(item.representative_key)}>{item.summary.prompt||item.summary.id}</button>:<h3>{item.summary.prompt||item.summary.id}</h3>}
    <div className="data-question-foot"><span>{item.summary.choices} 个候选 · {item.keys.length} 个来源版本</span>{item.datasets.map(d=><span className="data-tag" key={d.collection_id}>{d.name}</span>)}</div>
   </div>
  </article>)}
  {data.data?.total===0&&<div className="data-empty">没有符合条件的题目。可以调整搜索，或导入、生成题目。</div>}
  <div className="data-pagination"><button aria-label="总题库上一页" disabled={!offset} onClick={()=>navigate(filters,Math.max(0,offset-25))}><ChevronLeft size={16}/></button><span>第 {Math.floor(offset/25)+1} 页</span><button aria-label="总题库下一页" disabled={!data.data||offset+25>=data.data.total} onClick={()=>navigate(filters,offset+25)}><ChevronRight size={16}/></button></div>
 </section>;
}
