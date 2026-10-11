import type {Json} from './types';
import {readableName} from './displayNames';

export type KnowledgeLibrary={key:string;name:string;section:'knowledge'|'experience'|'history';versions:Json[]};
export const isExperience=(record:Json)=>record.kind==='experience'||Array.isArray(record.snapshot?.lessons);
export const knowledgeVersionKey=(record:Json)=>`${record.id}:${record.version}`;
export function knowledgeTitle(record:Json){
 return readableName(record.name||record.title,isExperience(record)?'学习经验':record.counts?.legacy_unverified?'历史导入知识':'知识快照');
}
function whollyLegacy(record:Json){
 const claims=record.snapshot?.claims;
 if(Array.isArray(claims)&&claims.length)return claims.every((claim:Json)=>claim.status==='legacy_unverified');
 return record.counts?.records>0&&record.counts.legacy_unverified===record.counts.records;
}
/** Group presentation only by a server-declared library identity. Never infer
 * experiment identity from matching names, content or shared parent snapshots. */
export function groupKnowledgeLibraries(records:Json[]):KnowledgeLibrary[]{
 const groups=new Map<string,KnowledgeLibrary>();
 records.forEach((record,index)=>{
  const explicit=typeof record.library?.id==='string'&&record.library.id.trim();
  const key=explicit?`library:${record.kind}:${explicit}`:`record:${record.kind}:${record.id??index}:${record.version??index}`;
  if(!groups.has(key))groups.set(key,{key,name:explicit?readableName(record.library.name,'知识库'):knowledgeTitle(record),section:'knowledge',versions:[]});
  groups.get(key)!.versions.push(record);
 });
 return [...groups.values()].map(group=>{
  group.versions.sort((a,b)=>(Number(b.library?.version_order)||0)-(Number(a.library?.version_order)||0));
  const latest=group.versions[0];
  group.section=isExperience(latest)?'experience':group.versions.every(whollyLegacy)?'history':'knowledge';
  return group;
 });
}
export function knowledgeMatches(record:Json,query:string){
 const needle=query.trim().toLocaleLowerCase();if(!needle)return true;
 const snapshot=record.snapshot??{};
 const statements=[...(snapshot.rules??[]),...(snapshot.claims??[]),...(snapshot.lessons??[])];
 return [record.name,record.title,record.library?.name,record.library?.version_label,
  ...statements.flatMap((entry:Json)=>[entry.id,entry.metadata?.claim_id,entry.text])]
 .filter(value=>typeof value==='string').join(' ').toLocaleLowerCase().includes(needle);
}
