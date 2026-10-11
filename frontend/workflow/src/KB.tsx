import {useState} from 'react';
import {BookOpen,ChevronRight,Search} from 'lucide-react';
import {Drawer,Empty,ErrorBox,JsonView,Loading,useResource} from './ui';
import {RuleKnowledgeReader} from './RuleKnowledgeReader';
import {KnowledgeSnapshot} from './KnowledgeSnapshot';
import {ExperienceSnapshot} from './ExperienceSnapshot';
import {readableName} from './displayNames';
import {formatTimestamp} from './time';
import {ruleVersionCounts} from './ruleKnowledgePresentation';
import {groupKnowledgeLibraries,isExperience,knowledgeMatches,knowledgeVersionKey} from './knowledgeLibrary';
import type {KnowledgeLibrary} from './knowledgeLibrary';
import type {KBRef} from './ruleRefinementTypes';
import type {Json} from './types';
import './kb.css';

function countText(record:Json){
 const counts=record.counts??{};
 if(record.kind==='research_rules'){
  const stats=ruleVersionCounts(record.snapshot??{});
  return `${stats.claims} 条主张 · ${stats.clauses} 个执行分支`;
 }
 if(isExperience(record))return `${counts.lessons??record.snapshot?.lessons?.length??0} 条经验 · ${counts.episodes??record.snapshot?.episodes?.length??0} 次作答记录`;
 const claims=record.snapshot?.claims??[];
 const groups=new Set(claims.map((claim:Json)=>claim.source_claim_id??claim.id));
 return `${counts.source_claims??groups.size} 条主张`;
}
function detailText(record:Json){
 const counts=record.counts??{};
 if(record.kind==='research_rules'){
  const stats=ruleVersionCounts(record.snapshot??{});
  return `${stats.proposed} 条待独立确认 · ${stats.replicated} 条来源标记为范围内复现`;
 }
 if(isExperience(record))return '独立实验记录 · 待验证';
 if(counts.legacy_unverified)return '历史材料 · 待验证';
 return `${counts.verified_enabled??record.snapshot?.claims?.filter((claim:Json)=>claim.enabled&&claim.status==='replicated_in_scope').length??0} 条已验证且启用`;
}
export function KB({version,onEvaluate}:{version:number;onEvaluate?:(ref:KBRef)=>void}){
 const {data,error,loading}=useResource<any>('/kb',version);
 const [search,setSearch]=useState(''),[selection,setSelection]=useState<{key:string;version:string}>(),[experienceOpen,setExperienceOpen]=useState(false),[historyOpen,setHistoryOpen]=useState(false);
 const records:Json[]=Array.isArray(data)?data:Array.isArray(data?.items)?data.items:[...(data?.snapshots||[]),...(data?.claims||[]),...(data?.sources||[])];
 const groups=groupKnowledgeLibraries(records),query=search.trim();
 const visible=groups.filter(group=>group.versions.some(record=>knowledgeMatches(record,query)));
 const current=groups.find(group=>group.key===selection?.key);
 const selected=current?.versions.find(record=>knowledgeVersionKey(record)===selection?.version);
 function open(group:KnowledgeLibrary){const record=group.versions.find(value=>knowledgeMatches(value,query))??group.versions[0];setSelection({key:group.key,version:knowledgeVersionKey(record)});}
 function list(values:KnowledgeLibrary[]){return <div className="kb-library-list">{values.map(group=>{const record=group.versions[0];return <button key={group.key} className="kb-library-row" aria-label={`阅读 ${group.name}`} onClick={()=>open(group)}>
  <span className="kb-library-icon"><BookOpen size={22}/></span><span className="kb-library-copy"><span className="kb-library-title">{group.name}</span><span className="kb-library-count">{countText(record)}{group.versions.length>1?` · ${record.library?.version_label??'最新版本'} · ${group.versions.length} 个版本`:''}</span><span className="kb-library-state">{detailText(record)}{record.source_count>1?` · ${record.source_count} 个来源`:''}</span></span><ChevronRight size={18} className="kb-library-arrow"/>
 </button>;})}</div>;}
 const knowledge=visible.filter(group=>group.section==='knowledge'),experience=visible.filter(group=>group.section==='experience'),history=visible.filter(group=>group.section==='history');
 return <section className="kb-page"><div className="page-heading"><div><span className="eyebrow">KNOWLEDGE BASE</span><h1>知识库</h1><p>阅读知识，查看适用条件与版本演进。</p></div></div><ErrorBox error={error}/>
  <label className="kb-library-search"><Search size={18}/><input type="search" aria-label="搜索知识库" placeholder="搜索知识库或知识内容" value={search} onChange={event=>setSearch(event.target.value)}/></label>
  {Array.isArray(data?.warnings)&&data.warnings.length>0&&<details className="kb-read-warning"><summary>{data.warnings.length} 个来源暂未完成核验</summary><JsonView value={data.warnings}/></details>}
  {loading?<Loading/>:!records.length?<Empty title="尚无登记的知识或经验">完成学习后，保存的知识会显示在这里。</Empty>:!visible.length?<Empty title="没有找到匹配的知识">换一个名称、编号或知识关键词。</Empty>:<>
   {knowledge.length>0&&list(knowledge)}
   {experience.length>0&&<details className="kb-library-section" open={query?true:experienceOpen} onToggle={event=>{if(!query)setExperienceOpen(event.currentTarget.open);}}><summary><span>学习经验</span><span className="kb-section-count">{experience.length} 个实验</span></summary><p>各实验分别保留来源与作答记录。</p>{list(experience)}</details>}
   {history.length>0&&<details className="kb-library-section" open={query?true:historyOpen} onToggle={event=>{if(!query)setHistoryOpen(event.currentTarget.open);}}><summary><span>历史材料</span><span className="kb-section-count">{history.length} 份</span></summary><p>原始主张与条件分支保留，验证状态单独记录。</p>{list(history)}</details>}
  </>}
  {selected&&current&&<Drawer title={current.name} subtitle="知识阅读" onClose={()=>setSelection(undefined)}>
   {current.versions.length>1&&<label className="kb-version-picker">版本<select aria-label="知识库版本" value={knowledgeVersionKey(selected)} onChange={event=>setSelection({key:current.key,version:event.target.value})}>{current.versions.map(record=><option key={knowledgeVersionKey(record)} value={knowledgeVersionKey(record)}>{record.library?.version_label??record.name}</option>)}</select></label>}
   {selected.kind==='research_rules'?<RuleKnowledgeReader key={knowledgeVersionKey(selected)} kbRef={{id:selected.id,version:selected.version}} record={selected} onEvaluate={onEvaluate}/>:selected.snapshot?isExperience(selected)?<ExperienceSnapshot key={knowledgeVersionKey(selected)} snapshot={selected.snapshot}/>:<KnowledgeSnapshot key={knowledgeVersionKey(selected)} snapshot={selected.snapshot}/>:<JsonView value={selected}/>}
   <details className="kb-source-details"><summary>来源与完整记录{selected.source_count?` · ${selected.source_count} 个来源`:''}</summary>{selected.sources?.map((source:Json,index:number)=><div className="source-row" key={`${source.id}:${index}`}><div><b>{readableName(source.name,source.kind==='archive'?'历史导入材料':'运行保存记录')}</b>{Boolean(source.created_at)&&<small>{formatTimestamp(source.created_at)}</small>}{source.path&&<small className="mono wrap">{source.path}</small>}</div></div>)}<JsonView value={selected}/></details>
  </Drawer>}
 </section>;
}
