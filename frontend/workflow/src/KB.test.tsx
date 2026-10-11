import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { KB } from './KB';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('explains compiled counts and shared sources without presenting hashes as names', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{id:'archive_5c90af39120a9893',kind:'formal',name:'历史导入知识',source_count:3,sources:[{name:'历史材料',kind:'archive'}],counts:{records:299,source_claims:294,split_records:5,verified_enabled:0,legacy_unverified:299},snapshot:{version:'hashabcdef12345678',claims:Array.from({length:299},(_,i)=>({id:'C'+i,source_claim_id:'K'+(i%294),text:'历史主张 '+(i%294),status:'legacy_unverified'}))}}]}))));
 render(<KB version={0}/>);
 fireEvent.click(await screen.findByText('历史材料'));
 expect(screen.getByRole('button',{name:'阅读 历史导入知识'})).toBeTruthy();
 expect(screen.getByText('294 条主张')).toBeTruthy();
 expect(screen.getByText(/3 个来源/)).toBeTruthy();
 expect(screen.queryByRole('heading',{name:'archive_5c90af39120a9893'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'阅读 历史导入知识'}));
 expect(screen.getByText('294 条主张 · 299 个规则子项')).toBeTruthy();
});
it('shows learned experience independently of formal verified knowledge', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{id:'run_deadbeef',kind:'experience',name:'单题学习 · 学习经验',counts:{lessons:1,active_lessons:1,retired_lessons:0,episodes:2,verified_enabled:0},snapshot:{version:'experience_deadbeef',lessons:[{id:'lesson_abc',status:'active',text:'先检查目标函数是否振荡',conditions:['目标函数具有周期性'],source_episode_ids:['e1','e2']}],episodes:[{id:'e1'},{id:'e2'}]}}]}))));
 render(<KB version={0}/>);
 fireEvent.click(await screen.findByText('学习经验'));
 expect(screen.getByText(/1 条经验 · 2 次作答记录/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'阅读 单题学习 · 学习经验'}));
 expect(screen.getByText('先检查目标函数是否振荡')).toBeTruthy();
 expect(screen.getByText('目标函数具有周期性')).toBeTruthy();
 expect(screen.queryByText('这个版本尚无知识条目。')).toBeNull();
});

it('counts imported claims separately from their executable branches',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[{id:'builtin:kb-v10',version:'v10hash',kind:'research_rules',name:'KB v10 · 架构与优化器规则',snapshot:{source_document:{version_label:'v10',filename:'kb_v10_revision.json'},rules:[0,1].map(i=>({rule_id:'R6:'+i,state:'active',metadata:{claim_id:'R6',clause_index:i,validity_status:'proposed',validation_origin:'source_reported'},text:'参数量条件下的深度宽度权衡',rule:{max_param_ratio:2,predict:{higher_better:'depth'}}}))}}]})));
 render(<KB version={0}/>);
 expect(await screen.findByRole('button',{name:'阅读 架构与优化器规则'})).toBeTruthy();
 expect(screen.getByText('1 条主张 · 2 个执行分支')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'阅读 架构与优化器规则'}));
 expect(screen.getAllByRole('heading',{name:'参数量条件下的深度宽度权衡'})).toHaveLength(1);
});

const libraryVersion=(label:string,order:number)=>({
 id:`builtin:kb-${label}`,version:`hash-${label}`,kind:'research_rules',name:`KB ${label}`,
 library:{id:'builtin:architecture-rules',name:'架构与优化器规则',version_label:label,version_order:order},
 snapshot:{source_document:{version_label:label},rules:[{rule_id:`rule-${label}`,revision:'r',state:'active',text:`版本 ${label} 的知识`,rule:{predict:{higher_better:'depth'}},metadata:{claim_id:'R1',clause_index:1,validity_status:'proposed',validation_origin:'source_reported',inject:true}}]},sources:[]
});
it('opens one explicitly grouped library with the latest version and evaluates the selected exact version',async()=>{
 const onEvaluate=vi.fn();vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[libraryVersion('v9',9),libraryVersion('v10',10)]})));
 render(<KB version={0} onEvaluate={onEvaluate}/>);
 expect(await screen.findByRole('button',{name:'阅读 架构与优化器规则'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:'阅读 KB v9'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'阅读 架构与优化器规则'}));
 expect(screen.getByText('版本 v10 的知识')).toBeTruthy();
 expect(screen.queryByLabelText('知识库版本')).toBeNull();
 expect(screen.getByText('查看修订记录').closest('details')!.open).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'在 Task 中检查此规则 KB'}));
 expect(onEvaluate).toHaveBeenLastCalledWith({id:'builtin:kb-v10',version:'hash-v10'});
 fireEvent.click(screen.getByText('查看修订记录'));
 fireEvent.change(screen.getByLabelText('阅读记录'),{target:{value:'builtin:kb-v9:hash-v9'}});
 expect(screen.getByText('版本 v9 的知识')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'在 Task 中检查此规则 KB'}));
 expect(onEvaluate).toHaveBeenLastCalledWith({id:'builtin:kb-v9',version:'hash-v9'});
 expect(screen.getByText('正在阅读历史记录。')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'返回当前知识'}));
 expect(screen.getByText('版本 v10 的知识')).toBeTruthy();
});
it('keeps independent identically named experiments separate inside collapsed experience',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[1,2].map(i=>({id:`run-${i}`,version:`experience-${i}`,kind:'experience',name:'同名实验',snapshot:{lessons:[{id:`L${i}`,text:`研究经验${i}`,status:'active'}],episodes:[]},sources:[{id:`run-${i}`,kind:'run'}]}))})));
 render(<KB version={0}/>);
 const summary=await screen.findByText('学习经验');const section=summary.closest('details')!;
 expect(section.open).toBe(false);
 fireEvent.click(summary);
 expect(screen.getAllByRole('button',{name:'阅读 同名实验'})).toHaveLength(2);
});
it('searches older versions and expands matching historical material without promoting it to verified knowledge',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[libraryVersion('v9',9),libraryVersion('v10',10),{id:'archive',version:'old',kind:'formal',name:'历史导入知识',counts:{records:1,source_claims:1,legacy_unverified:1},snapshot:{claims:[{id:'K1',text:'周期边界独特内容',status:'legacy_unverified'}]}}]})));
 render(<KB version={0}/>);await screen.findByText('历史材料');
 expect(screen.getByText('历史材料').closest('details')!.open).toBe(false);
 fireEvent.change(screen.getByRole('searchbox',{name:'搜索知识库'}),{target:{value:'周期边界'}});
 expect(screen.getByText('历史材料').closest('details')!.open).toBe(true);
 expect(screen.getByRole('button',{name:'阅读 历史导入知识'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:'阅读 架构与优化器规则'})).toBeNull();
 fireEvent.change(screen.getByRole('searchbox',{name:'搜索知识库'}),{target:{value:'版本 v9 的知识'}});
 fireEvent.click(screen.getByRole('button',{name:'阅读 架构与优化器规则'}));
 expect(screen.getByText('版本 v9 的知识')).toBeTruthy();
});
