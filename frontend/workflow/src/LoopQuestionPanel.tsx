import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowUpRight,Check,Clock3} from 'lucide-react';
import {api} from './api';
import {QuestionReader} from './QuestionReader';
import type {HumanReviewSource} from './HumanQuestionPractice';
import {QuestionKnowledgeEvidence} from './QuestionKnowledgeEvidence';
import {Empty,ErrorBox,Loading,useResource} from './ui';
import {formatTimestamp} from './time';
import type {Json} from './types';
import type {TaskSeed} from './taskTypes';
import type {EvolutionGeneration,EvolutionTaskContext} from './knowledgeEvolutionState';

const families:Record<string,string>={univariate_regression:'一元回归',multivariate_regression:'多元回归',spiral_classification:'螺旋分类',xor_classification:'异或分类',synthetic_tabular_classification:'表格分类',bigram_lm:'序列建模'};
const types:Record<string,string>={architecture_only:'架构对比',architecture:'架构对比',optimizer_only:'优化器对比',optimizer:'优化器对比',loss_only:'损失函数对比',loss:'损失函数对比',mixed:'混合对比'};

export function EvolutionTaskEntry({selection,onTask,hint}:{selection?:EvolutionTaskContext&{question_id?:string;expected_question_hash?:string};onTask:(seed:TaskSeed)=>void;hint:string}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const mounted=useRef(true),locked=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const select=async()=>{
    if(locked.current||!selection)return;
    locked.current=true;setBusy(true);setError('');
    try{const seed=await api<TaskSeed>('/tasks/evolution/selection',selection);if(mounted.current)onTask(seed);}
    catch(caught){if(mounted.current)setError((caught as Error).message);}
    finally{locked.current=false;if(mounted.current)setBusy(false);}
  };
  return <div className="evolution-task-entry"><div><span>{selection?hint:'未取得完整快照，请重新打开详情'}</span><button className="evolution-task-link" disabled={!selection||busy} onClick={()=>void select()}>{busy?'正在带入…':'去 Task 解答'}<ArrowUpRight size={15}/></button></div><ErrorBox error={error}/></div>;
}

export function LoopQuestionPanel({id,backLabel,onBack,taskContext,onTask,onQuestion,showKnowledgeEvidence=true}:{id:string;showKnowledgeEvidence?:boolean;backLabel:string;onBack:()=>void;taskContext?:EvolutionTaskContext;onTask?:(seed:TaskSeed)=>void;onQuestion?:(id:string,context:EvolutionTaskContext)=>void}){
  const [retry,setRetry]=useState(0);
  const question=useResource<Json>(`/kb-loop/questions/${encodeURIComponent(id)}`,retry);
  const reviewSource:HumanReviewSource|undefined=taskContext&&question.data?.observation?.content_hash?{kind:'knowledge_evolution',question_id:id,observation:taskContext.observation,expected_question_hash:question.data.observation.content_hash}:undefined;
  return <div className="loop-question-panel">
    <div className="loop-question-toolbar"><button className="loop-back" onClick={onBack}><ArrowLeft size={15}/>{backLabel}</button>
      {onTask&&question.data&&<EvolutionTaskEntry selection={taskContext&&question.data.observation?.content_hash?{...taskContext,question_id:id,expected_question_hash:question.data.observation.content_hash}:undefined} onTask={onTask} hint={taskContext?.claim_ref?'带入题目与当前知识':'带入题目与本次知识快照'}/>}
    </div>
    {question.loading?<Loading/>:question.error?<><Empty title="完整题面暂时不可用">保留已有验证证据，等待来源题目恢复后再读取。</Empty><ErrorBox error={question.error}/><button className="secondary" onClick={()=>setRetry(value=>value+1)}>重新读取题目</button></>:question.data?<>
      <QuestionReader record={question.data} questionKey={id} reviewSource={reviewSource} evidence={showKnowledgeEvidence&&reviewSource&&taskContext&&<QuestionKnowledgeEvidence id={id} record={question.data} context={taskContext} onQuestion={onQuestion}/>}/>
      <details className="evolution-source"><summary>题面保存记录</summary><p>读取来源已保存的公开题面与候选配置。</p><small>{formatTimestamp(question.data.observation?.captured_at)}</small><code className="evolution-hash">{question.data.observation?.content_hash}</code></details>
    </>:null}
  </div>;
}

