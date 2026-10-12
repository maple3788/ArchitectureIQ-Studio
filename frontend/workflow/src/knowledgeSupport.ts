import type {KnowledgeRevision} from './knowledgeEntries';
export const HIGH_SUPPORT_QUESTIONS=20;
export type KnowledgeSupport={support:number|null;refute:number|null;notice:string};
export function knowledgeSupport(claimId:string,revision:KnowledgeRevision):KnowledgeSupport{
 const value=revision.record.evidence_summary,claim=value?.claims?.[claimId];
 const known=value?.scope==='saved_question_results'&&value.unit==='distinct_questions'
  &&value.kb_ref?.id===revision.record.id&&value.kb_ref?.version===revision.record.version
  &&claim?.complete===true&&[claim.support_questions,claim.refute_questions,claim.unknown_questions].every(count=>Number.isSafeInteger(count)&&count>=0);
 return known?{support:claim.support_questions,refute:claim.refute_questions,notice:claim.notice||'按保存的逐题结果统计。'}
  :{support:null,refute:null,notice:claim?.notice||'此版本尚无完整、可核验的逐题支持统计。'};
}
export function supportLabel(value:KnowledgeSupport){
 return value.support===null?'支持证据未统计':`支持 ${value.support} 题 · 反例 ${value.refute} 题`;
}
