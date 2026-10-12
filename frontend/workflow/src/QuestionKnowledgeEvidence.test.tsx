import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {QuestionKnowledgeEvidence} from './QuestionKnowledgeEvidence';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const context={observation:{source_identity:'a'.repeat(64),sequence:12},claim_ref:{id:'C0004',version:2}};
const record={public:{choices:[{id:'source-small',letter:'C'},{id:'source-large',letter:'A'}]}};
const claim={id:'C0004',version:2,text:'在固定条件下更宽的候选更好。',status:'candidate',registered_round:1,revisions:1,needs_revision:false,rules:[{scope:['model_type','eq','mlp'],same:['opt_key'],predict:{higher_better:'width'}}],evidence:{support:3,applicable:5,refute:2,conflicts:0}};
const row={question_id:'q_current',round:2,outcome:'refute',pairs:[['source-small','source-large',false]],conflicts:0};
function install(overrides:Record<string,unknown>={}){
 const fetch=vi.fn(async(_path:string)=>new Response(JSON.stringify({observation:context.observation,question_id:'q_current',claims:[{claim,relation:'selected',current_evidence:[row],counterexamples:{items:[{...row,question_id:'q_other'}],total:2,truncated:true},evidence_total:5,evidence_truncated:false,...overrides}]})));
 vi.stubGlobal('fetch',fetch);return fetch;
}

it('binds recorded predictions to actual public letters and the exact viewed observation',async()=>{
 const fetch=install();render(<QuestionKnowledgeEvidence id="q_current" record={record} context={context}/>);
 expect(await screen.findByText(claim.text)).toBeTruthy();
 const table=screen.getByRole('table',{name:'C0004 本题验证结果'});
 expect(within(table).getByText('A 优于 C')).toBeTruthy();
 expect(within(table).getByText('C 优于 A')).toBeTruthy();
 expect(screen.getByText('宽度更高的候选更好')).toBeTruthy();
 const url=new URL(fetch.mock.calls[0][0] as string,'http://localhost');
 expect(url.pathname).toBe('/api/studio/kb-loop/questions/q_current/evidence');
 expect(Object.fromEntries(url.searchParams)).toEqual({source_identity:'a'.repeat(64),sequence:'12',claim_id:'C0004',claim_version:'2'});
});

it('opens an actual counterexample with the same knowledge revision and never borrows current letters',async()=>{
 install();const onQuestion=vi.fn();render(<QuestionKnowledgeEvidence id="q_current" record={record} context={context} onQuestion={onQuestion}/>);
 const item=await screen.findByRole('button',{name:'阅读反例 q_other'});
 const section=screen.getByRole('region',{name:'C0004 反例'});
 expect(within(section).queryByText('A 优于 C')).toBeNull();
 expect(within(section).getByText(/仅列出已保存的 1 条/)).toBeTruthy();
 fireEvent.click(item);
 expect(onQuestion).toHaveBeenCalledWith('q_other',context);
});

it('does not interpret an absent or truncated record as support or zero counterexamples',async()=>{
 install({current_evidence:[],relation:'target',counterexamples:{items:[],total:null,truncated:true}});
 render(<QuestionKnowledgeEvidence id="q_current" record={record} context={context}/>);
 expect(await screen.findByText(/尚无本题验证记录/)).toBeTruthy();
 expect(screen.getByText(/反例记录不完整/)).toBeTruthy();
 expect(screen.queryByRole('table')).toBeNull();
});

it('keeps unmapped source identities explicit instead of inventing an answer letter',async()=>{
 install({current_evidence:[{...row,pairs:[['unknown-candidate','source-large',true]]}]});
 render(<QuestionKnowledgeEvidence id="q_current" record={record} context={context}/>);
 const table=await screen.findByRole('table',{name:'C0004 本题验证结果'});
 expect(within(table).getAllByText('来源 unknown-candidate 优于 A')).toHaveLength(2);
 expect(screen.getByText(/部分来源候选无法对应本题选项/)).toBeTruthy();
});

it('shows a recoverable read error and cannot substitute a newer knowledge snapshot',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({detail:'所见知识快照已不可用'}),{status:409})));
 render(<QuestionKnowledgeEvidence id="q_current" record={record} context={context}/>);
 expect(await screen.findByText('所见知识快照已不可用')).toBeTruthy();
 expect(screen.queryByRole('table')).toBeNull();
 expect(screen.getByRole('button',{name:'重新读取知识证据'})).toBeTruthy();
});
