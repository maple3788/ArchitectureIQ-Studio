import type {Run,Json} from './types';
import type {PublicCase,RuleRefinementView} from './ruleRefinementTypes';
const phases:Record<string,string>={baseline:'程序验证',ready:'检查下一步',initialize:'提出初始规则',revise:'修订规则',candidate_check:'候选 KB 回归',accept:'不退步验收',challenge:'生成新题挑战',first_test:'新题首测',promote:'纳入研究题池',finish:'已结束'};
export const stopLabels:Record<string,string>={target_reached:'目标已达成',resource_limit:'资源上限已达到',budget_exhausted:'资源上限已达到',no_progress:'连续尝试未取得进步',revision_limit:'修订尝试已达上限',generation_limit:'新题生成已达上限',user_stop:'已按请求停止',uncertain:'外部调用结果不确定',execution_failure:'执行未完成'};
export const independenceLabels:Record<string,string>={verified_first_use:'首次使用且可核验',repeated_evaluation:'重复评测',unknown_prior_exposure:'此前接触情况未知'};
export const decisionLabels:Record<string,string>={regression:'已答对的题目退步',incomplete_pool:'题池评分不完整',no_progress:'未取得规则进步',reduced_answer_coverage:'明确作答率下降',improved:'通过不退步验收'};
export const problemLabels:Record<string,string>={wrong_answer:'答错',conflict:'规则冲突',uncovered:'未覆盖',rule_counterexample:'规则反例',material_failure:'资料不完整'};
export function deriveRuleRefinementView(run:Run):RuleRefinementView{
 const cp=run.refinement||{},result=run.result||{};const seen=new Set<string>();const events=(run.events||[]).filter(e=>{const key=String(e.sequence??e.refinement_event_id??JSON.stringify(e));if(seen.has(key))return false;seen.add(key);return true;});
 const phase=cp.phase??events[events.length-1]?.phase;
 return {phase:phase?phases[phase]||phase:'等待运行记录',phaseId:phase,success:result.outcome==='target_reached',status:result.stop_reason?stopLabels[result.stop_reason]||'研究已停止':run.status==='paused'?'已暂停':phases[phase]||'等待运行记录',score:result.score??cp.score,batches:result.fresh_batches??cp.fresh_batches??[],kb:result.best_kb??cp.best_kb,kbVersion:cp.kb_version??result.score?.kb_version,poolVersion:cp.pool_version??result.score?.pool_version,events,budget:result.budget??cp.budget,revision:cp.revision??0};
}
export function retainRuleRun(previous:Run|undefined,next:Run):Run{
 if(!previous||previous.id!==next.id||!['rule_refinement','rule_evaluation'].includes(next.kind))return next;
 const rank=(r:Run)=>[r.refinement?.revision??0,Math.max(0,...(r.events||[]).map(e=>e.sequence??0))];const before=rank(previous),after=rank(next);
 if(after[0]<before[0]||after[0]===before[0]&&after[1]<before[1]||previous.result&&!next.result)return previous;
 return next;
}
export function caseRecord(c:PublicCase):Json{return {public:c.question,detail:{prompt:c.question.prompt,dataset:{files:{'dataset_spec.json':JSON.stringify(c.dataset_spec)}},choices:c.question.choices?.map((choice:Json)=>({letter:choice.letter,candidateId:choice.id,files:{'candidate_spec.json':JSON.stringify(c.candidate_specs.find(s=>s.candidate_id===choice.id)||{})}}))}};}
