import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {EvolutionRevisionHistory,KnowledgeEntryHistory} from './KnowledgeRevisionHistory';
import {knowledgeEntries} from './knowledgeEntries';
afterEach(cleanup);

const rule=(field:string)=>({scope:['model_type','eq','mlp'],predict:{higher_better:field}});
it('reads original and revised evolution content in order without duplicating the current revision or its evidence',async()=>{
 const first={id:'C1',version:1,text:'第一版的完整原文',registered_round:1,rules:[rule('width')]};
 const current={...first,version:2,text:'修订后的完整原文',registered_round:3,parent:{id:'C1',version:1},rationale:'反例要求收窄范围',rules:[rule('depth')],evidence:{support:99}};
 render(<EvolutionRevisionHistory data={{claim:current,history:[current,first,current]}}/>);
 fireEvent.click(screen.getByText('登记与修订记录'));
 const history=await screen.findByRole('region',{name:'知识修订历史'});
 expect(within(history).getAllByRole('listitem')).toHaveLength(2);
 expect(within(history).getByText('第一版原文')).toBeTruthy();
 expect(within(history).getByText('第一版的完整原文')).toBeTruthy();
 expect(within(history).getByText('修订后的完整原文')).toBeTruthy();
 expect(within(history).getByText('反例要求收窄范围')).toBeTruthy();
 expect(within(history).getByText('较 C1 · 第 1 版：正文、执行规则已调整。')).toBeTruthy();
 expect(within(history).queryByText(/99/)).toBeNull();
 expect(within(history).queryByRole('button',{name:/Task|题目/})).toBeNull();
 fireEvent.click(within(history).getByText('对照修订前后'));
 const before=(await screen.findByRole('heading',{name:'修订前 · C1 · 第 1 版'})).closest('section')!;
 const after=screen.getByRole('heading',{name:'修订后 · C1 · 第 2 版'}).closest('section')!;
 expect(within(before).getByText('宽度更高的候选更好')).toBeTruthy();
 expect(within(after).getByText('深度更高的候选更好')).toBeTruthy();
});

it('honors historical version and round limits and labels missing early history honestly',async()=>{
 const current={id:'C1',version:3,text:'第 4 轮封存内容',registered_round:4,rules:[]};
 render(<EvolutionRevisionHistory data={{claim:current,reading_round:4,history_truncated:true,history:[
  {...current,version:2,text:'更早的保存正文',registered_round:2},
  {...current,version:4,text:'不应出现的未来修订',registered_round:6},
  {...current,id:'C2',version:1,text:'不相关知识',registered_round:1},
 ]}}/>);
 fireEvent.click(screen.getByText('登记与修订记录'));
 expect(screen.queryByText('第一版原文')).toBeNull();
 expect(await screen.findByText('第一版原文未包含在这份记录中。')).toBeTruthy();
 expect(screen.getByText('历史记录只保留了部分版本。')).toBeTruthy();
 expect(screen.queryByText('不应出现的未来修订')).toBeNull();
 expect(screen.queryByText('不相关知识')).toBeNull();
});

it('opens the selected historical KB record with its original entry and hash',async()=>{
 const entries=knowledgeEntries(['v1','v2'].map((label,index)=>({id:`kb-${label}`,version:`hash-${label}`,kind:'research_rules',
  library:{id:'study',version_label:label,version_order:index+1},snapshot:{rules:[{rule_id:'R1:1',revision:`r-${label}`,text:`正文 ${label}`,rule:rule(index?'depth':'width'),metadata:{claim_id:'R1'}}]}})));
 const onRead=vi.fn();
 render(<KnowledgeEntryHistory entry={entries[0]} selected={entries[0].revisions[0]} onRead={onRead}/>);
 fireEvent.click(screen.getByText('查看修订记录'));
 expect(await screen.findByText('正文 v1')).toBeTruthy();expect(screen.getByText('正文 v2')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'阅读 R1 · v1 的知识与题目'}));
 expect(onRead).toHaveBeenCalledWith({key:entries[0].key,version:'kb-v1:hash-v1'});
});

