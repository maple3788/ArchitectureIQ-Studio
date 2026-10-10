import {JsonView} from './ui';
import type {Json} from './types';
import './knowledge-snapshot.css';

export function ExperienceSnapshot({snapshot}: {snapshot:Json}) {
 const lessons:Json[] = snapshot.lessons ?? [], episodes:Json[] = snapshot.episodes ?? [];
 return <div className="knowledge-reader"><p className="knowledge-note">来自已保存的作答与反馈，可帮助下一轮练习；它们仍是待验证的经验。</p>
  {lessons.length ? lessons.map((lesson,index)=><article className="knowledge-claim" key={lesson.id ?? index}><header><strong title={lesson.id}>经验 {index+1}</strong><span>{lesson.status === 'retired' ? '已停用' : '待验证'} · 修订 {lesson.revision ?? "未登记"}</span></header><p className="knowledge-statement">{lesson.text || '未提供经验正文'}</p><dl><dt>适用条件</dt><dd>{lesson.conditions?.join('；') || '尚未说明'}</dd><dt>例外</dt><dd>{lesson.exceptions?.join('；') || '尚未说明'}</dd></dl><small>关联 {lesson.source_episode_ids?.length ?? 0} 次作答</small><details><summary>来源与完整经验记录</summary><JsonView value={{lesson,episodes:episodes.filter(e=>lesson.source_episode_ids?.includes(e.id))}}/></details></article>):<p>此版本保存了作答记录，尚未形成经验条目。</p>}
  <details><summary>版本与完整经验快照</summary><JsonView value={snapshot}/></details></div>;
}
