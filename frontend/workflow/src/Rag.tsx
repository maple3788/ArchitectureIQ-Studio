import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from './api';
import {Card,ErrorBox,Field,Loading,useResource} from './ui';
import {QuestionPicker} from './QuestionPicker';
import {QuestionReader} from './QuestionReader';
import type {Action} from './Questions';
import type {Json,ModelProfile} from './types';
import type {RagHit,RagPreview} from './ragTypes';
import './rag.css';
export function RagKnowledge({hits}:{hits:RagHit[]}){
 return <ol className="rag-knowledge">{hits.map(hit=><li key={hit.citation_id} id={hit.citation_id}>
  <b>{hit.verified?'正式规则 · 已验证适用':'经验 · 待验证'}</b><p>{hit.text}</p>
  <small>相关性信号 {hit.score.toFixed(3)} · 条件文本信号 {hit.condition_score}</small>
  <ul>{hit.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
  <details><summary>来源与版本（{hit.source_refs.length}）</summary>
   <code>{hit.citation_id}</code>{hit.source_refs.map((ref,i)=><p key={i}>{ref.name} · {ref.id} · 版本 {ref.version}<br/>条目 {ref.record_id} · 修订 {ref.revision}{ref.sources.map((s,j)=><span key={j}> · {s.name||s.id||s.path}</span>)}</p>)}
  </details>
 </li>)}</ol>;
}
export function Rag({version,act,models,executionEnabled,questionKey,onQuestion,onRun}:{version:number;act:Action;models:ModelProfile[];executionEnabled:boolean;questionKey?:string;onQuestion:(key:string)=>void;onRun:(id:string)=>void}){
 const [modelId,setModelId]=useState(()=>models.find(m=>m.enabled)?.id||'');
 const [limit,setLimit]=useState(8);const [picker,setPicker]=useState(false);
 const [result,setResult]=useState<{signature:string;data:RagPreview;key:string}>();
 const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [starting,setStarting]=useState(false);
 const startLock=useRef(false);const requestId=useRef(0);
 const selection={question_key:questionKey,model_id:modelId,knowledge_limit:limit};const signature=JSON.stringify(selection);
 const latest=useRef(signature);latest.current=signature;
 const mounted=useRef(true);useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;requestId.current++;};},[]);
 useEffect(()=>{if(!modelId&&models.some(m=>m.enabled))setModelId(models.find(m=>m.enabled)!.id);},[models,modelId]);
 useEffect(()=>{requestId.current++;setResult(undefined);setError('');setBusy(false);},[signature]);
 const detail=useResource<Json>(questionKey?'/questions/'+encodeURIComponent(questionKey):null,version);
 const current=result?.signature===signature?result:undefined;
 const match=async()=>{
  const serial=++requestId.current;const captured=signature;setBusy(true);setError('');setResult(undefined);
  try{const data=await api<RagPreview>('/rag/preview',selection);
   if(mounted.current&&serial===requestId.current&&latest.current===captured)setResult({signature:captured,data,key:crypto.randomUUID()});
  }catch(e){if(mounted.current&&serial===requestId.current)setError((e as Error).message);}
  finally{if(mounted.current&&serial===requestId.current)setBusy(false);}
 };
 const start=async()=>{
  if(startLock.current||!current?.data.can_answer||!executionEnabled)return;
  startLock.current=true;setStarting(true);setError('');
  try{const run=await act(async()=>{
   try{return await api('/rag/runs',{...selection,preview_hash:current.data.preview_hash},undefined,{'Idempotency-Key':current.key});}
   catch(e){if(mounted.current){setError((e as Error).message);if(e instanceof ApiError&&e.status===409)setResult(undefined);}throw e;}
  });if(run&&mounted.current)onRun(run.id);
  }catch{}finally{startLock.current=false;if(mounted.current)setStarting(false);}
 };
 return <div className="rag-page"><div className="page-heading"><div><h1>RAG 作答</h1><p>根据公开题面匹配最相关的 KB，将适用知识交给模型作答。</p></div></div>
  <Card title="题目与模型"><div className="rag-selection">
   <div><button className="secondary" disabled={starting} onClick={()=>setPicker(true)}>{questionKey?'更换题目':'选择题目'}</button>{questionKey&&<small>{questionKey}</small>}</div>
   <Field label="作答模型"><select value={modelId} disabled={starting} onChange={e=>setModelId(e.target.value)}><option value="">选择模型</option>{models.filter(m=>m.enabled).map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>
   <Field label="知识条数"><input type="number" min={1} max={12} value={limit} disabled={starting} onChange={e=>setLimit(Number(e.target.value))}/></Field>
  </div>{questionKey&&(detail.loading?<Loading/>:detail.data?<details><summary>查看公开题面</summary><QuestionReader record={detail.data}/></details>:null)}<ErrorBox error={detail.error}/>
  <div className="rag-actions"><button className="primary" disabled={busy||starting||!questionKey||!modelId||!Number.isInteger(limit)||limit<1||limit>12} onClick={()=>void match()}>匹配 KB 并预览</button>
   <button className="primary" disabled={starting||busy||!current?.data.can_answer||!executionEnabled} onClick={()=>void start()}>启动 RAG 作答</button></div>
   {!executionEnabled&&<p className="rag-notice">本地可匹配和预览；模型调用只能在授权服务器执行。</p>}<ErrorBox error={error}/>
  </Card>
  {current&&<>
   {!current.data.can_answer?<Card title={current.data.blocked_reason==='empty_library'?'知识库目录为空':'没有适用的匹配知识'}><p>{current.data.blocked_reason==='empty_library'?'请先完成知识学习并发布 KB，再来匹配。':'可检查公开题面、适用范围及知识来源。当前没有可发送的请求。'}</p></Card>:<>
    <Card title="候选 KB"><p>自动采用第一名快照；相关性信号用于排序，经验仍需验证。</p><div className="rag-candidates">{current.data.retrieval.candidates.map((candidate,i)=><article key={candidate.kb.id+candidate.kb.version}><b>{i+1}. {candidate.kb.name}{i===0?' · 已选用':''}</b><small>{candidate.kb.kind==='formal'?'正式知识':'学习经验'} · {candidate.kb.version.slice(0,12)}</small><p>{candidate.hits.length} 条匹配知识 · 最高相关性信号 {candidate.hits[0]?.score.toFixed(3)||'0'}</p></article>)}</div></Card>
    <Card title="交给模型的知识"><RagKnowledge hits={current.data.retrieval.provenance}/><p>因条数限制省略 {current.data.retrieval.omitted.limit} 条；因预算省略 {current.data.retrieval.omitted.budget} 条。</p></Card>
    <Card title="实际请求预览"><p>尚未发送 · 1 次调用 · 保守预留 {current.data.reserved_tokens} tokens</p><pre className="rag-prompt">{current.data.request?.payload.messages?.[0]?.content}</pre></Card>
   </>}
   {!!current.data.retrieval.warnings.length&&<Card title="部分知识来源不可用">{current.data.retrieval.warnings.map((w,i)=><p key={i}>{w.message}</p>)}</Card>}
  </>}
  {picker&&<QuestionPicker version={version} act={act} purpose="rag" single onSelectQuestion={key=>{onQuestion(key);setPicker(false);}} onClose={()=>setPicker(false)}/>}
 </div>;
}
