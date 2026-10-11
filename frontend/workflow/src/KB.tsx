import {RuleKnowledgeReader} from './RuleKnowledgeReader';
import type {KBRef} from './ruleRefinementTypes';
import { useState } from 'react';
import { BookOpen, FileText, ShieldCheck } from 'lucide-react';
import { Card, Drawer, Empty, ErrorBox, JsonView, Loading, useResource } from './ui';
import type { Json } from './types';
import { KnowledgeSnapshot } from './KnowledgeSnapshot';
import {ExperienceSnapshot} from './ExperienceSnapshot';
import { readableName } from './displayNames';
import { formatTimestamp } from './time';
import './kb.css';

const isExperience = (record: Json) => record.kind === 'experience' || Array.isArray(record.snapshot?.lessons);
function title(record: Json) {
  return readableName(record.name || record.title, isExperience(record) ? '学习经验' : record.counts?.legacy_unverified ? '历史导入知识' : '知识快照');
}
function CountSummary({record}: {record: Json}) {
  const counts = record.counts ?? {};
  if(record.kind==='research_rules')return <p className="kb-count-line">{counts.active_rules??record.snapshot?.rules?.filter((r:Json)=>r.state==='active').length??0} 条启用规则 · 研究记录</p>;
  if (isExperience(record)) return <><p className="kb-count-line">{counts.lessons ?? record.snapshot?.lessons?.length ?? 0} 条经验 · {counts.episodes ?? record.snapshot?.episodes?.length ?? 0} 次作答记录</p><p>其中 {counts.active_lessons ?? record.snapshot?.lessons?.filter((l:Json)=>l.status === 'active').length ?? 0} 条可用于后续练习；经验尚未通过独立验证。</p></>;
  const claims = record.snapshot?.claims;
  if (!Array.isArray(claims)) return <p>{record.summary || record.description || '打开记录查看内容与来源。'}</p>;
  return <><p className="kb-count-line">{counts.records ?? claims.length} 条知识记录 · {counts.verified_enabled ?? claims.filter((c:Json)=>c.status === 'replicated_in_scope' && c.enabled === true).length} 条已验证且启用</p>
    {counts.source_claims !== undefined && <p className="kb-count-explanation">{counts.source_claims} 条原始主张{counts.split_records > 0 ? ` + ${counts.split_records} 条拆分记录` : ''}。这里按整理后的记录计数，不代表独立实验的数量。</p>}
    {counts.legacy_unverified > 0 && <p>其中 {counts.legacy_unverified} 条来自历史导入，尚未经过当前流程验证。</p>}</>;
}
export function KB({version,onEvaluate}: {version:number;onEvaluate?:(ref:KBRef)=>void}) {
 const {data,error,loading} = useResource<any>('/kb',version);
 const [selected,setSelected] = useState<Json>();
 const records:Json[] = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : [...(data?.snapshots || []),...(data?.claims || []),...(data?.sources || [])];
 return <><div className="page-heading"><div><span className="eyebrow">KNOWLEDGE BASE</span><h1>知识与经验</h1><p>查看学习得到的经验、已验证知识和历史导入材料。相同内容的快照合并展示，全部来源保留。</p></div><span className="pill"><ShieldCheck size={14}/>历史来源只读</span></div><ErrorBox error={error}/>
 {Array.isArray(data?.warnings) && data.warnings.length > 0 && <details className="kb-read-warning"><summary>{data.warnings.length} 个来源暂未完成核验</summary><p>以下来源未计入可用记录，请查看读取与完整性检查信息。</p><JsonView value={data.warnings}/></details>}
 {loading ? <Loading/> : records.length ? <div className="kb-grid">{records.map((r,index)=><Card key={r.id || index} className="kb-card"><div className="model-top"><div className="model-icon"><BookOpen size={23}/></div><span className="pill">{r.kind==='research_rules'?'研究规则':isExperience(r) ? '学习经验 · 待验证' : r.counts?.legacy_unverified ? '历史导入' : '知识快照'}</span></div><h2>{title(r)}</h2><CountSummary record={r}/>
 {(r.updated_at || r.sources?.[0]?.created_at) && <small>最近记录：{formatTimestamp(r.updated_at || r.sources?.[0]?.created_at)}</small>}
 {r.source_count > 1 && <p className="kb-shared-sources">同一份内容 · {r.source_count} 个来源，不重复计算</p>}
 <button className="wide" onClick={()=>setSelected(r)}><FileText size={15}/>查看记录</button></Card>)}</div> : <Card><Empty title="尚无登记的知识或经验">完成学习后，保存的经验与知识会显示在这里。</Empty></Card>}
 {selected && <Drawer title={title(selected)} subtitle="查看内容、计数方式与来源" onClose={()=>setSelected(undefined)}><CountSummary record={selected}/>{selected.kind==='research_rules'?<RuleKnowledgeReader kbRef={{id:selected.id,version:selected.version}} record={selected} onEvaluate={onEvaluate}/>:selected.snapshot ? isExperience(selected) ? <ExperienceSnapshot snapshot={selected.snapshot}/> : <KnowledgeSnapshot snapshot={selected.snapshot}/> : <JsonView value={selected}/>}
 <details><summary>全部来源与技术标识{selected.source_count ? ` · ${selected.source_count} 个来源` : ''}</summary>{selected.sources?.map((s:Json,i:number)=><div className="source-row" key={s.id || i}><div><b>{readableName(s.name, s.kind === 'archive' ? '历史导入材料' : '运行保存记录')}</b>{s.created_at && <small>{formatTimestamp(s.created_at)}</small>}{s.path && <small className="mono wrap">{s.path}</small>}</div></div>)}<JsonView value={selected}/></details></Drawer>}</>;
}
