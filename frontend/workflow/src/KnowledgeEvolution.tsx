import {useEffect,useState} from 'react';
import {ArrowUpRight,ChevronRight} from 'lucide-react';
import {api} from './api';
import {evidenceQuestionSummary} from './evidenceQuestionSummary';
import {Drawer,Empty,ErrorBox,JsonView,Loading,Tabs} from './ui';
import {ResearchPathCanvas} from './ResearchPathCanvas';
import {ruleConditions} from './ruleKnowledgePresentation';
import {formatTimestamp} from './time';
import {EvolutionTaskEntry,initialGenerationView,LoopGenerationPanel,LoopQuestionPanel} from './LoopQuestionPanel';
import type {Json} from './types';
import type {TaskSeed} from './taskTypes';
import {
  claimStateLabels,evolutionDescriptions,evolutionLabels,evolutionPresentation,useKnowledgeEvolution,
  type EvolutionClaim,type EvolutionClaimDetail,type EvolutionRoundDetail,type EvolutionSnapshot,type EvolutionStage,type EvolutionTaskContext,
} from './knowledgeEvolutionState';
import './knowledge-evolution.css';

const percent=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?`${(value*100).toFixed(1)}%`:'待判定';
const count=(value:unknown)=>typeof value==='number'?value.toLocaleString('zh-CN'):'—';

function useDetail<T>(path:string|undefined,sequence:number,connected:boolean){
  const [result,setResult]=useState<{path?:string;data?:T;error?:string}>({});
  useEffect(()=>{
    let active=true;
    if(path)void api<T>(path).then(data=>{if(active)setResult({path,data});}).catch(()=>{
      if(active)setResult(old=>({path,data:old.path===path?old.data:undefined,error:'详情暂时无法同步，请稍后重新打开。'}));
    });
    return()=>{active=false;};
  },[path,sequence,connected]);
  return result.path===path?result:{};
}

function ClaimEvidence({claim}:{claim:EvolutionClaim}){
  return <dl className="evolution-evidence-numbers">
    <div><dt>支持 / 适用题</dt><dd>{count(claim.evidence?.support)} / {count(claim.evidence?.applicable)}</dd></div>
    <div><dt>反例</dt><dd>{count(claim.evidence?.refute)}</dd></div>
    <div><dt>统计下界</dt><dd>{percent(claim.stats?.lower_bound)}</dd></div>
  </dl>;
}

