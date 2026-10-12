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
   const snapshot=record.snapshot??{},parts:Json[]=isExperience(record)?snapshot.lessons??[]:record.kind==='research_rules'?snapshot.rules??[]:snapshot.claims??[];
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
 if(isExperience(revision.record))return 'pending';
 if(parts.some(part=>part.status==='refuted'||part.metadata?.validity_status==='refuted'))return 'refuted';
 if(parts.every(part=>revision.record.kind==='research_rules'
  ?part.metadata?.validity_status==='replicated_in_scope'&&part.metadata?.validation_origin==='source_reported'
  :part.status==='replicated_in_scope'))return 'verified';
 return 'pending';
}
export const entryStateLabels:Record<string,string>={retired:'已停用',refuted:'存在反例',verified:'范围内已验证',pending:'待验证'};
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
