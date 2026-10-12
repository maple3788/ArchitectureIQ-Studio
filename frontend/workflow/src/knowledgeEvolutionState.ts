import {useEffect, useState} from 'react';
import {api} from './api';
import type {Json} from './types';
import type {Timestamp} from './time';
import type {PathEdge, PathNode, PathPortSide} from './ResearchPathCanvas';

export const evolutionStages = ['plan','build','score','judge','propose','register','report'] as const;
export type EvolutionStage = typeof evolutionStages[number];
export const evolutionLabels: Record<EvolutionStage,string> = {
  plan:'研究计划', build:'生成新题', score:'规则验证', judge:'证据判定',
  propose:'提出与修订', register:'预注册', report:'轮次归档',
};
export const evolutionDescriptions: Record<EvolutionStage,string> = {
  plan:'定向检验与探索题相结合', build:'正式管线生成 · 真实训练结果',
  score:'程序执行规则 · 每道题一票', judge:'支持率与统计下界共同判定',
  propose:'模型提出修订 · 程序检查', register:'登记并封存 · 下一轮新题检验',
  report:'保存本轮证据 · 继续复验',
};
export const claimStateLabels: Record<string,string> = {
  candidate:'候选', verified:'来源已验证', flagged:'存疑', retired:'停用',
};
export type EvolutionSync = {status:string; last_success_at?:Timestamp; last_attempt_at?:Timestamp; message?:string};
export type EvolutionObservation = {source_identity:string;sequence:number};
export type EvolutionTaskContext = {observation:EvolutionObservation;claim_ref?:{id:string;version:number}};
export type EvolutionClaim = {
  id:string; version:number; text:string; rules:Json[]; status:string; registered_round:number;
  needs_revision:boolean; revisions:number; stats?:Json|null; parent?:Json|null; rationale?:string;
  consistency?:{consistent:boolean|null;issue?:string}|null;
  evidence:{applicable:number;support:number;refute:number;conflicts:number};
};
export type EvolutionRound = {
  index:number; completed?:boolean; completed_stages:string[]; next_stage?:string;
  plan?:{total:number;target:number;explore:number};
  build?:{completed:number;ok:number;failed:number}; report?:Json|null;
};
export type EvolutionSnapshot = {
  configured:boolean; name?:string; sequence:number; sync:EvolutionSync;
  observation?:EvolutionObservation;
  captured_at?:Timestamp; source_updated_at?:Timestamp;
  execution?:{status:string;stop_requested:boolean;alert:boolean};
  round?:EvolutionRound|null; kb?:{claims:number;candidate:number;verified:number;flagged:number;retired:number};
  evidence?:{questions:number;verdicts:number}; claims?:EvolutionClaim[]; rounds?:EvolutionRound[]; thresholds?:Json;
};
export type EvolutionClaimDetail = {observation?:EvolutionObservation;claim:EvolutionClaim;history:EvolutionClaim[];evidence:Json[];evidence_total:number|null;evidence_truncated:boolean;reading_round?:number;evidence_unavailable?:boolean;notice?:string};
export type EvolutionGeneration = {total:number;completed:number;ok:number;failed:number;pending:number;items:{item_id:string;family:string;question_type:string;budget?:Json;purpose:string;targets:string[];status:string;seconds?:number;question_id?:string}[]};
export type EvolutionRoundDetail = EvolutionRound & {
  observation?:EvolutionObservation;
  generation?:EvolutionGeneration;
  score?:Json|null; judge_events?:Json[]; proposals?:{new_count:number;revision_count:number;rejections:Json;qwen:Json}|null;
  registration?:{count:number;hash?:string;hash_matches?:boolean|null}|null; registered?:Json[];
};

