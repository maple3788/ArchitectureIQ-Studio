import {useState} from 'react';
import {ChevronRight,Search} from 'lucide-react';
import {Drawer,Empty,ErrorBox,JsonView,Loading,Tabs,useResource} from './ui';
import {RuleKnowledgeReader} from './RuleKnowledgeReader';
import {KnowledgeSnapshot} from './KnowledgeSnapshot';
import {KnowledgeQuestions} from './KnowledgeQuestions';
import {KnowledgeEntryHistory} from './KnowledgeRevisionHistory';
import {ExperienceSnapshot} from './ExperienceSnapshot';
import {readableName} from './displayNames';
import {formatTimestamp} from './time';
import {isExperience} from './knowledgeLibrary';
import {entryState,entryStateLabels,entryText,knowledgeEntries,revisionKey,currentEntryRevision,evolutionSourceLabel,knowledgeContentGroups,knowledgeEquivalentSources} from './knowledgeEntries';
import {HIGH_SUPPORT_QUESTIONS,knowledgeSupport,supportLabel} from './knowledgeSupport';
import {ruleConditions} from './ruleKnowledgePresentation';
import type {KnowledgeEntry,KnowledgeRevision} from './knowledgeEntries';
import type {KBRef} from './ruleRefinementTypes';
import type {Json} from './types';
import './kb.css';

