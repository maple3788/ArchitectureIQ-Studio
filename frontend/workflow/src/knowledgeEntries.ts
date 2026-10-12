import {groupKnowledgeLibraries,isExperience,knowledgeVersionKey} from './knowledgeLibrary';
import type {KnowledgeLibrary} from './knowledgeLibrary';
import type {Json} from './types';

export type KnowledgeRevision={record:Json;parts:Json[]};
export type KnowledgeEntry={key:string;claimId:string;library:KnowledgeLibrary;revisions:KnowledgeRevision[]};
export function knowledgeEntries(records:Json[]):KnowledgeEntry[]{
 return groupKnowledgeLibraries(records).flatMap(library=>{
  const entries=new Map<string,KnowledgeEntry>();
  const seenRecords=new Set<string>();
  for(const record of library.versions){
   const recordKey=knowledgeVersionKey(record);
   if(seenRecords.has(recordKey))continue;
   seenRecords.add(recordKey);
   const snapshot=record.snapshot??{},stored:Json[]=isExperience(record)?snapshot.lessons??[]:record.kind==='research_rules'?snapshot.rules??[]:snapshot.claims??[];
   const represented=new Set(stored.map(part=>part.metadata?.claim_id??part.source_claim_id??part.rule_id??part.id));
   const reading:Json[]=record.source_kind==='knowledge_evolution'&&Array.isArray(record.reading_claims)?record.reading_claims:[];
   const parts:Json[]=[...stored,...reading.filter(claim=>!represented.has(claim.id)).flatMap(claim=>{
    const rules=Array.isArray(claim.rules)&&claim.rules.length?claim.rules:[undefined];
    return rules.map((rule:Json|undefined)=>({...claim,source_claim_id:claim.id,source_status:claim.status,revision:claim.version,rule,library_only:true}));
   })];
   const grouped=new Map<string,Json[]>();
   parts.forEach((part,index)=>{const id=String(part.metadata?.claim_id??part.source_claim_id??part.rule_id??part.id??`record-${index}`);grouped.set(id,[...(grouped.get(id)??[]),part]);});
   for(const [claimId,parts] of grouped){
    if(!entries.has(claimId))entries.set(claimId,{key:`${library.key}:${claimId}`,claimId,library,revisions:[]});
    entries.get(claimId)!.revisions.push({record,parts});
   }
  }
  return [...entries.values()];
 });
}
export function entryText(revision:KnowledgeRevision){return [...new Set(revision.parts.map(part=>part.text).filter(Boolean))].join('；')||'未提供知识正文';}
export function entryState(revision:KnowledgeRevision){
 const parts=revision.parts.filter(part=>part.state!=='retired'&&part.status!=='retired');
 if(!parts.length)return revision.parts.length?'retired':'pending';
 if(parts.some(part=>part.status==='flagged'))return 'flagged';
 if(isExperience(revision.record))return 'pending';
 if(parts.some(part=>part.status==='refuted'||part.metadata?.validity_status==='refuted'))return 'refuted';
 if(parts.every(part=>revision.record.kind==='research_rules'
  ?part.metadata?.validity_status==='replicated_in_scope'&&part.metadata?.validation_origin==='source_reported'
  :part.status==='replicated_in_scope'))return 'verified';
 return 'pending';
}
export const entryStateLabels:Record<string,string>={retired:'已停用',flagged:'来源已标记',refuted:'存在反例',verified:'范围内已验证',pending:'待验证'};
export function evolutionSourceLabel(revision:KnowledgeRevision){
 if(revision.record.source_kind!=='knowledge_evolution')return undefined;
 const names:Record<string,string>={candidate:'候选',verified:'已验证',flagged:'已标记',retired:'已退役'};
 const statuses=[...new Set(revision.parts.flatMap(part=>[part.source_status,...(Array.isArray(part.source_refs)?part.source_refs.map((ref:Json)=>ref.source_status):[])]).filter((value):value is string=>typeof value==='string'&&Boolean(value)))];
 return statuses.length?`演化来源：${statuses.map(value=>names[value]??value).join('、')}`:'演化来源状态未记录';
}
export function revisionMatches(entry:KnowledgeEntry,revision:KnowledgeRevision,search:string){
 return [entry.claimId,entry.library.name,entryText(revision),revision.record.library?.version_label].join(' ').toLocaleLowerCase().includes(search.trim().toLocaleLowerCase());
}
export function revisionKey(revision:KnowledgeRevision){return knowledgeVersionKey(revision.record);}
export function currentEntryRevision(entry:KnowledgeEntry){
 return entry.revisions.find(revision=>revisionKey(revision)===knowledgeVersionKey(entry.library.versions[0]));
}
export function displayedEntryRevision(entry:KnowledgeEntry,search:string){
 return entry.revisions.find(revision=>revisionMatches(entry,revision,search));
}

export type KnowledgeHistoryEntry={key:string;entryKey:string;claimId:string;revision:KnowledgeRevision;parentKeys:string[];missingParents:boolean};
/** Read ancestry only within an explicitly grouped library and exact snapshot/rule references. */
export function knowledgeEntryHistory(entry:KnowledgeEntry):KnowledgeHistoryEntry[]{
 const nodes=knowledgeEntries(entry.library.versions).flatMap(item=>item.revisions.map(revision=>({
  key:`${item.key}@${revisionKey(revision)}`,entryKey:item.key,claimId:item.claimId,revision,parentKeys:[] as string[],missingParents:false,
 })));
 const chosen=new Map<string,KnowledgeHistoryEntry>();
 function visit(node:KnowledgeHistoryEntry){
  if(chosen.has(node.key))return;
  chosen.set(node.key,node);
  const refs:Json[]=node.revision.parts.flatMap(part=>Array.isArray(part.parents)?part.parents:[]);
  for(const ref of refs){
   if(!ref||typeof ref.rule_id!=='string'||typeof ref.revision!=='string'||typeof node.revision.record.snapshot?.parent_version!=='string'){node.missingParents=true;continue;}
   const parents=nodes.filter(candidate=>candidate.revision.record.version===node.revision.record.snapshot?.parent_version&&candidate.revision.parts.some(part=>part.rule_id===ref.rule_id&&part.revision===ref.revision));
   if(!parents.length)node.missingParents=true;
   for(const parent of parents){if(!node.parentKeys.includes(parent.key))node.parentKeys.push(parent.key);visit(parent);}
  }
  if(!refs.length){
   const versions=nodes.filter(candidate=>candidate.entryKey===node.entryKey);
   const previous=versions[versions.indexOf(node)+1];
   if(previous){node.parentKeys.push(previous.key);visit(previous);}
  }
 }
 nodes.filter(node=>node.entryKey===entry.key).forEach(visit);
 return [...chosen.values()].sort((a,b)=>entry.library.versions.indexOf(b.revision.record)-entry.library.versions.indexOf(a.revision.record)||a.claimId.localeCompare(b.claimId));
}
