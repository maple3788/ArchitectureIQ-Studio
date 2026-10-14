import {revisionKey,type KnowledgeContentSource,type KnowledgeEntry,type KnowledgeRevision} from './knowledgeEntries';
import type {Json} from './types';

export type ForestNode={key:string;entry:KnowledgeEntry;revision:KnowledgeRevision;parentKeys:string[];missingParents:string[];context:boolean;sourceClaim?:Json};
export type KnowledgeGrove={key:string;roots:string[];nodes:ForestNode[]};

const object=(value:unknown):value is Json=>!!value&&typeof value==='object'&&!Array.isArray(value);
const nonempty=(value:unknown):value is string=>typeof value==='string'&&!!value.trim();
const versionNumber=(value:unknown):value is number=>Number.isSafeInteger(value)&&Number(value)>0;
const nodeKey=({entry,revision}:KnowledgeContentSource)=>`${entry.key}@${revisionKey(revision)}`;
const tuple=(...values:unknown[])=>JSON.stringify(values);
function sourceClaim({entry,revision}:KnowledgeContentSource):Json|undefined{
 const claims=revision.record.snapshot?.source_document?.source_claims;
 return Array.isArray(claims)?claims.find(claim=>object(claim)&&claim.id===entry.claimId):undefined;
}
function claimReference(parent:Json){
 return `${nonempty(parent.id)?parent.id:'未知知识'} · 第 ${typeof parent.version==='number'||typeof parent.version==='string'?parent.version:'未知'} 版`;
}
function missing(node:ForestNode,reference:string){
 if(!node.missingParents.includes(reference))node.missingParents.push(reference);
}