it('shows saved validation and reference-policy revisions even when wording and executable rules are unchanged',async()=>{
 const entries=knowledgeEntries(['v9','v10'].map((label,index)=>({id:`kb-${label}`,version:`hash-${label}`,kind:'research_rules',
  library:{id:'study',version_label:label,version_order:index+9},snapshot:{rules:[{rule_id:'R1:1',revision:`r-${label}`,state:'active',text:'固定条件下宽度越大越好',rule:rule('width'),metadata:{
   claim_id:'R1',validity_status:index?'replicated_in_scope':'proposed',validation_origin:'source_reported',inject:!!index,inject_same:index?[]:['depth'],
  }}]}})));
 render(<KnowledgeEntryHistory entry={entries[0]} selected={entries[0].revisions[0]} onRead={()=>{}}/>);
 fireEvent.click(screen.getByText('查看修订记录'));
 const history=await screen.findByRole('region',{name:'知识修订历史'}),[before,after]=within(history).getAllByRole('listitem');
 expect(within(before).getByText('来源标记：待独立确认')).toBeTruthy();
 expect(within(before).getByText('模型参考：不注入模型')).toBeTruthy();
 expect(within(before).queryByText('来源标记：范围内复现')).toBeNull();
 expect(within(after).getByText('来源标记：范围内复现')).toBeTruthy();
 expect(within(after).getByText('模型参考：允许注入')).toBeTruthy();
 expect(within(after).getByText('参考时不要求保持相同字段')).toBeTruthy();
 expect(within(after).getByText('较 R1 · v9：验证状态、模型参考策略已调整。')).toBeTruthy();
 fireEvent.click(within(after).getByText('对照修订前后'));
 const oldComparison=(await screen.findByRole('heading',{name:'修订前 · R1 · v9'})).closest('section')!;
 expect(within(oldComparison).getByText('来源标记：待独立确认')).toBeTruthy();
 expect(within(oldComparison).getByText('参考时要求相同：深度')).toBeTruthy();
});

it('shows each frozen evolution source status without promoting its saved validation status',async()=>{
 const entries=knowledgeEntries(['candidate','verified'].map((status,index)=>({id:`evolution-${index}`,version:`hash-${index}`,kind:'research_rules',
  library:{id:'evolution',version_label:`第 ${index+1} 轮`,version_order:index+1},snapshot:{rules:[{rule_id:'C1:1',revision:`r-${index}`,text:'演化知识原文',rule:rule('width'),
   metadata:{claim_id:'C1',validity_status:'proposed',validation_origin:'source_reported',inject:true},source_refs:[{kind:'knowledge_evolution',source_status:status}],
  }]}})));
 render(<KnowledgeEntryHistory entry={entries[0]} selected={entries[0].revisions[0]} onRead={()=>{}}/>);
 fireEvent.click(screen.getByText('查看修订记录'));
 const history=await screen.findByRole('region',{name:'知识修订历史'}),[before,after]=within(history).getAllByRole('listitem');
 expect(within(before).getByText('演化来源状态：研究候选')).toBeTruthy();
 expect(within(before).queryByText('演化来源状态：源报告已验证')).toBeNull();
 expect(within(after).getByText('演化来源状态：源报告已验证')).toBeTruthy();
 expect(within(history).getAllByText('来源标记：待独立确认')).toHaveLength(2);
 expect(within(history).queryByText('来源标记：范围内复现')).toBeNull();
 expect(within(after).getByText('较 C1 · 第 1 轮：演化来源状态已调整。')).toBeTruthy();
});

it('keeps original claim status separate from the current claim status in evolution history',async()=>{
 const first={id:'C1',version:1,text:'保存的知识原文',status:'candidate',registered_round:1,rules:[]};
 render(<EvolutionRevisionHistory data={{claim:{...first,version:2,status:'verified',registered_round:2},history:[first]}}/>);
 fireEvent.click(screen.getByText('登记与修订记录'));
 const history=await screen.findByRole('region',{name:'知识修订历史'}),[before,after]=within(history).getAllByRole('listitem');
 expect(within(before).getByText('演化来源状态：研究候选')).toBeTruthy();
 expect(within(before).queryByText('演化来源状态：源报告已验证')).toBeNull();
 expect(within(after).getByText('演化来源状态：源报告已验证')).toBeTruthy();
 expect(within(after).getByText('较 C1 · 第 1 版：演化来源状态已调整。')).toBeTruthy();
 expect(within(history).queryByText(/允许注入/)).toBeNull();
});