function FormalEntry({entry,revision}:{entry:KnowledgeEntry;revision:KnowledgeRevision}){
 const [tab,setTab]=useState('知识内容');
 return <><Tabs tabs={['知识内容','适用题目','不适用题目']} value={tab} onChange={setTab}/>{tab==='知识内容'?<KnowledgeSnapshot single snapshot={{...revision.record.snapshot,claims:revision.parts}}/>:<KnowledgeQuestions kbRef={{id:revision.record.id,version:revision.record.version}} claimId={entry.claimId} relation={tab==='适用题目'?'applicable':'inapplicable'}/>}</>;
}
function ReadingOnlyEvolutionEntry({revision}:{revision:KnowledgeRevision}){
 const first=revision.parts[0];
 return <section className="knowledge-claim" aria-label="演化知识保存记录">
  <p>{first.id} · 第 {first.version} 版 · {entryStateLabels[entryState(revision)]}</p>
  <h3>{entryText(revision)}</h3>
  <p className="kb-support-note">此保存版本未进入 Task 可用规则，原文、条件和反例统计仍保留供检查。</p>
  {revision.parts.map((part,index)=>{let conditions:[string,string][]=[];try{conditions=ruleConditions(part.rule);}catch{/* The exact saved syntax remains available below. */}
   return part.rule&&<details key={index}><summary>保存的适用条件与规则{revision.parts.length>1?` · 分支 ${index+1}`:''}</summary>
    <dl>{conditions.flatMap(([label,value],index)=>[<dt key={`label-${index}`}>{label}</dt>,<dd key={`value-${index}`}>{value}</dd>])}</dl><JsonView value={part.rule}/>
   </details>;
  })}
 </section>;
}
export function KB({version,onEvaluate}:{version:number;onEvaluate?:(ref:KBRef)=>void}){
 const {data,error,loading}=useResource<any>('/kb',version);
 const [search,setSearch]=useState(''),[section,setSection]=useState('knowledge'),[status,setStatus]=useState('all'),[support,setSupport]=useState('all'),[limit,setLimit]=useState(30),[selection,setSelection]=useState<{key:string;version:string}>();
 const records:Json[]=Array.isArray(data)?data:Array.isArray(data?.items)?data.items:[...(data?.snapshots||[]),...(data?.claims||[]),...(data?.sources||[])];
 const entries=knowledgeEntries(records);
 const visible=knowledgeContentGroups(entries,search).flatMap(group=>{
  const matches=group.sources.filter(({entry,revision})=>(section==='all'||entry.library.section===section)&&(status==='all'||entryState(revision)===status)&&(support==='all'||(knowledgeSupport(entry.claimId,revision).support??-1)>=HIGH_SUPPORT_QUESTIONS));
  const source=matches.find(({entry,revision})=>knowledgeSupport(entry.claimId,revision).support!==null)??matches[0];
  return source?[{...group,...source}]:[];
 });
 const current=entries.find(entry=>entry.key===selection?.key),selected=current?.revisions.find(revision=>revisionKey(revision)===selection?.version);
 const latest=current&&currentEntryRevision(current);
 const equivalentSources=selected?knowledgeEquivalentSources(entries,selected):[];
 return <section className="kb-page"><div className="page-heading"><div><span className="eyebrow">KNOWLEDGE BASE</span><h1>知识库</h1><p>逐条阅读知识，检查适用条件与题目。</p></div></div><ErrorBox error={error}/>
  <div className="kb-entry-filters"><label className="kb-library-search"><Search size={18}/><input type="search" aria-label="搜索知识库" placeholder="搜索知识内容" value={search} onChange={event=>{setSearch(event.target.value);setLimit(30);}}/></label>
   <select aria-label="知识来源" value={section} onChange={event=>{setSection(event.target.value);setLimit(30);}}><option value="knowledge">研究知识</option><option value="experience">学习经验</option><option value="history">历史材料</option><option value="all">全部来源</option></select>
   <select aria-label="验证状态" value={status} onChange={event=>{setStatus(event.target.value);setLimit(30);}}><option value="all">全部状态</option>{Object.entries(entryStateLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select>
   <select aria-label="支持情况" value={support} onChange={event=>{setSupport(event.target.value);setLimit(30);}}><option value="all">全部支持情况</option><option value="high">高价值 · ≥{HIGH_SUPPORT_QUESTIONS} 道支持题</option></select>
  </div>
  {support==='high'&&<p className="kb-support-note">至少 {HIGH_SUPPORT_QUESTIONS} 道不同题目支持，反例仍保留。</p>}
  <details className="kb-support-definition"><summary>支持统计说明</summary><p>高价值门槛为同一保存版本的 {HIGH_SUPPORT_QUESTIONS} 道支持题。同题重复与多组比较只计一次；同题有反例时不计为支持，反例仍保留。这不代表独立验证，也不以适用题目数代替支持。证据未知的知识不进入此筛选。</p></details>
  {Array.isArray(data?.warnings)&&data.warnings.length>0&&<details className="kb-read-warning"><summary>{data.warnings.length} 个来源暂未完成核验</summary><JsonView value={data.warnings}/></details>}
  {loading?<Loading/>:!entries.length?<Empty title="尚无登记的知识或经验">保存的知识会显示在这里。</Empty>:!visible.length?<Empty title="没有找到匹配的知识">调整内容、来源、验证状态或支持情况筛选。</Empty>:<>
   <p className="kb-entry-count">{visible.length} 条知识</p>
   <div className="kb-library-list">{visible.slice(0,limit).map(({key,entry,revision,sources})=>{const state=entryState(revision);return <button key={key} className="kb-library-row" aria-label={`阅读 ${entry.claimId} ${entryText(revision)}`} onClick={()=>setSelection({key:entry.key,version:revisionKey(revision)})}>
    <span className="kb-library-copy"><span className="kb-library-title">{entryText(revision)}</span><span className="kb-library-state"><span className={`kb-entry-status is-${state}`}>{revision.record.kind==='research_rules'&&state==='verified'?'来源标记：范围内复现':revision.record.source_kind==='knowledge_evolution'&&state==='pending'?'待独立验证':entryStateLabels[state]}</span>{evolutionSourceLabel(revision)&&<span>{evolutionSourceLabel(revision)}</span>}<span className="kb-support-count">{sources.length>1?'当前来源：':''}{supportLabel(knowledgeSupport(entry.claimId,revision))}</span>{sources.length>1&&<span>{sources.length} 个来源</span>}{revision!==currentEntryRevision(entry)&&<span>历史记录</span>}<span>{entry.library.name}</span><span>{entry.claimId}</span></span></span><ChevronRight size={18} className="kb-library-arrow"/>
   </button>;})}</div>{visible.length>limit&&<button className="kb-load-more" onClick={()=>setLimit(value=>value+30)}>继续阅读 · 还有 {visible.length-limit} 条</button>}
  </>}
  {selected&&current&&<Drawer title="知识详情" subtitle={current.claimId} onClose={()=>setSelection(undefined)}>
   {equivalentSources.length>1&&<details className="kb-equivalent-sources"><summary>同内容来源 · {equivalentSources.length} 个来源</summary><p>相同正文与执行条件在列表中折叠。状态、题目、统计和修订记录按所选来源分别阅读，支持数不相加。</p><div>{equivalentSources.map(({entry,revision})=>{const label=`${entry.library.name} · ${entry.claimId} · ${revision.record.library?.version_label??'保存版本'}`;return <button key={entry.key} disabled={entry.key===current.key&&revisionKey(revision)===revisionKey(selected)} aria-label={`阅读来源 ${label}`} onClick={()=>setSelection({key:entry.key,version:revisionKey(revision)})}>{label}</button>;})}</div></details>}
   {selected!==latest&&<p className="kb-history-notice">{latest?'正在阅读历史记录。':'当前库版本未收录此知识，正在阅读历史记录。'}{latest&&<button onClick={()=>setSelection({key:current.key,version:revisionKey(latest)})}>返回当前知识</button>}</p>}
   <div className="kb-support-detail"><strong>{supportLabel(knowledgeSupport(current.claimId,selected))}</strong>{evolutionSourceLabel(selected)&&<p>{evolutionSourceLabel(selected)}</p>}<p>{knowledgeSupport(current.claimId,selected).notice}</p></div>
   {selected.parts.every(part=>part.library_only===true)?<ReadingOnlyEvolutionEntry revision={selected}/>:selected.record.kind==='research_rules'?<RuleKnowledgeReader key={`${current.key}:${revisionKey(selected)}`} claimId={current.claimId} kbRef={{id:selected.record.id,version:selected.record.version}} record={selected.record} onEvaluate={onEvaluate}/>:isExperience(selected.record)?<ExperienceSnapshot key={`${current.key}:${revisionKey(selected)}`} snapshot={{...selected.record.snapshot,lessons:selected.parts}}/>:<FormalEntry key={`${current.key}:${revisionKey(selected)}`} entry={current} revision={selected}/>}
   <KnowledgeEntryHistory entry={current} selected={selected} onRead={setSelection}/>
   <details className="kb-source-details"><summary>来源与完整记录{selected.record.source_count?` · ${selected.record.source_count} 个来源`:''}</summary>{selected.record.sources?.map((source:Json,index:number)=><div className="source-row" key={`${source.id}:${index}`}><div><b>{readableName(source.name,source.kind==='archive'?'历史导入材料':'运行保存记录')}</b>{Boolean(source.created_at)&&<small>{formatTimestamp(source.created_at)}</small>}</div></div>)}<JsonView value={{knowledge:current.claimId,record:selected.record.id,version:selected.record.version,entries:selected.parts}}/></details>
  </Drawer>}
 </section>;
}
