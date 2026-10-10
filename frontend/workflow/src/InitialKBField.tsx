import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {BookOpen, Check, ChevronLeft} from 'lucide-react';
import {Drawer, ErrorBox, JsonView, Loading, useResource} from './ui';
import {ExperienceSnapshot} from './ExperienceSnapshot';
import {KnowledgeSnapshot} from './KnowledgeSnapshot';
import {familyLabel,readableName} from './displayNames';
import {formatTimestamp} from './time';
import type {Json} from './types';
import './initial-kb.css';

export type InitialKBSelection = {id:string; version:string};
type Category = 'all' | 'verified' | 'experience' | 'history' | 'pending';
const categories:Record<Category,string> = {all:'全部', verified:'已验证知识', experience:'学习经验', history:'历史导入', pending:'待验证知识'};
const experience = (item:Json) => item.kind === 'experience';
const usable = (item:Json) => Number(experience(item) ? item.counts?.active_lessons ?? 0 : item.counts?.verified_enabled ?? 0);
const category = (item:Json):Category => experience(item) ? 'experience' : usable(item) > 0 ? 'verified' : item.counts?.legacy_unverified > 0 ? 'history' : 'pending';
const title = (item:Json) => readableName(item.name, experience(item) ? '学习经验' : category(item) === 'history' ? '历史导入知识' : '知识快照');
const itemVersion = (item:Json):string => item.version ?? item.snapshot?.version ?? '';
const countText = (item:Json) => experience(item) ? `${usable(item)} 条可用经验 · 待验证` : `${usable(item)} 条已验证且启用 · 共 ${item.counts?.records ?? 0} 条记录`;
const blockedReason = (item:Json) => usable(item) > 0 ? '' : experience(item) ? '这个版本尚无可用经验，可先查看已有作答记录。' : '尚无已验证且启用的知识，可查看内容，暂不能用于作答。';
function Snapshot({item}:{item:Json}) {
 return item.snapshot ? experience(item) ? <ExperienceSnapshot snapshot={item.snapshot}/> : <KnowledgeSnapshot snapshot={item.snapshot}/> : <p>此来源未提供可查看的内容。</p>;
}
function Source({item}:{item:Json}) {
 const source=item.sources?.[0];
 const topics=Array.from(new Set<string>((item.snapshot?.episodes??[]).map((episode:Json)=>episode.question?.family??episode.public?.family??episode.family).filter((family:unknown)=>typeof family==='string'))).map(familyLabel);
 return <div className="ikb-source">{source && <span>{readableName(source.name, source.kind === 'archive' ? '历史研究归档' : '学习记录')}{source.round_index ? ` · 第 ${source.round_index} 轮` : ''}{item.source_count > 1 ? ` 等 ${item.source_count} 个来源` : ''}</span>}{item.updated_at && <span>{formatTimestamp(item.updated_at)}</span>}{topics.length>0&&<span>来源题型：{topics.join('、')}</span>}</div>;
}
export function FrozenInitialKB({item,selection}:{item?:Json|null;selection?:InitialKBSelection|null}) {
 if(!item)return <p className="basic-muted">{selection ? '此运行未记录可展示的起始 KB 内容，请查看该轮实际输入。' : '未选择起始 KB，从空经验开始。'}</p>;
 return <section className="ikb-current"><span className="ikb-label">起始 KB · 已冻结</span><strong>{title(item)}</strong><p>{countText(item)}</p><Source item={item}/><details><summary>查看本次选用的 KB 内容</summary><Snapshot item={item}/></details></section>;
}
export function InitialKBField({value,onChange,version}:{value?:InitialKBSelection|null;onChange:(selection:InitialKBSelection|null)=>void;version:number}) {
 const [open,setOpen]=useState(false),[filter,setFilter]=useState<Category>('all'),[search,setSearch]=useState(''),[detail,setDetail]=useState<Json>(),[refresh,setRefresh]=useState(0);
 const {data,error,loading}=useResource<{items:Json[];warnings?:Json[]}>('/kb',version+refresh);
 const records=Array.isArray(data?.items)?data.items:[];
 const sameId=value && records.find(item=>item.id === value.id);
 const selected=sameId && itemVersion(sameId) === value?.version ? sameId : undefined;
 const selectionError = !error&&!loading&&value&&!selected ? sameId ? '所选 KB 已有新版本，请重新选择要使用的版本。保存的选择不会自动替换。' : '所选 KB 暂时不可用，请重新读取或选择其他 KB。' : '';
 const shown=records.filter(item=>(filter==='all'||category(item)===filter)&&[title(item),...(item.snapshot?.lessons??[]).map((l:Json)=>l.text),...(item.snapshot?.claims??[]).map((c:Json)=>c.text)].join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()));
 const modal=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  if(!open)return;
  const previous=document.activeElement as HTMLElement|null;
  modal.current?.querySelector<HTMLButtonElement>('button')?.focus();
  return ()=>{if(previous?.isConnected)previous.focus();};
 },[open]);
 const choose=(item:Json)=>{if(!usable(item)||!itemVersion(item))return;onChange({id:item.id,version:itemVersion(item)});setOpen(false);};
 const openPicker=()=>{setDetail(undefined);setOpen(true);setRefresh(n=>n+1);};
 return <section className="initial-kb-field" aria-label="起始知识库">
  <span className="ikb-label"><BookOpen size={15}/>起始 KB</span>
  <div className="ikb-current">{selected ? <><strong>{title(selected)}</strong><p>{countText(selected)}</p><Source item={selected}/></> : <><strong>{value ? '已保存 KB 选择' : '从空经验开始'}</strong><p>{value ? loading ? '正在读取所选版本…' : '保留已选版本，等待核对。' : '也可以从知识库选一个版本，在第一轮作答时使用。'}</p></>}
   {selected&&blockedReason(selected)&&<p className="ikb-warning">{blockedReason(selected)}</p>}
   <ErrorBox error={error ? `知识库读取失败：${error}` : selectionError}/>
   <div className="ikb-actions"><button onClick={openPicker}>{value ? '更换 KB' : '选择 KB'}</button>{selected&&<button onClick={()=>{setDetail(selected);setOpen(true);}}>查看已选内容</button>}{value&&<button className="text-button" aria-label="清除起始 KB" onClick={()=>onChange(null)}>清除</button>}{(error||selectionError)&&<button onClick={()=>setRefresh(n=>n+1)}>重新读取 KB</button>}</div>
  </div>
  <p className="ikb-help">起始 KB 在运行前固定版本。知识会按题目条件检索，经验会按输入预算选取；预览会列出实际带入的内容。</p>
  {open&&createPortal(<div ref={modal} className="ikb-modal" onKeyDown={e=>{
   if(e.key!=='Tab')return;
   const controls=Array.from(modal.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, summary, a[href]')??[]).filter(el=>el.getClientRects().length>0);
   if(!controls.length)return;
   if(e.shiftKey&&document.activeElement===controls[0]){e.preventDefault();controls.at(-1)?.focus();}
   else if(!e.shiftKey&&document.activeElement===controls.at(-1)){e.preventDefault();controls[0].focus();}
  }}><Drawer title="选择起始 KB" subtitle="先查看内容和适用条件，再选一个版本用于作答。" onClose={()=>setOpen(false)}>
   {detail ? <><button className="ikb-back" onClick={()=>setDetail(undefined)}><ChevronLeft size={15}/>返回 KB 列表</button><div className="ikb-detail-heading"><span className="pill">{categories[category(detail)]}</span><h3>{title(detail)}</h3><p>{countText(detail)}</p><Source item={detail}/></div><Snapshot item={detail}/><details className="ikb-technical"><summary>来源与版本标识</summary><JsonView value={{version:itemVersion(detail),sources:detail.sources??detail.source}}/></details><div className="ikb-detail-action">{blockedReason(detail)&&<p>{blockedReason(detail)}</p>}<button className="primary" disabled={!usable(detail)||!itemVersion(detail)} onClick={()=>choose(detail)}>使用这个 KB</button></div></> : <>
    <div className="ikb-filters"><div className="ikb-categories" role="group" aria-label="KB 分类">{(Object.keys(categories) as Category[]).filter(key=>key!=='pending'||records.some(item=>category(item)==='pending')).map(key=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{categories[key]} · {key==='all'?records.length:records.filter(item=>category(item)===key).length}</button>)}</div><input aria-label="搜索 KB" placeholder="搜索名称或知识内容" value={search} onChange={e=>setSearch(e.target.value)}/></div>
    <ErrorBox error={error?`知识库读取失败：${error}`:undefined}/>{error&&<button onClick={()=>setRefresh(n=>n+1)}>重新读取 KB</button>}
    {loading ? <Loading/> : <div className="ikb-list">{shown.map(item=><article className="ikb-card" key={`${item.id}:${itemVersion(item)}`}><div className="ikb-card-top"><span className="pill">{categories[category(item)]}</span>{selected&&selected.id===item.id&&itemVersion(selected)===itemVersion(item)&&<span className="ikb-selected"><Check size={14}/>已选</span>}</div><h3>{title(item)}</h3><p className="ikb-count">{countText(item)}</p><Source item={item}/>{blockedReason(item)&&<p className="ikb-warning">{blockedReason(item)}</p>}<div className="ikb-actions"><button onClick={()=>setDetail(item)}>查看内容</button><button disabled={!usable(item)||!itemVersion(item)} onClick={()=>choose(item)}>使用这个 KB</button></div></article>)}{!shown.length&&!error&&<p className="ikb-empty">{records.length?'没有符合筛选的 KB。':'知识库还没有可选内容。完成学习后，保存的经验会出现在这里。'}</p>}</div>}
    {!!data?.warnings?.length&&<p className="ikb-help">有 {data.warnings.length} 个来源未通过完整性检查，未列入可选内容。</p>}
   </>}
  </Drawer></div>,document.body)}
 </section>;
}
