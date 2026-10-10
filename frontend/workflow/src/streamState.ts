export type LiveCall = {wireKey:string;nodeId:string;round?:number;operationKey?:string;content:string;reasoning:string;done:boolean;lastSeq:number;truncated?:boolean};
export type StreamState = {lastSeq:number;calls:Record<string,LiveCall>};
export const emptyStream = ():StreamState => ({lastSeq:0,calls:{}});
const displayLimit=500_000;
export function appendStreamEvent(state:StreamState,event:any):StreamState {
  if(!Number.isSafeInteger(event?.seq)||event.seq<=state.lastSeq||typeof event.wire_key!=='string'||typeof event.node_id!=='string')return state;
  const previous=state.calls[event.wire_key];
  if(previous&&(previous.nodeId!==event.node_id||previous.round!==event.round_index||previous.operationKey!==event.operation_key))return state;
  const call:LiveCall={...(previous??{wireKey:event.wire_key,nodeId:event.node_id,round:event.round_index,operationKey:event.operation_key,content:'',reasoning:'',done:false,lastSeq:0})};
  if(event.kind==='done')call.done=true;
  else if(event.kind==='chunk')for(const choice of Array.isArray(event.chunk?.choices)?event.chunk.choices:[]){
    if(!choice||typeof choice!=='object')continue;
    if(choice.index!==0&&choice.index!==undefined)continue;
    if(typeof choice.delta?.content==='string')call.content+=choice.delta.content;
    if(typeof choice.delta?.reasoning_content==='string')call.reasoning+=choice.delta.reasoning_content;
  }
  if(call.content.length>displayLimit||call.reasoning.length>displayLimit)call.truncated=true;
  call.content=call.content.slice(0,displayLimit);call.reasoning=call.reasoning.slice(0,displayLimit);call.lastSeq=event.seq;
  return {lastSeq:event.seq,calls:{...state.calls,[event.wire_key]:call}};
}
export function matchingStream(state:StreamState,nodeId:string,round?:number,key?:string):LiveCall|undefined {
  if(round===undefined||!key)return undefined;
  return Object.values(state.calls).filter(c=>c.nodeId===nodeId&&c.round===round&&c.operationKey===key).sort((a,b)=>b.lastSeq-a.lastSeq)[0];
}
