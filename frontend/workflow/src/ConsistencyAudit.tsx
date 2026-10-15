import {JsonView} from './ui';
import {formatTimestamp} from './time';
import './consistency-audit.css';

export type ConsistencyAudit = {
 status:'passed'|'needs_review'|'unchecked';
 issues:{code:string;message:string;quote?:string;rule_indices?:number[]}[];
 conditions?:{quote:string;rule_indices:number[];status:string}[];
 explanation?:{text:string;status:'hypothesis'};
 budget_context?:unknown;
 checked_at?:number;
 checker_version?:string;
};
export const consistencyLabels={passed:'一致性检查通过',needs_review:'一致性待复核',unchecked:'一致性未检查'};
function ruleReferences(indices?:number[]){return indices?.length?`分支 ${indices.map(index=>index+1).join('、')}`:undefined;}
export function ConsistencyAuditView({audit}:{audit?:ConsistencyAudit|null}){
 const status=audit?.status??'unchecked';
 const conditions=audit?.conditions??[],issues=audit?.issues??[];
 return <>
  <section className={`consistency-audit is-${status}`} aria-label="文字与规则一致性审计">
   <strong>{consistencyLabels[status]}</strong>
   <p>{status==='passed'?'文字条件与执行规则已核对；这不代表命题经过实证验证。':status==='needs_review'?`${issues.length} 项问题需要复核。`:'尚无该保存版本的审计结果。'}</p>
   {audit&&(issues.length>0||conditions.length>0||audit.budget_context!=null||audit.checked_at||audit.checker_version)&&<details>
    <summary>审计详情</summary>
    {issues.length>0&&<ul className="consistency-issues">{issues.map((issue,index)=><li key={`${issue.code}-${index}`}><p>{issue.message}</p>{issue.quote&&<blockquote>{issue.quote}</blockquote>}{ruleReferences(issue.rule_indices)&&<small>{ruleReferences(issue.rule_indices)}</small>}</li>)}</ul>}
    {conditions.length>0&&<section aria-label="文字条件对应关系"><h4>文字条件与执行规则</h4><ul>{conditions.map((condition,index)=><li key={index}><blockquote>{condition.quote}</blockquote><small>{({matched:'已匹配',missing:'未匹配执行规则',unmatched:'未匹配执行规则',ambiguous:'对应关系待确认'} as Record<string,string>)[condition.status]??'对应关系待确认'}{ruleReferences(condition.rule_indices)?` · ${ruleReferences(condition.rule_indices)}`:''}</small></li>)}</ul></section>}
    {audit.budget_context!=null&&<details><summary>真实预算上下文</summary><JsonView value={audit.budget_context}/></details>}
    {(audit.checked_at||audit.checker_version)&&<p className="consistency-metadata">{audit.checked_at?formatTimestamp(audit.checked_at):''}{audit.checker_version?` · 检查器 ${audit.checker_version}`:''}</p>}
   </details>}
  </section>
  {audit?.explanation?.text&&<section className="consistency-explanation" aria-label="因果解释 · 待验证"><h4>因果解释 · 待验证</h4><p>{audit.explanation.text}</p><small>保留原文解释，尚未建立因果证据。</small></section>}
 </>;
}