/** Sequence controls business snapshots; heartbeats only update connection metadata. */
export function useKnowledgeEvolution() {
  const [snapshot,setSnapshot] = useState<EvolutionSnapshot>();
  const [connection,setConnection] = useState<'connecting'|'connected'|'disconnected'>('connecting');
  useEffect(()=>{
    let active=true, source:EventSource|undefined, retry:ReturnType<typeof setTimeout>|undefined, sequence=0;
    const accept=(value:EvolutionSnapshot)=>{
      if(typeof value?.configured!=='boolean'||!Number.isFinite(value.sequence))throw Error('Invalid snapshot');
      if(!active||value.sequence<sequence)return;
      sequence=value.sequence;
      setSnapshot(value);setConnection('connected');
    };
    const fail=()=>{if(active)setConnection('disconnected');};
    const connect=()=>{
      if(!active)return;
      if(typeof EventSource==='undefined'){
        retry=setTimeout(()=>void load(),5000);return;
      }
      source=new EventSource(`/api/studio/kb-loop/stream?after=${sequence}`);
      source.addEventListener('snapshot',event=>{
        try{accept(JSON.parse((event as MessageEvent).data));}catch{fail();}
      });
      source.addEventListener('sync',event=>{
        try{
          const payload=JSON.parse((event as MessageEvent).data),sync:EvolutionSync=payload.sync??payload;
          if(typeof sync.status!=='string')throw Error('Invalid sync');
          if(active){setSnapshot(old=>old?{...old,sync}:old);setConnection('connected');}
        }catch{fail();}
      });
      source.onerror=()=>{
        source?.close();fail();
        if(active)retry=setTimeout(()=>void load(),3000);
      };
    };
    const load=async()=>{
      try{accept(await api<EvolutionSnapshot>('/kb-loop'));}
      catch{fail();}
      finally{if(active)connect();}
    };
    void load();
    return()=>{active=false;source?.close();clearTimeout(retry);};
  },[]);
  return {snapshot,connection};
}

export function evolutionPresentation(snapshot?:EvolutionSnapshot,connected=true):{nodes:PathNode[];edges:PathEdge[]} {
  const positions=[{x:0,y:0},{x:270,y:0},{x:540,y:0},{x:540,y:185},{x:270,y:185},{x:0,y:185},{x:0,y:370}];
  const done=new Set(snapshot?.round?.completed_stages??[]);
  const nodes:PathNode[]=evolutionStages.map((id,index)=>({
    id,label:evolutionLabels[id],description:id==='build'&&snapshot?.round?.plan
      ?`${snapshot.round.build?.completed??0} / ${snapshot.round.plan.total} 组已完成 · ${snapshot.round.build?.ok??0} 道有效题`
      :evolutionDescriptions[id],position:positions[index],stage:id==='plan'||id==='build'?'data':id==='register'||id==='report'?'kb':'harness',
    kind:id==='propose'?'model':id==='judge'?'decision':'program',
    status:done.has(id)?'complete':snapshot?.round?.next_stage===id
      ?connected&&snapshot.execution?.status==='running'&&!snapshot.execution.alert?'running':'待完成':undefined,
    inputs:[],outputs:[],inputSides:{},outputSides:{},
  }));
  const edges:PathEdge[]=[];
  const connect=(from:EvolutionStage,to:EvolutionStage,fromSide:PathPortSide,toSide:PathPortSide,label?:string,loop=false)=>{
    const id=`evolution-${from}-${to}`,source=nodes.find(node=>node.id===from)!,target=nodes.find(node=>node.id===to)!;
    source.outputs!.push(id);source.outputSides![id]=fromSide;target.inputs!.push(id);target.inputSides![id]=toSide;
    edges.push({id,source:from,target:to,sourceHandle:id,targetHandle:id,label,loop});
  };
  connect('plan','build','right','left');connect('build','score','right','left');
  connect('score','judge','bottom','top');connect('judge','propose','left','right','证据与反例');
  connect('propose','register','left','right','通过检查');connect('register','report','bottom','top');
  connect('report','plan','left','left',undefined,true);
  return {nodes,edges};
}
