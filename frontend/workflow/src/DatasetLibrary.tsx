import {useRef,useState} from 'react';
import {Database,Plus,Search} from 'lucide-react';
import {api} from './api';
import {ErrorBox,Loading,useResource} from './ui';
import {datasetTypeDistribution} from './displayNames';
import {datasetRef,type DatasetRef,type DatasetRevision,type DatasetSummary,type Page} from './dataTypes';
export function DatasetLibrary({version,onOpen}:{version:number;onOpen:(ref:DatasetRef)=>void}){
 const [search,setSearch]=useState(''),[archived,setArchived]=useState(false),[offset,setOffset]=useState(0),[create,setCreate]=useState(false);
 const [name,setName]=useState(''),[description,setDescription]=useState(''),[mode,setMode]=useState('single'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0);
 const data=useResource<Page<DatasetSummary>&{dataset_total?:number}>('/datasets?'+new URLSearchParams({grouped:'true',search,archived:String(archived),offset:String(offset),limit:'24'}),version+retry);
 const current=(data.data?.items??[]).filter(d=>d.origin?.kind!=='set'),historical=(data.data?.items??[]).filter(d=>d.origin?.kind==='set');
 const operation=useRef<{signature:string;key:string}|undefined>(undefined);
 const save=async()=>{const signature=JSON.stringify({name,description,mode});if(operation.current?.signature!==signature)operation.current={signature,key:crypto.randomUUID()};setBusy(true);setError('');try{const d=await api<DatasetRevision>('/datasets',{name,description,...(mode==='pairs'?{pair_keys:[]}:{keys:[]})},undefined,{'Idempotency-Key':operation.current.key});onOpen(datasetRef(d));}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 return <section><div className="data-heading"><div><p className="data-eyebrow">DATA / COLLECTIONS</p><h1>我的 Datasets</h1><p>按研究目的组织题目，构建属于你的实验材料。</p></div><button className="primary" onClick={()=>setCreate(true)}><Plus size={17}/>新建 Dataset</button></div>
 <div className="data-toolbar"><label className="data-search"><Search size={17}/><input aria-label="搜索 Dataset" placeholder="搜索题库名称或用途" value={search} onChange={e=>{setSearch(e.target.value);setOffset(0);}}/></label><label className="data-inline-check"><input type="checkbox" checked={archived} onChange={e=>{setArchived(e.target.checked);setOffset(0);}}/>查看已归档</label></div>
 <ErrorBox error={data.error}/>{data.error&&<button onClick={()=>setRetry(v=>v+1)}>重新读取 Datasets</button>}{data.loading&&<Loading/>}
 {data.data&&<p className="dataset-library-count">{data.data.dataset_total??data.data.total} 个 Dataset{data.data.dataset_total!=null&&data.data.dataset_total!==data.data.total?` · 相同题目归为 ${data.data.total} 组展示`:''}</p>}
 <div className="dataset-list">{current.map(d=><DatasetRow key={d.collection_id} dataset={d} onOpen={onOpen}/>)}</div>
 {historical.length>0&&<details className="dataset-history" key={search?'matching':'folded'} open={Boolean(search)}><summary>历史研究选集 · {historical.length}</summary><p>保留过去研究所选的题目与固定修订。</p><div className="dataset-list">{historical.map(d=><DatasetRow key={d.collection_id} dataset={d} onOpen={onOpen}/>)}</div></details>}
 {data.data?.total===0&&<div className="data-empty"><Database size={32}/><h2>{archived?'暂无归档题库':'从第一个 Dataset 开始'}</h2><p>题目可以属于多个 Dataset，总题库会统一保留和去重。</p></div>}
 {data.data&&data.data.total>24&&<div className="data-pagination"><button disabled={!offset} onClick={()=>setOffset(v=>Math.max(0,v-24))}>上一页</button><span>{offset+1}–{Math.min(offset+24,data.data.total)} / {data.data.total}</span><button disabled={offset+24>=data.data.total} onClick={()=>setOffset(v=>v+24)}>下一页</button></div>}
 {create&&<div className="data-dialog-backdrop"><form className="data-dialog" role="dialog" aria-modal="true" aria-label="新建 Dataset" onSubmit={e=>{e.preventDefault();void save();}} onKeyDown={e=>{if(e.key==='Escape'&&!busy)setCreate(false);}}><p className="data-eyebrow">NEW DATASET</p><h2>给研究材料一个名字</h2><label>Dataset 名称<input autoFocus value={name} onChange={e=>setName(e.target.value)} required/></label><label>研究用途<textarea value={description} onChange={e=>setDescription(e.target.value)} placeholder="例如：比较不同优化器在回归任务上的表现"/></label><label>题目模式<select value={mode} onChange={e=>setMode(e.target.value)}><option value="single">普通题目</option><option value="pairs">完整题对</option></select></label><ErrorBox error={error}/><div className="data-actions"><button type="button" disabled={busy} onClick={()=>setCreate(false)}>取消</button><button className="primary" disabled={busy||!name.trim()} type="submit">创建题库</button></div></form></div>}
 </section>;
}

const originLabel=(dataset:DatasetSummary)=>dataset.origin?.kind==='source'?'导入题源':dataset.origin?.kind==='set'?'历史选集':dataset.origin?.kind==='imported'?'导入材料':'研究题库';
function DatasetRow({dataset:d,onOpen}:{dataset:DatasetSummary;onOpen:(ref:DatasetRef)=>void}){
 const equivalents=d.equivalent_datasets?.length?d.equivalent_datasets:[d];
 const others=equivalents.filter(item=>item.collection_id!==d.collection_id);
 const description=d.origin?.kind&&d.origin.kind!=='created'&&d.description.startsWith('Imported from existing ')?'':d.description;
 return <article className="dataset-row">
  <div className="dataset-row-main"><Database size={20}/><div className="dataset-row-content"><button className="data-title-button" aria-label={`打开 Dataset ${d.name}`} onClick={()=>onOpen(datasetRef(d))}><h2>{d.name}</h2></button><div className="dataset-row-meta"><span>{originLabel(d)}</span><span>{d.selection_mode==='pairs'?`${d.pair_count} 对题目`:'单题集合'}</span><span>{!d.count?'等待添加题目':''}</span></div>{d.type_counts&&<div className="dataset-type-counts" aria-label="Dataset 题型分布">{datasetTypeDistribution(d.type_counts).map(label=><span key={label}>{label}</span>)}</div>}{description&&<p>{description}</p>}</div><b className="dataset-row-count">{d.count}<small> 道题</small></b></div>
  {others.length>0&&<details className="dataset-equivalents"><summary>相同题目 · {equivalents.length} 个集合</summary><p>这些是独立集合，保留各自名称与固定修订。</p><div>{others.map(item=><div className="dataset-equivalent-row" key={item.collection_id}><button className="data-title-button" aria-label={`打开 Dataset ${item.name}`} onClick={()=>onOpen(datasetRef(item))}>{item.name}</button><small>{originLabel(item)} · 固定修订 {item.revision.slice(0,8)}</small></div>)}</div></details>}
 </article>;
}
