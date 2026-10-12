import {expect,it} from 'vitest';
import {knowledgeEntries,entryState,entryText,knowledgeEntryHistory,knowledgeContentGroups,knowledgeEquivalentSources} from './knowledgeEntries';
const rule=(id:string,clause:number)=>({rule_id:`${id}:${clause}`,text:'同一知识',metadata:{claim_id:id,clause_index:clause,validity_status:'proposed'}});
it('groups compiled branches into one logical claim while preserving explicit versions and independent experiments',()=>{
 const shared={kind:'research_rules',name:'同名研究'};
 const earlier={...shared,id:'old',version:'old-hash',library:{id:'explicit',version_order:1},snapshot:{rules:[rule('R1',0)]}};
 const latest={...shared,id:'new',version:'new-hash',library:{id:'explicit',version_order:2},snapshot:{rules:[rule('R1',0),rule('R1',1),rule('R2',0)]}};
 const independent={...shared,id:'experiment',version:'separate',snapshot:{rules:[rule('R1',0)]}};
 const input=[earlier,latest,independent,latest],before=JSON.stringify(input),entries=knowledgeEntries(input);
 expect(entries).toHaveLength(3);
 const grouped=entries.find(entry=>entry.claimId==='R1'&&entry.library.key.includes('explicit'))!;
 expect(grouped.revisions.map(item=>item.record.id)).toEqual(['new','old']);expect(grouped.revisions[0].parts).toHaveLength(2);
 expect(entryText(grouped.revisions[0])).toBe('同一知识');expect(new Set(entries.map(entry=>entry.key)).size).toBe(3);
 expect(JSON.stringify(input)).toBe(before);
});
it('reads renamed parent knowledge only through exact rule and snapshot references in the same library',()=>{
 const old={kind:'research_rules',id:'old',version:'old-hash',library:{id:'study',version_order:1},snapshot:{rules:[{...rule('R1',0),revision:'r1',text:'最初保存的正文'}]}};
 const next={kind:'research_rules',id:'new',version:'new-hash',library:{id:'study',version_order:2},snapshot:{parent_version:'old-hash',rules:[{...rule('R2',0),revision:'r2',text:'修订后的正文',parents:[{rule_id:'R1:0',revision:'r1'}]}]}};
 const entry=knowledgeEntries([next,old]).find(item=>item.claimId==='R2')!;
 expect(knowledgeEntryHistory(entry).map(item=>[item.claimId,item.revision.record.version])).toEqual([['R1','old-hash'],['R2','new-hash']]);
 const unrelated={...old,id:'unrelated',library:{id:'another-study',version_order:1}};
 const isolated=knowledgeEntries([next,unrelated]).find(item=>item.claimId==='R2')!;
 expect(knowledgeEntryHistory(isolated)).toHaveLength(1);
 next.snapshot.parent_version='not-the-recorded-snapshot';
 expect(knowledgeEntryHistory(knowledgeEntries([next,old]).find(item=>item.claimId==='R2')!)).toHaveLength(1);
 next.snapshot.parent_version='old-hash';
 next.snapshot.rules[0].parents[0].revision='different-revision';
 expect(knowledgeEntryHistory(knowledgeEntries([next,old]).find(item=>item.claimId==='R2')!)).toHaveLength(1);
});
it('uses active branches for current state and never calls locally modified or experience knowledge verified',()=>{
 const verified={state:'active',metadata:{validity_status:'replicated_in_scope',validation_origin:'source_reported'}};
 expect(entryState({record:{kind:'research_rules'},parts:[verified,{state:'retired',metadata:{validity_status:'refuted'}}]})).toBe('verified');
 expect(entryState({record:{kind:'research_rules'},parts:[verified,{state:'active',metadata:{validity_status:'refuted'}}]})).toBe('refuted');
 expect(entryState({record:{kind:'research_rules'},parts:[{...verified,metadata:{...verified.metadata,validation_origin:'modified_in_studio'}}]})).toBe('pending');
 expect(entryState({record:{kind:'experience'},parts:[{status:'replicated_in_scope'}]})).toBe('pending');
 expect(entryState({record:{kind:'formal'},parts:[{status:'retired'}]})).toBe('retired');
});

it('folds identical content and rules only in presentation while retaining exact source histories',()=>{
 const clause={scope:[['opt','eq','Adam']],predict:{higher_better:'lr'}};
 const record=(id:string,claimId:string,version:string,order:number,text='相同正文')=>({id,version,kind:'research_rules',library:{id,name:id,version_order:order},snapshot:{rules:[{...rule(claimId,0),text,rule:clause,state:'active',metadata:{claim_id:claimId,validity_status:'proposed',inject:true}}]}});
 const old=record('imported','O1','old',1,'最初原文'),current=record('imported','O1','new',2),evolution=record('evolution','C1','ev',1);
 evolution.snapshot.rules[0].rule={predict:{higher_better:'lr'},scope:[['opt','eq','Adam']]};
 const records=[old,current,evolution],before=JSON.stringify(records),entries=knowledgeEntries(records);
 const groups=knowledgeContentGroups(entries,'');
 expect(groups).toHaveLength(1);
 expect(groups[0].sources.map(source=>[source.entry.claimId,source.revision.record.version])).toEqual([['O1','new'],['C1','ev']]);
 expect(knowledgeEntryHistory(entries[0]).map(node=>entryText(node.revision))).toEqual(['最初原文','相同正文']);
 expect(knowledgeEquivalentSources(entries,entries[0].revisions[1])).toHaveLength(1);
 expect(knowledgeContentGroups(entries,'O1')[0].sources.map(source=>source.entry.claimId)).toEqual(['O1']);
 expect(JSON.stringify(records)).toBe(before);
});

it('does not fold missing rules or changed executable, applicability, or validation boundaries',()=>{
 const base={kind:'research_rules',snapshot:{rules:[{...rule('R1',0),state:'active',rule:{scope:[['opt','eq','Adam']],predict:{higher_better:'lr'}},metadata:{claim_id:'R1',validity_status:'proposed',inject:true,inject_same:[]}}]}};
 for(const change of [
  {rule:undefined},{rule:{scope:[['opt','eq','SGD']],predict:{higher_better:'lr'}}},
  {conditions:['仅适用于新范围']},{exceptions:['新增例外']},{state:'retired'},
  {metadata:{...base.snapshot.rules[0].metadata,validity_status:'replicated_in_scope'}},
  {metadata:{...base.snapshot.rules[0].metadata,inject:false}},
  {metadata:{...base.snapshot.rules[0].metadata,inject_same:['depth']}},
 ]){
  const changed={...base,id:'other',version:'other',snapshot:{rules:[{...base.snapshot.rules[0],...change}]}};
  expect(knowledgeContentGroups(knowledgeEntries([{...base,id:'base',version:'base'},changed]),'')).toHaveLength(2);
 }
});
