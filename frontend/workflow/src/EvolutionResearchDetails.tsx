import type {Json} from './types';
import type {EvolutionConfiguration,EvolutionRoundDetail} from './knowledgeEvolutionState';

const count=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN'):'未记录';
const percentage=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?`${(value*100).toFixed(1)}%`:'未记录';

export function EvolutionStrategyDetails({configuration}:{configuration?:EvolutionConfiguration}){
 const config=configuration;
 const facts:[string,unknown][]=[['提出模型',config?.proposer?.model],['每轮计划题数',config?.questions?.per_round],
  ['定向题比例',config?.questions?.target_fraction===undefined?undefined:percentage(config.questions.target_fraction)],
  ['历史适用题下限',config?.checks?.min_history_applicable],['历史支持率下限',config?.checks?.new_min_rate===undefined?undefined:percentage(config.checks.new_min_rate)],
  ['每条规则条件上限',config?.checks?.max_conditions],['每轮收录上限',config?.proposer?.max_new_per_round],
  ['新增反例拆分阈值',config?.proposer?.split_new_errors],['每轮拆分原命题上限',config?.proposer?.split_max_claims],
  ['比较相对差距下限',config?.evidence?.min_relative_gap===undefined?undefined:percentage(config.evidence.min_relative_gap)]];
 return <details className="evolution-strategy"><summary>研究策略</summary><section aria-label="研究策略说明">
  <div className="evolution-strategy-columns"><div><h3>来源当前配置</h3><p className="evolution-note">读取来源保存的配置；不能据此认定当前轮已经执行，也不代表历史轮次的设置。</p>
   {config?<dl className="evolution-config-facts">{facts.filter(([,value])=>value!==undefined).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl>:<p className="evolution-note">尚未同步配置，运行阶段仍以保存的记录为准。</p>}
  </div><div><h3>最新设计 · 第 7 轮起</h3><p>先积累适用范围窄、准确率高的知识叶子；发现反例后向下拆分，保留原知识为父节点。合并为更一般知识留待后续。</p>
   <ul><li>新知识历史支持率 ≥ 95%，至少适用 1 道历史题，每条规则最多 10 个条件。</li><li>新增 3 道反例可触发拆分；每轮最多处理 30 条原知识，每条提出 3 份方案。</li><li>60% 定向题沿叶子条件寻找可判断的题，40% 随机探索。选题只检查适用性。</li></ul>
   <p className="evolution-note">来源：10 月 13 日更新的闭环设计。设计说明与实际运行记录分别展示。</p>
  </div></div>
  <div className="evolution-validation-separation"><div><h4>入库前 · 质量检查</h4><p>格式、允许字段、历史覆盖和支持率、去重。通过后登记为候选。</p></div><div><h4>登记后 · 新题验证</h4><p>设计要求：新题至少适用 40 道、支持率 ≥ 85%、统计下界 ≥ 0.70，才标记来源已验证。实际阈值见证据判定节点。</p></div></div>
 </section></details>;
}

function JointResults({label,results}:{label:string;results:Json}){
 return <article><h4>{label}</h4><dl className="evolution-config-facts">
  <div><dt>已验证知识</dt><dd>{count(results.claims)} 条</dd></div>
  <div><dt>作答 / 题目</dt><dd>{count(results.answered)} / {count(results.questions)}</dd></div>
  <div><dt>答对</dt><dd>{count(results.correct)} 道</dd></div>
  <div><dt>覆盖率</dt><dd>{percentage(results.coverage)}</dd></div>
  <div><dt>已答题正确率</dt><dd>{results.answered===0?'未作答':percentage(results.accuracy)}</dd></div>
  <div><dt>全部题正确率</dt><dd>{percentage(results.overall)}</dd></div>
 </dl></article>;
}

export function EvolutionRoundResults({data}:{data:EvolutionRoundDetail}){
 const report=data.report,build=report?.build,splits=report?.splits,proposal=data.proposals;
 const hasSplit=splits||proposal?.split_count!==undefined||proposal?.split_parent_count!==undefined||proposal?.split_attempt_count!==undefined;
 return <>
  {(build?.steered!==undefined||build?.target_hit!==undefined||hasSplit)&&<section aria-label="定向与拆分结果"><h3>定向与拆分</h3><dl className="evolution-evidence-numbers">
   {(build?.steered!==undefined||build?.target_hit!==undefined)&&<div><dt>目标适用 / 已记录定向检验的有效题</dt><dd>{count(build?.target_hit)} / {count(build?.steered)}</dd></div>}
   {(splits?.parents!==undefined||proposal?.split_attempt_count!==undefined)&&<div><dt>尝试拆分的原知识</dt><dd>{count(splits?.parents??proposal?.split_attempt_count)}</dd></div>}
   {proposal?.split_parent_count!==undefined&&<div><dt>通过检查的原知识</dt><dd>{count(proposal.split_parent_count)}</dd></div>}
   {splits?.registered!==undefined?<div><dt>新登记的窄知识</dt><dd>{count(splits.registered)}</dd></div>:proposal?.split_count!==undefined&&<div><dt>通过检查的拆分提案</dt><dd>{count(proposal.split_count)}</dd></div>}
  </dl><p className="evolution-note">命中表示目标知识能判断这道题，正确与否由后续规则验证记录。</p></section>}
  <section aria-label="KB 联合答题"><h3>KB 联合答题</h3><p className="evolution-note">仅已验证知识对候选两两投票，胜场最多者作答，平票不答；候选不参与。这是研究轮次统计，并非独立的 500 题评测。</p>
   {report?.ensemble||report?.ensemble_explore?<div className="evolution-joint-results">{report?.ensemble&&<JointResults label="本轮全部题（含定向）" results={report.ensemble}/>} {report?.ensemble_explore&&<JointResults label="随机探索题" results={report.ensemble_explore}/>}</div>:<p className="evolution-note">这轮尚无保存的联合答题报告。</p>}
  </section>
  {(report?.model||proposal?.model)&&<p className="evolution-note">本轮报告记录模型：<span>{report?.model??proposal?.model}</span></p>}
 </>;
}
