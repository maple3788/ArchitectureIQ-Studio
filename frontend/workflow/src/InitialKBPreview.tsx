import type {Json} from './types';
import {readableName} from './displayNames';

/** Counts come from the preview's real first request, never the catalog total. */
export function InitialKBPreview({preview}: {preview?:Json}) {
 const selected=preview?.initial_kb;
 if(!selected)return <p>从空经验开始；后续轮次按开关读取本次学习的经验。</p>;
 const first=preview?.requests?.[0];
 const experience=selected.kind==='experience';
 const contents=experience?first?.initial_experience?.lessons:first?.knowledge;
 const omitted=first?.initial_experience?.omitted?.lessons??0;
 const excluded=first?.initial_experience?.excluded?.lessons_with_excluded_sources??0;
 return <><p>{readableName(selected.name,experience?'学习经验':'已验证知识')}</p>
  {Array.isArray(contents)?<>
   <p>{experience?`本题实际带入 ${contents.length} 条起始经验 · 待验证`:`本题匹配 ${contents.length} 条已验证知识`}</p>
   {omitted>0&&<p>{omitted} 条因输入长度限制省略。</p>}
   {excluded>0&&<p>{excluded} 条未通过本题检索条件。</p>}
   {first?.initial_experience?.prior_related_feedback===true&&<p className="muted">起始经验含本题或相关题目的反馈来源，本次属于学习复盘。</p>}
   {contents.length===0&&<p className="muted">所选 KB 没有内容进入本题的首轮请求。可返回作答节点更换 KB。</p>}
  </>:<p>实际带入数量尚未返回，请重新预览。</p>}
  <p className="muted">所选版本固定用于本次运行。后续轮次的新增经验由作答节点的开关控制。</p>
 </>;
}
