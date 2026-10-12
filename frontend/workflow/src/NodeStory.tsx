import { useState, type ReactNode } from "react";
import type { Run } from "./types";
import { parseSentContent, parseOutput } from "./runWorkflow";
import "./node-story.css";
import { LearningNote } from "./LearningTrace";
import { QuestionReader } from "./QuestionReader";
export type NodeStoryProps = {
  nodeId: string;
  direction: "input" | "output";
  value: any;
  run?: Run;
  questionKey?: string;
  roundIndex?: number;
  showIntro?: boolean;
};
const families: Record<string, string> = {
  bigram_lm: "二元序列建模",
  univariate_regression: "一元回归",
  multivariate_regression: "多元回归",
  spiral_classification: "螺旋分类",
  xor_classification: "异或分类",
  synthetic_tabular_classification: "合成表格分类",
};
const purposes: Record<string, [string, string]> = {
  input: ["选择本轮题目", "公开题目交给 Solver 作答。"],
  solver: [
    "独立比较候选方案",
    "返回的排序交给答案保存步骤；模型理由不等同于实验事实。",
  ],
  commit: ["锁定本轮回答", "已保存的回答供反馈揭示步骤进行对照。"],
  reveal: ["揭示真实训练结果", "已揭示的答案和实验结果供发现者提出假说。"],
  discoverer: ["提出可检验的假说", "假说及竞争解释交给怀疑者审查。"],
  skeptic: ["审查假说与反例", "被接受的实验方案供探索实验步骤执行。"],
  experiment: ["执行探索实验", "真实实验记录交给分析与知识整理步骤。"],
  confirmation: [
    "独立确认假说",
    "独立实验记录作为证据；是否通过科学门槛由后续验证判断。",
  ],
  analyst: ["解释实验结论", "证据摘要、局限和后续问题交给知识整理者。"],
  curator: [
    "决定如何使用知识",
    "知识处理建议交给发布步骤验证；建议本身不会直接发布。",
  ],
  publish: ["验证证据并发布知识", "封存知识版本供下一轮或独立评测使用。"],
  loop: ["汇总本轮并控制循环", "下一步按冻结工作流路由继续研究或结束。"],
  evaluate: [
    "独立评测知识效果",
    "对照条件得分供任务结果查看；正确率不等同于科学证据验证。",
  ],
  end: ["汇总任务产物", "保留任务结果、知识版本和调用记录供审阅。"],
};
const object = (v: any): Record<string, any> =>
  v && typeof v === "object" && !Array.isArray(v) ? v : {};
