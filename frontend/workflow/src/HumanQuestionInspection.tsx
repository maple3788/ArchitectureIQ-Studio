import {useEffect,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {api} from './api';
import {ErrorBox} from './ui';
import {StoredTrainingResults} from './NodeStory';
import type {HumanReviewSource} from './HumanQuestionPractice';
import type {Json} from './types';
import './human-question-inspection.css';

export type InspectedAnswer={id:string;letter:string};
type Inspection={scope:'human_inspection';correct_answer:InspectedAnswer|null;feedback:Json;notice?:string};
type Props={source:HumanReviewSource;question:Json;renderChoices:(correctAnswer:InspectedAnswer|null)=>ReactNode;onInspected?:()=>void};

export function HumanQuestionInspection(props:Props){
 // A new public question must never retain or receive a previous answer marker.
 return <InspectionReading key={JSON.stringify([props.source,props.question])} {...props}/>;
}

function InspectionReading({source,question,renderChoices,onInspected}:Props){
 const [result,setResult]=useState<Inspection>(),[error,setError]=useState(''),[busy,setBusy]=useState(true),[retry,setRetry]=useState(0),[showResults,setShowResults]=useState(false);
 const callback=useRef(onInspected);callback.current=onInspected;
 const choices:InspectedAnswer[]=Array.isArray(question.choices)?question.choices:[];
 const valid=choices.length>0&&choices.every(choice=>choice&&typeof choice.id==='string'&&!!choice.id&&typeof choice.letter==='string'&&!!choice.letter)&&new Set(choices.map(choice=>choice.id)).size===choices.length&&new Set(choices.map(choice=>choice.letter)).size===choices.length;
 useEffect(()=>{
  let active=true;
  if(!valid){setBusy(false);return;}
  setBusy(true);setError('');
  void api<Inspection>('/questions/inspect',{source}).then(next=>{
   if(!active)return;
   const answer=next.correct_answer;
   const letters=[next.feedback?.correct_letter,next.feedback?.reveal?.correctLetter].filter(letter=>letter!==undefined&&letter!==null&&letter!=='');
   if(next.scope!=='human_inspection'||!next.feedback||typeof next.feedback!=='object'||
      answer!==null&&(!answer||!choices.some(choice=>choice.id===answer.id&&choice.letter===answer.letter))||
      letters.some(letter=>letter!==answer?.letter))throw new Error('保存结果与当前题目选项不一致，请重新打开题目。');
   setResult(next);callback.current?.();
  }).catch(caught=>{if(active)setError((caught as Error).message);})
   .finally(()=>{if(active)setBusy(false);});
  return()=>{active=false;};
 // Source and public question changes remount this reading via its outer key.
 },[retry]);
 return <section className="human-question-inspection" aria-label="人工查看题目结果">
  {renderChoices(result?.correct_answer??null)}
  {!valid&&<p className="human-inspection-note">候选标识不完整或重复，暂不能匹配保存结果。</p>}
  {busy&&<p className="human-inspection-note" role="status">正在读取已保存的答案与训练结果…</p>}
  <ErrorBox error={error}/>
  {error&&<button onClick={()=>setRetry(value=>value+1)}>重新读取保存结果</button>}
  {result&&<div className="human-inspection-feedback">
   {(result.notice||!result.correct_answer)&&<p className="human-inspection-note">{result.notice||'来源未提供可确认的正确答案。'}</p>}
   <details className="human-inspection-results" onToggle={event=>setShowResults(event.currentTarget.open)}>
    <summary>训练曲线与结果</summary>
    {showResults&&<StoredTrainingResults feedback={result.feedback} question={question} compact/>}
   </details>
  </div>}
 </section>;
}
