import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {KB} from './KB';
import {knowledgeSupport} from './knowledgeSupport';
import type {Json} from './types';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

function item(id:string,support:number|null,refute:number|null,version='v1',verified=false):Json{
 return {id,version,kind:'research_rules',name:id,
  library:{id,name:id,version_label:version,version_order:version==='v2'?2:1},
  snapshot:{rules:[{rule_id:'R1:0',revision:`${id}-${version}`,state:'active',text:`${id} ${version} 正文`,rule:{predict:{higher_better:'width'}},
   metadata:{claim_id:'R1',validity_status:verified?'replicated_in_scope':'proposed',validation_origin:'source_reported'}}]},
  evidence_summary:{scope:'saved_question_results',unit:'distinct_questions',kb_ref:{id,version},claims:{R1:{support_questions:support,refute_questions:refute,unknown_questions:support===null?null:0,complete:support!==null,notice:'保存的逐题结果'}}},
 };
}
function inventory(items:Json[]){vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items})));}

it('filters high support independently of verification and retains known counterexamples',async()=>{
 inventory([item('研究候选',20,3),item('已验证',30,1,'v1',true),item('不足门槛',19,0),item('尚无证据',null,null)]);
 render(<KB version={0}/>);
 await screen.findByRole('button',{name:'阅读 R1 研究候选 v1 正文'});
 expect(screen.queryByText('至少 20 道不同题目支持，反例仍保留。')).toBeNull();
 expect(screen.getByText('支持统计说明').closest('details')?.open).toBe(false);
 fireEvent.change(screen.getByLabelText('支持情况'),{target:{value:'high'}});
 expect(screen.getAllByRole('button',{name:/^阅读 R1/})).toHaveLength(2);
 expect(screen.getByText(/至少 20 道不同题目支持/)).toBeTruthy();
 const row=screen.getByRole('button',{name:'阅读 R1 研究候选 v1 正文'});
 expect(within(row).getByText('支持 20 题 · 反例 3 题')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'阅读 R1 尚无证据 v1 正文'})).toBeNull();
 fireEvent.change(screen.getByLabelText('验证状态'),{target:{value:'pending'}});
 expect(screen.getAllByRole('button',{name:/^阅读 R1/})).toHaveLength(1);
 fireEvent.click(row);
 expect(within(screen.getByRole('dialog')).getByText('支持 20 题 · 反例 3 题')).toBeTruthy();
});

it('keeps saved evolution source status separate from independent verification and from later revisions',async()=>{
 const current=item('演化知识',25,2,'v2'),old=item('演化知识',2,1,'v1');
 for(const [value,status] of [[current,'verified'],[old,'candidate']] as const){
  value.source_kind='knowledge_evolution';
  value.snapshot.rules[0].source_refs=[{source_status:status}];
 }
 inventory([current,old]);render(<KB version={0}/>);
 const row=await screen.findByRole('button',{name:'阅读 R1 演化知识 v2 正文'});
 expect(within(row).getByText('演化来源：已验证')).toBeTruthy();
 expect(within(row).getByText('待独立验证')).toBeTruthy();
 expect(within(row).queryByText('来源标记：范围内复现')).toBeNull();
 fireEvent.change(screen.getByLabelText('验证状态'),{target:{value:'verified'}});
 expect(screen.getByText('没有找到匹配的知识')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('验证状态'),{target:{value:'all'}});
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'v1 正文'}});
 const historical=screen.getByRole('button',{name:'阅读 R1 演化知识 v1 正文'});
 expect(within(historical).getByText('演化来源：候选')).toBeTruthy();
 expect(within(historical).queryByText('演化来源：已验证')).toBeNull();
 fireEvent.click(historical);
 expect(within(screen.getByRole('dialog')).getByText('演化来源：候选')).toBeTruthy();
 expect(within(screen.getByRole('dialog')).queryByText('演化来源：已验证')).toBeNull();
});

