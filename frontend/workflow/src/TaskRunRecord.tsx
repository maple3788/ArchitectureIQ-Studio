import {useState,type ReactNode} from 'react';
import {ArrowUpRight} from 'lucide-react';
import {ErrorBox,Loading,useResource} from './ui';
import {QuestionReader} from './QuestionReader';
import {StoredTrainingResults} from './NodeStory';
import {formatTimestamp} from './time';
import {taskRunLabel,type TaskRun} from './taskTypes';
import type {Json} from './types';
import './task-run-record.css';

type Answer={id:string;letter:string};
type Review={status:string;feedback_released:boolean;selected_answer?:Answer;correct_answer?:Answer|null;correct?:boolean|null;feedback?:Json;notice?:string};
type RunDetail=TaskRun&{question_record?:Json;question_notice?:string;review?:Review};
type Props={record:TaskRun;initialOpen?:boolean;onRun:(id:string)=>void;renderAnswer:(result:Json|undefined,question:Json|undefined)=>ReactNode};

export function TaskRunRecord({record,initialOpen=false,onRun,renderAnswer}:Props){
 const [open,setOpen]=useState(initialOpen);
 return <details className="task-run" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary><span><b>{record.mode==='rules'?'KB 直接解答':'LLM + KB'}</b><small>{formatTimestamp(record.created_at)}</small></span><span className={`task-run-status ${record.status}`}>{taskRunLabel(record.status)}</span></summary>
  {open&&<RunReading key={`${record.id}:${record.status}`} record={record} onRun={onRun} renderAnswer={renderAnswer}/>}
 </details>;
}

/** A saved answer may reveal results only when both IDs and option letters match its frozen question. */
function verifiedReview(run:RunDetail,question?:Json):Review|undefined{
 const review=run.review,choices:Json[]=question?.choices??[];
 if(!review||review.status!=='revealed'||!review.feedback_released||!review.selected_answer||choices.length<2)return;
 const matches=(answer:Answer)=>choices.filter(choice=>choice.id===answer.id&&choice.letter===answer.letter).length===1;
 if(!matches(review.selected_answer)||review.correct_answer&&!matches(review.correct_answer))return;
 if(run.mode==='rules'){
  const prediction=run.result?.prediction;
  if(prediction?.status!=='answered'||prediction.answer_id!==review.selected_answer.id||prediction.answer_letter!==review.selected_answer.letter)return;
 }else{
  const first=run.result?.answer?.ranking?.[0];
  if(first!==review.selected_answer.id&&first!==review.selected_answer.letter)return;
 }
 return review;
}

function RunReading({record,onRun,renderAnswer}:Omit<Props,'initialOpen'>){
 const pending=['pending','queued','running','starting'].includes(record.status);
 const detail=useResource<RunDetail>(`/tasks/${encodeURIComponent(record.task_id)}/runs/${encodeURIComponent(record.id)}`,0,pending?5000:0);
 const loaded=detail.data?.id===record.id&&detail.data.task_id===record.task_id?detail.data:undefined;
 const saved=loaded??record;
 const questionRecord=loaded?.question_record??(record.result?.question?{public:record.result.question}:undefined);
 const question=questionRecord?.public;
 const review=loaded?verifiedReview(loaded,question):undefined;
 const mismatch=loaded?.review?.feedback_released===true&&!review;
 return <div className="task-run-body task-run-reading">
  <section className="task-run-question" aria-label="本次保存的题目"><div className="task-run-step"><span>1</span><h3>本次题目</h3><small>使用本次作答时保存的配置</small></div>
   {questionRecord?<QuestionReader record={questionRecord} showApplicableKnowledge={false} compactDetails answerMarkers={review?{committedId:review.selected_answer?.id,correctId:review.correct_answer?.id}:undefined}/>:detail.loading?<Loading/>:<p className="task-muted">这份历史记录没有可读取的题面快照。</p>}
   {loaded?.question_notice&&<p className="task-muted">{loaded.question_notice}</p>}
  </section>
  <section className="task-run-application" aria-label="本次 KB 应用过程"><div className="task-run-step"><span>2</span><h3>{record.mode==='rules'?'KB 如何得出答案':'模型如何使用 KB'}</h3></div>
   {renderAnswer(saved.result,question)}
   {!saved.result&&<p className="task-muted">尚无保存的作答结果。</p>}
  </section>
  <section className="task-run-verification" aria-label="正确答案对照"><div className="task-run-step"><span>3</span><h3>正确答案对照</h3></div>
   <ErrorBox error={detail.error}/>
   {review?<><div className={`task-answer-comparison ${review.correct_answer?(review.selected_answer?.id===review.correct_answer.id?'is-correct':'is-different'):'is-unknown'}`}>
    <div><span>本次作答</span><strong>{review.selected_answer?.letter}</strong></div><div><span>正确答案</span><strong>{review.correct_answer?.letter??'未确认'}</strong></div>
    <p>{review.correct_answer?(review.selected_answer?.id===review.correct_answer.id?'与已保存结果一致':'与已保存结果不同'):'来源未提供可确认的正确答案'}</p>
   </div><p className="task-muted">{review.notice??'依据已有训练结果核对，仅作为研究检查。'}</p>
    {review.feedback&&<StoredTrainingResults feedback={review.feedback} question={question} compact/>}
   </>:detail.loading?<Loading/>:<p className="task-muted">{mismatch?'反馈与本次题目或已提交选项不一致，暂不显示正确答案。':loaded?.review?.notice??'这份记录尚无可核对的正确答案。'}</p>}
  </section>
  {record.job_id&&<button className="task-text-action" onClick={()=>onRun(record.job_id!)}>查看完整运行记录<ArrowUpRight size={14}/></button>}
  <details className="task-disclosure"><summary>本次配置与记录</summary><small className="task-muted">{record.id}</small><pre>{JSON.stringify(record,null,2)}</pre></details>
 </div>;
}