const list = (v: any): any[] => (Array.isArray(v) ? v : []);
const present = (v: any) => v !== undefined && v !== null;
const number = (v: any) => typeof v === "number" && Number.isFinite(v);
const nonnegative = (v: any) => number(v) && v >= 0;
function display(v: any) {
  if (!number(v)) return typeof v === "string" ? v : "未提供";
  if (Number.isInteger(v)) return String(v);
  if (Math.abs(v) < 0.0001 || Math.abs(v) >= 1000000) return v.toExponential(2);
  return Number(v.toFixed(4)).toString();
}
function familyName(v: any) {
  return typeof v === "string"
    ? Object.hasOwn(families, v)
      ? families[v]
      : v
    : "数据集族未提供";
}
function Notice({ children }: { children: ReactNode }) {
  return <p className="ns-notice">{children}</p>;
}
function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="ns-block">
      <h5>{title}</h5>
      {children}
    </section>
  );
}
function Prose({
  value,
  missing = "未提供",
}: {
  value: any;
  missing?: string;
}) {
  return (
    <p className="ns-prose">
      {typeof value === "string" && value.length ? value : missing}
    </p>
  );
}
function TextList({
  title,
  value,
  missing = "未提供",
}: {
  title: string;
  value: any;
  missing?: string;
}) {
  const rows = list(value).filter((v) => typeof v === "string");
  return (
    <Block title={title}>
      {rows.length ? (
        <ul className="ns-text-list">
          {rows.map((row, i) => (
            <li key={i}>{row}</li>
          ))}
        </ul>
      ) : (
        <Notice>{missing}</Notice>
      )}
    </Block>
  );
}
function Cards({
  items,
  renderItem,
}: {
  items: any[];
  renderItem: (item: any, index: number) => ReactNode;
}) {
  const [all, setAll] = useState(false);
  return (
    <>
      {items.slice(0, all ? items.length : 6).map((item, i) => (
        <div key={i}>{renderItem(item, i)}</div>
      ))}
      {items.length > 6 && (
        <button
          className="ns-more"
          type="button"
          onClick={() => setAll((v) => !v)}
        >
          {all ? "收起列表" : `查看全部 ${items.length} 条`}
        </button>
      )}
    </>
  );
}
function QuestionCard({
  question,
  index = 0,
}: {
  question: any;
  index?: number;
}) {
  const q = object(question),
    choices = list(q.choices);
  return (
    <article className="ns-question">
      <div className="ns-question-heading">
        <strong>{familyName(q.family)}</strong>
        <span>题目 {index + 1}</span>
      </div>
      <p>
        {choices.length ? `${choices.length} 个候选方案` : "候选方案未提供"}
      </p>
      {choices.length > 0 && (
        <div className="ns-choice-list">
          {choices.map((choice, i) => (
            <span key={i}>
              <b>
                {typeof choice.letter === "string"
                  ? choice.letter
                  : "选项未提供"}
              </b>
              {typeof choice.view?.model_type === "string"
                ? choice.view.model_type
                : typeof choice.model?.type === "string"
                  ? choice.model.type
                  : "候选配置见题面"}
            </span>
          ))}
        </div>
      )}
      {typeof q.prompt === "string" && q.prompt ? (
        <details className="ns-disclosure">
          <summary>查看题目详情</summary>
          <QuestionReader record={{ public: q }} />
        </details>
      ) : (
        <Notice>完整公开题面未提供</Notice>
      )}
    </article>
  );
}
function publicQuestions(run?: Run, round?: number) {
  const found: any[] = [];
  for (const obs of list(run?.node_observations)) {
    if (
      obs.availability === "unavailable" ||
      (round !== undefined && obs.round_index !== round)
    )
      continue;
    if (obs.node_id === "input") found.push(...list(obs.output));
    if (typeof obs.input?.prompt === "string") {
      const data = parseSentContent(obs.input.prompt).data;
      if (data?.question) found.push(data.question);
      for (const p of list(data?.episodes ?? data?.packet))
        if (p.question) found.push(p.question);
    }
  }
  for (const record of list(run?.records)) {
    const payload =
      record.actual_request?.payload ?? record.transport?.request?.payload;
    for (const message of list(payload?.messages)) {
      const data = parseSentContent(message.content).data;
      if (data?.question) found.push(data.question);
      for (const p of list(data?.episodes ?? data?.packet))
        if (p.question) found.push(p.question);
    }
  }
  return found.filter(
    (q) => typeof q?.id === "string" && Array.isArray(q.choices),
  );
}
function publicQuestion(id: string, run?: Run, round?: number) {
  const questions = publicQuestions(run, round).filter((q) => q.id === id);
  if (!questions.length) return undefined;
  const signature = (q: any) =>
    JSON.stringify(
      q.choices.map((c: any) => [
        c.id ?? c.candidate_id ?? c.candidateId,
        c.letter,
      ]),
    );
  return questions.every((q) => signature(q) === signature(questions[0]))
    ? questions[0]
    : undefined;
}
function committedAnswer(id: string, run?: Run, round?: number) {
  if (round === undefined) return undefined;
  const rows = list(run?.node_observations).filter(
    (o) =>
      o.node_id === "commit" &&
      o.round_index === round &&
      o.key === id &&
      o.availability !== "unavailable" &&
      o.output !== undefined,
  );
  return rows.length === 1 ? rows[0].output : undefined;
}
function Ranking({ value }: { value: any }) {
  const ranking = list(value).filter((v) => typeof v === "string");
  return ranking.length ? (
    <div className="ns-ranking" aria-label="排序由最好到最差">
      {ranking.map((letter, i) => (
        <span key={i}>
          {i > 0 && <em>→</em>}
          <strong>{letter}</strong>
        </span>
      ))}
    </div>
  ) : (
    <Notice>有效排序未提供</Notice>
  );
}
function AnswerStory({
  value,
  locked = false,
}: {
  value: any;
  locked?: boolean;
}) {
  const answer = object(value);
  return (
    <>
      <Block title={locked ? "已保存的答案" : "模型返回的排序"}>
        <Ranking value={answer.ranking} />
        {locked && typeof answer.valid === "boolean" && (
          <p className={answer.valid ? "ns-positive" : "ns-warning"}>
            {answer.valid ? "答案格式校验通过" : "答案格式校验未通过"} ·
            格式校验不代表回答正确。
          </p>
        )}
        {number(answer.knowledge_count) && (
          <p className="ns-caption">正式知识 {number(answer.formal_knowledge_count) ? answer.formal_knowledge_count : answer.knowledge_count} 条</p>
        )}
        {number(answer.experience_count) && <p className="ns-caption">带入经验 {answer.experience_count} 条</p>}
        {typeof answer.invalid_citations === "boolean" && (
          <p className="ns-caption">
            {answer.invalid_citations
              ? "存在无效知识引用"
              : "未记录到无效知识引用"}
          </p>
        )}
      </Block>
      <Block title="判断理由">
        <Prose value={answer.rationale} missing="该回答未提供解释" />
      </Block>
      {list(answer.citations).length > 0 && (
        <TextList title="引用的知识条目" value={answer.citations} />
      )}{" "}
      {answer._invalid && (
        <Notice>回答解析未通过；请查看高级记录中的原始返回。</Notice>
      )}
    </>
  );
}
function Knowledge({ value }: { value: any }) {
  const notes = list(value);
  return (
    <Block title="本次提供的正式知识">
      {notes.length ? (
        <>
          <p className="ns-caption">
            {notes.length} 条知识记录 · 知识仍需结合题目判断。
          </p>
          <Cards
            items={notes}
            renderItem={(claim) => (
              <article className="ns-small-card">
                <Prose value={claim.text} missing="知识正文未提供" />
                {typeof claim.enabled === "boolean" && (
                  <span className="ns-caption">
                    {claim.enabled ? "已启用" : "未启用"}
                  </span>
                )}
              </article>
            )}
          />
        </>
      ) : (
        <Notice>本次未提供正式知识条目</Notice>
      )}
    </Block>
  );
}
function experienceSources(run?: Run, beforeRound?: number) {
  const sources: Record<string, any> = {};
  for (const obs of list(run?.node_observations)) {
    if (obs.availability === "unavailable" ||
        (beforeRound !== undefined && obs.round_index >= beforeRound)) continue;
    if (obs.node_id === "experience_save") {
      for (const episode of list(obs.output?.episodes)) sources[episode.id] = episode;
    }
    if (obs.node_id === "loop") {
      for (const [id, source] of Object.entries(object(obs.output?.experience?.episode_provenance))) {
        if (!sources[id]) sources[id] = source;
      }
    }
  }
  return sources;
}
function LessonCard({ lesson, index, sources = {}, questionId, initial = false }: {
  lesson: any; index: number; sources?: Record<string, any>; questionId?: string; initial?: boolean;
}) {
  const ids = list(lesson.source_episode_ids).filter((id) => typeof id === "string");
  const sourceLabels = ids.map((id) => {
    const source = sources[id];
    if (!number(source?.round)) return undefined;
    const sameQuestion = questionId && (source.question?.id ?? source.question_id) === questionId;
    return `${initial ? "起始 KB · " : ""}第 ${source.round} 轮${sameQuestion ? " · 本题练习" : source.question?.family ? ` · ${familyName(source.question.family)}` : ""}`;
  });
  const labels = [...new Set(sourceLabels.filter((label): label is string => Boolean(label)))];
  const unknown = sourceLabels.filter((label) => !label).length;
  return <article className="ns-small-card">
    <strong>经验 {index + 1}{lesson.revision ? ` · 修订 ${lesson.revision}` : ""}</strong>
    {(lesson.status === "retired" || lesson.op === "retire") && <p className="ns-caption">已停用</p>}
    <Prose value={lesson.text} missing="未提供经验正文" />
    <TextList title="适用条件" value={lesson.conditions} missing="未记录适用条件" />
    <TextList title="例外与限制" value={lesson.exceptions} missing="未记录例外与限制" />
    {lesson.reason && <details className="ns-disclosure"><summary>为何形成这条经验</summary><Prose value={lesson.reason} /></details>}
    <Block title="经验来源">
      {labels.map((label) => <p className="ns-caption" key={label}>{label}</p>)}
      {unknown > 0 && <p className="ns-caption">{unknown} 条来源记录 · 轮次信息未提供</p>}
      {!ids.length && <p className="ns-caption">来源信息未提供</p>}
    </Block>
    {(lesson.id || ids.length > 0) && <details className="ns-disclosure"><summary>技术标识</summary>
      {lesson.id && <p className="ns-prose">经验编号：{lesson.id}</p>}
      {ids.length > 0 && <p className="ns-prose">来源编号：{ids.join("、")}</p>}
    </details>}
  </article>;
}
function RetrievedExperience({ value, run, roundIndex, questionId, initial = false }: {
  value: any; run?: Run; roundIndex?: number; questionId?: string; initial?: boolean;
}) {
  const memory = object(value), lessons = list(memory.lessons), examples = list(memory.examples);
  const sources:Record<string,any> = initial ? Object.fromEntries(list(run?.config.initial_kb?.snapshot?.episodes).map(episode=>[episode.id,episode])) : { ...experienceSources(run, roundIndex) };
  for (const episode of examples) sources[episode.id] = episode;
  const omitted = object(memory.omitted), excluded = object(memory.excluded);
  const skippedExamples = (nonnegative(excluded.ineligible_examples) ? excluded.ineligible_examples : 0)
    + (nonnegative(excluded.related_or_other_family_examples) ? excluded.related_or_other_family_examples : 0);
  const skippedLessons = nonnegative(excluded.lessons_with_excluded_sources) ? excluded.lessons_with_excluded_sources : 0;
  const omissions = [omitted.examples > 0 && `${omitted.examples} 个历史案例`, omitted.lessons > 0 && `${omitted.lessons} 条经验规律`].filter(Boolean);
  return <Block title={initial ? "来自起始 KB 的经验" : "本次带入的经验"}>
    {lessons.length + examples.length > 0 ? <>
      <p className="ns-positive">已带入 {lessons.length} 条经验规律 · {examples.length} 个历史案例</p>
      <p className="ns-caption">来自先前作答与反馈，尚未通过独立验证。{memory.practice === "same_question_practice" && "本轮为同题练习。"}</p>
      {initial&&memory.prior_related_feedback===true&&<p className="ns-caption">起始经验包含本题或相关题目的反馈来源，本次属于学习复盘。</p>}
      <Cards items={lessons} renderItem={(lesson, index) => <LessonCard lesson={lesson} index={index} sources={sources} questionId={questionId} initial={initial} />} />
      <Cards items={examples} renderItem={(episode, index) => <article className="ns-small-card">
        <strong>历史案例 {index + 1}{number(episode.round) ? ` · 第 ${episode.round} 轮` : ""}</strong>
        {episode.question && <QuestionCard question={episode.question} />}
        <Block title="当时的回答"><Ranking value={episode.answer?.ranking} /><Prose value={episode.answer?.rationale} /></Block>
        {typeof episode.feedback?.correct_letter === "string" && <p>当时的正确选项：{episode.feedback.correct_letter}</p>}
      </article>} />
    </> : <Notice>本次实际请求没有包含经验条目。</Notice>}
    {omissions.length > 0 && <p className="ns-caption">为控制输入长度，未带入 {omissions.join("、")}；完整记录仍保存在运行产物中。</p>}
    {skippedExamples + skippedLessons > 0 && <p className="ns-caption">有 {skippedExamples} 个案例与 {skippedLessons} 条经验规律未通过本次检索条件。</p>}
    {typeof memory.version === "string" && <details className="ns-disclosure"><summary>经验版本标识</summary><p className="ns-prose">{memory.version}</p></details>}
  </Block>;
}
type MetricRow = {
  label: string;
  candidateId?: string;
  letter?: string;
  metric?: string;
  mean?: number;
  std?: number;
  seeds?: number;
  conflict?: boolean;
  mappingConflict?: boolean;
  rejectedLetters?: string[];
};
function metricRows(feedback: any, question: any): MetricRow[] {
  const metrics = object(feedback.candidate_metrics),
    ranked = list(feedback.reveal?.ranked);
  const letters = new Map<string, string>(),
    conflicted = new Set<string>(),
    seenLetters = new Map<string, Set<string>>();
  const bind = (id: string, letter: string) => {
    const seen = seenLetters.get(id) ?? new Set<string>();
    seen.add(letter);
    seenLetters.set(id, seen);
    if (conflicted.has(id)) return;
    if (letters.has(id) && letters.get(id) !== letter) {
      conflicted.add(id);
      letters.delete(id);
    } else letters.set(id, letter);
  };
  for (const choice of list(question?.choices)) {
    const id = choice.id ?? choice.candidate_id ?? choice.candidateId;
    if (typeof id === "string" && typeof choice.letter === "string")
      bind(id, choice.letter);
  }
  for (const [id, summary] of Object.entries(metrics))
    if (typeof summary?.letter === "string") bind(id, summary.letter);
  for (const row of ranked)
    if (typeof row.candidateId === "string" && typeof row.letter === "string")
      bind(row.candidateId, row.letter);
  for (const [id, letter] of [...letters])
    if ([...letters].some(([other, l]) => other !== id && l === letter)) {
      conflicted.add(id);
      letters.delete(id);
    }
  const ids = [
    ...new Set([
      ...ranked
        .map((row) => row.candidateId)
        .filter((v) => typeof v === "string"),
      ...Object.keys(metrics),
    ]),
  ];
  return ids.map((id) => {
    const saved = object(metrics[id]),
      ranking = ranked.find((row) => row.candidateId === id) ?? {};
    const declared = [
      saved.selection_metric,
      saved.metric,
      ranking.metric,
    ].filter((v) => typeof v === "string" && v);
    const conflict = declared.some((v) => v !== declared[0]),
      metric = conflict ? undefined : declared[0];
    const mean = metric
        ? (saved[`mean_${metric}`] ?? saved.mean ?? ranking.mean)
        : undefined,
      std = metric
        ? (saved[`std_${metric}`] ?? saved.std ?? ranking.std)
        : undefined;
    const letter = letters.get(id);
    return {
      candidateId: id,
      letter,
      label: letter ?? `候选 ${id}（选项映射未提供）`,
      metric,
      mean: number(mean) ? mean : undefined,
      std: nonnegative(std) ? std : undefined,
      seeds: number(saved.n_seeds) ? saved.n_seeds : undefined,
      conflict,
      mappingConflict: conflicted.has(id),
      rejectedLetters: [...(seenLetters.get(id) ?? [])],
    };
  });
}
function resolveDirection(
  feedback: any,
  question: any,
  metric?: string,
): { higher?: boolean; conflict: boolean; source?: string } {
  const flags = [
    feedback.higher_is_better,
    feedback.reveal?.higher_is_better,
    question?.higher_is_better,
  ].filter((v) => typeof v === "boolean");
  const text =
    typeof question?.prompt === "string"
      ? question.prompt.replace(/\*\*/g, "")
      : "";
  const match =
    /correct choice has the (lowest|highest) mean\s+([A-Za-z0-9_.-]+)/i.exec(
      text,
    );
  const promptFlag =
    match && (!metric || metric === match[2])
      ? match[1].toLowerCase() === "highest"
      : undefined;
  const directions = [
    ...flags,
    ...(promptFlag !== undefined ? [promptFlag] : []),
  ];
  if (directions.length && directions.some((v) => v !== directions[0]))
    return { conflict: true };
  if (flags.length)
    return { higher: flags[0], conflict: false, source: "反馈" };
  if (promptFlag !== undefined)
    return { higher: promptFlag, conflict: false, source: "题面" };
  return { conflict: false };
}
function metricDirection(feedback: any, question: any, metric?: string) {
  const direction = resolveDirection(feedback, question, metric);
  if (direction.conflict) return "指标方向冲突，未作高低判断。";
  if (direction.higher !== undefined)
    return `${direction.source}说明：指标越${direction.higher ? "高" : "低"}越好。`;
  return "指标方向未提供，不能仅凭数值判断哪一项更好。";
}
const metricName = (v: any) =>
  v === "test_ce"
    ? "测试交叉熵（test_ce）"
    : v === "test_mse"
      ? "测试均方误差（test_mse）"
      : typeof v === "string"
        ? v
        : "指标名称未提供";
