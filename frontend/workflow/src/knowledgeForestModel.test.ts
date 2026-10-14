import {describe,expect,it} from 'vitest';
import {knowledgeEntries,type KnowledgeContentSource,type KnowledgeEntry} from './knowledgeEntries';
import {buildKnowledgeForest} from './knowledgeForestModel';
import type {Json} from './types';

const claim=(id:string,version=1,parent:Json|null=null,status='candidate'):Json=>({id,version,parent,status,text:`Saved ${id} v${version}`,rules:[{scope:[],predict:{higher_better:'lr'}}],registered_round:version});
function evolution(version:string,claims:Json[],order=1,source='source-a',library=source):Json{
 return {id:`kb-${source}`,version,kind:'research_rules',source_kind:'knowledge_evolution',provenance:{source_identity:source,sequence:order},library:{id:library,name:library,version_order:order},
  snapshot:{source_document:{source_claims:claims.map(({text:_text,rules:_rules,...saved})=>saved)},rules:claims.filter(item=>!['flagged','retired'].includes(item.status)).map(item=>({rule_id:`${item.id}:1`,revision:`rule-${item.version}`,text:item.text,rule:item.rules[0],metadata:{claim_id:item.id,revision:item.version}}))},
  reading_claims:claims.filter(item=>['flagged','retired'].includes(item.status))};
}
function select(entries:KnowledgeEntry[],id:string,version?:string):KnowledgeContentSource{
 const entry=entries.find(item=>item.claimId===id&&(!version||item.revisions.some(revision=>revision.record.version===version)))!;
 return {entry,revision:entry.revisions.find(revision=>!version||revision.record.version===version)!};
}
const allNodes=(result:ReturnType<typeof buildKnowledgeForest>)=>[...result.groves.flatMap(grove=>grove.nodes),...result.independent];

