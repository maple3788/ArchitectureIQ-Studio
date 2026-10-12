import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within,waitFor} from '@testing-library/react';
import {TaskRunRecord} from './TaskRunRecord';
import type {TaskRun} from './taskTypes';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const question={id:'frozen-q',family:'multivariate_regression',prompt:'## Task\nWhich saved configuration learns this function best?\n## Choices\nA or B',choices:[{id:'old-a',letter:'A',view:{model_type:'mlp',width:32,layer_norm:[true,false]}},{id:'old-b',letter:'B',view:{model_type:'mlp',width:64,layer_norm:[true,true]}}]};
const run:TaskRun={id:'answer1',task_id:'task1',task_revision:1,mode:'rules',status:'complete',created_at:1,result:{question,prediction:{status:'answered',answer_id:'old-b',answer_letter:'B'}}};
const detail={...run,question_record:{public:question},review:{status:'revealed',feedback_released:true,selected_answer:{id:'old-b',letter:'B'},correct_answer:{id:'old-a',letter:'A'},correct:false,feedback:{correct_letter:'A',reveal:{curves:[]}}}};
const renderAnswer=(result:any)=><p>冻结 KB 根据候选参数选择 {result?.prediction?.answer_letter??result?.answer?.ranking?.[0]}</p>;
function setup(value:any=detail,open=true,record=run){
 const fetcher=vi.fn(async(_path:string,_init?:RequestInit)=>new Response(JSON.stringify(value)));vi.stubGlobal('fetch',fetcher);
 const view=render(<TaskRunRecord record={record} initialOpen={open} onRun={vi.fn()} renderAnswer={renderAnswer}/>);
 return {...view,fetcher};
}

it('shows the frozen question before KB application and stored answer comparison, without live retrieval',async()=>{
 const {fetcher}=setup();
 await screen.findByText('与已保存结果不同');
 const questionRegion=screen.getByRole('region',{name:'本次保存的题目'}),application=screen.getByRole('region',{name:'本次 KB 应用过程'}),review=screen.getByRole('region',{name:'正确答案对照'});
 expect(questionRegion.compareDocumentPosition(application)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(questionRegion.querySelector('.question-reader-comparison-workspace')?.contains(application)).toBe(true);
 expect(screen.getByText('训练曲线与最终指标').closest('details')?.open).toBe(false);
 expect(application.compareDocumentPosition(review)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 expect(within(questionRegion).getByText('Which saved configuration learns this function best?')).toBeTruthy();
 expect(within(screen.getByRole('article',{name:'候选 A'})).getByText('正确答案')).toBeTruthy();
 expect(within(screen.getByRole('article',{name:'候选 B'})).getByText('本次作答')).toBeTruthy();
 expect(within(screen.getByRole('article',{name:'候选 A'})).getByText('(yes, no)')).toBeTruthy();
 expect(document.querySelector('.question-reader-advanced')?.hasAttribute('open')).toBe(false);
 expect(screen.queryByRole('radio')).toBeNull();
 expect(fetcher.mock.calls).toHaveLength(1);
 expect(fetcher.mock.calls[0][0]).toBe('/api/studio/tasks/task1/runs/answer1');
});

it('does not show mismatched feedback against a different option identity',async()=>{
 setup({...detail,review:{...detail.review,correct_answer:{id:'old-a',letter:'B'},feedback:{reveal:{text:'SECRET-FEEDBACK'}}}});
 await screen.findByText('反馈与本次题目或已提交选项不一致，暂不显示正确答案。');
 expect(screen.queryByText('与已保存结果不同')).toBeNull();
 expect(document.body.textContent).not.toContain('SECRET-FEEDBACK');
 expect(document.querySelector('.question-reader-answer-markers')).toBeNull();
});

it('keeps pending and conflicting answers unrevealed and never submits a human answer',async()=>{
 const conflict={...run,result:{question,prediction:{status:'conflict',answer_id:null,answer_letter:null}}};
 const {fetcher}=setup({...conflict,question_record:{public:question},review:{status:'not_committed',feedback_released:false,notice:'规则存在冲突，尚未提交答案。'}},true,conflict);
 await screen.findByText('规则存在冲突，尚未提交答案。');
 expect(document.querySelector('.question-reader-answer-markers')).toBeNull();
 expect(fetcher.mock.calls).toHaveLength(1);
 expect(screen.queryByRole('button',{name:'提交并查看结果'})).toBeNull();
});

it('loads a historical receipt only when its record is expanded',async()=>{
 const {container,fetcher}=setup(detail,false);
 expect(fetcher).not.toHaveBeenCalled();
 const disclosure=container.querySelector('details')!;
 disclosure.open=true;fireEvent(disclosure,new Event('toggle'));
 await screen.findByText('与已保存结果不同');
 expect(fetcher).toHaveBeenCalledTimes(1);
});

it('accepts a committed LLM ranking and displays an unavailable-GT notice honestly',async()=>{
 const llm={...run,mode:'llm' as const,result:{answer:{ranking:['B','A'],rationale:'依据已保存知识'},question}};
 setup({...llm,question_record:{public:question},review:{...detail.review,correct_answer:null,correct:null,notice:'此来源没有保存可用的正确答案。'}},true,llm);
 await screen.findByText('此来源没有保存可用的正确答案。');
 expect(screen.getByText('未确认')).toBeTruthy();
 expect(within(screen.getByRole('article',{name:'候选 B'})).getByText('本次作答')).toBeTruthy();
 expect(document.querySelector('.is-correct-answer')).toBeNull();
});

it('ignores a late response from a different receipt',async()=>{
 const {fetcher}=setup({...detail,id:'another-answer'});
 await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
 await screen.findByText('这份记录尚无可核对的正确答案。');
 expect(document.querySelector('.question-reader-answer-markers')).toBeNull();
});
