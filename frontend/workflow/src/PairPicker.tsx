import { familyLabel, questionLabel } from "./displayNames";
import { useEffect, useRef, useState } from 'react';
import { X, ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from './api';
import { Empty, ErrorBox, Field, Loading, useResource } from './ui';
import { QuestionReader } from './QuestionReader';
import { questionTypeLabel } from './QuestionPicker';
import type { Action } from './Questions';
import type { Json, List, QuestionSet } from './types';
import './pair-learning.css';
export type QuestionPair = Json & {pair_key:string;pair_id:string;members:Json[];intervention:Json};
const show = (v:any) => typeof v === 'string' ? v : JSON.stringify(v);
function PublicMember({member}:{member:Json}) {
  const [open,setOpen]=useState(false);
  const detail=useResource<Json>(open?'/questions/'+encodeURIComponent(member.key):null);
  return <section className="pp-member"><button onClick={()=>setOpen(!open)} aria-expanded={open}>
    <span>{member.role==='original'?'正常题':'DataFlip 题'}</span><strong title={member.key}>{questionLabel(detail.data ?? member)}</strong><span>{open?'收起':'阅读题面'}</span>
  </button>{open&&<div className="pp-reading"><ErrorBox error={detail.error}/>{detail.loading?<Loading/>:detail.data&&<QuestionReader record={detail.data}/>}</div>}</section>;
}
export function PairDetails({pair}:{pair:QuestionPair}) {
 return <div className="pp-detail"><h2 title={pair.pair_key}>{familyLabel(pair.family)} · 对照题组</h2><p>{familyLabel(pair.family)} · {questionTypeLabel(pair.type)} · 正常题 + DataFlip</p>
   <h3>这一对改变了什么</h3>
   {pair.intervention?.changes?.length?<div className="pp-changes">{pair.intervention.changes.map((c:Json,i:number)=><div key={i}>
     <strong>{c.path}</strong><span>{show(c.before)} → {show(c.after)}</span><small>{c.kind==='sampling'?'采样 / 随机因素':'数据因素'}</small></div>)}</div>:<p>尚无可核对的因素差异。</p>}
   <p className="pp-notice">{pair.intervention?.notice || (pair.intervention?.causal_status==='single_factor_fixed_sampling'?'已核对单一数据因素变化与固定采样；仍需实验解释其作用。':'这对题包含多因素变化，或无法核对全部采样条件；不能据此断言单一因素的因果作用。')}</p>
   {pair.intervention?.selection_history !== 'all_significant_pairs' && <p className="pp-notice">这批题的收录过程未保证包含赢家不变的对照。历史 DataFlip 发布包经过赢家翻转筛选，不应据此估计自然翻转率。</p>}
   {pair.intervention?.controls?.length>0&&<p>保持一致：候选模型、优化器、损失函数与训练预算。</p>}
   <ErrorBox error={pair.issues?.join('；')}/>
   <h3>阅读这一对题目</h3>{pair.members.map(m=><PublicMember key={m.key} member={m}/>)}
   <details><summary>候选方案的对应关系</summary><div className="pp-changes">{pair.candidate_mapping?.map((m:Json,i:number)=><div key={m.choice_identity}><strong title={m.choice_identity}>候选方案 {i+1}</strong><span>正常题 {m.original_letter} ↔ DataFlip {m.counterfactual_letter}</span></div>)}</div><p>按同一候选方案比较，不把选项字母变化当作赢家变化。</p></details>
 </div>;
}
export function PairPicker({version,act,questionSetId,purpose='research',phase='final',onApply,onClose}:{version:number;act:Action;questionSetId?:string;purpose?:'research'|'evaluation';phase?:'development'|'final';onApply:(s:QuestionSet)=>void;onClose:()=>void}) {
 const [search,setSearch]=useState(''),[type,setType]=useState(''),[offset,setOffset]=useState(0);
 const [selected,setSelected]=useState<string[]>([]),[known,setKnown]=useState<Record<string,QuestionPair>>({});
 const [selectedOnly,setSelectedOnly]=useState(false),[detail,setDetail]=useState<string>();
 const [initializing,setInitializing]=useState(!!questionSetId),[error,setError]=useState(''),[saving,setSaving]=useState(false),[retry,setRetry]=useState(0);
 const dialog=useRef<HTMLElement>(null), mounted=useRef(true);
 const split=purpose==='research'?'discovery':phase;
 const query=new URLSearchParams({search,type,split,offset:String(offset),limit:'20'});
 const list=useResource<List<QuestionPair>>('/question-pairs?'+query,version+retry);
 const issue=(p:QuestionPair)=>!p.ready || p.split!==split || (purpose==='research'?!p.kb_ready:!p.evaluation_ready);
 useEffect(()=>{mounted.current=true;const prior=document.activeElement as HTMLElement;dialog.current?.focus();return()=>{mounted.current=false;prior?.focus();};},[]);
 useEffect(()=>{if(list.data)setKnown(prev=>({...prev,...Object.fromEntries(list.data!.items.map(p=>[p.pair_key,p]))}));},[list.data]);
 useEffect(()=>{let active=true;setInitializing(!!questionSetId);setError('');setSelected([]);
   if(questionSetId)void api<QuestionSet>('/question-sets/'+encodeURIComponent(questionSetId)).then(s=>{
     if(!active)return;
     if(s.selection_mode!=='pairs'||!Array.isArray(s.pairs)||!Array.isArray(s.pair_keys)||s.pair_keys.length!==s.pairs.length)throw Error('原题对集资料不完整，暂不能应用选择。');
     setSelected(s.pair_keys);setKnown(prev=>({...prev,...Object.fromEntries(s.pairs!.map(p=>[p.pair_key,p]))}));
   }).catch(e=>{if(active)setError(String(e.message));}).finally(()=>{if(active)setInitializing(false);});
   return()=>{active=false;};
 },[questionSetId,retry]);
 const toggle=(key:string)=>setSelected(s=>s.includes(key)?s.filter(k=>k!==key):[...s,key]);
 const rows=selectedOnly?selected.map(k=>known[k]).filter(Boolean):(list.data?.items||[]);
 const invalid=selected.some(k=>!known[k]||issue(known[k]));
 const apply=async()=>{setSaving(true);try{const saved=await act(()=>api<QuestionSet>('/question-sets',{name:`${purpose==='research'?'研究':'独立评测'}题对 · ${selected.length} 对`,pair_keys:selected}));if(saved&&mounted.current)onApply(saved);}catch(e){if(mounted.current)setError((e as Error).message);}finally{if(mounted.current)setSaving(false);}};
 return <div className="pp-backdrop"><section ref={dialog} className="pp-dialog" role="dialog" aria-modal="true" aria-label="选择题目对" tabIndex={-1} onKeyDown={e=>{
   if(e.key==='Escape'){e.preventDefault();detail?setDetail(undefined):onClose();}
   if(e.key==='Tab'){const focusables=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,[tabindex="0"]')||[]).filter(el=>el.getClientRects().length>0);const first=focusables[0],last=focusables.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
 }}>
 <header className="pp-header"><div><h2>选择题目对</h2><p>正常题与 DataFlip 成对保留 · {purpose==='research'?'用于知识发现':'用于独立评测'}</p></div><button aria-label="关闭题对选择" onClick={onClose}><X/></button></header>
 <ErrorBox error={error||list.error}/>{error&&<button onClick={()=>setRetry(r=>r+1)}>重新读取原题对集</button>}
 {detail&&known[detail]?<div className="pp-content"><button onClick={()=>setDetail(undefined)}><ArrowLeft size={15}/>返回题对列表</button><PairDetails pair={known[detail]}/></div>:<>
 <div className="pp-filters"><Field label="搜索题对"><input value={search} placeholder="题对、题目编号或数据家族" onChange={e=>{setSearch(e.target.value);setOffset(0);}}/></Field><Field label="题对类型"><select value={type} onChange={e=>{setType(e.target.value);setOffset(0);}}><option value="">全部类型</option>{['architecture_only','optimizer_only','loss_only','mixed'].map(t=><option key={t} value={t}>{questionTypeLabel(t)}</option>)}</select></Field></div>
 <div className="pp-tabs"><button aria-pressed={!selectedOnly} onClick={()=>setSelectedOnly(false)}>全部题对 {list.data?.total??'…'}</button><button aria-pressed={selectedOnly} onClick={()=>setSelectedOnly(true)}>已选 {selected.length} 对</button></div>
 <div className="pp-content">{initializing||(!selectedOnly&&list.loading)?<Loading/>:rows.length?rows.map((p,index)=><article className={`pp-row ${selected.includes(p.pair_key)?'is-selected':''}`} key={p.pair_key}>
 <input type="checkbox" aria-label={`选择题对 ${p.pair_id}`} checked={selected.includes(p.pair_key)} disabled={!selected.includes(p.pair_key)&&issue(p)} onChange={()=>toggle(p.pair_key)}/><button className="pp-row-detail" onClick={()=>setDetail(p.pair_key)}><span className="pp-row-heading"><strong>{familyLabel(p.family)} · 第 {selectedOnly ? selected.indexOf(p.pair_key)+1 : offset+index+1} 组</strong><span>{questionTypeLabel(p.type)}</span></span><span className="pp-pair-members">{p.members.map(m=><span key={m.key}><small>{m.role==='original'?'正常题':'DataFlip'}</small><b title={m.key}>{familyLabel(p.family)}</b></span>)}</span><small>{p.intervention?.changes?.length??0} 项变化 · {p.intervention?.causal_status==='single_factor_fixed_sampling'?'单一数据因素':'含多因素或采样变化'} · 查看对照与题面 →</small>{issue(p)&&<small className="pp-warning">{p.issues?.join('；')||'资料或分区不满足当前用途'}</small>}</button></article>):<Empty title={selectedOnly?'尚未选择题对':'没有符合条件的完整题对'}>{purpose==='evaluation'?'需使用独立分区的题对；可在生成页选择对应分区。':'可切换筛选条件，或在生成页生成新的受控题对。'}</Empty>}</div>
 {!selectedOnly&&<nav className="pp-pagination"><span>{list.data?.total??0} 对 · 第 {Math.floor(offset/20)+1} 页</span><button aria-label="上一页题对" disabled={offset===0} onClick={()=>setOffset(o=>Math.max(0,o-20))}><ChevronLeft/></button><button aria-label="下一页题对" disabled={list.loading||offset+20>=(list.data?.total||0)} onClick={()=>setOffset(o=>o+20)}><ChevronRight/></button></nav>}
 </>}
 <footer className="pp-footer"><div><button onClick={()=>{setDetail(undefined);setSelectedOnly(true);}}>查看已选 {selected.length} 对</button><small>跨筛选与分页保留 · 每对固定包含 2 题</small>{invalid&&<small className="pp-warning">部分已选题对不满足当前分区或完整性要求，请移除。</small>}</div><button className="primary" disabled={initializing||!!error||saving||!selected.length||invalid} onClick={()=>void apply()}>{saving?'保存中…':`应用 ${selected.length} 对 · ${selected.length*2} 题`}</button></footer>
 </section></div>;
}
