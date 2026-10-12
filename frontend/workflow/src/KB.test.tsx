import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {KB} from './KB';
import type {Json} from './types';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const rule=(claimId:string,text:string,index=0)=>({rule_id:`${claimId}:${index}`,revision:'rule-fixed',state:'active',text,
 rule:{scope:['model_type','eq','mlp'],predict:{higher_better:'depth'}},
 metadata:{claim_id:claimId,clause_index:index,validity_status:'proposed',validation_origin:'source_reported'}});
const libraryVersion=(label:string,order:number,parts:Json[]=[rule('R1',`版本 ${label} 的知识`)])=>({
 id:`builtin:kb-${label}`,version:`hash-${label}`,kind:'research_rules',name:`KB ${label}`,
 library:{id:'builtin:architecture-rules',name:'架构与优化器规则',version_label:label,version_order:order},
 snapshot:{source_document:{version_label:label},rules:parts},sources:[]
});
function inventory(items:Json[]){
 const paths:string[]=[];
 vi.stubGlobal('fetch',async(path:string)=>{paths.push(path);return new Response(JSON.stringify(path.includes('/kb/questions?')?
  {items:[],counts:{applicable:0,inapplicable:0,unknown:0},total:0,offset:0,limit:25}:
  path.endsWith('/kb')?{items}:{}));});
 return paths;
}
it('folds duplicate sources without adding evidence and preserves source-specific history and exact question references',async()=>{
 const imported=libraryVersion('v10',10,[rule('O1','相同规则正文')]);
 const earlier=libraryVersion('v9',9,[rule('O1','导入第一版原文')]);
 const evolved={...libraryVersion('evolution',1,[rule('C0001','相同规则正文')]),id:'evolution',source_kind:'knowledge_evolution',library:{id:'evolution',name:'知识演化',version_label:'第 3 轮',version_order:1}};
 const counts=(record:Json,id:string,support:number,refute:number)=>{record.evidence_summary={scope:'saved_question_results',unit:'distinct_questions',kb_ref:{id:record.id,version:record.version},claims:{[id]:{support_questions:support,refute_questions:refute,unknown_questions:0,complete:true,notice:'保存的逐题结果'}}};};
 counts(imported,'O1',12,1);counts(evolved,'C0001',22,4);
 const paths=inventory([imported,earlier,evolved]);render(<KB version={0}/>);
 await screen.findByText('1 条知识');
 expect(screen.getAllByRole('button',{name:/^阅读 /})).toHaveLength(1);
 expect(screen.getByText('2 个来源')).toBeTruthy();
 expect(screen.queryByText(/支持 34 题/)).toBeNull();
 fireEvent.change(screen.getByLabelText('支持情况'),{target:{value:'high'}});
 fireEvent.click(screen.getByRole('button',{name:'阅读 C0001 相同规则正文'}));
 let dialog=screen.getByRole('dialog');
 expect(within(dialog).getByText('支持 22 题 · 反例 4 题')).toBeTruthy();
 fireEvent.click(within(dialog).getByText('同内容来源 · 2 个来源'));
 fireEvent.click(within(dialog).getByRole('button',{name:'阅读来源 架构与优化器规则 · O1 · v10'}));
 dialog=screen.getByRole('dialog');
 expect(within(dialog).getByText('支持 12 题 · 反例 1 题')).toBeTruthy();
 expect(within(dialog).queryByText('支持 22 题 · 反例 4 题')).toBeNull();
 fireEvent.click(within(dialog).getByRole('tab',{name:'适用题目'}));
 await waitFor(()=>expect(paths.some(path=>path.includes('/kb/questions?')&&path.includes('kb_id=builtin%3Akb-v10')&&path.includes('kb_version=hash-v10')&&path.includes('claim_id=O1'))).toBe(true));
 const history=within(dialog).getByText('查看修订记录').closest('details')!;history.open=true;fireEvent(history,new Event('toggle'));
 expect(within(dialog).getByText('导入第一版原文')).toBeTruthy();
});
it('lists one logical knowledge statement per row and opens only its executable branches',async()=>{
 inventory([libraryVersion('v10',10,[rule('R6','深度宽度的条件权衡',0),rule('R6','深度宽度的条件权衡',1),rule('R7','另外一条知识')])]);
 render(<KB version={0}/>);
 const button=await screen.findByRole('button',{name:'阅读 R6 深度宽度的条件权衡'});
 expect(screen.getByText('2 条知识')).toBeTruthy();
 expect(screen.getAllByRole('button',{name:/^阅读 R/})).toHaveLength(2);
 fireEvent.click(button);
 const dialog=screen.getByRole('dialog',{name:'知识详情'});
 expect(within(dialog).getAllByRole('heading',{name:'深度宽度的条件权衡'})).toHaveLength(1);
 expect(within(dialog).getByText('分支 1')).toBeTruthy();expect(within(dialog).getByText('分支 2')).toBeTruthy();
 expect(within(dialog).queryByText('另外一条知识')).toBeNull();expect(within(dialog).queryByLabelText('按规则查看')).toBeNull();
 expect(within(dialog).getByRole('tab',{name:'适用题目'})).toBeTruthy();
 expect(within(dialog).getByRole('tab',{name:'不适用题目'})).toBeTruthy();
});
it('keeps exact KB references across library revisions and historical search',async()=>{
 const paths=inventory([libraryVersion('v9',9),libraryVersion('v10',10)]);
 const onEvaluate=vi.fn();render(<KB version={0} onEvaluate={onEvaluate}/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读 R1 版本 v10 的知识'}));
 let dialog=screen.getByRole('dialog');
 expect(within(dialog).getByText('查看修订记录').closest('details')!.open).toBe(false);
 fireEvent.click(within(dialog).getByRole('button',{name:'在 Task 中检查此知识所在 KB'}));
 expect(onEvaluate).toHaveBeenLastCalledWith({id:'builtin:kb-v10',version:'hash-v10'});
 fireEvent.click(within(dialog).getByText('查看修订记录'));
 fireEvent.click(await within(dialog).findByRole('button',{name:'阅读 R1 · v9 的知识与题目'}));
 fireEvent.click(within(dialog).getByRole('button',{name:'在 Task 中检查此知识所在 KB'}));
 expect(onEvaluate).toHaveBeenLastCalledWith({id:'builtin:kb-v9',version:'hash-v9'});
 expect(within(dialog).getByText('正在阅读历史记录。')).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('tab',{name:'适用题目'}));
 await waitFor(()=>expect(paths.some(path=>{const q=new URL(path,'http://localhost').searchParams;return q.get('kb_id')==='builtin:kb-v9'&&q.get('kb_version')==='hash-v9'&&q.get('claim_id')==='R1'&&q.get('relation')==='applicable';})).toBe(true));
 fireEvent.click(within(dialog).getByRole('button',{name:'关闭详情'}));
 fireEvent.change(screen.getByRole('searchbox',{name:'搜索知识库'}),{target:{value:'版本 v9 的知识'}});
 const old=screen.getByRole('button',{name:'阅读 R1 版本 v9 的知识'});
 expect(within(old).getByText('历史记录')).toBeTruthy();
 fireEvent.click(old);dialog=screen.getByRole('dialog');
 expect(within(dialog).getByRole('heading',{name:'版本 v9 的知识'})).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('button',{name:'返回当前知识'}));
 expect(within(dialog).getByRole('heading',{name:'版本 v10 的知识'})).toBeTruthy();
});
it('keeps independent identically named experiments as distinct knowledge entries',async()=>{
 inventory([1,2].map(index=>({id:`run-${index}`,version:`experience-${index}`,kind:'experience',name:'同名实验',
 snapshot:{lessons:[{id:'L1',text:`研究经验${index}`,status:'active',conditions:[`条件${index}`]}],episodes:[]},sources:[{id:`run-${index}`,kind:'run'}]})));
 render(<KB version={0}/>);
 fireEvent.change(await screen.findByLabelText('知识来源'),{target:{value:'experience'}});
 const first=await screen.findByRole('button',{name:'阅读 L1 研究经验1'});
 expect(screen.getByRole('button',{name:'阅读 L1 研究经验2'})).toBeTruthy();
 expect(screen.getByText('2 条知识')).toBeTruthy();fireEvent.click(first);
 const dialog=screen.getByRole('dialog');expect(within(dialog).getByText('条件1')).toBeTruthy();
 expect(within(dialog).queryByText('研究经验2')).toBeNull();expect(within(dialog).queryByText('查看修订记录')).toBeNull();
});
it('reads renamed parent knowledge through its own exact snapshot and question scope',async()=>{
 const previous=libraryVersion('v9',9,[{...rule('R1','修订前的原始命题'),revision:'parent-rule'}]);
 const latest=libraryVersion('v10',10,[{...rule('R2','由旧命题修订的知识'),parents:[{rule_id:'R1:0',revision:'parent-rule'}]}]);
 latest.snapshot={...latest.snapshot,parent_version:'hash-v9'} as typeof latest.snapshot;
 const paths=inventory([latest,previous]);render(<KB version={0}/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读 R2 由旧命题修订的知识'}));
 fireEvent.click(screen.getByText('查看修订记录'));
 fireEvent.click(await screen.findByRole('button',{name:'阅读 R1 · v9 的知识与题目'}));
 const dialog=screen.getByRole('dialog',{name:'知识详情'});
 expect(within(dialog).getByRole('heading',{name:'修订前的原始命题'})).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('tab',{name:'适用题目'}));
 await waitFor(()=>expect(paths.some(path=>{const query=new URL(path,'http://localhost').searchParams;return query.get('kb_id')==='builtin:kb-v9'&&query.get('kb_version')==='hash-v9'&&query.get('claim_id')==='R1';})).toBe(true));
});
it('filters the actually displayed revision rather than borrowing verification from a newer revision',async()=>{
 const latest=libraryVersion('current',2,[{...rule('R1','现在的知识'),metadata:{claim_id:'R1',clause_index:0,validity_status:'replicated_in_scope',validation_origin:'source_reported'}}]);
 inventory([libraryVersion('old',1,[rule('R1','早期未验证假说')]),latest]);
 render(<KB version={0}/>);await screen.findByRole('button',{name:'阅读 R1 现在的知识'});
 fireEvent.change(screen.getByLabelText('验证状态'),{target:{value:'verified'}});
 fireEvent.change(screen.getByRole('searchbox',{name:'搜索知识库'}),{target:{value:'早期未验证'}});
 expect(screen.queryByRole('button',{name:'阅读 R1 早期未验证假说'})).toBeNull();
 expect(screen.getByText('没有找到匹配的知识')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('验证状态'),{target:{value:'pending'}});
 const row=screen.getByRole('button',{name:'阅读 R1 早期未验证假说'});
 expect(within(row).getByText('待验证')).toBeTruthy();expect(within(row).getByText('历史记录')).toBeTruthy();
});
it('retains knowledge removed from the latest library strictly as historical material',async()=>{
 inventory([libraryVersion('old',1,[rule('R1','旧版独有知识')]),libraryVersion('current',2,[rule('R2','当前知识')])]);
 render(<KB version={0}/>);
 const row=await screen.findByRole('button',{name:'阅读 R1 旧版独有知识'});
 expect(within(row).getByText('历史记录')).toBeTruthy();fireEvent.click(row);
 const dialog=screen.getByRole('dialog');
 expect(within(dialog).getByText('当前库版本未收录此知识，正在阅读历史记录。')).toBeTruthy();
 expect(within(dialog).queryByRole('button',{name:'返回当前知识'})).toBeNull();
});
it('reads one formal source claim and binds both question pages to the original claim and frozen version',async()=>{
 const paths=inventory([{id:'formal:experiment',version:'sealed-hash',kind:'formal',name:'研究知识',snapshot:{claims:[
  {id:'K1.a',source_claim_id:'K1',text:'同一原始知识',status:'replicated_in_scope',enabled:true},
  {id:'K1.b',source_claim_id:'K1',text:'同一原始知识',status:'refuted',enabled:false},
  {id:'K2',text:'不相关知识',status:'proposed'}],evidence:[]}}]);
 render(<KB version={0}/>);
 fireEvent.click(await screen.findByRole('button',{name:'阅读 K1 同一原始知识'}));
 const dialog=screen.getByRole('dialog');
 expect(within(dialog).getAllByRole('article')).toHaveLength(1);expect(within(dialog).getByText('2 个条件分支')).toBeTruthy();
 expect(within(dialog).queryByText('不相关知识')).toBeNull();expect(within(dialog).queryByLabelText('查找知识')).toBeNull();
 for(const [label,relation] of [['适用题目','applicable'],['不适用题目','inapplicable']]){
  fireEvent.click(within(dialog).getByRole('tab',{name:label}));
  await waitFor(()=>expect(paths.some(path=>{const q=new URL(path,'http://localhost').searchParams;return q.get('kb_id')==='formal:experiment'&&q.get('kb_version')==='sealed-hash'&&q.get('claim_id')==='K1'&&q.get('relation')===relation;})).toBe(true));
 }
});
it('keeps historical imports behind the source filter without promoting their status',async()=>{
 inventory([{id:'archive',version:'old',kind:'formal',name:'历史导入知识',snapshot:{claims:[{id:'K1',text:'周期边界独特内容',status:'legacy_unverified'}]}}]);
 render(<KB version={0}/>);await screen.findByText('没有找到匹配的知识');
 fireEvent.change(screen.getByLabelText('知识来源'),{target:{value:'history'}});
 const row=screen.getByRole('button',{name:'阅读 K1 周期边界独特内容'});expect(within(row).getByText('待验证')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('验证状态'),{target:{value:'verified'}});
 expect(screen.queryByRole('button',{name:'阅读 K1 周期边界独特内容'})).toBeNull();
});