export type GenerationView={filter:string;search:string;visible:number;returnId?:string};
export const initialGenerationView=():GenerationView=>({filter:'all',search:'',visible:40});
export function LoopGenerationPanel({data,error,connected,onQuestion,view,onView}:{data?:EvolutionGeneration;error?:string;connected:boolean;onQuestion:(id:string)=>void;view:GenerationView;onView:(value:GenerationView)=>void}){
  const {filter,search,visible,returnId}=view;
  const returningRow=useRef<HTMLButtonElement>(null);
  useEffect(()=>{if(returnId){returningRow.current?.focus();returningRow.current?.scrollIntoView?.({block:'nearest'});}},[returnId]);
  const filtered=(data?.items??[]).filter(row=>
    (filter==='all'||filter==='failed'&&['failed','crashed'].includes(row.status)||row.status===filter)&&
    [row.question_id,row.item_id,row.family,families[row.family],row.question_type,...row.targets].join(' ').toLowerCase().includes(search.toLowerCase()));
  const rows=[...filtered].reverse().sort((a,b)=>Number(a.status==='pending')-Number(b.status==='pending'));
  return <div className="loop-generation-panel">
    <p className={`loop-generation-sync${connected?'':' is-stale'}`} role="status"><i/>{connected?'新记录会自动更新':'同步中断，保留最近记录'}</p>
    <p className="evolution-note">每组完成后显示真实产出。尚未写入结果的条目标为等待产出。</p>
    <ErrorBox error={error}/>
    {!data?!error&&<Loading/>:<>
      <dl className="loop-generation-counts"><div><dt>有效新题</dt><dd>{data.ok}</dd></div><div><dt>等待产出</dt><dd>{data.pending}</dd></div><div><dt>未成功</dt><dd>{data.failed}</dd></div></dl>
      <div className="loop-generation-filter"><input aria-label="搜索生成记录" placeholder="搜索题号、类别或目标命题" value={search} onChange={event=>onView({...view,search:event.target.value,visible:40,returnId:undefined})}/><select aria-label="筛选生成状态" value={filter} onChange={event=>onView({...view,filter:event.target.value,visible:40,returnId:undefined})}><option value="all">全部记录 · {data.total}</option><option value="ok">已生成</option><option value="pending">等待产出</option><option value="failed">未成功</option></select></div>
      <div className="loop-generation-list">{rows.slice(0,visible).map(row=>{
        const ok=row.status==='ok',label=ok?'已生成':row.status==='pending'?'等待产出':'未成功';
        const content=<><span className={`loop-generation-icon is-${row.status}`}>{ok?<Check size={17}/>:<Clock3 size={17}/>}</span><span className="loop-generation-row-copy"><strong>{families[row.family]??row.family} · {types[row.question_type]??row.question_type}</strong><small>{row.question_id??row.item_id} · {row.purpose==='target'?'定向检验':'探索题'}{row.targets.length?` · ${row.targets.join('、')}`:''}</small></span><span className={`loop-generation-outcome is-${row.status}`}>{label}{typeof row.seconds==='number'&&<small>{row.seconds.toFixed(1)} 秒</small>}</span>{ok&&row.question_id&&<ArrowUpRight size={16}/>}</>;
        return ok&&row.question_id?<button ref={row.question_id===returnId?returningRow:undefined} className="loop-generation-row" key={row.item_id} aria-label={`阅读完整题目 ${row.question_id}`} onClick={()=>{onView({...view,returnId:row.question_id});onQuestion(row.question_id!);}}>{content}</button>:<div className="loop-generation-row" key={row.item_id}>{content}</div>;
      })}</div>
      {!rows.length&&<Empty title="没有符合条件的生成记录"/>}
      {rows.length>visible&&<button className="loop-show-more" onClick={()=>onView({...view,visible:visible+40})}>继续查看 · 还有 {rows.length-visible} 条</button>}
    </>}
  </div>;
}