/** Derive presentation only from exact saved references; never change the source snapshots. */
export function buildKnowledgeForest(entries:KnowledgeEntry[],matches:KnowledgeContentSource[]):{groves:KnowledgeGrove[];independent:ForestNode[];matchedCount:number}{
 const candidates=new Map<string,ForestNode>(),evolution=new Map<string,ForestNode[]>(),rules=new Map<string,ForestNode[]>();
 const matchedKeys=new Set(matches.map(nodeKey));
 const addIndex=(index:Map<string,ForestNode[]>,key:string,node:ForestNode)=>{
  const values=index.get(key)??[];if(!values.some(value=>value.key===node.key))values.push(node);index.set(key,values);
 };
 for(const entry of entries)for(const revision of entry.revisions){
  const key=nodeKey({entry,revision});if(candidates.has(key))continue;
  const node:ForestNode={key,entry,revision,parentKeys:[],missingParents:[],context:!matchedKeys.has(key),sourceClaim:sourceClaim({entry,revision})};
  candidates.set(key,node);
  const record=revision.record,identity=record.provenance?.source_identity;
  if(record.source_kind==='knowledge_evolution'){
   if(nonempty(identity)&&node.sourceClaim&&versionNumber(node.sourceClaim.version))addIndex(evolution,tuple(entry.library.key,identity,entry.claimId,node.sourceClaim.version),node);
  }else for(const part of revision.parts){
   if(nonempty(part.rule_id)&&nonempty(part.revision))addIndex(rules,tuple(entry.library.key,record.version,part.rule_id,part.revision),node);
  }
 }
 const selected=new Map<string,ForestNode>();
 const add=(node:ForestNode)=>{if(!selected.has(node.key))selected.set(node.key,node);};
 for(const key of matchedKeys){const node=candidates.get(key);if(node)add(node);}
 const matchedCount=selected.size;
 const rank=(node:ForestNode)=>node.entry.library.versions.findIndex(record=>`${record.id}:${record.version}`===revisionKey(node.revision));
 // Repeated captures can contain the same claim version. Prefer its copy in the
 // child's saved snapshot, then an earlier save; never replace it with a new version.
 const chooseParent=(node:ForestNode,options:ForestNode[])=>options.find(parent=>revisionKey(parent.revision)===revisionKey(node.revision))
  ??options.filter(parent=>rank(parent)>=rank(node)&&rank(node)>=0).sort((a,b)=>rank(a)-rank(b))[0];
 const connect=(node:ForestNode,parent:ForestNode,reference:string)=>{
  if(parent.key===node.key){missing(node,`${reference}（自引用）`);return;}
  if(!node.parentKeys.includes(parent.key))node.parentKeys.push(parent.key);
  add(parent);
 };
 // Map iteration includes newly added ancestors, without recursive depth limits.
 for(const node of selected.values()){
  const {record}=node.revision;
  if(record.source_kind==='knowledge_evolution'){
   const parent=node.sourceClaim?.parent;
   if(parent===undefined||parent===null)continue;
   if(!object(parent)){missing(node,'父知识引用格式不完整');continue;}
   const reference=claimReference(parent),identity=record.provenance?.source_identity;
   if(!nonempty(parent.id)||!versionNumber(parent.version)||!nonempty(identity)){
    missing(node,`${reference}（引用或来源不完整）`);continue;
   }
   const resolved=chooseParent(node,evolution.get(tuple(node.entry.library.key,identity,parent.id,parent.version))??[]);
   if(resolved)connect(node,resolved,reference);else missing(node,`${reference}（保存版本不可用）`);
  }else for(const part of node.revision.parts){
   if(part.parents===undefined||part.parents===null)continue;
   if(!Array.isArray(part.parents)){missing(node,'父规则引用格式不完整');continue;}
   for(const parent of part.parents){
    if(!object(parent)||!nonempty(parent.rule_id)||!nonempty(parent.revision)){
     missing(node,'父规则引用格式不完整');continue;
    }
    const reference=`${parent.rule_id} · ${parent.revision}`,parentVersion=record.snapshot?.parent_version;
    const resolved=nonempty(parentVersion)?rules.get(tuple(node.entry.library.key,parentVersion,parent.rule_id,parent.revision))??[]:[];
    if(!resolved.length){missing(node,`${reference}（保存版本不可用）`);continue;}
    for(const value of resolved)connect(node,value,reference);
   }
  }
 }
 // Remove only back edges from malformed cyclic input. Retain the recorded
 // reference as a visible missing-parent notice so it cannot look like a root claim.
 const visited=new Map<string,'visiting'|'done'>();
 for(const initial of selected.values()){
  if(visited.has(initial.key))continue;
  const stack=[{node:initial,index:0}];visited.set(initial.key,'visiting');
  while(stack.length){
   const frame=stack[stack.length-1],parentKey=frame.node.parentKeys[frame.index];
   if(parentKey===undefined){visited.set(frame.node.key,'done');stack.pop();continue;}
   const parent=selected.get(parentKey)!;
   if(visited.get(parentKey)==='visiting'){
    frame.node.parentKeys.splice(frame.index,1);
    missing(frame.node,`${parent.entry.claimId}${parent.sourceClaim?` · 第 ${parent.sourceClaim.version} 版`:''}（循环关系）`);continue;
   }
   frame.index++;
   if(!visited.has(parentKey)){visited.set(parentKey,'visiting');stack.push({node:parent,index:0});}
  }
 }
 const neighbors=new Map([...selected.keys()].map(key=>[key,new Set<string>()]));
 for(const node of selected.values())for(const parent of node.parentKeys){neighbors.get(node.key)!.add(parent);neighbors.get(parent)!.add(node.key);}
 const groves:KnowledgeGrove[]=[],independent:ForestNode[]=[],grouped=new Set<string>();
 for(const initial of selected.values()){
  if(grouped.has(initial.key))continue;
  const nodes:ForestNode[]=[],pending=[initial.key];grouped.add(initial.key);
  while(pending.length){
   const key=pending.pop()!;nodes.push(selected.get(key)!);
   for(const neighbor of neighbors.get(key)!)if(!grouped.has(neighbor)){grouped.add(neighbor);pending.push(neighbor);}
  }
  if(nodes.length===1){independent.push(nodes[0]);continue;}
  const roots=nodes.filter(node=>!node.parentKeys.length).map(node=>node.key).sort();
  groves.push({key:roots[0],roots,nodes});
 }
 return {groves,independent,matchedCount};
}
