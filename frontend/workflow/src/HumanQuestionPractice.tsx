import {useEffect,useId,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {api} from './api';
import {ErrorBox} from './ui';
import {StoredTrainingResults} from './NodeStory';
import type {EvolutionObservation} from './knowledgeEvolutionState';
import type {Json} from './types';
import './human-question-practice.css';
export type HumanReviewSource={kind:'catalog';key:string}|{kind:'knowledge_evolution';question_id:string;observation:EvolutionObservation;expected_question_hash:string};
type Answer={id:string;letter:string};
type Choice=Answer&{label?:string};
type Review={selected_answer:Answer;correct_answer:Answer|null;correct:boolean|null;feedback:Json;notice?:string};
export type PracticeChoiceControls={selected:string;disabled:boolean;name:string;select:(id:string)=>void};
type Props={source:HumanReviewSource;question:Json;onRevealed?:()=>void;renderChoices?:(controls:PracticeChoiceControls)=>ReactNode};
export function HumanQuestionPractice(props:Props){
 return <PracticeAttempt key={JSON.stringify(props.source)} {...props}/>;
}
function PracticeAttempt({source,question,onRevealed,renderChoices}:Props){
 const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<Review>();
 const live=useRef(true),locked=useRef(false),name=useId();
 useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
 const choices:Choice[]=Array.isArray(question.choices)?question.choices:[];
 const valid=choices.length>1&&choices.every(choice=>typeof choice.id==='string'&&!!choice.id&&typeof choice.letter==='string'&&!!choice.letter)&&new Set(choices.map(choice=>choice.id)).size===choices.length&&new Set(choices.map(choice=>choice.letter)).size===choices.length;
 const submit=async()=>{
  const answer=choices.find(choice=>choice.id===selected);
  if(!valid||!answer||locked.current||result)return;
  locked.current=true;setBusy(true);setError('');
  try{
   const next=await api<Review>('/questions/review',{source,answer_id:answer.id});
   if(!live.current)return;
   if(next.selected_answer?.id!==answer.id||next.selected_answer.letter!==answer.letter||next.correct_answer&&!choices.some(choice=>choice.id===next.correct_answer?.id&&choice.letter===next.correct_answer?.letter))throw new Error('返回结果与当前题目选项不一致，请重新打开题目。');
   setResult(next);onRevealed?.();
  }catch(caught){if(live.current)setError((caught as Error).message);}
  finally{locked.current=false;if(live.current)setBusy(false);}
 };
 return <section className="human-question-practice" aria-label="人工检查题目">
  {!renderChoices&&<div className="human-practice-heading"><h3>你的判断</h3><p>选择一个候选，再查看已保存的训练结果。</p></div>}
  {renderChoices?renderChoices({selected,disabled:busy||!!result||!valid,name,select:id=>{if(!busy&&!result&&valid)setSelected(id);}}):<fieldset disabled={busy||!!result||!valid}><legend>选择答案</legend><div className="human-practice-options">{choices.map((choice,index)=><label className={selected===choice.id?'is-selected':''} key={`${choice.id}-${index}`}><input type="radio" name={name} aria-label={`选择 ${choice.letter}`} value={choice.id} checked={selected===choice.id} onChange={()=>setSelected(choice.id)}/><strong>{choice.letter}</strong><span>{choice.label||`候选 ${choice.letter}`}</span></label>)}</div></fieldset>}
  {!valid&&<p className="human-practice-note">候选标识不完整或重复，暂不能提交人工检查。</p>}
  {!result&&<button className="primary human-practice-submit" disabled={!valid||!selected||busy} onClick={()=>void submit()}>{busy?'正在读取已保存结果…':'提交并查看结果'}</button>}
  <ErrorBox error={error}/>
  {result&&<div className="human-practice-reveal" aria-live="polite">
   <div className={`human-practice-answer ${result.correct===true?'is-correct':result.correct===false?'is-different':'is-unknown'}`}><span>你的选择 {result.selected_answer.letter}</span><strong>{result.correct_answer?`正确答案 ${result.correct_answer.letter}`:'来源未提供可确认的正确答案'}</strong>{typeof result.correct==='boolean'&&<small>{result.correct?'与已保存结果一致':'与已保存结果不同'}</small>}</div>
   {result.notice&&<p className="human-practice-note">{result.notice}</p>}
   <p className="human-practice-note">这是对已有训练结果的人工检查，不计作独立评测。</p>
   <StoredTrainingResults feedback={result.feedback} question={question} compact/>
  </div>}
 </section>;
}