const colors = [
  "#12877f",
  "#436cae",
  "#ce8530",
  "#925fa8",
  "#ba5367",
  "#648637",
];
function CurveChart({ curves, rows, after }: { curves: any[]; rows: MetricRow[]; after?:(hasCurve:boolean)=>ReactNode }) {
  const groups = new Map<
    string,
    { axis: string; metric: string; series: any[] }
  >();
  let missing = 0,
    invalid = 0,
    ambiguous = 0;
  for (const curve of curves) {
    if (
      rows.some(
        (r) =>
          r.mappingConflict &&
          (r.candidateId === (curve.candidateId ?? curve.candidate_id) ||
            r.rejectedLetters?.includes(curve.letter)),
      )
    ) {
      ambiguous++;
      continue;
    }
    let x: any[] = [],
      axis = "";
    if (Array.isArray(curve.samples)) {
      x = curve.samples;
      axis = "训练已见样本数";
    } else if (Array.isArray(curve.steps)) {
      x = curve.steps;
      axis = "训练步数";
    } else if (Array.isArray(curve.x)) {
      x = curve.x;
      axis = "原始横轴值（单位未提供）";
    } else {
      missing++;
      continue;
    }
    const y = list(curve.mean);
    if (
      !y.length ||
      x.length !== y.length ||
      !x.every(number) ||
      !y.every(number)
    ) {
      invalid++;
      continue;
    }
    const letter =
      typeof curve.letter === "string"
        ? curve.letter
        : rows.find(
            (r) => r.candidateId === (curve.candidateId ?? curve.candidate_id),
          )?.letter;
    const metric =
      typeof curve.metric === "string"
        ? curve.metric
        : rows.find((r) => r.letter === letter)?.metric;
    if (!metric) {
      ambiguous++;
      continue;
    }
    const key = `${axis}:${metric}`;
    const group = groups.get(key) ?? {
      axis,
      metric: metricName(metric),
      series: [],
    };
    group.series.push({ x, y, letter: letter ?? "选项未绑定", std: curve.std });
    groups.set(key, group);
  }
  return (
    <Block title="训练过程对比">
      {groups.size > 0 &&
        [...groups.entries()].map(([key, group]) => (
          <Plot key={key} {...group} />
        ))}
      {ambiguous > 0 && (
        <Notice>曲线选项或指标关系存在冲突或未绑定，未作可比较绘图。</Notice>
      )}
      {missing > 0 && <Notice>曲线横轴未提供，无法按训练进度绘图。</Notice>}
      {invalid > 0 && (
        <Notice>
          部分曲线坐标缺失或长度不一致，未将它们补成零或推测坐标。
        </Notice>
      )}
      {curves.length === 0 && <Notice>本次反馈未记录训练曲线</Notice>}
      {after?.(groups.size>0)}
    </Block>
  );
}
function Plot({
  axis,
  metric,
  series,
}: {
  axis: string;
  metric: string;
  series: any[];
}) {
  const minX = Math.min(...series.flatMap((s) => s.x)),
    maxX = Math.max(...series.flatMap((s) => s.x));
  const allY = series.flatMap((s) =>
    s.y.flatMap((v: number, i: number) =>
      nonnegative(s.std?.[i]) ? [v - s.std[i], v + s.std[i]] : [v],
    ),
  );
  let minY = Math.min(...allY),
    maxY = Math.max(...allY);
  const pad = (maxY - minY) * 0.08 || Math.abs(maxY) * 0.02 || 0.1;
  minY -= pad;
  maxY += pad;
  const px = (v: number) => 52 + ((v - minX) / (maxX - minX || 1)) * 376,
    py = (v: number) => 188 - ((v - minY) / (maxY - minY || 1)) * 150;
  const band = series.some(
    (s) =>
      Array.isArray(s.std) &&
      s.std.length === s.y.length &&
      s.std.every(nonnegative),
  );
  return (
    <figure className="ns-chart">
      <svg
        viewBox="0 0 456 240"
        role="img"
        aria-label={`训练曲线 · ${metric} · ${axis}`}
      >
        <title>
          {metric} 随 {axis} 的变化
        </title>
        {[0, 0.5, 1].map((t) => {
          const value = minY + (maxY - minY) * t;
          return (
            <g key={t}>
              <line
                x1="52"
                y1={py(value)}
                x2="428"
                y2={py(value)}
                stroke="#e3ebf1"
              />
              <text x="46" y={py(value) + 4} textAnchor="end">
                {display(value)}
              </text>
            </g>
          );
        })}
        <line x1="52" y1="38" x2="52" y2="188" stroke="#99adbd" />
        <line x1="52" y1="188" x2="428" y2="188" stroke="#99adbd" />
        <text x="52" y="206">
          {display(minX)}
        </text>
        <text x="428" y="206" textAnchor="end">
          {display(maxX)}
        </text>
        <text x="240" y="230" textAnchor="middle">
          {axis}
        </text>
        <text x="52" y="21">
          {metric}
        </text>
        {series.map((s, index) => {
          const color = colors[index % colors.length];
          const goodStd =
            Array.isArray(s.std) &&
            s.std.length === s.y.length &&
            s.std.every(nonnegative);
          const points = s.x
            .map((v: number, i: number) => `${px(v)},${py(s.y[i])}`)
            .join(" ");
          const polygon = goodStd
            ? [
                ...s.x.map(
                  (v: number, i: number) => `${px(v)},${py(s.y[i] + s.std[i])}`,
                ),
                ...s.x
                  .map(
                    (v: number, i: number) =>
                      `${px(v)},${py(s.y[i] - s.std[i])}`,
                  )
                  .reverse(),
              ].join(" ")
            : undefined;
          return (
            <g key={index}>
              {polygon && (
                <polygon points={polygon} fill={color} opacity=".12" />
              )}
              <polyline
                points={points}
                fill="none"
                stroke={color}
                strokeWidth="2.2"
              >
                <title>
                  选项 {s.letter}：{s.y.length} 个记录点
                </title>
              </polyline>
            </g>
          );
        })}
      </svg>
      <figcaption>
        <div className="ns-legend">
          {series.map((s, i) => (
            <span key={i}>
              <i style={{ background: colors[i % colors.length] }} />
              选项 {s.letter}
            </span>
          ))}
        </div>
        <p>
          实线表示平均表现。
          {band ? "淡色区域表示训练结果的波动（±1 标准差）。" : ""}
        </p>
      </figcaption>
    </figure>
  );
}
function completeSeedValues(
  row: MetricRow,
  feedback: any,
): Map<number, number> | undefined {
  if (!row.candidateId || !row.metric) return undefined;
  const summary = object(object(feedback.candidate_metrics)[row.candidateId]);
  const declared = [summary.selection_metric, summary.metric].filter(
    (v) => typeof v === "string" && v,
  );
  if (
    !declared.length ||
    declared.some((v) => v !== row.metric) ||
    summary.excluded === true ||
    (present(summary.candidate_id) && summary.candidate_id !== row.candidateId)
  )
    return undefined;
  const n = summary.n_seeds,
    results = list(summary.seed_results);
  if (
    !Number.isInteger(n) ||
    n < 2 ||
    results.length !== n ||
    (present(summary.failed_seeds) && summary.failed_seeds !== 0)
  )
    return undefined;
  const values = new Map<number, number>();
  for (const result of results) {
    if (
      !result ||
      result.failed !== false ||
      !Number.isInteger(result.seed) ||
      result.seed < 0 ||
      !number(result[`final_${row.metric}`]) ||
      values.has(result.seed)
    )
      return undefined;
    values.set(result.seed, result[`final_${row.metric}`]);
  }
  return values;
}
function GapStory({
  rows,
  feedback,
  question,
}: {
  rows: MetricRow[];
  feedback: any;
  question: any;
}) {
  if (
    rows.length < 2 ||
    rows.some(
      (r) =>
        r.conflict ||
        r.mappingConflict ||
        !r.letter ||
        !r.metric ||
        !number(r.mean),
    )
  )
    return null;
  const metric = rows[0].metric!;
  if (rows.some((r) => r.metric !== metric)) return null;
  const direction = resolveDirection(feedback, question, metric);
  if (direction.conflict || direction.higher === undefined) return null;
  const ordered = [...rows].sort((a, b) =>
    direction.higher ? b.mean! - a.mean! : a.mean! - b.mean!,
  );
  const [first, second] = ordered,
    gap = Math.abs(first.mean! - second.mean!);
  const a = completeSeedValues(first, feedback),
    b = completeSeedValues(second, feedback);
  const paired =
    !!a &&
    !!b &&
    a.size === b.size &&
    [...a.keys()].every((seed) => b.has(seed));
  let wins = 0,
    ties = 0;
  if (paired)
    for (const [seed, value] of a!) {
      const other = b!.get(seed)!;
      if (value === other) ties++;
      else if (direction.higher ? value > other : value < other) wins++;
    }
  const bounds = (values: Map<number, number>) => [
    Math.min(...values.values()),
    Math.max(...values.values()),
  ];
  const range = (values: Map<number, number>) =>
    bounds(values).map(display).join("–");
  const separated =
    !!a &&
    !!b &&
    (direction.higher
      ? bounds(a)[0] > bounds(b)[1]
      : bounds(a)[1] < bounds(b)[0]);
  return (
    <section className="ns-gap-story" aria-label="差距与重复训练波动">
      <h5>差距与重复训练波动</h5>
      <strong>{`均值差距 ${display(gap)}`}</strong>
      <p className="ns-prose">
        按本题指标比较的前两项是 {first.letter} 与 {second.letter}；
        {first.letter} 的标准差 {display(first.std)}，{second.letter} 的标准差{" "}
        {display(second.std)}。
      </p>
      {a && b ? (
        <>
          <p className="ns-prose">
            已记录训练的范围：{first.letter}：{range(a)}；{second.letter}：
            {range(b)}。
          </p>
          {separated && (
            <p className="ns-range-note">
              已记录训练的结果范围完全分开；{first.letter} 最差一次仍优于{" "}
              {second.letter} 最好一次。
            </p>
          )}
          {paired && (
            <details className="ns-disclosure">
              <summary>查看逐次训练对照</summary>
              <p className="ns-caption">
                同编号训练中，{first.letter} 优于 {second.letter} {wins} /{" "}
                {a.size}，并列 {ties}
                。这是描述性对照，不是显著性检验；同编号种子不保证不同模型经历相同随机过程。
              </p>
              <div className="ns-table-wrap">
                <table aria-label="同编号训练记录">
                  <thead>
                    <tr>
                      <th>种子编号</th>
                      <th>选项 {first.letter}</th>
                      <th>选项 {second.letter}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...a]
                      .sort(([x], [y]) => x - y)
                      .map(([seed, value]) => (
                        <tr key={seed}>
                          <th>{seed}</th>
                          <td>{display(value)}</td>
                          <td>{display(b.get(seed))}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </>
      ) : (
        <p className="ns-caption">
          逐次训练结果不完整，仅凭均值和波动摘要不能据此声称统计显著。
        </p>
      )}
      <p className="ns-caption">
        结论只适用于本题固定的数据与各选项训练预算；多个设置同时变化时，不能解释单个因素的因果作用。
      </p>
    </section>
  );
}
function MetricsTable({
  rows,
  feedback,
  question,
}: {
  rows: MetricRow[];
  feedback: any;
  question: any;
}) {
  const groups = new Map<string, MetricRow[]>();
  for (const row of rows) {
    const key = row.conflict ? "conflict" : (row.metric ?? "unknown");
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return (
    <Block title="候选最终表现">
      {!rows.length && <Notice>候选最终指标未提供</Notice>}
      {groups.size > 1 && (
        <Notice>
          候选采用不同指标或声明不一致，分别展示，不跨指标比较数值。
        </Notice>
      )}
      {[...groups].map(([metric, items]) => (
        <div key={metric} className="ns-metric-group">
          <strong className="ns-metric-title">
            {metric === "conflict"
              ? "指标声明冲突"
              : metric === "unknown"
                ? "指标名称未提供"
                : metricName(metric)}
          </strong>
          {metric === "test_ce" && (
            <p className="ns-caption">衡量模型对测试目标的预测误差。</p>
          )}
          {metric === "test_mse" && (
            <p className="ns-caption">衡量预测值与测试目标的平均平方误差。</p>
          )}
          <p className="ns-caption">
            {metric === "conflict"
              ? "未对指标声明冲突的数值作比较。"
              : metricDirection(feedback, question, metric)}
          </p>
          <div className="ns-table-wrap">
            <table aria-label="候选指标对比">
              <thead>
                <tr>
                  <th>选项</th>
                  <th>
                    最终表现
                    <br />
                    均值
                  </th>
                  <th>
                    波动
                    <br />
                    标准差
                  </th>
                  <th>
                    重复训练
                    <br />
                    次数
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((row, i) => (
                  <tr key={i}>
                    <th>{row.label}</th>
                    <td>{display(row.mean)}</td>
                    <td>{display(row.std)}</td>
                    <td>{display(row.seeds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      <p className="ns-caption">
        均值是多次训练的平均表现，标准差表示结果波动。数值已四舍五入，精确值保留在高级详情。
      </p>
      <GapStory rows={rows} feedback={feedback} question={question} />
    </Block>
  );
}
/** Render stored results only; callers control when feedback is revealed. */
export function StoredTrainingResults({feedback,question,compact=false}:{feedback:any;question:any;compact?:boolean}){
  const rows=metricRows(feedback,question),curves=list(feedback.reveal?.curves??feedback.curves);
  const metrics=<MetricsTable rows={rows} feedback={feedback} question={question}/>;
  return compact?<CurveChart curves={curves} rows={rows} after={hasCurve=><details className="ns-disclosure human-practice-statistics" open={!hasCurve}><summary>候选最终指标与统计信息</summary>{metrics}</details>}/>:<>{metrics}<CurveChart curves={curves} rows={rows}/></>;
}
function FeedbackCard({
  id,
  feedback,
  run,
  roundIndex,
  question: given,
  answer: provided,
}: {
  id: string;
  feedback: any;
  run?: Run;
  roundIndex?: number;
  question?: any;
  answer?: any;
}) {
  const question = given ?? publicQuestion(id, run, roundIndex),
    answer = provided ?? committedAnswer(id, run, roundIndex),
    winnerConflict =
      typeof feedback.correct_letter === "string" &&
      typeof feedback.reveal?.correctLetter === "string" &&
      feedback.correct_letter !== feedback.reveal.correctLetter,
    winner = winnerConflict
      ? undefined
      : (feedback.correct_letter ?? feedback.reveal?.correctLetter);
  const submitted =
    answer?.valid === true && typeof answer?.ranking?.[0] === "string"
      ? answer.ranking[0]
      : undefined;
  const rows = metricRows(feedback, question);
  const curves = list(feedback.reveal?.curves ?? feedback.curves);
  return (
    <article className="ns-feedback">
      <div className="ns-question-heading">
        <strong>{question ? familyName(question.family) : "题目反馈"}</strong>
        <span>
          {typeof winner === "string" ? `正确选项 ${winner}` : "正确选项未提供"}
        </span>
      </div>
      <div className="ns-answer-compare">
        {winnerConflict && (
          <Notice>正确答案来源冲突，未作提交一致性判断。</Notice>
        )}
        {submitted ? (
          <>
            <strong>本轮提交 {submitted}</strong>
            {typeof winner === "string" && (
              <span
                className={submitted === winner ? "ns-positive" : "ns-warning"}
              >
                {submitted === winner
                  ? "提交答案与正确选项一致"
                  : "提交答案与正确选项不同"}
              </span>
            )}
          </>
        ) : (
          <Notice>
            {answer?.valid === false
              ? "本轮回答格式未通过，不能作为有效选项比较。"
              : "本轮已提交答案未提供"}
          </Notice>
        )}
      </div>
      {question && (
        <details className="ns-disclosure">
          <summary>查看这道题的公开题面</summary>
          <QuestionCard question={question} />
        </details>
      )}
      <MetricsTable rows={rows} feedback={feedback} question={question} />
      <CurveChart curves={curves} rows={rows} />
    </article>
  );
}
function FeedbackStory(props: NodeStoryProps) {
  const data = object(props.value);
  const direct =
    "correct_letter" in data || "candidate_metrics" in data || "reveal" in data;
  const entries = direct
    ? [[props.questionKey ?? "", data] as const]
    : Object.entries(data).filter(
        ([, v]) =>
          v &&
          typeof v === "object" &&
          ("correct_letter" in v || "candidate_metrics" in v || "reveal" in v),
      );
  return entries.length ? (
    <Cards
      items={entries}
      renderItem={([id, feedback]) => (
        <FeedbackCard
          id={id}
          feedback={feedback}
          run={props.run}
          roundIndex={props.roundIndex}
        />
      )}
    />
  ) : (
    <Notice>已揭示反馈未提供可读的答案或候选指标。</Notice>
  );
}
const factorNames: Record<string, string> = {
  layernorm: "层归一化",
  activation: "激活函数",
  residual: "残差连接",
  depth: "网络深度",
  width: "网络宽度",
  model_type: "模型类型",
  batch_size: "每批样本数",
  lr: "学习率",
  opt: "优化器",
  budget: "训练样本预算",
  family: "数据集族",
};
const field = (v: any) =>
  typeof v === "string"
    ? Object.hasOwn(factorNames, v)
      ? factorNames[v]
      : v
    : "条件未提供";
function predicate(v: any): string {
  if (v === null || v === undefined) return "未限定";
  if (Array.isArray(v) && v.length === 3 && typeof v[0] === "string") {
    const ops: Record<string, string> = {
      eq: "等于",
      ne: "不等于",
      lt: "小于",
      le: "不大于",
      gt: "大于",
      ge: "不小于",
      in: "属于",
      nin: "不属于",
    };
    const scalar = (x: any) =>
      typeof x === "boolean"
        ? x
          ? "开启"
          : "关闭"
        : typeof x === "string" || number(x)
          ? String(x)
          : "条件值未提供";
    return `${field(v[0])} ${ops[v[1]] ?? "条件"} ${Array.isArray(v[2]) ? v[2].map(scalar).join("、") : scalar(v[2])}`;
  }
  if (Array.isArray(v)) return v.map(predicate).join("；同时 ");
  const o = object(v);
  if (o.all) return list(o.all).map(predicate).join("；同时 ");
  if (o.any) return list(o.any).map(predicate).join("；或 ");
  if (o.not) return `不满足：${predicate(o.not)}`;
  return "规则条件见高级完整记录";
}
function RuleStory({ rule }: { rule: any }) {
  if (!rule || typeof rule !== "object") return null;
  const r = object(rule),
    p = object(r.predict);
  let prediction = "预测关系见完整规则";
  if (p.better && p.worse)
    prediction = `预期更优：${predicate(p.better)}；预期更差：${predicate(p.worse)}`;
  else if (typeof p.higher_better === "string")
    prediction = `${field(p.higher_better)} 越高的候选预期更好`;
  else if (typeof p.lower_better === "string")
    prediction = `${field(p.lower_better)} 越低的候选预期更好`;
  else if (Array.isArray(p.dominates))
    prediction = p.dominates
      .map(
        (axis: any) =>
          `${field(axis[0])} ${axis[1] === "higher" ? "更高" : "更低"}${number(axis[2]) ? `，至少 ${axis[2]} 倍` : ""}`,
      )
      .join("；");
  return (
    <Block title="可检验的规则">
      <p className="ns-prose">{prediction}</p>
      {present(r.scope) && (
        <p className="ns-caption">适用条件：{predicate(r.scope)}</p>
      )}
      {list(r.same).length > 0 && (
        <p className="ns-caption">保持一致：{r.same.map(field).join("、")}</p>
      )}
      {list(r.differ).length > 0 && (
        <p className="ns-caption">允许变化：{r.differ.map(field).join("、")}</p>
      )}
    </Block>
  );
}
function PlanStory({ value }: { value: any }) {
  const plan = object(value);
  return (
    <Block title="实验方案">
      <div className="ns-facts">
        {typeof plan.family === "string" && (
          <span>数据集：{familyName(plan.family)}</span>
        )}
        {typeof plan.factor === "string" && (
          <span>控制因素：{field(plan.factor)}</span>
        )}
        {number(plan.count) && <span>计划实验 {plan.count} 组</span>}
        {number(plan.n_seeds) && (
          <span>每候选计划 {plan.n_seeds} 个训练种子</span>
        )}
      </div>
      {!Object.keys(plan).some((k) =>
        ["family", "factor", "count", "n_seeds"].includes(k),
      ) && <Notice>可读实验方案未提供</Notice>}
      <RuleStory rule={plan.rule} />
    </Block>
  );
}
function HypothesisStory({ value }: { value: any }) {
  if (value?.hypothesis === null)
    return <Notice>本次没有提出新的假说。</Notice>;
  const h = object(value?.hypothesis ?? value);
  return (
    <>
      <Block title="提出的假说">
        <Prose value={h.text} missing="假说正文未提供" />
      </Block>
      {present(h.boundary) && (
        <Block title="适用边界">
          <Prose value={h.boundary} />
        </Block>
      )}
      {present(h.competing_explanation) && (
        <Block title="竞争解释">
          <Prose value={h.competing_explanation} />
        </Block>
      )}
      <RuleStory rule={h.rule} />
      {h.experiment && <PlanStory value={h.experiment} />}
    </>
  );
}
function SkepticStory({ value }: { value: any }) {
  const v = object(value);
  return (
    <>
      <Block title="审查决定">
        <strong className={v.accept === true ? "ns-positive" : "ns-warning"}>
          {v.accept === true
            ? "接受此假说进入实验"
            : v.accept === false
              ? "不接受此假说"
              : "审查决定未提供"}
        </strong>
        <Prose value={v.reason} missing="审查理由未提供" />
      </Block>
      {present(v.counterexample) && (
        <Block title="需要检验的反例">
          <Prose value={v.counterexample} />
        </Block>
      )}
      {v.experiment && <PlanStory value={v.experiment} />}
    </>
  );
}
function AnalysisStory({ value }: { value: any }) {
  const v = object(value);
  return (
    <>
      <Block title="证据结论">
        <Prose value={v.summary} missing="分析摘要未提供" />
      </Block>
      <TextList title="局限与边界" value={v.limitations} />
      <TextList title="后续研究问题" value={v.next_questions} />
    </>
  );
}
const actions: Record<string, string> = {
  upsert: "新增或修订",
  keep: "保持现状",
  retire: "退出使用",
};
function Decisions({ value }: { value: any }) {
  const decisions = list(value?.decisions ?? value?.operations ?? value);
  return (
    <Block title="知识处理建议">
      {decisions.length ? (
        <Cards
          items={decisions}
          renderItem={(decision) => (
            <article className="ns-small-card">
              <strong>
                {Object.hasOwn(actions, decision.action ?? decision.op)
                  ? actions[decision.action ?? decision.op]
                  : "处理方式未提供"}
              </strong>
              <Prose
                value={decision.claim?.text ?? decision.text ?? decision.reason}
                missing="处理理由未提供"
              />
              {decision.claim?.text && decision.reason && (
                <Prose value={decision.reason} />
              )}
              <p className="ns-caption">
                {decision.enabled === true
                  ? "建议启用"
                  : decision.enabled === false
                    ? "建议保持未启用"
                    : "启用状态未提供"}{" "}
                · 最终发布仍需证据验证。
              </p>
            </article>
          )}
        />
      ) : (
        <Notice>本次未记录知识变更建议</Notice>
      )}
    </Block>
  );
}
function ExperimentStory({
  value,
  confirmation = false,
}: {
  value: any;
  confirmation?: boolean;
}) {
  const records = list(value?.records ?? value?.evidence ?? value);
  if (!records.length)
    return <Notice>真实实验记录未提供，无法报告支持或反驳数量。</Notice>;
  const counts = (outcome: string) =>
    records.filter((r) => r.outcome === outcome).length;
  return (
    <>
      <Block title={confirmation ? "独立确认记录" : "探索实验记录"}>
        <div className="ns-facts">
          <strong>{records.length} 条实验记录</strong>
          <span>支持 {counts("support")}</span>
          <span>反驳 {counts("refute")}</span>
          <span>未决 {counts("inconclusive")}</span>
        </div>
        <p className="ns-caption">
          {confirmation
            ? "这些是实验结果记录；记录数量和支持比例本身不代表科学门槛已通过。"
            : "探索结果不等同于独立确认通过。"}
        </p>
      </Block>
      <Cards
        items={records}
        renderItem={(record, index) => (
          <article className="ns-small-card">
            <strong>
              实验 {index + 1} ·{" "}
              {record.outcome === "support"
                ? "支持假说"
                : record.outcome === "refute"
                  ? "反驳假说"
                  : record.outcome === "inconclusive"
                    ? "结果未决"
                    : "结果未提供"}
            </strong>
            <div className="ns-facts">
              {typeof record.metric === "string" && (
                <span>{metricName(record.metric)}</span>
              )}
              {list(record.seed_ids).length > 0 && (
                <span>{record.seed_ids.length} 个训练种子</span>
              )}
              {list(record.candidate_ids).length > 0 && (
                <span>{record.candidate_ids.length} 个候选</span>
              )}
            </div>
            {record.summary && <Prose value={record.summary} />}
            <p className="ns-caption">
              {Array.isArray(record.candidates)
                ? "候选最终数值保存在完整证据中。"
                : "此记录未嵌入候选指标均值；不从结果标签推测数值。"}
            </p>
          </article>
        )}
      />
    </>
  );
}
function Publication({
  value,
  input = false,
}: {
  value: any;
  input?: boolean;
}) {
  if (input)
    return (
      <>
        <Decisions value={value?.patch ?? value} />
        {Array.isArray(value?.evidence) && (
          <p className="ns-caption">
            提交 {value.evidence.length} 条证据供发布验证。
          </p>
        )}
      </>
    );
  const claims = list(value?.claims);
  return (
    <>
      <Block title="本轮封存的知识库">
        <div className="ns-facts">
          {Array.isArray(value?.claims) ? (
            <>
              <strong>{claims.length} 条知识</strong>
              <span>
                已启用 {claims.filter((c) => c.enabled === true).length} 条
              </span>
              <span>
                未启用 {claims.filter((c) => c.enabled === false).length} 条
              </span>
            </>
          ) : (
            <Notice>知识条目数量未提供</Notice>
          )}
        </div>
        <p className="ns-caption">
          这是本轮保存的知识版本，不代表之后更新的最新状态。
        </p>
      </Block>
      {claims.length > 0 && (
        <Cards
          items={claims}
          renderItem={(claim) => (
            <article className="ns-small-card">
              <Prose value={claim.text} missing="知识正文未提供" />
              <p className="ns-caption">
                {claim.enabled === true
                  ? "本轮已启用"
                  : claim.enabled === false
                    ? "本轮未启用"
                    : "启用状态未提供"}
                {Array.isArray(claim.evidence_ids)
                  ? ` · ${claim.evidence_ids.length} 条证据`
                  : ""}
              </p>
              <RuleStory rule={claim.rule} />
            </article>
          )}
        />
      )}
    </>
  );
}
function RoundStory({ value }: { value: any }) {
  const v = object(value);
  if(v.practice?.kind==='same_question_practice')return <><Block title="本轮学习已封存"><p>第 {v.round??'—'} 轮 · 同题复盘</p><p>已保存 {Object.keys(v.answers??{}).length} 份回答与对应反馈。</p></Block>{v.experience&&<ExperienceStory value={v.experience}/>}<Notice>继续或结束以本次运行的轮末决定为准。</Notice></>;

  return (
    <>
      <Block title="本轮已保存的结果">
        <div className="ns-facts">
          {number(v.round) && <span>第 {v.round} 轮</span>}
          {v.answers && typeof v.answers === "object" && (
            <span>保存 {Object.keys(v.answers).length} 份答案</span>
          )}
          {number(v.evidence_count) && (
            <span>{v.evidence_count} 条实验记录</span>
          )}
          {Array.isArray(v.candidates) && (
            <span>{v.candidates.length} 个研究假说</span>
          )}
          {typeof v.confirmation_attempted === "boolean" && (
            <span>
              {v.confirmation_attempted
                ? "本轮尝试了独立确认"
                : "本轮未尝试独立确认"}
            </span>
          )}
        </div>
      </Block>
      {v.analysis && <AnalysisStory value={v.analysis} />}
      <Decisions value={v.patch} />
      <Notice>
        {v.next_action === "continue"
          ? "记录指定继续下一轮。"
          : v.next_action === "done"
            ? "记录指定结束本轮流程。"
            : "此结果没有单独记录下一步决定；请结合冻结路由和实际阶段事件查看。"}
      </Notice>
    </>
  );
}
function Evaluation({ value }: { value: any }) {
  const v = object(value),
    scores = object(v.scores);
  const labels: Record<string, string> = {
    clean: "无知识条件",
    initial: "初始知识条件",
    current: "当前知识条件",
    experience_examples: "经验案例 · 未验证",
    experience_lessons: "经验规律 · 未验证",
    experience_combined: "案例与规律 · 未验证",
  };
  const entries = Object.entries(scores);
  return entries.length ? (
    <Block title="独立评测对照">
      <div className="ns-score-grid">
        {entries.map(([arm, s]) => (
          <article className="ns-small-card" key={arm}>
            <strong>{Object.hasOwn(labels, arm) ? labels[arm] : arm}</strong>
            <p className="ns-score">
              {display(s.correct)} / {display(s.total)}
            </p>
            <span className="ns-caption">正确题数 / 总题数</span>
            {number(s.covered_questions) && <p className="ns-caption">{arm.startsWith("experience_") ? "实际检索经验" : "实际使用知识"} {s.covered_questions} / {display(s.total)} 题</p>}
            {arm !== "clean" && number(s.helpful_changes) && number(s.harmful_changes) && <p className="ns-caption">相对无 KB：答错变答对 {s.helpful_changes} 题，答对变答错 {s.harmful_changes} 题</p>}
            {arm !== "clean" && !arm.startsWith("experience_") && s.covered_questions === 0 && <p className="ns-caption">本条件没有向模型注入可用知识，分数差异不能视为 KB 收益。</p>}
            {number(s.invalid) && (
              <p className="ns-caption">格式无效 {s.invalid} 份</p>
            )}
            {number(s.pairwise_accuracy) && (
              <p className="ns-caption">
                已判定候选对排序准确率 {(s.pairwise_accuracy * 100).toFixed(1)}%
              </p>
            )}
          </article>
        ))}
      </div>
      <p className="ns-caption">
        对照得分反映答题表现，不能单独证明知识规则获得科学验证。
      </p>
    </Block>
  ) : (
    <Notice>独立评测得分未提供</Notice>
  );
}
function EndStory({ value }: { value: any }) {
  const v = object(value);
  return (
    <>
      <Block title="任务结果摘要">
        <div className="ns-facts">
          {Array.isArray(v.rounds) && (
            <span>保存 {v.rounds.length} 轮结果</span>
          )}
          {Array.isArray(v.calls) ? (
            <span>{v.calls.length} 份角色调用记录</span>
          ) : (
            number(v.calls) && <span>{v.calls} 次调用</span>
          )}
          {number(v.charged_tokens) && (
            <span>计费 {v.charged_tokens} token</span>
          )}
        </div>
        {!Array.isArray(v.rounds) && !present(v.calls) && (
          <Notice>轮次与调用数量未提供</Notice>
        )}
      </Block>
      {v.evaluation && <Evaluation value={v.evaluation} />}{" "}
      {v.kb && <Publication value={v.kb} />}
    </>
  );
}
function InputStory(props: NodeStoryProps) {
  let data = props.value;
  const original = object(data);
  if (typeof original.prompt === "string") {
    const parsed = parseSentContent(original.prompt);
    if (parsed.data === undefined)
      return (
        <Notice>
          封存角色输入未提供可解析的研究数据；完整 Prompt 保留在高级记录中。
        </Notice>
      );
    data = parsed.data;
  }
  const v = object(data);
  if (props.nodeId === "input" || props.nodeId === "reveal") {
    const ids = list(v.question_ids ?? v.committed_question_ids);
    return ids.length ? (
      <Block
        title={
          props.nodeId === "reveal" ? "等待对照的已保存答案" : "本轮选入的题目"
        }
      >
        <p className="ns-caption">
          {ids.length} 道题目
          {props.nodeId === "reveal"
            ? "的回答已提交用于反馈对照。"
            : "进入本轮。"}
        </p>
        <Cards
          items={ids}
          renderItem={(id, index) => {
            const q =
              typeof id === "string"
                ? publicQuestion(id, props.run, props.roundIndex)
                : undefined;
            return q ? (
              <QuestionCard question={q} index={index} />
            ) : (
              <p className="ns-caption">题目 {index + 1} · 公开题面未提供</p>
            );
          }}
        />
      </Block>
    ) : (
      <Notice>本轮题目列表未提供</Notice>
    );
  }
  if (props.nodeId === "commit") return <AnswerStory value={v} />;
  if (["experiment", "confirmation"].includes(props.nodeId))
    return <PlanStory value={v} />;
  if (props.nodeId === "publish") return <Publication value={v} input />;
  return (
    <>
      {['experience_curator','experience_save'].includes(props.nodeId)&&Array.isArray(v.lessons)&&<ExperienceStory value={{lessons:v.lessons}}/>}
      {props.nodeId==='experience_save'&&Array.isArray(v.operations)&&<ExperienceStory value={v}/>}
      {v.stage && v.original && <Block title={v.stage === "induction" ? "正常题归纳材料" : "反事实对照材料"}>
        <QuestionCard question={v.original.question}/>
        <p>{v.stage === "induction" ? "只有正常题及其已揭示反馈，尚未提供 DataFlip 材料。" : "保留正常题公开题面、已核对的因素变化和双侧反馈摘要。"}</p>
        {v.pair?.intervention?.changes?.map((c:any,i:number)=><p key={i}>{c.path}：{JSON.stringify(c.before)} → {JSON.stringify(c.after)}</p>)}
        {v.induction?.learning && <LearningNote value={v.induction}/>}
      </Block>}
      {v.provisional_learning && <Block title="本次迁移使用的初步规律 · 待验证"><LearningNote value={v.provisional_learning}/></Block>}
      {v.question && <QuestionCard question={v.question} />}{" "}
      {Object.hasOwn(v, "knowledge") && <Knowledge value={v.knowledge} />}{" "}
      {Object.hasOwn(v, "initial_experience") && <RetrievedExperience value={v.initial_experience} run={props.run} roundIndex={props.roundIndex} questionId={v.question?.id} initial />}
      {Object.hasOwn(v, "experience") && <RetrievedExperience value={v.experience} run={props.run} roundIndex={props.roundIndex} questionId={v.question?.id} />}
      {list(v.episodes ?? v.packet).length > 0 && (
        <Block title={`本次研究包 · ${(v.episodes ?? v.packet).length} 道题目`}>
          <Cards
            items={v.episodes ?? v.packet}
            renderItem={(packet, index) => (
              <div className="ns-packet">
                {packet.question && (
                  <QuestionCard question={packet.question} index={index} />
                )}{" "}
                {packet.feedback && (
                  <FeedbackCard
                    id={packet.question?.id ?? props.questionKey ?? ""}
                    question={packet.question}
                    answer={packet.answer}
                    feedback={packet.feedback}
                    run={props.run}
                    roundIndex={props.roundIndex}
                  />
                )}
              </div>
            )}
          />
        </Block>
      )}{" "}
      {Array.isArray(v.candidates) && (
        <Block title="待审查的研究假说">
          <Cards
            items={v.candidates}
            renderItem={(claim) => <HypothesisStory value={claim} />}
          />
        </Block>
      )}{" "}
      {v.hypothesis && <HypothesisStory value={v} />}{" "}
      {v.analysis && <AnalysisStory value={v.analysis} />}{" "}
      {Array.isArray(v.evidence) && <ExperimentStory value={v.evidence} />}{" "}
      {!v.question && !v.stage && !v.provisional_learning &&
        !Object.hasOwn(v, "knowledge") &&
        !Object.hasOwn(v, "initial_experience") &&
        !Object.hasOwn(v, "experience") &&
        !list(v.episodes ?? v.packet).length &&
        !Array.isArray(v.candidates) &&
        !v.hypothesis &&
        !v.analysis &&
        !Array.isArray(v.evidence) && (
          <Notice>此输入尚无可读摘要；完整内容保留在高级记录中。</Notice>
        )}
    </>
  );
}
function ExperienceStory({value,run,roundIndex}:{value:any;run?:Run;roundIndex?:number}) {
 const v=object(value), snapshot=object(v.after_snapshot??v), lessons=list(snapshot.lessons), operations=list(v.operations);
 const rows=lessons.length?lessons:operations;
 const sources=experienceSources(run,roundIndex === undefined ? undefined : roundIndex+1);
 for(const episode of list(v.episodes))sources[episode.id]=episode;
 for(const [id,source] of Object.entries(object(v.episode_provenance)))if(!sources[id])sources[id]=source;
 return <Block title="待验证经验">
   <p className="ns-caption">来自作答与反馈的经验，尚未通过独立验证。</p>
   {(v.version||v.after)&&<details className="ns-disclosure"><summary>经验版本标识</summary><p className="ns-prose">上一版：{v.parent_version??v.before??'初始'}</p><p className="ns-prose">当前版：{v.version??v.after}</p></details>}
   {!rows.length&&<Notice>本轮没有新增或修订经验；来源记录仍保留。</Notice>}
   <Cards items={rows} renderItem={(lesson,index)=><LessonCard lesson={lesson} index={index} sources={sources}/>}/>
 </Block>;
}
export function NodeStory(props: NodeStoryProps) {
  const purpose = purposes[props.nodeId];
  let value = props.value;
  if (
    props.direction === "output" &&
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.hasOwn(value, "result")
  )
    value = value.result;
  if (typeof value === "string" && props.direction === "output") {
    const parsed = parseOutput(value);
    if (parsed !== undefined) value = parsed;
  }
  const content = () => {
    if (value === undefined || value === null)
      return (
        <Notice>
          实际{props.direction === "input" ? "输入" : "输出"}
          未提供；未根据配置或其他节点重建产物。
        </Notice>
      );
    if (props.direction === "input")
      return <InputStory {...props} value={value} />;
    switch (props.nodeId) {
      case "input": {
        const questions = list(value);
        return questions.length ? (
          <Block title={`本轮公开题目 · ${questions.length} 道`}>
            <Cards
              items={questions}
              renderItem={(q, index) => (
                <QuestionCard question={q} index={index} />
              )}
            />
          </Block>
        ) : (
          <Notice>公开题目列表未提供</Notice>
        );
      }
      case "experience_curator":
      case "experience_save":
        return <ExperienceStory value={value} run={props.run} roundIndex={props.roundIndex}/>;
      case "solver":
      case "commit":
        return <AnswerStory value={value} locked={props.nodeId === "commit"} />;
      case "reveal":
        return <FeedbackStory {...props} value={value} />;
      case "discoverer":
        return value?.learning ? <Block title="反事实归纳 · 待验证"><LearningNote value={value}/>{value.hypothesis && <HypothesisStory value={value}/>}</Block> : <HypothesisStory value={value} />;
      case "skeptic":
        return <SkepticStory value={value} />;
      case "analyst":
        return <AnalysisStory value={value} />;
      case "curator":
        return <Decisions value={value} />;
      case "experiment":
      case "confirmation":
        return (
          <ExperimentStory
            value={value}
            confirmation={props.nodeId === "confirmation"}
          />
        );
      case "publish":
        return <Publication value={value} />;
      case "loop":
        return <RoundStory value={value} />;
      case "evaluate":
        return object(value).scores ? (
          <Evaluation value={value} />
        ) : object(value).ranking ? (
          <AnswerStory value={value} />
        ) : (
          <Notice>独立评测得分未提供</Notice>
        );
      case "end":
        return <EndStory value={value} />;
      default:
        return <Notice>此产物尚无可读摘要；完整内容保留在高级记录中。</Notice>;
    }
  };
  return (
    <div className="node-story">
      {props.showIntro && (
        <div className="ns-intro">
          <strong>
            {purpose?.[0] ?? "节点产物"} ·{" "}
            {props.direction === "input" ? "实际输入" : "实际输出"}
          </strong>
          <p>{purpose?.[1] ?? "这里只显示已提供的产物，未补充推测结果。"}</p>
        </div>
      )}
      {content()}
    </div>
  );
}
