import {Card,JsonView} from './ui';
import {LiveOutput,RunStreamProvider,useLiveOutput} from './LiveOutput';
import {RagKnowledge} from './Rag';
import {QuestionReader} from './QuestionReader';
import type {Run} from './types';
import type {RagHit} from './ragTypes';
export function RagRunView({run}:{run:Run}){
 return <RunStreamProvider run={run}><Content run={run}/></RunStreamProvider>;
}
function Content({run}:{run:Run}){
 const live=useLiveOutput(run);const config=run.config;const model=config.models?.[0];
 const result=run.result;const answer=result?.answer;const terminal=['complete','failed','uncertain','cancelled'].includes(run.status);
 const hits:RagHit[]=config.retrieval?.provenance||[];
 const used:RagHit[]=result?.used_sources||[];
 return <div className="rag-page">
  <Card title="RAG 作答记录">{config.question&&<QuestionReader record={{public:config.question}} showApplicableKnowledge={false}/>}<p>自动匹配：{config.retrieval?.selected_kb?.name||'未记录'} · 版本 {config.retrieval?.selected_kb?.version}</p><p>模型：{model?.name||model?.id} · {model?.service_identity?.weights_verified===true?'权重身份已核验':'模型配置身份；未验证权重'}</p>{result?.response_model&&<small>服务返回模型：{result.response_model}</small>}</Card>
  <Card title={answer?'已提交回答':'模型作答'}><LiveOutput live={live} nodeId="solver" round={0} operationKey={`rag:${config.question_key}:${model?.id}`} terminal={terminal}/>
   {answer?<><p className="rag-answer">{answer.ranking.join(' → ')}</p><p className="rag-answer">{typeof answer.rationale==='string'?answer.rationale:JSON.stringify(answer.rationale)}</p></>:<p>{terminal?'没有通过校验并提交的回答。':'等待模型返回并校验完整回答。'}</p>}
  </Card>
  <Card title="模型实际引用">{answer?<><div className="rag-citations">{used.map((hit,i)=><a key={hit.citation_id} href={'#'+hit.citation_id}>引用知识 {i+1}</a>)}</div>{!used.length&&<p>模型没有引用已提供的知识。</p>}{!!result.unknown_citations?.length&&<p role="alert">未知引用：{result.unknown_citations.join('、')}。无法映射到提供过的知识来源。</p>}{answer.invalid_citations&&!result.unknown_citations?.length&&<p role="alert">模型引用格式异常。</p>}</>:<p>完整回答提交后显示实际引用。</p>}</Card>
  <Card title="提供给模型的知识"><RagKnowledge hits={hits}/></Card>
  {run.records?.length?<Card title="持久化调用收据">{run.records.map((record,i)=><details key={i}><summary>调用 {i+1} · {record.status}</summary><JsonView value={{status:record.status,actual_request:record.actual_request,raw:record.raw,usage:record.usage,error:record.error}}/></details>)}{run.status==='uncertain'&&<p>调用结果不确定，保留已收到的文本与收据；不会自动重试。</p>}</Card>:null}
 </div>;
}
