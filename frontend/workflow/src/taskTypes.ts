import type {Json,ModelProfile} from './types';
import type {RagRetrieval} from './ragTypes';
export type TaskMode='llm'|'rules';
export type TaskKB={id:string;version:string;name:string;kind:string;summary?:string;[key:string]:unknown};
export type TaskFields={name:string;question_key:string|null;mode:TaskMode;model_id:string|null;kb_selection:{mode:'auto'|'manual';ref?:{id:string;version:string}};knowledge_limit:number};
export type TaskCard=TaskFields&{id:string;revision:number;created_at:number|string;updated_at:number|string};
export type TaskPrediction={status:string;answer_id:string|null;answer_letter:string|null;matches:{kb:TaskKB;prediction:Json;rules?:Json[]}[];issues:{code:string;message:string}[]};
export type TaskPreview={task_id:string;task_revision:number;mode:TaskMode;preview_hash:string;can_run:boolean;can_answer:boolean;question:Json;selected_kbs:TaskKB[];model?:Partial<ModelProfile>;retrieval?:RagRetrieval;request?:{payload:Json};reserved_tokens?:number;prediction?:TaskPrediction;warnings:{code:string;message:string}[]};
export type TaskRun={id:string;task_id:string;task_revision:number;mode:TaskMode;status:string;created_at:number|string;job_id?:string;result?:Json;[key:string]:unknown};
export function taskFields(card:TaskFields):TaskFields{return {name:card.name,question_key:card.question_key,mode:card.mode,model_id:card.mode==='rules'?null:card.model_id,kb_selection:card.kb_selection.mode==='auto'?{mode:'auto'}:{mode:'manual',ref:card.kb_selection.ref},knowledge_limit:card.knowledge_limit};}
export function taskSignature(fields:TaskFields){return JSON.stringify(taskFields(fields));}
export function newTask(questionKey?:string):TaskFields{return {name:'',question_key:questionKey||null,mode:'llm',model_id:null,kb_selection:{mode:'auto'},knowledge_limit:8};}
export function taskRunLabel(status:string){return ({complete:'已完成',uncertain:'结果待核实',completed:'已完成',succeeded:'已完成',running:'作答中',queued:'等待执行',pending:'等待执行',starting:'准备执行',failed:'执行失败',interrupted:'已中断',cancelled:'已取消'} as Record<string,string>)[status]||status;}
