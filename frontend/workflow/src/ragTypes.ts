import type {Json,ModelProfile} from './types';
export type RagKB={id:string;version:string;name:string;kind:string};
export type RagHit={citation_id:string;record_id:string;revision:number;kind:string;text:string;verified:boolean;score:number;condition_score:number;reasons:string[];source_refs:(RagKB&{record_id:string;revision:number;sources:Json[]})[]};
export type RagRetrieval={strategy:string;inventory_hash:string;selected_kb:RagKB|null;candidates:{kb:RagKB;hits:RagHit[]}[];knowledge:Json[];provenance:RagHit[];warnings:Json[];excluded:Record<string,number>;omitted:Record<string,number>};
export type RagPreview={preview_hash:string;sent:false;can_answer:boolean;blocked_reason:'empty_library'|'no_match'|null;question:Json;models:ModelProfile[];retrieval:RagRetrieval;request:{payload:Json}|null;reserved_tokens:number};
export function publicRagReady(record:Json):boolean{
 const q=record.public;const choices=q?.choices;
 return !!q?.id&&!!q?.family&&typeof q?.prompt==='string'&&!!q.prompt.trim()&&Array.isArray(choices)&&choices.length>=2&&
 choices.every((c:any)=>typeof c.id==='string'&&!!c.id&&/^[A-Z]$/.test(c.letter)&&c.view&&typeof c.view==='object'&&!Array.isArray(c.view))&&
 new Set(choices.map((c:any)=>c.letter)).size===choices.length&&new Set(choices.map((c:any)=>c.id)).size===choices.length;
}