it('does not carry current support counts into a historical search or historical reader',async()=>{
 inventory([item('同一知识',25,2,'v2'),item('同一知识',2,1,'v1')]);
 render(<KB version={0}/>);
 await screen.findByText('支持 25 题 · 反例 2 题');
 fireEvent.change(screen.getByLabelText('支持情况'),{target:{value:'high'}});
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'v1 正文'}});
 expect(screen.getByText('没有找到匹配的知识')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('支持情况'),{target:{value:'all'}});
 fireEvent.click(screen.getByRole('button',{name:'阅读 R1 同一知识 v1 正文'}));
 expect(within(screen.getByRole('dialog')).getByText('支持 2 题 · 反例 1 题')).toBeTruthy();
 expect(within(screen.getByRole('dialog')).queryByText('支持 25 题 · 反例 2 题')).toBeNull();
});

it('keeps missing, malformed and mismatched evidence unknown instead of using coverage or a zero fallback',()=>{
 const record=item('KB',20,2),revision={record,parts:record.snapshot.rules};
 expect(knowledgeSupport('R1',revision).support).toBe(20);
 for(const summary of [undefined,{...record.evidence_summary,kb_ref:{id:'KB',version:'other'}},
  {...record.evidence_summary,unit:'pairs'},
  {...record.evidence_summary,claims:{R1:{support_questions:20,refute_questions:0,complete:false}}},
  {...record.evidence_summary,claims:{R1:{support_questions:20,refute_questions:null,complete:true}}}]){
  expect(knowledgeSupport('R1',{...revision,record:{...record,evidence_summary:summary,counts:{applicable:999,support:999}}}).support).toBeNull();
 }
});

it('never qualifies duplicate sources by summing their sub-threshold support',async()=>{
 const first=item('来源甲',12,1),second=item('来源乙',12,2);
 first.snapshot.rules[0].text=second.snapshot.rules[0].text='相同知识正文';
 inventory([first,second]);render(<KB version={0}/>);
 await screen.findByText('1 条知识');
 expect(screen.queryByText(/支持 24 题/)).toBeNull();
 fireEvent.change(screen.getByLabelText('支持情况'),{target:{value:'high'}});
 expect(screen.getByText('没有找到匹配的知识')).toBeTruthy();
});

it.each([['flagged','来源已标记'],['retired','已停用']])('retains %s evolution knowledge and counterexamples in the human library',async(status,label)=>{
 const value=item('演化知识',21,2);
 value.source_kind='knowledge_evolution';
 value.snapshot.rules=[];
 value.reading_claims=[{id:'R1',version:3,status,text:'仍需查看反例的保存知识',rules:[{predict:{higher_better:'width'}}]}];
 inventory([value]);const onEvaluate=vi.fn();render(<KB version={0} onEvaluate={onEvaluate}/>);
 const row=await screen.findByRole('button',{name:'阅读 R1 仍需查看反例的保存知识'});
 expect(within(row).getByText(label)).toBeTruthy();
 expect(within(row).getByText('支持 21 题 · 反例 2 题')).toBeTruthy();
 expect(within(row).queryByText('历史记录')).toBeNull();
 fireEvent.change(screen.getByLabelText('支持情况'),{target:{value:'high'}});
 expect(screen.getByRole('button',{name:'阅读 R1 仍需查看反例的保存知识'})).toBeTruthy();
 fireEvent.click(row);
 const dialog=screen.getByRole('dialog');
 expect(within(dialog).getByRole('heading',{name:'仍需查看反例的保存知识'})).toBeTruthy();
 expect(within(dialog).getByText('支持 21 题 · 反例 2 题')).toBeTruthy();
 expect(within(dialog).getByText('宽度更高的候选更好')).toBeTruthy();
 expect(within(dialog).queryByRole('button',{name:'在 Task 中检查此知识所在 KB'})).toBeNull();
 expect(onEvaluate).not.toHaveBeenCalled();
});
