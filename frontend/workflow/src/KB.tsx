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
import {entryState,entryStateLabels,entryText,knowledgeEntries,revisionKey,currentEntryRevision,displayedEntryRevision} from './knowledgeEntries';
import type {KnowledgeEntry,KnowledgeRevision} from './knowledgeEntries';
import type {KBRef} from './ruleRefinementTypes';
import type {Json} from './types';
import './kb.css';

function FormalEntry({entry,revision}:{entry:KnowledgeEntry;revision:KnowledgeRevision}){
 const [tab,setTab]=useState('知识内容');
 return <><Tabs tabs={['知识内容','适用题目','不适用题目']} value={tab} onChange={setTab}/>{tab==='知识内容'?<KnowledgeSnapshot single snapshot={{...revision.record.snapshot,claims:revision.parts}}/>:<KnowledgeQuestions kbRef={{id:revision.record.id,version:revision.record.version}} claimId={entry.claimId} relation={tab==='适用题目'?'applicable':'inapplicable'}/>}</>;
}
export function KB({version,onEvaluate}:{version:number;onEvaluate?:(ref:KBRef)=>void}){
 const {data,error,loading}=useResource<any>('/kb',version);
 const [search,setSearch]=useState(''),[section,setSection]=useState('knowledge'),[status,setStatus]=useState('all'),[limit,setLimit]=useState(30),[selection,setSelection]=useState<{key:string;version:string}>();
 const records:Json[]=Array.isArray(data)?data:Array.isArray(data?.items)?data.items:[...(data?.snapshots||[]),...(data?.claims||[]),...(data?.sources||[])];
 const entries=knowledgeEntries(records);
 const visible=entries.filter(entry=>{const revision=displayedEntryRevision(entry,search);return (section==='all'||entry.library.section===section)&&revision&&(status==='all'||entryState(revision)===status);});
 const current=entries.find(entry=>entry.key===selection?.key),selected=current?.revisions.find(revision=>revisionKey(revision)===selection?.version);
 const latest=current&&currentEntryRevision(current);
 function open(entry:KnowledgeEntry){const revision=displayedEntryRevision(entry,search)??entry.revisions[0];setSelection({key:entry.key,version:revisionKey(revision)});}
 return <section className="kb-page"><div className="page-heading"><div><span className="eyebrow">KNOWLEDGE BASE</span><h1>知识库</h1><p>逐条阅读知识，检查适用条件与题目。</p></div></div><ErrorBox error={error}/>
  <div className="kb-entry-filters"><label className="kb-library-search"><Search size={18}/><input type="search" aria-label="搜索知识库" placeholder="搜索知识内容" value={search} onChange={event=>{setSearch(event.target.value);setLimit(30);}}/></label>
   <select aria-label="知识来源" value={section} onChange={event=>{setSection(event.target.value);setLimit(30);}}><option value="knowledge">研究知识</option><option value="experience">学习经验</option><option value="history">历史材料</option><option value="all">全部来源</option></select>
   <select aria-label="验证状态" value={status} onChange={event=>{setStatus(event.target.value);setLimit(30);}}><option value="all">全部状态</option>{Object.entries(entryStateLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select>
  </div>
  {Array.isArray(data?.warnings)&&data.warnings.length>0&&<details className="kb-read-warning"><summary>{data.warnings.length} 个来源暂未完成核验</summary><JsonView value={data.warnings}/></details>}
  {loading?<Loading/>:!entries.length?<Empty title="尚无登记的知识或经验">保存的知识会显示在这里。</Empty>:!visible.length?<Empty title="没有找到匹配的知识">调整内容、来源或状态筛选。</Empty>:<>
   <p className="kb-entry-count">{visible.length} 条知识</p>
   <div className="kb-library-list">{visible.slice(0,limit).map(entry=>{const revision=displayedEntryRevision(entry,search)??entry.revisions[0],state=entryState(revision);return <button key={entry.key} className="kb-library-row" aria-label={`阅读 ${entry.claimId} ${entryText(revision)}`} onClick={()=>open(entry)}>
    <span className="kb-library-copy"><span className="kb-library-title">{entryText(revision)}</span><span className="kb-library-state"><span className={`kb-entry-status is-${state}`}>{revision.record.kind==='research_rules'&&state==='verified'?'来源标记：范围内复现':entryStateLabels[state]}</span>{revision!==currentEntryRevision(entry)&&<span>历史记录</span>}<span>{entry.library.name}</span><span>{entry.claimId}</span></span></span><ChevronRight size={18} className="kb-library-arrow"/>
   </button>;})}</div>{visible.length>limit&&<button className="kb-load-more" onClick={()=>setLimit(value=>value+30)}>继续阅读 · 还有 {visible.length-limit} 条</button>}
  </>}
  {selected&&current&&<Drawer title="知识详情" subtitle={current.claimId} onClose={()=>setSelection(undefined)}>
   {selected!==latest&&<p className="kb-history-notice">{latest?'正在阅读历史记录。':'当前库版本未收录此知识，正在阅读历史记录。'}{latest&&<button onClick={()=>setSelection({key:current.key,version:revisionKey(latest)})}>返回当前知识</button>}</p>}
   {selected.record.kind==='research_rules'?<RuleKnowledgeReader key={`${current.key}:${revisionKey(selected)}`} claimId={current.claimId} kbRef={{id:selected.record.id,version:selected.record.version}} record={selected.record} onEvaluate={onEvaluate}/>:isExperience(selected.record)?<ExperienceSnapshot key={`${current.key}:${revisionKey(selected)}`} snapshot={{...selected.record.snapshot,lessons:selected.parts}}/>:<FormalEntry key={`${current.key}:${revisionKey(selected)}`} entry={current} revision={selected}/>}
   <KnowledgeEntryHistory entry={current} selected={selected} onRead={setSelection}/>
   <details className="kb-source-details"><summary>来源与完整记录{selected.record.source_count?` · ${selected.record.source_count} 个来源`:''}</summary>{selected.record.sources?.map((source:Json,index:number)=><div className="source-row" key={`${source.id}:${index}`}><div><b>{readableName(source.name,source.kind==='archive'?'历史导入材料':'运行保存记录')}</b>{Boolean(source.created_at)&&<small>{formatTimestamp(source.created_at)}</small>}</div></div>)}<JsonView value={{knowledge:current.claimId,record:selected.record.id,version:selected.record.version,entries:selected.parts}}/></details>
  </Drawer>}
 </section>;
}
