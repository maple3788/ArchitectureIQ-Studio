import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { KB } from './KB';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('explains compiled counts and shared sources without presenting hashes as names', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{id:'archive_5c90af39120a9893',kind:'formal',name:'历史导入知识',source_count:3,sources:[{name:'历史材料',kind:'archive'}],counts:{records:299,source_claims:294,split_records:5,verified_enabled:0,legacy_unverified:299},snapshot:{version:'hashabcdef12345678',claims:Array.from({length:299},(_,i)=>({id:'C'+i,status:'legacy_unverified'}))}}]}))));
 render(<KB version={0}/>);
 expect(await screen.findByRole('heading',{name:'历史导入知识'})).toBeTruthy();
 expect(screen.getByText(/294 条原始主张/)).toBeTruthy();
 expect(screen.getByText(/5 条拆分记录/)).toBeTruthy();
 expect(screen.getByText(/3 个来源/)).toBeTruthy();
 expect(screen.queryByRole('heading',{name:'archive_5c90af39120a9893'})).toBeNull();
});
it('shows learned experience independently of formal verified knowledge', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{id:'run_deadbeef',kind:'experience',name:'单题学习 · 学习经验',counts:{lessons:1,active_lessons:1,retired_lessons:0,episodes:2,verified_enabled:0},snapshot:{version:'experience_deadbeef',lessons:[{id:'lesson_abc',status:'active',text:'先检查目标函数是否振荡',conditions:['目标函数具有周期性'],source_episode_ids:['e1','e2']}],episodes:[{id:'e1'},{id:'e2'}]}}]}))));
 render(<KB version={0}/>);
 expect(await screen.findByText(/1 条经验 · 2 次作答记录/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'查看记录'}));
 expect(screen.getByText('先检查目标函数是否振荡')).toBeTruthy();
 expect(screen.getByText('目标函数具有周期性')).toBeTruthy();
 expect(screen.queryByText('这个版本尚无知识条目。')).toBeNull();
});

it('counts imported claims separately from their executable branches',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[{id:'builtin:kb-v10',version:'v10hash',kind:'research_rules',name:'KB v10 · 架构与优化器规则',snapshot:{source_document:{version_label:'v10',filename:'kb_v10_revision.json'},rules:[0,1].map(i=>({rule_id:'R6:'+i,state:'active',metadata:{claim_id:'R6',clause_index:i,validity_status:'proposed',validation_origin:'source_reported'},text:'参数量条件下的深度宽度权衡',rule:{max_param_ratio:2,predict:{higher_better:'depth'}}}))}}]})));
 render(<KB version={0}/>);
 expect(await screen.findByRole('heading',{name:'KB v10 · 架构与优化器规则'})).toBeTruthy();
 expect(screen.getByText('1 条主张 · 2 个执行分支')).toBeTruthy();
 expect(screen.getByText('内置研究版本')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'查看记录'}));
 expect(screen.getAllByRole('heading',{name:'参数量条件下的深度宽度权衡'})).toHaveLength(1);
});
