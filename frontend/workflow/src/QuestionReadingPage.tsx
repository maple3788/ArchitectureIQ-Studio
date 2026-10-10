import {useState} from 'react';
import {ArrowLeft,ChevronLeft,ChevronRight} from 'lucide-react';
import {api} from './api';
import {ErrorBox,Loading,useResource} from './ui';
import {QuestionReader} from './QuestionReader';
import type {Json} from './types';
import type {BrowseLocation,DataQuestion,Page,BankItem,DatasetSummary,DatasetRevision} from './dataTypes';

export function QuestionReadingPage({questionKey,context,onBack,onQuestion,onAddToDataset,onRag}:{questionKey:string;context:BrowseLocation;onBack:()=>void;onQuestion:(key:string)=>void;onAddToDataset:(key:string)=>void;onRag:(key:string)=>void}){
 const [offset,setOffset]=useState(context.view==='datasets'?0:context.offset),[busy,setBusy]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const record=useResource<Json>('/questions/'+encodeURIComponent(questionKey),retry);
 const prefix=context.view==='dataset'?`/datasets/${context.ref.collection_id}/questions?`:'/question-bank?';
 const query=(pageOffset:number)=>new URLSearchParams({...(context.view==='dataset'?{revision:context.ref.revision}:{}),...(context.view==='datasets'?{}:context.filters),offset:String(pageOffset),limit:'25'});
 const siblings=useResource<Page<DataQuestion|BankItem>>(prefix+query(offset));
 const keyOf=(item:DataQuestion|BankItem)=>'representative_key' in item?item.representative_key:item.key;
 const index=siblings.data?.items.findIndex(item=>keyOf(item)===questionKey)??-1;
 const move=async(delta:number)=>{const items=siblings.data?.items||[];if(index<0)return;const next=index+delta;if(next>=0&&next<items.length){onQuestion(keyOf(items[next]));return;}setBusy(true);try{const nextOffset=offset+delta*25;const page=await api<Page<DataQuestion|BankItem>>(prefix+query(nextOffset));const item=delta>0?page.items[0]:page.items.at(-1);if(item){setOffset(nextOffset);onQuestion(keyOf(item));}}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 return <section className="data-reading-page"><div className="data-toolbar"><button className="data-back" onClick={onBack}><ArrowLeft size={16}/>返回题目列表</button><div className="data-actions"><button disabled={busy||index<0||offset+index===0} aria-label="上一题" onClick={()=>void move(-1)}><ChevronLeft size={16}/></button><span>{index>=0?`${offset+index+1} / ${siblings.data?.total}`:'读取位置…'}</span><button disabled={busy||index<0||offset+index+1>=(siblings.data?.total||0)} aria-label="下一题" onClick={()=>void move(1)}><ChevronRight size={16}/></button></div></div>
 <ErrorBox error={record.error||siblings.error||error}/>{record.error&&<button onClick={()=>setRetry(v=>v+1)}>重试读取题目</button>}{record.loading&&<Loading/>}
 {record.data&&<><QuestionReader record={record.data} interactive questionKey={questionKey}/><div className="data-reading-actions"><span>当前选择仅用于阅读与比较</span><div className="data-actions"><button onClick={()=>onAddToDataset(questionKey)}>加入 Dataset</button><button disabled={record.data.metadata?.rag_ready===false} onClick={()=>onRag(questionKey)}>用 RAG 匹配 KB 作答</button></div></div></>}
 </section>;
}

export function AddQuestionToDataset({questionKey,onClose}:{questionKey:string;onClose:()=>void}){
 const [search,setSearch]=useState(''),[selected,setSelected]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const datasets=useResource<Page<DatasetSummary>>('/datasets?'+new URLSearchParams({search,limit:'1000'}));
 const add=async()=>{setBusy(true);try{const target=await api<DatasetRevision>('/datasets/'+selected);await api('/datasets/'+selected+'/revisions',{expected_revision:target.revision,changes:{keys:[...target.keys,questionKey]}},undefined,{'Idempotency-Key':crypto.randomUUID()});onClose();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 return <div className="data-dialog-backdrop"><section className="data-dialog" role="dialog" aria-modal="true" aria-label="加入 Dataset"><h2>加入 Dataset</h2><label>查找题库<input autoFocus value={search} onChange={e=>setSearch(e.target.value)}/></label><label>目标 Dataset<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">请选择</option>{datasets.data?.items.filter(d=>d.selection_mode==='single').map(d=><option value={d.collection_id} key={d.collection_id}>{d.name} · {d.count} 道题</option>)}</select></label><ErrorBox error={error||datasets.error}/><div className="data-actions"><button disabled={busy} onClick={onClose}>取消</button><button className="primary" disabled={busy||!selected} onClick={()=>void add()}>加入题库</button></div></section></div>;
}