describe('buildKnowledgeForest',()=>{
 it('keeps the complete multi-level ancestry of a matched descendant as context without adding its siblings',()=>{
  const record=evolution('saved',[claim('A'),claim('B',1,{id:'A',version:1}),claim('C',1,{id:'B',version:1}),claim('D',1,{id:'A',version:1}),claim('Single')]);
  const before=JSON.stringify(record),entries=knowledgeEntries([record]);
  const result=buildKnowledgeForest(entries,[select(entries,'C')]);
  expect(result.matchedCount).toBe(1);expect(result.groves).toHaveLength(1);expect(result.independent).toEqual([]);
  const nodes=result.groves[0].nodes;
  expect(nodes.map(node=>node.entry.claimId).sort()).toEqual(['A','B','C']);
  const a=nodes.find(node=>node.entry.claimId==='A')!,b=nodes.find(node=>node.entry.claimId==='B')!,c=nodes.find(node=>node.entry.claimId==='C')!;
  expect(result.groves[0].roots).toEqual([a.key]);expect(c.parentKeys).toEqual([b.key]);expect(b.parentKeys).toEqual([a.key]);
  expect([a.context,b.context,c.context]).toEqual([true,true,false]);expect(a.sourceClaim?.version).toBe(1);
  expect(JSON.stringify(record)).toBe(before);
  const ancestorOnly=buildKnowledgeForest(entries,[select(entries,'A')]);
  expect(ancestorOnly.groves).toEqual([]);expect(ancestorOnly.independent.map(node=>node.entry.claimId)).toEqual(['A']);
 });

 it('resolves the recorded older parent version and retains flagged and retired reading-only ancestors',()=>{
  const old=evolution('old',[claim('A',1,null,'retired')],1);
  const current=evolution('current',[claim('A',2),claim('B',1,{id:'A',version:1},'flagged'),claim('C',1,{id:'B',version:1})],2);
  const entries=knowledgeEntries([current,old]),result=buildKnowledgeForest(entries,[select(entries,'C')]);
  const nodes=allNodes(result),parent=nodes.find(node=>node.entry.claimId==='A')!;
  expect(nodes.map(node=>[node.entry.claimId,node.revision.record.version]).sort()).toEqual([['A','old'],['B','current'],['C','current']]);
  expect(parent.sourceClaim?.version).toBe(1);expect(parent.revision.parts[0].library_only).toBe(true);
  expect(nodes.find(node=>node.entry.claimId==='B')?.revision.parts[0].library_only).toBe(true);
 });

 it('does not substitute a current parent or a matching id from another source or library',()=>{
  const missing=evolution('child',[claim('A',2),claim('B',1,{id:'A',version:1})],2,'source-a','same-library');
  const foreignSource=evolution('foreign',[claim('A')],1,'source-b','same-library');
  const foreignLibrary=evolution('elsewhere',[claim('A')],1,'source-a','other-library');
  const entries=knowledgeEntries([missing,foreignSource,foreignLibrary]),result=buildKnowledgeForest(entries,[select(entries,'B')]);
  expect(result.groves).toEqual([]);expect(result.independent).toHaveLength(1);
  expect(result.independent[0].parentKeys).toEqual([]);
  expect(result.independent[0].missingParents.join(' ')).toMatch(/A.*1/);
 });

 it('marks malformed references and absent source identity instead of inventing ancestry',()=>{
  const malformed=evolution('saved',[claim('A'),claim('B',1,{id:'A',version:'1'}),claim('C',1,{id:'A',version:1})]);
  delete malformed.provenance.source_identity;
  const entries=knowledgeEntries([malformed]),result=buildKnowledgeForest(entries,[select(entries,'B'),select(entries,'C')]);
  expect(result.groves).toEqual([]);expect(result.independent).toHaveLength(2);
  expect(result.independent.every(node=>node.missingParents.length>0&&node.parentKeys.length===0)).toBe(true);
 });

 it('deduplicates snapshots and exact matches while keeping same-id prior revisions as distinct nodes',()=>{
  const old=evolution('old',[claim('A')],1),current=evolution('current',[claim('A',2,{id:'A',version:1})],2);
  const entries=knowledgeEntries([current,old,old]),selected=select(entries,'A','current');
  const result=buildKnowledgeForest(entries,[selected,selected,select(entries,'A','old')]);
  expect(result.matchedCount).toBe(2);expect(result.groves).toHaveLength(1);
  const nodes=result.groves[0].nodes;
  expect(nodes).toHaveLength(2);expect(nodes.every(node=>!node.context)).toBe(true);
  expect(nodes.find(node=>node.revision.record.version==='current')?.parentKeys).toEqual([nodes.find(node=>node.revision.record.version==='old')!.key]);
 });

 it('cuts cycles and self references so every retained component has readable roots',()=>{
  const entries=knowledgeEntries([evolution('saved',[claim('A',1,{id:'B',version:1}),claim('B',1,{id:'A',version:1}),claim('Self',1,{id:'Self',version:1})])]);
  const result=buildKnowledgeForest(entries,[select(entries,'A'),select(entries,'Self')]);
  expect(result.groves).toHaveLength(1);expect(result.groves[0].roots).toHaveLength(1);
  expect(result.groves[0].nodes.reduce((count,node)=>count+node.parentKeys.length,0)).toBe(1);
  expect(result.groves[0].nodes.some(node=>node.missingParents.length>0)).toBe(true);
  expect(result.independent[0].entry.claimId).toBe('Self');expect(result.independent[0].parentKeys).toEqual([]);expect(result.independent[0].missingParents).toHaveLength(1);
 });

 it('connects non-evolution knowledge only through exact explicit snapshot and rule references',()=>{
  const record=(version:string,order:number,rules:Json[],parent_version?:string,library='rules'):Json=>({id:`rules-${version}`,version,kind:'research_rules',library:{id:library,version_order:order},snapshot:{rules,parent_version}});
  const old=record('old',1,[{rule_id:'first',revision:'rev-1',text:'Original'}]);
  const current=record('current',2,[{rule_id:'second',revision:'rev-2',text:'Revision',parents:[{rule_id:'first',revision:'rev-1'}]}],'old');
  const entries=knowledgeEntries([current,old]),result=buildKnowledgeForest(entries,[select(entries,'second')]);
  expect(result.groves[0].nodes.map(node=>node.entry.claimId).sort()).toEqual(['first','second']);
  for(const changed of [
   {...current,snapshot:{...current.snapshot,parent_version:'absent'}},
   {...current,snapshot:{...current.snapshot,rules:[{...current.snapshot.rules[0],parents:[{rule_id:'first',revision:'wrong'}]}]}},
  ]){
   const input=knowledgeEntries([changed,old]),unresolved=buildKnowledgeForest(input,[select(input,'second')]);
   expect(unresolved.groves).toEqual([]);expect(unresolved.independent[0].missingParents).toHaveLength(1);
  }
  const noRefs=record('no-refs',3,[{rule_id:'first',revision:'rev-3',text:'Unrelated save'}]);
  const unlinked=knowledgeEntries([noRefs,old]);
  expect(buildKnowledgeForest(unlinked,[select(unlinked,'first','no-refs')]).independent).toHaveLength(1);
  expect(buildKnowledgeForest(unlinked,[select(unlinked,'first','no-refs')]).groves).toEqual([]);
 });
});
