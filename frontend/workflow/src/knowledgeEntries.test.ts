import {expect,it} from 'vitest';
import {knowledgeEntries,entryState,entryText,knowledgeEntryHistory} from './knowledgeEntries';
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
