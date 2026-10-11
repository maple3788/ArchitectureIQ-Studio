import {expect,it} from 'vitest';
import {groupKnowledgeLibraries} from './knowledgeLibrary';
it('groups only explicit library identity and never uses shared names or ancestry as identity',()=>{
 const items=[{id:'a',version:'a',kind:'research_rules',name:'研究',snapshot:{parent_version:'shared'}},
 {id:'b',version:'b',kind:'research_rules',name:'研究',snapshot:{parent_version:'a'}},
 {id:'v9',version:'nine',kind:'research_rules',library:{id:'arch',name:'架构',version_order:9}},
 {id:'v10',version:'ten',kind:'research_rules',library:{id:'arch',name:'架构',version_order:10}}];
 const before=JSON.stringify(items);const groups=groupKnowledgeLibraries(items);
 expect(groups).toHaveLength(3);
 expect(groups.find(group=>group.name==='架构')?.versions.map(item=>item.id)).toEqual(['v10','v9']);
 expect(JSON.stringify(items)).toBe(before);
});
it('archives only wholly legacy knowledge and keeps mixed or current formal knowledge visible',()=>{
 const groups=groupKnowledgeLibraries([
 {id:'legacy',version:'a',kind:'formal',counts:{records:2,legacy_unverified:2},snapshot:{claims:[{id:'k1',status:'legacy_unverified'},{id:'k2',status:'legacy_unverified'}]}},
 {id:'mixed',version:'b',kind:'formal',counts:{records:2,legacy_unverified:1},snapshot:{claims:[{id:'k1',status:'legacy_unverified'},{id:'k2',status:'proposed'}]}},
 {id:'experience',version:'c',kind:'experience',snapshot:{lessons:[]}},
 ]);
 expect(groups.map(group=>[group.versions[0].id,group.section])).toEqual([['legacy','history'],['mixed','knowledge'],['experience','experience']]);
});
it('keeps ungrouped selection identities stable when inventory order changes',()=>{
 const a={id:'run-a',version:'a',kind:'experience'},b={id:'run-b',version:'b',kind:'experience'};
 const before=groupKnowledgeLibraries([a,b]),after=groupKnowledgeLibraries([b,a]);
 expect(before.find(group=>group.versions[0].id==='run-a')!.key).toBe(after.find(group=>group.versions[0].id==='run-a')!.key);
});
