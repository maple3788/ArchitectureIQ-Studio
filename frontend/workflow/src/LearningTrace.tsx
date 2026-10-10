import type { Json } from './types';
import './pair-learning.css';
const fields:Record<string,string>={conditions:'适用条件',exceptions:'例外与失效边界',interactions:'因素之间的交互',changed_factors:'改变的因素',controlled_factors:'保持不变的因素',competing_explanation:'竞争解释',next_test:'下一步可检验的预测'};
export function LearningNote({value}:{value:Json}) {
 const note=value?.learning;
 if(!note)return <p>本次没有形成符合格式要求的归纳。原始回答保留在调用记录中。</p>;
 return <div><p>{note.summary}</p><dl>{Object.entries(fields).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{Array.isArray(note[key])?note[key].length?<ul>{note[key].map((v:string,i:number)=><li key={i}>{v}</li>)}</ul>:'尚未提出':typeof note[key]==='string'?note[key]:'未记录'}</dd></div>)}</dl></div>;
}
export function LearningTrace({trace}:{trace:Json}) {
 return <section className="learning-traces" aria-label="反事实学习轨迹"><h3>知识怎样随对照反馈变化</h3><p title={trace.pair_id}>题对学习 · 待验证的研究记录 · 模型权重固定</p>
 {trace.induction&&<article className="learning-trace-step"><h4>1 · 从正常题归纳初步规律</h4><p>此时只给出正常题的作答与反馈。</p><LearningNote value={trace.induction}/></article>}
 {trace.transfer&&<article className="learning-trace-step"><h4>2 · 用初步规律预测 DataFlip</h4><p>这次迁移预测使用待验证规律，尚未获得 DataFlip 反馈；它与独立作答基线分别保存。</p><p>预测排序：{Array.isArray(trace.transfer.ranking)?trace.transfer.ranking.join(' → '):'未形成有效排序'}</p><p>{trace.transfer.rationale || trace.transfer.explanation}</p></article>}
 {(trace.revision||trace.contrastive)&&<article className="learning-trace-step"><h4>{trace.revision?'3 · 对照反馈后修订':'对照两题，解释变化与不变'}</h4><LearningNote value={trace.revision||trace.contrastive}/></article>}
 <p>这些文字用于观察归纳过程。正式 KB 只接受通过实验、证据与发布检查的更新。</p></section>;
}