function RuleBranches({rules}:{rules:Json[]}){
  return <>{rules.map((rule,index)=>{
    let conditions:[string,string][]=[];
    try{conditions=ruleConditions(rule);}catch{/* Unknown source syntax remains available in the original record. */}
    const hasConclusion=conditions.some(([label])=>['结论','胜者条件'].includes(label));
    return <article className="evolution-rule-branch" key={index}>
      {rules.length>1&&<h4>执行分支 {index+1}</h4>}
      {conditions.length>0&&<dl className="evolution-rule-conditions">{conditions.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
      {!hasConclusion&&<p className="evolution-note">这个执行分支暂未转换为阅读形式，可展开查看原始规则。</p>}
      <details className="evolution-raw-record"><summary>完整规则记录</summary><JsonView value={rule}/></details>
    </article>;
  })}{!rules.length&&<p className="evolution-note">尚无保存的执行规则。</p>}</>;
}

function EvidenceComparisons({row}:{row:Json}){
  const brief=evidenceQuestionSummary(row.question),alias=brief.alias;
  const pairs=(Array.isArray(row.pairs)?row.pairs:[]).filter((pair:unknown)=>Array.isArray(pair)&&pair.length>=2) as unknown[][];
  const relation=(better:unknown,worse:unknown)=>`${alias(better)} 优于 ${alias(worse)}`;
  return <>
    <div className="evolution-question-brief"><h4>{brief.title}</h4><p>{brief.description}</p><div className="evolution-candidate-briefs">{brief.candidates.map(candidate=><div key={candidate.id}><strong>{candidate.label}</strong><small>{candidate.id}</small></div>)}</div></div>
    {pairs.length?<div className="evolution-comparison-scroll"><table className="evolution-comparisons"><thead><tr><th>存储结果</th><th>规则预测</th><th>检验</th></tr></thead><tbody>{pairs.map((pair,index)=><tr key={index}><td>{relation(pair[0],pair[1])}</td><td>{pair[2]===true?relation(pair[0],pair[1]):pair[2]===false?relation(pair[1],pair[0]):'未记录'}</td><td>{pair[2]===true?'支持':pair[2]===false?'反例':'待判定'}</td></tr>)}</tbody></table></div>:<p className="evolution-note">这条记录没有保存可阅读的比较关系。</p>}
    <p className="evolution-note">按保存的候选配置比较；完整题目中可选择答案并检查训练结果。</p>
    {typeof row.conflicts==='number'&&row.conflicts>0&&<p className="evolution-warning">另有 {row.conflicts} 个内部冲突的比较被来源跳过，不参与这道题的支持或推翻判定。</p>}
    <details className="evolution-raw-record"><summary>候选配置与完整证据</summary><JsonView value={{comparisons:row.pairs,conflicts:row.conflicts,question:row.question}}/></details>
  </>;
}

function ClaimReader({data,onQuestion,onTask}:{data:EvolutionClaimDetail;onQuestion:(id:string)=>void;onTask?:(seed:TaskSeed)=>void}){
  const claim=data.claim;
  return <div className="evolution-claim-reader">
    <span className={`evolution-claim-status is-${claim.status}`}>{claimStateLabels[claim.status]??claim.status}</span>
    <p className="evolution-claim-text">{claim.text}</p>
    {onTask&&<EvolutionTaskEntry selection={data.observation?{observation:data.observation,claim_ref:{id:claim.id,version:claim.version}}:undefined} onTask={onTask} hint="带入当前知识"/>}
    <ClaimEvidence claim={claim}/>
    <p className="evolution-note">证据计数仅包含当前修订登记之后的新题；统计下界来自来源判定记录。</p>
    {claim.needs_revision&&<p className="evolution-warning">该命题已被标记为需要修订。</p>}
    {claim.rationale&&<p>{claim.rationale}</p>}
    <section><h3>适用条件与执行规则</h3><RuleBranches rules={claim.rules}/></section>
    {claim.consistency?.consistent!==undefined&&claim.consistency.consistent!==true&&<p className="evolution-warning">文字与规则一致性：{claim.consistency.consistent===false?'需要复核':'尚未确认'}{claim.consistency.issue?` · ${claim.consistency.issue}`:''}</p>}
    <section><h3>验证过的题目</h3>
      <p className="evolution-note">{data.evidence_truncated?`展示最近 ${data.evidence.length} 条，共 ${data.evidence_total} 条证据。`:`共 ${data.evidence_total} 条证据。`}</p>
      {data.evidence.length?data.evidence.map((row,index)=><details className="evolution-evidence-row" key={`${row.question_id}-${row.round}-${index}`}>
        <summary><span>{row.question_id}</span><span>第 {row.round} 轮 · {({support:'支持',refute:'推翻'} as Record<string,string>)[row.outcome]??row.outcome}</span></summary>
        <button className="loop-open-question" aria-label={`阅读完整题目 ${row.question_id}`} onClick={()=>onQuestion(row.question_id)}>阅读完整题目 <ArrowUpRight size={14}/></button>
        <EvidenceComparisons row={row}/>
      </details>):<p>登记后的适用题证据尚未积累。</p>}
    </section>
    <details className="evolution-source"><summary>登记与修订记录</summary><p>第 {claim.registered_round} 轮登记 · 修订 {claim.revisions} 次</p><JsonView value={{id:claim.id,version:claim.version,parent:claim.parent,history:data.history}}/></details>
  </div>;
}

function RoundReader({data}:{data:EvolutionRoundDetail}){
  return <div className="evolution-round-reader">
    <p>{data.completed?'本轮已归档。':'本轮尚未归档，以下仅展示已保存的产物。'}</p>
    <dl className="evolution-evidence-numbers"><div><dt>有效新题 / 计划</dt><dd>{count(data.build?.ok)} / {count(data.plan?.total)}</dd></div><div><dt>新命题</dt><dd>{count(data.proposals?.new_count)}</dd></div><div><dt>修订通过</dt><dd>{count(data.proposals?.revision_count)}</dd></div></dl>
    <section><h3>证据判定</h3>{data.judge_events?.length?data.judge_events.map((event,index)=><p key={index}>{event.claim_id} · {claimStateLabels[event.from]??event.from} → {claimStateLabels[event.to]??event.to}{event.needs_revision?' · 需要修订':''}<small className="evolution-block-note">支持 {event.support} / {event.applicable} · 下界 {percent(event.lower_bound)}</small></p>):<p className="evolution-note">{data.completed_stages.includes('judge')?'本轮没有状态变更。':'等待已保存的判定结果。'}</p>}</section>
    <section><h3>新登记的知识</h3>{data.registered?.length?data.registered.map((claim,index)=><p key={`${claim.id}-${index}`}><small className="evolution-block-note">{claim.id}</small>{claim.text}</p>):<p className="evolution-note">{data.completed_stages.includes('register')?'本轮没有新登记的命题。':'等待完成检查与登记。'}</p>}</section>
    {data.proposals&&<details className="evolution-source"><summary>规则检查与模型调用记录</summary><JsonView value={{rejections:data.proposals.rejections,qwen:data.proposals.qwen}}/></details>}
    <details className="evolution-source"><summary>预注册与封存凭据</summary>{data.registration?<><p>登记 {data.registration.count} 条 · {data.registration.hash_matches===true?'封存摘要一致':data.registration.hash_matches===false?'封存摘要不一致，需检查来源':'尚未取得摘要核验结果'}</p>{data.registration.hash&&<code className="evolution-hash">{data.registration.hash}</code>}</>:<p>预注册记录尚未保存。</p>}</details>
    <details className="evolution-source"><summary>来源轮次报告</summary>{data.report?<JsonView value={data.report}/>:<p>本轮报告尚未保存。</p>}</details>
  </div>;
}

function StageReader({stage,snapshot,detail,onClose}:{stage:EvolutionStage;snapshot:EvolutionSnapshot;detail?:EvolutionRoundDetail;onClose:()=>void}){
  const round=snapshot.round,done=round?.completed_stages?.includes(stage);
  return <div className="evolution-stage-reader"><header><small>第 {round?.index??'—'} 轮 · {done?'已保存阶段结果':'等待阶段完成'}</small><button aria-label="关闭节点详情" onClick={onClose}>×</button></header><h3>{evolutionLabels[stage]}</h3><p>{evolutionDescriptions[stage]}</p>
    {stage==='plan'&&<><p>定向题 {count(round?.plan?.target)} 道 · 探索题 {count(round?.plan?.explore)} 道</p><p className="evolution-note">定向检查现有命题的适用范围，同时探索尚未覆盖的问题。</p></>}
    {stage==='build'&&<><p>完成 {count(round?.build?.completed)} / {count(round?.plan?.total)} 组</p><p>有效新题 {count(round?.build?.ok)} 道 · 未生成有效题 {count(round?.build?.failed)} 组</p><p className="evolution-note">题目由正式生成管线产生，判定来自真实训练的存储结果。</p></>}
    {stage==='score'&&<><p>当前轮已保存评分：{count(detail?.score?.questions)} 道题，{count(detail?.score?.verdicts)} 条判定。</p><p className="evolution-note">每条命题在一道题上只记一票；参与计分的比较中出现错误，即记为反例。已收录命题也持续接受新题复验。</p><p className="evolution-note">来源会跳过内部冲突的比较；仅有冲突、没有有效预测的题不计入适用题。这里沿用来源判定。</p></>}
    {stage==='judge'&&<><p>积累足够的登记后证据，再根据支持率和统计下界判断。</p><p className="evolution-note">证据不足时继续积累；存疑或失败的命题进入修订。</p><details><summary>本次研究的判定阈值</summary><JsonView value={snapshot.thresholds??{}}/></details></>}
    {stage==='propose'&&<><p>模型基于历史证据提出新命题或修订；程序检查公开字段、覆盖、重复与回归。</p><p className="evolution-note">规则检查属于这个阶段。这里只显示已保存的结果。</p>{detail?.proposals?<p>通过检查：新命题 {detail.proposals.new_count} 条 · 修订 {detail.proposals.revision_count} 条</p>:<p className="evolution-note">等待保存提案与检查记录。</p>}</>}
    {stage==='register'&&<><p>通过检查后登记并计算封存摘要；从下一轮的新题开始验证。</p>{detail?.registration?<p>登记 {detail.registration.count} 条 · {detail.registration.hash_matches===true?'摘要核验一致':detail.registration.hash_matches===false?'摘要不一致':'等待摘要核验'}</p>:<p className="evolution-note">尚无本轮预注册记录。</p>}</>}
    {stage==='report'&&<><p>保留本轮生成、验证、修订和登记结果，然后进入下一轮。</p><p className="evolution-note">{detail?.report?'报告已保存，可在轮次记录中阅读。':'等待本轮报告。'}</p></>}
  </div>;
}

export function KnowledgeEvolution({onTask}:{onTask?:(seed:TaskSeed)=>void}={}){
  const {snapshot,connection}=useKnowledgeEvolution();
  const [tab,setTab]=useState('知识进展'),[stage,setStage]=useState<EvolutionStage>(),[filter,setFilter]=useState('all');
  const [claimId,setClaimId]=useState<string>(),[roundIndex,setRoundIndex]=useState<number>();
  const [question,setQuestion]=useState<{id:string;context?:EvolutionTaskContext}>();
  const questionId=question?.id;
  const [generationView,setGenerationView]=useState(initialGenerationView);
  useEffect(()=>setGenerationView(initialGenerationView()),[snapshot?.round?.index]);
  const sequence=snapshot?.sequence??0;
  const connected=connection==='connected'&&snapshot?.sync.status==='connected';
  const claimDetail=useDetail<EvolutionClaimDetail>(claimId?`/kb-loop/claims/${encodeURIComponent(claimId)}`:undefined,sequence,connected);
  const selectedRound=roundIndex??(stage?snapshot?.round?.index:undefined);
  const roundDetail=useDetail<EvolutionRoundDetail>(selectedRound!==undefined?`/kb-loop/rounds/${selectedRound}`:undefined,sequence,connected);
  const stale=connection==='disconnected'||['disconnected','stale'].includes(snapshot?.sync.status??'');
  const graph=evolutionPresentation(snapshot,connected),round=snapshot?.round,execution=snapshot?.execution;
  const claims=(snapshot?.claims??[]).filter(claim=>filter==='all'||claim.status===filter);
  const status=stale?'同步中断 · 显示上次记录':!snapshot?.configured?'尚未连接研究':connected?'同步正常':'正在连接研究';
  const stageName=round?.next_stage&&evolutionLabels[round.next_stage as EvolutionStage];
  const activity=execution?.alert?'来源报告异常':!connected?'等待同步确认':execution?.status==='running'
    ?`${stageName??'轮次切换'}${execution.stop_requested?' · 已请求轮末停止':''}`
    :execution?.status==='stopped'?'进程已停止':'进程状态待确认';
  return <section className="knowledge-evolution" aria-label="知识演化实时观察">
    <header className="evolution-header"><div><span className="eyebrow">HARNESS · 持续研究</span><h1>知识演化</h1><p>生成证据，让知识持续接受检验。</p></div><div className={`evolution-connection${stale?' is-stale':''}`} role="status"><span><i/>{status}</span>{snapshot?.sync.last_success_at&&<small>最近同步 {formatTimestamp(snapshot.sync.last_success_at)}</small>}</div></header>
    {!snapshot?connection==='disconnected'?<Empty title="暂时无法连接研究记录">连接恢复后会继续读取，页面不会启动或改变实验。</Empty>:<Loading/>:!snapshot.configured?<Empty title="连接正在进行的研究">配置研究记录来源后，这里会展示真实出题进度、命题证据和轮次变化。原有工作流仍可在“编辑工作流”中使用。</Empty>:<>
      {round?<div className="evolution-current"><div className="evolution-round-heading"><strong>第 {round.index} 轮</strong><span>{activity}</span></div><div className="evolution-build"><div><span>本轮出题</span><strong>{count(round.build?.completed)} <small>/ {count(round.plan?.total)}</small></strong></div>{round.plan?.total? <progress aria-label="本轮出题进度" value={round.build?.completed??0} max={round.plan.total}/>:null}<small>{count(round.build?.ok)} 道有效题 · {count(round.build?.failed)} 组未生成有效题</small></div></div>:<p className="evolution-note">等待来源保存首轮研究记录。</p>}
      {snapshot.kb&&<div className="evolution-kb-counts" aria-label="来源知识状态">{(['candidate','verified','flagged','retired'] as const).map(state=><span key={state} className={`is-${state}`}><i/>{claimStateLabels[state]} <b>{count(snapshot.kb?.[state])}</b></span>)}</div>}
      <ResearchPathCanvas nodes={graph.nodes} edges={graph.edges} selectedId={stage??''} onSelect={id=>setStage(id as EvolutionStage)} ariaLabel="知识演化研究路径" inspectorPresentation="overlay"
        inspector={stage&&stage!=='build'&&<StageReader stage={stage} snapshot={snapshot} detail={roundIndex===undefined||roundIndex===round?.index?roundDetail.data:undefined} onClose={()=>setStage(undefined)}/>}
        toolbar={<div className="evolution-canvas-heading"><span>研究路径</span><small>节点状态来自已保存的阶段记录</small></div>}
        interactionHint="拖动画布 · 点击查看证据"
        footer={<p className="evolution-note">命题登记后用新题检验，已收录知识持续复验。来源验证状态与人工审核分别保留。</p>}/>
      <section className="evolution-library" aria-label="知识与轮次记录"><div className="evolution-library-heading"><Tabs tabs={['知识进展','轮次记录']} value={tab} onChange={setTab}/>{tab==='知识进展'&&<select aria-label="筛选命题状态" value={filter} onChange={event=>setFilter(event.target.value)}><option value="all">全部知识 · {snapshot.kb?.claims??snapshot.claims?.length??0}</option>{Object.entries(claimStateLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select>}</div>
        {tab==='知识进展'?claims.length?<div className="evolution-claims">{claims.map(claim=><button className="evolution-claim-row" aria-label={`阅读命题 ${claim.id}`} key={claim.id} onClick={()=>setClaimId(claim.id)}><div><span className="evolution-claim-id">{claim.id}</span><span className={`evolution-claim-status is-${claim.status}`}>{claimStateLabels[claim.status]??claim.status}</span>{claim.needs_revision&&<small>待修订</small>}</div><p>{claim.text}</p><span className="evolution-claim-meta">支持 {count(claim.evidence?.support)} / {count(claim.evidence?.applicable)} 道适用题 <span>统计下界 {percent(claim.stats?.lower_bound)}</span><ArrowUpRight size={16}/></span></button>)}</div>:<Empty title="尚无这一状态的命题">新的证据与登记结果会自动显示。</Empty>:snapshot.rounds?.length?<div className="evolution-rounds">{[...snapshot.rounds].sort((a,b)=>b.index-a.index).map(item=><button key={item.index} onClick={()=>setRoundIndex(item.index)} aria-label={`阅读第 ${item.index} 轮`}><strong>第 {item.index} 轮</strong><span>{item.completed?'已归档':'未归档'}<small>{count(item.build?.ok)} / {count(item.plan?.total)} 道有效题</small></span><ChevronRight size={17}/></button>)}</div>:<Empty title="还没有轮次记录">完成的阶段与报告会在这里保存。</Empty>}
      </section>
    </>}
    {!questionId&&claimId&&<Drawer title="知识与证据" subtitle={claimId} onClose={()=>setClaimId(undefined)}><ErrorBox error={claimDetail.error}/>{claimDetail.data?<ClaimReader key={claimId} data={claimDetail.data} onTask={onTask} onQuestion={id=>setQuestion({id,context:claimDetail.data?.observation?{observation:{...claimDetail.data.observation},claim_ref:{id:claimDetail.data.claim.id,version:claimDetail.data.claim.version}}:undefined})}/>:!claimDetail.error&&<Loading/>}</Drawer>}
    {!questionId&&roundIndex!==undefined&&<Drawer title={`第 ${roundIndex} 轮研究`} onClose={()=>setRoundIndex(undefined)}><ErrorBox error={roundDetail.error}/>{roundDetail.data?<RoundReader data={roundDetail.data}/>:!roundDetail.error&&<Loading/>}</Drawer>}
    {!questionId&&!claimId&&roundIndex===undefined&&stage==='build'&&<Drawer title="本轮新题" subtitle={`第 ${round?.index??'—'} 轮 · 生成记录`} onClose={()=>setStage(undefined)}><LoopGenerationPanel data={roundDetail.data?.generation} error={roundDetail.error} connected={connected} onQuestion={id=>setQuestion({id,context:roundDetail.data?.observation?{observation:{...roundDetail.data.observation}}:undefined})} view={generationView} onView={setGenerationView}/></Drawer>}
    {questionId&&<div className="evolution-question-reader"><Drawer title="完整题目" subtitle={questionId} onClose={()=>setQuestion(undefined)}><LoopQuestionPanel key={questionId} id={questionId} backLabel={claimId?'返回知识与证据':'返回生成记录'} taskContext={question?.context} onTask={onTask} onQuestion={(id,context)=>setQuestion({id,context})} onBack={()=>setQuestion(undefined)}/></Drawer></div>}
  </section>;
}
