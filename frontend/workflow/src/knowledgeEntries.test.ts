import {expect,it} from 'vitest';
import {knowledgeEntries,entryState,entryText} from './knowledgeEntries';
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
it('uses active branches for current state and never calls locally modified or experience knowledge verified',()=>{
 const verified={state:'active',metadata:{validity_status:'replicated_in_scope',validation_origin:'source_reported'}};
 expect(entryState({record:{kind:'research_rules'},parts:[verified,{state:'retired',metadata:{validity_status:'refuted'}}]})).toBe('verified');
 expect(entryState({record:{kind:'research_rules'},parts:[verified,{state:'active',metadata:{validity_status:'refuted'}}]})).toBe('refuted');
 expect(entryState({record:{kind:'research_rules'},parts:[{...verified,metadata:{...verified.metadata,validation_origin:'modified_in_studio'}}]})).toBe('pending');
 expect(entryState({record:{kind:'experience'},parts:[{status:'replicated_in_scope'}]})).toBe('pending');
 expect(entryState({record:{kind:'formal'},parts:[{status:'retired'}]})).toBe('retired');
});
