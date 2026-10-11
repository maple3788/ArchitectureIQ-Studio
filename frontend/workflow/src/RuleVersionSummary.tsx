import {JsonView} from './ui';
import {ruleVersionCounts} from './ruleKnowledgePresentation';
import type {Json} from './types';

export function RuleVersionSummary({snapshot,compact=false}:{snapshot:Json;compact?:boolean}){
 const source=snapshot.source_document,protocol=snapshot.confirmation_protocol;
 if(!source&&!protocol)return null;
 const counts=ruleVersionCounts(snapshot);
 return <section className={'rr-source-summary'+(compact?' is-compact':'')} aria-label="规则版本来源">
  <p><b>{source?.version_label?(/^KB\s/i.test(source.version_label)?source.version_label:`KB ${source.version_label}`):'来源规则'}</b> · {counts.claims} 条主张 · {counts.clauses} 个执行分支</p>
  <p>{[counts.proposed?`${counts.proposed} 条待独立确认`:'',counts.replicated?`${counts.replicated} 条来源标记为范围内复现`:''].filter(Boolean).join(' · ')||'验证状态见各条规则'}。来源标记与本平台评分分开记录。</p>
  {source&&<details><summary>版本关系与来源</summary><p className="rr-version">{source.filename}{snapshot.parent_version?` · 父版本 ${snapshot.parent_version}`:''}</p>{source.legacy_disposition&&<><h4>旧规则的合并、拆分与停用</h4><dl className="rr-condition-list">{Object.entries(source.legacy_disposition).map(([id,value])=><div key={id}><dt>{id}</dt><dd>{String(value)}</dd></div>)}</dl></>}<JsonView value={source}/></details>}
  {protocol&&<details className="rr-protocol"><summary>来源预注册协议</summary><p className="muted">预注册协议不代表确认结果；研究题池通过也不等于独立确认。修改后的规则需重新确认。</p><dl className="rr-condition-list">{[['统计单位',protocol.unit],['确认主张',protocol.decision_rule?.confirmatory?.join('、')],['通过门槛',protocol.decision_rule?.REPLICATED],['反驳门槛',protocol.decision_rule?.REFUTED],['证据不足',protocol.decision_rule?.INCONCLUSIVE],['显著性门槛',protocol.decision_rule?.alpha],['后续使用',protocol.downstream]].filter(([,value])=>value).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><details><summary>完整预注册文档</summary><JsonView value={protocol}/></details></details>}
 </section>;
}
