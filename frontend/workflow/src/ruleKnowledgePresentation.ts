import type {Json} from './types';

const fields:Record<string,string>={model_type:'模型类型',family:'数据家族',task:'任务',opt:'优化器',opt_key:'优化器完整配置',arch_key:'网络完整结构',batch_size:'批大小',depth:'深度',width:'宽度',activation:'激活函数',residual:'残差连接',ln_any:'含 LayerNorm',ln_all:'所有层含 LayerNorm',ln_count:'LayerNorm 层数',smooth_activation:'平滑激活函数',disp:'累计步长',eff_lr:'有效学习率',lr:'学习率',steps:'训练步数',momentum:'动量',beta2:'β₂',weight_decay:'权重衰减',sign_normalized:'符号归一化优化器'};
Object.assign(fields, {
 input_dim:'输入维数', n_used_inputs:'目标实际使用的输入变量数', transition_alpha:'转移表集中度',
 rule_family:'数据规则', n_active_features:'有效特征数', spiral_turns:'螺旋圈数',
 vocab_size:'词表大小', context_length:'上下文长度', train_size:'训练集大小',
 target_abs_mean:'目标绝对值均值', target_std:'目标标准差', target_oscillatory:'目标含振荡项',
});
export const ruleField=(key:string)=>fields[key]??key;
const valueText=(value:unknown):string=>value===true?'是':value===false?'否':Array.isArray(value)?value.map(valueText).join('、'):String(value);
export function predicateText(value:any):string{
 if(value==null||Array.isArray(value)&&value.length===0)return '无额外范围限制';
 if(Array.isArray(value)){
  if(typeof value[0]==='string')return `${ruleField(value[0])} ${(({eq:'=',ne:'≠',lt:'<',le:'≤',gt:'>',ge:'≥',in:'属于',nin:'不属于'} as Record<string,string>)[value[1]]??value[1])} ${valueText(value[2])}`;
  return value.map(predicateText).join(' 且 ');
 }
 if(value.any)return `（${value.any.map(predicateText).join(' 或 ')}）`;
 if(value.all)return `（${value.all.map(predicateText).join(' 且 ')}）`;
 if(value.not)return `不满足（${predicateText(value.not)}）`;
 return JSON.stringify(value);
}
export function ruleConditions(rule:Json):[string,string][]{
 if(!rule?.predict)return [];
 const result:[string,string][]=[['适用范围',predicateText(rule.scope)]];
 if(rule.same?.length)result.push(['保持相同',rule.same.map(ruleField).join('、')]);
 if(rule.differ?.length)result.push(['需要不同',rule.differ.map(ruleField).join('、')]);
 if(rule.max_param_ratio!=null)result.push(['参数量边界',`两候选参数量之比不超过 ${rule.max_param_ratio} 倍`]);
 const p=rule.predict;
 if(p.higher_better||p.lower_better){
  result.push(['结论',`${ruleField(p.higher_better??p.lower_better)}${p.higher_better?'更高':'更低'}的候选更好${p.min_ratio>1?`，两者之比至少 ${p.min_ratio} 倍`:''}`]);
 }else if(p.dominates){
  result.push(['结论',p.dominates.map((a:any[])=>`${ruleField(a[0])}${a[1]==='higher'?'不低于':'不高于'}另一候选${a[2]>1?`（比值至少 ${a[2]} 倍）`:''}`).join('，')+'；至少一项严格改善']);
  if(p.winner)result.push(['胜者还需满足',predicateText(p.winner)]);
  if(p.loser)result.push(['败者还需满足',predicateText(p.loser)]);
 }else if(p.better&&p.worse){result.push(['胜者条件',predicateText(p.better)],['败者条件',predicateText(p.worse)]);}
 return result;
}
export function ruleGroups(rules:Json[]):{id:string;rules:Json[]}[]{
 const groups=new Map<string,Json[]>();
 for(const rule of rules){const key=rule.metadata?.claim_id??rule.rule_id;groups.set(key,[...(groups.get(key)??[]),rule]);}
 return [...groups].map(([id,entries])=>({id,rules:entries.sort((a,b)=>(a.metadata?.clause_index??0)-(b.metadata?.clause_index??0))}));
}
export function sourceStatus(metadata:Json):string{
 if(metadata.validation_origin==='modified_in_studio')return '本平台已修订 · 待重新验证';
 const names:Record<string,string>={proposed:'待独立确认',replicated_in_scope:'范围内复现',refuted:'已被反驳',inconclusive:'证据不足'};
 return `来源标记：${names[metadata.validity_status]??metadata.validity_status??'未标记验证状态'}`;
}
export function ruleVersionCounts(snapshot:Json){
 const groups=ruleGroups(snapshot.rules??[]);
 const current=groups.map(g=>({...g,rules:g.rules.filter(r=>r.state!=='retired')})).filter(g=>g.rules.length);
 const proposed=current.filter(g=>g.rules.some(r=>r.metadata?.validity_status==='proposed'||r.metadata?.validation_origin==='modified_in_studio')).length;
 const replicated=current.filter(g=>g.rules.every(r=>r.metadata?.validity_status==='replicated_in_scope'&&r.metadata?.validation_origin==='source_reported')).length;
 return {claims:groups.length,clauses:(snapshot.rules??[]).length,proposed,replicated};
}
