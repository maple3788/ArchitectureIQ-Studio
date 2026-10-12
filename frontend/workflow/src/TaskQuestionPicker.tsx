import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowUpRight,ChevronLeft,ChevronRight,Search,X} from 'lucide-react';
import {api} from './api';
import {Empty,ErrorBox,Loading,useResource} from './ui';
import {QuestionReader} from './QuestionReader';
import {familyLabel,questionListSummary,typeLabel} from './displayNames';
import {publicRagReady} from './ragTypes';
import type {Json} from './types';
import './task-question-picker.css';

type Source='catalog'|'evolution';
type Row={id:string;key?:string;family:string;type?:string;question_type?:string;round_index?:number;rag_ready?:boolean;candidate_configs?:Json[];model_types?:string[]};
type Selection={source:Source;row:Row};
type Resolved={key:string;record:Json};
const PAGE_SIZE=25;

export function TaskQuestionPicker({version,onSelectQuestion,onClose}:{version:number;onSelectQuestion:(key:string)=>void;onClose:()=>void}){
 const [source,setSource]=useState<Source>('catalog'),[search,setSearch]=useState(''),[offset,setOffset]=useState(0);
 const [selected,setSelected]=useState<Selection>(),[reading,setReading]=useState<{selection:Selection;value?:Resolved}>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const dialog=useRef<HTMLElement>(null),mounted=useRef(true),resolving=useRef(false);
 const cache=useRef(new Map<string,Resolved>());
 const query=new URLSearchParams({search,offset:String(offset),limit:String(PAGE_SIZE)});
 const list=useResource<{items:Row[];total:number;source?:{connected:boolean}}>(`${source==='evolution'?'/tasks/evolution/questions':'/questions'}?${query}`,version,source==='evolution'?10000:0);
 useEffect(()=>{mounted.current=true;const previous=document.activeElement as HTMLElement|null;dialog.current?.focus();return()=>{mounted.current=false;previous?.focus();};},[]);
 const identity=(choice:Selection)=>`${choice.source}:${choice.row.key||choice.row.id}`;
 const resolve=async(choice:Selection)=>{
  const cached=cache.current.get(identity(choice));if(cached)return cached;
  const value=choice.source==='evolution'?await api<Resolved>(`/tasks/evolution/questions/${encodeURIComponent(choice.row.id)}`,{}):{key:choice.row.key!,record:await api<Json>(`/tasks/questions/${encodeURIComponent(choice.row.key!)}`)};
  if(choice.row.key&&value.key!==choice.row.key)throw Error('题目来源已变化，请重新打开选择器后重试。');
  if(!value.key||!publicRagReady(value.record))throw Error('题目公开输入不可用，请选择其他题目。');
  cache.current.set(identity(choice),value);return value;
 };
 const read=async(choice:Selection)=>{
  if(resolving.current)return;resolving.current=true;setBusy(true);setError('');setReading({selection:choice});
  try{const value=await resolve(choice);if(mounted.current)setReading({selection:choice,value});}
  catch(caught){if(mounted.current)setError((caught as Error).message);}
  finally{resolving.current=false;if(mounted.current)setBusy(false);}
 };
 const apply=async()=>{
  if(!selected||resolving.current)return;resolving.current=true;setBusy(true);setError('');
  try{const value=await resolve(selected);if(mounted.current)onSelectQuestion(value.key);}
  catch(caught){if(mounted.current)setError((caught as Error).message);}
  finally{resolving.current=false;if(mounted.current)setBusy(false);}
 };
 const changeSource=(value:Source)=>{setSource(value);setOffset(0);setSearch('');setError('');};
 const rows=list.data?.items??[],total=list.data?.total??0;
 return <div className="task-picker-backdrop" onClick={onClose}><section ref={dialog} className={`task-picker${reading?' is-reading':''}`} role="dialog" aria-modal="true" aria-label="选择 Task 题目" tabIndex={-1} onClick={event=>event.stopPropagation()} onKeyDown={event=>{
  if(event.key==='Escape'){event.stopPropagation();onClose();}
  if(event.key==='Tab'){const controls=dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), summary, [tabindex="0"]');if(!controls?.length)return;const first=controls[0],last=controls[controls.length-1];if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
 }}>
  <header className="task-picker-heading"><div><span className="eyebrow">QUESTION</span><h2>{reading?'阅读题目':'选择研究问题'}</h2><p>{reading?`${reading.selection.row.id} · ${reading.selection.source==='evolution'?`知识演化 · 第 ${reading.selection.row.round_index} 轮`:'题库'}`:'题库与知识演化的真实题目，都可以用于解答。'}</p></div><button className="icon-button" aria-label="关闭题目选择器" onClick={onClose}><X size={20}/></button></header>
  {reading?<div className="task-picker-reader"><button className="task-back" onClick={()=>{setReading(undefined);setError('');}} disabled={busy}><ArrowLeft size={15}/>返回题目列表</button>{busy?<Loading/>:reading.value?<QuestionReader record={reading.value.record} questionKey={reading.value.key} interactive/>:<><ErrorBox error={error}/><button className="secondary" onClick={()=>void read(reading.selection)}>重试读取题目</button></>}</div>:<>
   <nav className="task-picker-tabs" role="tablist" aria-label="题目来源"><button role="tab" aria-selected={source==='catalog'} disabled={busy} onClick={()=>changeSource('catalog')}>题库</button><button role="tab" aria-selected={source==='evolution'} disabled={busy} onClick={()=>changeSource('evolution')}>知识演化</button></nav>
   <div className="task-picker-toolbar"><label><Search size={16}/><input aria-label="搜索题目" placeholder="搜索题号、题型或数据类别" value={search} disabled={busy} onChange={event=>{setSearch(event.target.value);setOffset(0);}}/></label>{source==='evolution'&&list.data?.source&&<span className={list.data.source.connected?'':'is-stale'}>{list.data.source.connected?'新题自动更新':'显示最近同步记录'}</span>}</div>
   <div className="task-picker-body"><ErrorBox error={list.error}/>{list.loading?<Loading/>:!rows.length?<Empty title="没有符合条件的题目">{source==='evolution'?'知识演化已完成并保存的题目会显示在这里。':'换一个搜索条件试试。'}</Empty>:rows.map(row=>{
    const choice={source,row},chosen=selected&&identity(selected)===identity(choice),unavailable=row.rag_ready===false;
    const questionType=row.type||row.question_type,summary=questionListSummary({...row,type:questionType});
    return <article className={`task-picker-row${chosen?' is-selected':''}`} key={row.key||row.id}>
     <label><input type="radio" name="task-question" checked={!!chosen} disabled={unavailable||busy} aria-label={`选择 ${row.id}`} onChange={()=>{setSelected(choice);setError('');}}/>
      <span className="task-picker-copy"><span className="task-picker-kind">{familyLabel(row.family)} · {typeLabel(questionType)}</span>
       <span className="task-picker-question">{summary.description}</span>
       <strong>{summary.title}</strong>
       {summary.candidates.length?<span className="task-picker-candidates" role="list" aria-label={`${row.id} 的公开候选`}>
        {summary.candidates.map((candidate,index)=><span role="listitem" key={`${candidate.letter}-${index}`}><b aria-hidden={candidate.letter==='?'?true:undefined}>{candidate.letter==='?'?'·':candidate.letter}</b><span>{candidate.label}</span></span>)}
       </span>:<span className="task-picker-summary-note">候选摘要暂未记录，可阅读完整题目。</span>}
       {summary.candidates.some(candidate=>candidate.letter==='?')&&<span className="task-picker-summary-note">选项字母以完整题面为准。</span>}
       <small>{row.id}{source==='evolution'?` · 第 ${row.round_index} 轮`:''}{unavailable?' · 公开题面暂不可用':''}</small>
      </span>
     </label>
     <button className="task-text-action" disabled={busy} aria-label={`阅读题目 ${row.id}`} onClick={()=>void read(choice)}>阅读题目<ArrowUpRight size={14}/></button>
    </article>;
   })}</div>
   <div className="task-picker-pagination"><span>{total?`${offset+1}–${Math.min(offset+PAGE_SIZE,total)} / ${total} 道题`:'0 道题'}</span><button className="icon-button" aria-label="上一页" disabled={!offset||busy||list.loading} onClick={()=>setOffset(value=>Math.max(0,value-PAGE_SIZE))}><ChevronLeft size={18}/></button><button className="icon-button" aria-label="下一页" disabled={offset+PAGE_SIZE>=total||busy||list.loading} onClick={()=>setOffset(value=>value+PAGE_SIZE)}><ChevronRight size={18}/></button></div>
  </>}
  <footer className="task-picker-footer"><div>{!reading&&<ErrorBox error={error}/>}<p>{selected?`已选择 ${selected.row.id}`:'选择一道题目，保留本次题面快照。'}</p></div><button className="primary" disabled={!selected||busy} onClick={()=>void apply()}>{busy?'正在读取…':'应用所选题目'}</button></footer>
 </section></div>;
}
