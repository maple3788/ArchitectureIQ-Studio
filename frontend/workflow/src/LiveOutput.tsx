import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {appendStreamEvent,emptyStream,matchingStream} from './streamState';
import type {Run} from './types';
import './live-output.css';

const RunStreamContext=createContext<ReturnType<typeof useLocalOutput>|null>(null);

export function RunStreamProvider({run,children}:{run:Run;children:ReactNode}) {
  const live=useLocalOutput(run);
  return <RunStreamContext.Provider value={live}>{children}</RunStreamContext.Provider>;
}
export function useLiveOutput(run:Run) {
  const shared=useContext(RunStreamContext);
  const local=useLocalOutput(run,!shared);
  return shared??local;
}
function useLocalOutput(run:Run,subscribe=true) {
  const [stream,setStream]=useState(emptyStream);
  const [connection,setConnection]=useState('connecting');
  const enabled=run.transport?.stream===true||run.config?.transport?.stream===true;
  useEffect(()=>{
    setStream(emptyStream());setConnection(enabled?'connecting':'unavailable');
    if(!enabled||!subscribe||typeof EventSource==='undefined')return;
    const source=new EventSource(`/api/studio/runs/${encodeURIComponent(run.id)}/stream?after=0`);
    let closed=false;
    source.addEventListener('metadata',()=>setConnection('connected'));
    source.addEventListener('chunk',message=>{
      try{const event=JSON.parse((message as MessageEvent).data);setStream(old=>appendStreamEvent(old,event));setConnection('connected');}
      catch{setConnection('invalid');}
    });
    source.addEventListener('unavailable',()=>{closed=true;setConnection('unavailable');source.close();});
    source.addEventListener('terminal',()=>{closed=true;setConnection('closed');source.close();});
    source.onerror=()=>{if(!closed)setConnection('reconnecting');};
    return()=>{closed=true;source.close();};
  },[run.id,enabled,subscribe]);
  return {stream,connection,enabled};
}

export function LiveOutput({live,nodeId,round,operationKey,terminal=false}:{live:ReturnType<typeof useLiveOutput>;nodeId:string;round?:number;operationKey?:string;terminal?:boolean}) {
  const call=matchingStream(live.stream,nodeId,round,operationKey);
  const scroll=useRef<HTMLPreElement>(null),follow=useRef(true);
  useEffect(()=>{const el=scroll.current;if(el&&follow.current)el.scrollTop=el.scrollHeight;},[call?.content]);
  if(!live.enabled)return terminal?null:<p className="live-note">这次调用使用旧版非流式请求，需要等模型返回后才能查看输出。新运行支持实时输出。</p>;
  if(!call&&terminal)return null;
  return <section className="live-output" aria-label="模型实时输出">
    <header><strong>{terminal?'本次流式记录':'实时输出'}</strong><span>{terminal?'已保存':call?.done?'传输结束 · 等待节点校验':'生成中 · 尚未提交'}</span></header>
    {live.connection==='reconnecting'&&<p role="status" className="live-note">输出连接暂时中断，正在续接已保存的内容；服务器任务继续运行。</p>}
    {live.connection==='invalid'&&<p role="status" className="live-note">收到无法读取的增量记录，保留已有内容。</p>}
    {call?.content?<pre ref={scroll} onScroll={()=>{const el=scroll.current;if(el)follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<40;}}>{call.content}</pre>:<p className="live-note">{call?.reasoning?'服务正在返回推理文本，回答正文尚未开始。':'正在等待服务返回第一段内容…'}</p>}
    {call?.reasoning&&<details open={!call.content}><summary>服务返回的推理文本</summary><pre>{call.reasoning}</pre></details>}
    {call?.truncated&&<p className="live-note">当前阅读窗口达到显示上限，完整增量保存在运行记录中。</p>}
    {!terminal&&<small>这里是已收到的原文，完整回答通过校验后才会成为本节点结果。</small>}
  </section>;
}
