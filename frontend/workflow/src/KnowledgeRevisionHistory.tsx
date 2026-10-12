import {useState} from 'react';
import {JsonView} from './ui';
import {ruleConditions,ruleField,sourceStatus} from './ruleKnowledgePresentation';
import {entryText,knowledgeEntryHistory,revisionKey,type KnowledgeEntry,type KnowledgeRevision} from './knowledgeEntries';
import type {Json} from './types';
import './knowledge-revision-history.css';

type Selection={key:string;version:string};
type RevisionState={validation:Json[];reference:Json[];sourceStatuses:string[]};
type Revision=RevisionState&{key:string;label:string;text:string;rules:Json[];conditions:string[];exceptions:string[];rationale:string[];parentKeys:string[];original:boolean;round?:number;selection?:Selection;source:Json};
const strings=(value:unknown):string[]=>Array.isArray(value)?value.filter((item):item is string=>typeof item==='string'&&!!item):[];
const unique=(value:string[])=>[...new Set(value)];
const stable=(value:unknown):string=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const savedFields=(value:Json,keys:string[])=>Object.fromEntries(keys.filter(key=>value[key]!==undefined).map(key=>[key,value[key]]));
const distinctRecords=(values:Json[])=>[...new Map(values.filter(value=>Object.keys(value).length).map(value=>[stable(value),value])).values()];
function savedState(parts:Json[],evolution=false):RevisionState{
 return {
  validation:distinctRecords(parts.map(part=>savedFields(part.metadata??part,['validity_status','validation_origin']))),
  reference:distinctRecords(parts.map(part=>({...savedFields(part.metadata??part,['inject','inject_same','role','usage_note']),...savedFields(part,['state'])}))),
  sourceStatuses:unique(parts.flatMap(part=>strings([part.source_status,part.metadata?.source_status,...(evolution?[part.status]:[]),...(Array.isArray(part.source_refs)?part.source_refs.map((ref:Json)=>ref.source_status):[])]))),
 };
}
function changed(before:Revision,after:Revision){
 return [before.text!==after.text?'正文':null,stable(before.rules)!==stable(after.rules)?'执行规则':null,
  stable(before.conditions)!==stable(after.conditions)?'适用条件':null,stable(before.exceptions)!==stable(after.exceptions)?'例外条件':null,
  stable(before.validation)!==stable(after.validation)?'验证状态':null,stable(before.reference)!==stable(after.reference)?'模型参考策略':null,
  stable(before.sourceStatuses)!==stable(after.sourceStatuses)?'演化来源状态':null].filter(Boolean).join('、');
}
function RevisionStatus({revision}:{revision:Revision}){
 const sourceNames:Record<string,string>={candidate:'研究候选',verified:'源报告已验证',flagged:'存在疑问',retired:'已退役'};
 return <div className="knowledge-revision-rules">
  {revision.validation.map((metadata,index)=><div key={index}><p>{sourceStatus(metadata)}</p>{metadata.validation_origin&&<p>验证来源：{({source_reported:'来源报告',modified_in_studio:'本平台修订'} as Record<string,string>)[metadata.validation_origin]??metadata.validation_origin}</p>}</div>)}
  {revision.sourceStatuses.map(status=><p key={status}>演化来源状态：{sourceNames[status]??status}</p>)}
  {revision.reference.map((policy,index)=><div key={index}>
   {policy.state&&<p>保存状态：{({active:'启用',retired:'已退役'} as Record<string,string>)[policy.state]??policy.state}</p>}
   {typeof policy.inject==='boolean'&&<p>模型参考：{policy.inject?'允许注入':'不注入模型'}</p>}
   {Array.isArray(policy.inject_same)&&<p>{policy.inject_same.length?`参考时要求相同：${strings(policy.inject_same).map(ruleField).join('、')}`:'参考时不要求保持相同字段'}</p>}
   {policy.role&&<p>使用角色：{({exploratory:'探索记录',descriptive:'描述记录',confirmatory:'确认性研究'} as Record<string,string>)[policy.role]??policy.role}</p>}
   {policy.usage_note&&<p>使用说明：{policy.usage_note}</p>}
  </div>)}
  {revision.reference.some(policy=>policy.inject===true)&&<p className="knowledge-revision-note">以上为该版保存的参考设置；能否用于模型参考还取决于该版验证状态与适用范围。</p>}
 </div>;
}
function RevisionRules({revision}:{revision:Revision}){
 return <div className="knowledge-revision-rules">
  {revision.conditions.length>0&&<p>适用条件：{revision.conditions.join('；')}</p>}
  {revision.exceptions.length>0&&<p>例外条件：{revision.exceptions.join('；')}</p>}
  {revision.rules.map((rule,index)=>{let conditions:[string,string][]=[];try{conditions=ruleConditions(rule);}catch{/* Preserve unfamiliar saved syntax in the raw record. */}
   return <div key={index}>{revision.rules.length>1&&<h5>分支 {index+1}</h5>}{conditions.length?<dl>{conditions.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>:<p>该版本保存了执行规则，可在完整记录中核对。</p>}</div>;
  })}
 </div>;
}
function RevisionChange({before,after}:{before:Revision;after:Revision}){
 const [open,setOpen]=useState(false),fields=changed(before,after);
 return <div className="knowledge-revision-change"><p>{fields?`较 ${before.label}：${fields}已调整。`:`较 ${before.label}：正文与执行条件保持一致。`}</p>
  {fields&&<details onToggle={event=>setOpen(event.currentTarget.open)}><summary>对照修订前后</summary>{open&&<div className="knowledge-revision-comparison">{[before,after].map((revision,index)=><section key={revision.key}><h5>{index?'修订后':'修订前'} · {revision.label}</h5><p>{revision.text}</p><RevisionStatus revision={revision}/><RevisionRules revision={revision}/></section>)}</div>}</details>}
 </div>;
}
export function KnowledgeRevisionHistory({revisions,summary,missingInitial,truncated=false,selected,onRead}:{revisions:Revision[];summary:string;missingInitial:boolean;truncated?:boolean;selected?:Selection;onRead?:(selection:Selection)=>void}){
 const [open,setOpen]=useState(false);
 return <details className="knowledge-revision-history" onToggle={event=>setOpen(event.currentTarget.open)}><summary>{summary}<span>{revisions.length} 个保存版本</span></summary>
  {open&&<section aria-label="知识修订历史">
   <p className="knowledge-revision-note">按保存顺序阅读原文与变化；每条记录保留自己的版本。</p>
   {missingInitial&&<p className="knowledge-revision-note">第一版原文未包含在这份记录中。</p>}
   {truncated&&<p className="knowledge-revision-note">历史记录只保留了部分版本。</p>}
   <ol>{revisions.map((revision,index)=>{
    const parents=revision.parentKeys.map(key=>revisions.find(item=>item.key===key)).filter((item):item is Revision=>!!item);
    const active=!!revision.selection&&revision.selection.key===selected?.key&&revision.selection.version===selected?.version;
    return <li key={revision.key}><header><div><strong>{revision.original?'第一版原文':index===0?'最早保存原文':'修订记录'}</strong><span>{revision.label}{revision.round!==undefined?` · 第 ${revision.round} 轮登记`:''}</span></div>{active&&<small>正在阅读</small>}</header>
     <p className="knowledge-revision-text">{revision.text}</p>
     <RevisionStatus revision={revision}/>
     {revision.rationale.map(text=><div className="knowledge-revision-rationale" key={text}><small>修订说明</small><p>{text}</p></div>)}
     {parents.map(parent=><RevisionChange key={parent.key} before={parent} after={revision}/>)}
     {revision.parentKeys.length>parents.length&&<p className="knowledge-revision-note">前序版本未保存在此记录中，无法完整对照变化。</p>}
     {(revision.rules.length>0||revision.conditions.length>0||revision.exceptions.length>0)&&<details className="knowledge-revision-rule-details"><summary>这一版的适用条件与执行规则</summary><RevisionRules revision={revision}/></details>}
     {onRead&&revision.selection&&<button className="knowledge-revision-read" disabled={active} onClick={()=>onRead(revision.selection!)}>阅读 {revision.label} 的知识与题目</button>}
     <details className="knowledge-revision-source"><summary>版本引用与完整记录</summary><JsonView value={revision.source}/></details>
    </li>;
   })}</ol>
  </section>}
 </details>;
}

export function KnowledgeEntryHistory({entry,selected,onRead}:{entry:KnowledgeEntry;selected:KnowledgeRevision;onRead:(selection:Selection)=>void}){
 const history=knowledgeEntryHistory(entry);
 const revisions:Revision[]=history.map(node=>{
  const {record,parts}=node.revision;
  const sourceParents=parts.flatMap(part=>strings(part.metadata?.parents));
  const original=parts.length>0&&parts.every(part=>(part.metadata?.revision??part.revision)===1)&&!node.parentKeys.length&&!node.missingParents&&!sourceParents.length;
  return {key:node.key,label:`${node.claimId} · ${record.library?.version_label??record.snapshot?.source_document?.version_label??'保存版本'}`,
   text:entryText(node.revision),rules:parts.flatMap(part=>part.rule?[part.rule]:[]),
   conditions:unique(parts.flatMap(part=>strings(part.conditions))),exceptions:unique(parts.flatMap(part=>strings(part.exceptions))),
   rationale:unique(parts.map(part=>part.rationale).filter((text):text is string=>typeof text==='string'&&!!text)),
   ...savedState(parts),
   parentKeys:[...node.parentKeys,...(node.missingParents?['unavailable-parent']:[])],original,
   selection:{key:node.entryKey,version:revisionKey(node.revision)},
   source:{knowledge:node.claimId,record:record.id,version:record.version,entries:parts}};
 });
 return <KnowledgeRevisionHistory key={entry.key} revisions={revisions} summary={revisions.length>1?'查看修订记录':'查看初始记录'} missingInitial={!revisions.some(row=>row.original)} selected={{key:entry.key,version:revisionKey(selected)}} onRead={onRead}/>;
}

export function EvolutionRevisionHistory({data}:{data:Json}){
 const current=data.claim;
 // History may include the selected revision, duplicates, or newer records in legacy captures.
 const claims=new Map<number,Json>();
 for(const claim of [...(Array.isArray(data.history)?data.history:[]),current]){
  if(claim?.id!==current.id||!Number.isInteger(claim.version)||claim.version<1||claim.version>current.version)continue;
  if(data.reading_round!==undefined&&!(typeof claim.registered_round==='number'&&claim.registered_round<=data.reading_round))continue;
  claims.set(claim.version,claim);
 }
 const revisions:Revision[]=[...claims.values()].sort((a,b)=>a.version-b.version).map(claim=>({
  key:`${claim.id}:${claim.version}`,label:`${claim.id} · 第 ${claim.version} 版`,text:claim.text||'未提供知识正文',
  rules:Array.isArray(claim.rules)?claim.rules:[],conditions:[],exceptions:[],rationale:claim.rationale?[claim.rationale]:[],
  ...savedState([claim],true),
  parentKeys:claim.parent?.id&&Number.isInteger(claim.parent.version)?[`${claim.parent.id}:${claim.parent.version}`]:claim.version>1?[`${claim.id}:${claim.version-1}`]:[],
  original:claim.version===1,round:claim.registered_round,
  source:{id:claim.id,version:claim.version,registered_round:claim.registered_round,parent:claim.parent,text:claim.text,rules:claim.rules,rationale:claim.rationale,...savedFields(claim,['status','source_status','source_refs','metadata','validity_status','validation_origin','inject','inject_same','role','usage_note'])},
 }));
 return <KnowledgeRevisionHistory revisions={revisions} summary="登记与修订记录" missingInitial={!revisions.some(row=>row.original)} truncated={data.history_truncated===true}/>;
}
