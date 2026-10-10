import { afterEach, expect, it } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { NodeStory } from "./NodeStory";
import type { Run } from "./types";
afterEach(cleanup);
const question = {
  id: "q@revision",
  family: "bigram_lm",
  prompt:
    "## Evaluation metric\nThe correct choice has the lowest **mean** test_ce across seeds.",
  choices: [
    { id: "candidate-A", letter: "A", view: { model_type: "gru_lm" } },
    { id: "candidate-B", letter: "B", view: { model_type: "transformer_lm" } },
    { id: "candidate-C", letter: "C", view: { model_type: "mlp_lm" } },
  ],
};
const feedback = {
  correct_letter: "C",
  candidate_metrics: {
    "candidate-A": {
      selection_metric: "test_ce",
      mean_test_ce: 3.4,
      std_test_ce: 0.01,
      n_seeds: 10,
      environment: { python: "SECRET-ENV" },
    },
    "candidate-B": {
      selection_metric: "test_ce",
      mean_test_ce: 3.04,
      std_test_ce: 0.014,
      n_seeds: 10,
    },
    "candidate-C": {
      selection_metric: "test_ce",
      mean_test_ce: 2.94,
      std_test_ce: 0.008,
      n_seeds: 10,
    },
  },
  reveal: {
    correctLetter: "C",
    ranked: [
      {
        letter: "C",
        candidateId: "candidate-C",
        metric: "test_ce",
        mean: 2.94,
        std: 0.008,
      },
      {
        letter: "B",
        candidateId: "candidate-B",
        metric: "test_ce",
        mean: 3.04,
        std: 0.014,
      },
      {
        letter: "A",
        candidateId: "candidate-A",
        metric: "test_ce",
        mean: 3.4,
        std: 0.01,
      },
    ],
    curves: [
      {
        letter: "A",
        samples: [32, 64, 96],
        mean: [3.48, 3.45, 3.4],
        std: [0.01, 0.01, 0.01],
      },
      { letter: "B", samples: [32, 64, 96], mean: [3.57, 3.2, 3.04] },
      { letter: "C", samples: [32, 64, 96], mean: [3.32, 3.05, 2.94] },
    ],
    files: { A: { "summary.json": { raw: "SECRET-RAW" } } },
  },
};
const run: Run = {
  id: "r",
  kind: "workflow",
  status: "failed",
  created_at: 1,
  config: {},
  node_observations: [
    {
      node_id: "input",
      round_index: 1,
      availability: "available",
      output: [question],
    },
    {
      node_id: "commit",
      round_index: 1,
      key: question.id,
      availability: "available",
      output: {
        valid: true,
        ranking: ["B", "A", "C"],
        rationale: "Solver reason",
        knowledge_count: 0,
        citations: [],
      },
    },
  ],
};
it("turns live-shaped feedback into answer comparison, candidate table, and true sample-axis curves", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: feedback }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(screen.getByText("正确选项 C")).toBeTruthy();
  expect(screen.getByText("本轮提交 B")).toBeTruthy();
  expect(screen.getByText("提交答案与正确选项不同")).toBeTruthy();
  const table = screen.getByRole("table", { name: "候选指标对比" });
  expect(within(table).getByText("2.94")).toBeTruthy();
  expect(screen.getByText(/题面说明：指标越低越好/)).toBeTruthy();
  expect(screen.getByRole("img", { name: /训练曲线/ })).toBeTruthy();
  expect(screen.getByText("训练已见样本数")).toBeTruthy();
  expect(screen.queryByText("candidate_metrics")).toBeNull();
  expect(screen.queryByText("correct_letter")).toBeNull();
  expect(screen.queryByText("SECRET-ENV")).toBeNull();
  expect(screen.queryByText("SECRET-RAW")).toBeNull();
});
it("does not reuse another round answer or invent candidate letters and metric direction", () => {
  const noPrompt = { ...question, prompt: "" };
  const limited = {
    ...run,
    node_observations: [
      {
        node_id: "input",
        round_index: 2,
        availability: "available",
        output: [noPrompt],
      },
      run.node_observations[1],
    ],
  };
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{
        [question.id]: {
          correct_letter: "C",
          candidate_metrics: {
            "unknown-candidate": {
              selection_metric: "new_metric",
              mean_new_metric: 0,
              n_seeds: 2,
            },
          },
        },
      }}
      run={limited}
      roundIndex={2}
    />,
  );
  expect(screen.getByText("本轮已提交答案未提供")).toBeTruthy();
  expect(screen.queryByText("本轮提交 B")).toBeNull();
  expect(screen.getByText(/选项映射未提供/)).toBeTruthy();
  expect(screen.getByText(/指标方向未提供/)).toBeTruthy();
});
it("does not invent training steps when a curve lacks an explicit horizontal axis", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{
        [question.id]: {
          ...feedback,
          reveal: { curves: [{ letter: "A", mean: [3, 2, 1] }] },
        },
      }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(screen.queryByRole("img", { name: /训练曲线/ })).toBeNull();
  expect(screen.getByText(/曲线横轴未提供/)).toBeTruthy();
  expect(screen.queryByText("训练步数")).toBeNull();
});
it("reads sealed role prompt DATA as one public question and knowledge, without exposing protocol JSON", () => {
  render(
    <NodeStory
      nodeId="solver"
      direction="input"
      value={{
        prompt: `Role instruction\n\nDATA:\n${JSON.stringify({ question, knowledge: [] })}`,
        model: { name: "model" },
        runtime_fingerprint: "PRIVATE-FP",
      }}
    />,
  );
  expect(screen.getAllByText("二元序列建模").length).toBeGreaterThan(0);
  expect(screen.getByText("3 个候选方案")).toBeTruthy();
  expect(screen.getByText("本次未提供正式知识条目")).toBeTruthy();
  expect(screen.queryByText("runtime_fingerprint")).toBeNull();
  expect(screen.queryByText("PRIVATE-FP")).toBeNull();
  expect(screen.queryByText("Role instruction")).toBeNull();
  expect(screen.getByText("查看题目详情").closest("details")?.open).toBe(false);
  fireEvent.click(screen.getByText("查看题目详情"));
  expect(screen.getByRole("tab", { name: "题目概览" })).toBeTruthy();
});
it("distinguishes committed format validity from correctness and preserves zero knowledge", () => {
  render(
    <NodeStory
      nodeId="commit"
      direction="output"
      value={{
        valid: true,
        ranking: ["B", "A", "C"],
        rationale: "Saved reasoning",
        knowledge_count: 0,
        invalid_citations: false,
        raw: { rationale: "Saved reasoning" },
      }}
    />,
  );
  expect(screen.getByText(/答案格式校验通过/)).toBeTruthy();
  expect(screen.getAllByText("Saved reasoning")).toHaveLength(1);
  expect(screen.getByText("正式知识 0 条")).toBeTruthy();
  expect(screen.queryByText("答对")).toBeNull();
  expect(screen.queryByText("raw")).toBeNull();
});
it("shows hypothesis, skeptic judgement, analysis, and knowledge actions as semantic cards", () => {
  const { rerender } = render(
    <NodeStory
      nodeId="discoverer"
      direction="output"
      value={{
        hypothesis: {
          text: "Hypothesis prose",
          boundary: "Small samples",
          competing_explanation: "Optimizer difference",
          experiment: { family: "bigram_lm", factor: "depth" },
        },
      }}
    />,
  );
  expect(screen.getByText("Hypothesis prose")).toBeTruthy();
  expect(screen.getByText("竞争解释")).toBeTruthy();
  rerender(
    <NodeStory
      nodeId="skeptic"
      direction="output"
      value={{
        accept: false,
        reason: "Insufficient controls",
        counterexample: "Different budget",
      }}
    />,
  );
  expect(screen.getByText("不接受此假说")).toBeTruthy();
  expect(screen.getByText("Insufficient controls")).toBeTruthy();
  rerender(
    <NodeStory
      nodeId="analyst"
      direction="output"
      value={{
        summary: "Evidence summary",
        limitations: ["Only one family"],
        next_questions: ["Test another family"],
      }}
    />,
  );
  expect(screen.getByText("Evidence summary")).toBeTruthy();
  expect(screen.getByText("局限与边界")).toBeTruthy();
  rerender(
    <NodeStory
      nodeId="curator"
      direction="output"
      value={{
        decisions: [
          {
            id: "claim-id",
            action: "retire",
            reason: "Counter-evidence",
            enabled: false,
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("退出使用")).toBeTruthy();
  expect(screen.getByText("Counter-evidence")).toBeTruthy();
  expect(screen.queryByText("action")).toBeNull();
});
it("summarizes experimental outcomes and evaluation arms without asserting scientific validation", () => {
  const { rerender } = render(
    <NodeStory
      nodeId="experiment"
      direction="output"
      value={[
        { outcome: "support", phase: "exploration", seed_ids: [0, 1] },
        { outcome: "refute", phase: "exploration", seed_ids: [0, 1] },
        { outcome: "inconclusive", phase: "exploration", seed_ids: [0, 1] },
      ]}
    />,
  );
  expect(screen.getByText("支持 1")).toBeTruthy();
  expect(screen.getByText("反驳 1")).toBeTruthy();
  expect(screen.getByText("未决 1")).toBeTruthy();
  expect(screen.getByText(/探索结果不等同于独立确认通过/)).toBeTruthy();
  rerender(
    <NodeStory
      nodeId="evaluate"
      direction="output"
      value={{
        scores: {
          clean: { correct: 0, total: 1 },
          current: { correct: 1, total: 1, covered_questions: 0, helpful_changes: 1, harmful_changes: 0 },
        },
        answers: { hidden: "RAW" },
        binding: { hash: "SECRET" },
      }}
    />,
  );
  expect(screen.getByText("无知识条件")).toBeTruthy();
  expect(screen.getByText("当前知识条件")).toBeTruthy();
  expect(screen.getByText(/答错变答对 1 题，答对变答错 0 题/)).toBeTruthy();
  expect(screen.getByText(/分数差异不能视为 KB 收益/)).toBeTruthy();
  expect(screen.getByText("0 / 1")).toBeTruthy();
  expect(screen.queryByText("SECRET")).toBeNull();
});
it("provides honest unavailable views for absent or unknown shapes rather than recursive technical keys", () => {
  const { rerender } = render(
    <NodeStory nodeId="reveal" direction="output" value={undefined} />,
  );
  expect(screen.getByText(/实际输出未提供/)).toBeTruthy();
  rerender(
    <NodeStory
      nodeId="unknown"
      direction="output"
      value={{ raw: { huge: [1, 2, 3] }, source_hashes: { SECRET: "hash" } }}
    />,
  );
  expect(screen.getByText(/此产物尚无可读摘要/)).toBeTruthy();
  expect(screen.queryByText("source_hashes")).toBeNull();
});

it("reads actual discoverer episodes and retains their same-episode committed feedback comparison", () => {
  const episode = {
    question,
    answer: { valid: true, ranking: ["B", "A", "C"] },
    feedback,
  };
  render(
    <NodeStory
      nodeId="discoverer"
      direction="input"
      value={{
        prompt: `Instruction\n\nDATA:\n${JSON.stringify({ episodes: [episode] })}`,
      }}
    />,
  );
  expect(screen.getByText("正确选项 C")).toBeTruthy();
  expect(screen.getByText("本轮提交 B")).toBeTruthy();
  expect(screen.getByRole("img", { name: /训练曲线/ })).toBeTruthy();
  expect(screen.queryByText(/此输入尚无可读摘要/)).toBeNull();
});
it("does not compare conflicting correct answers or infer a winner from metric values", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{
        [question.id]: {
          ...feedback,
          correct_letter: "A",
          reveal: { ...feedback.reveal, correctLetter: "B" },
        },
      }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(
    screen.getByText("正确答案来源冲突，未作提交一致性判断。"),
  ).toBeTruthy();
  expect(screen.queryByText("正确选项 A")).toBeNull();
  expect(screen.queryByText("提交答案与正确选项不同")).toBeNull();
});
it("retains conflicting candidate mappings as unavailable even after a later duplicate row and skips ambiguous curves", () => {
  const conflict = {
    ...feedback,
    reveal: {
      ...feedback.reveal,
      ranked: [
        {
          candidateId: "candidate-A",
          letter: "B",
          metric: "test_ce",
          mean: 3.4,
        },
        {
          candidateId: "candidate-A",
          letter: "A",
          metric: "test_ce",
          mean: 3.4,
        },
      ],
      curves: [
        {
          candidateId: "candidate-A",
          letter: "A",
          samples: [32, 64],
          mean: [3.5, 3.4],
        },
      ],
    },
  };
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: conflict }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(screen.getByText(/candidate-A（选项映射未提供）/)).toBeTruthy();
  expect(screen.queryByRole("img", { name: /训练曲线/ })).toBeNull();
  expect(screen.getByText(/曲线选项或指标关系存在冲突/)).toBeTruthy();
});
it("does not prefer a feedback direction over a contradictory public protocol", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: { ...feedback, higher_is_better: true } }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(screen.getByText(/指标方向冲突/)).toBeTruthy();
  expect(screen.queryByText(/反馈说明：指标越高越好/)).toBeNull();
});
it("does not draw a negative standard-deviation uncertainty band", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{
        [question.id]: {
          ...feedback,
          reveal: {
            ...feedback.reveal,
            curves: [
              {
                letter: "A",
                samples: [32, 64],
                mean: [3.5, 3.4],
                std: [-0.1, -0.2],
              },
            ],
          },
        },
      }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(
    screen.getByRole("img", { name: /训练曲线/ }).querySelector("polygon"),
  ).toBeNull();
  expect(screen.queryByText(/半透明区域为已记录/)).toBeNull();
});

it("explains the leading mean gap and stored deviations without claiming significance from summaries", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: feedback }}
      run={run}
      roundIndex={1}
    />,
  );
  const card = screen.getByRole("region", { name: "差距与重复训练波动" });
  expect(within(card).getByText("均值差距 0.1")).toBeTruthy();
  expect(card.textContent).toContain("C 的标准差 0.008");
  expect(card.textContent).toContain("B 的标准差 0.014");
  expect(card.textContent).toContain("不能据此声称统计显著");
  expect(card.textContent).toContain("单个因素的因果");
  expect(within(card).queryByText(/逐种子对照/)).toBeNull();
});
function repeatedFeedback() {
  const seed_results = (values: number[]) =>
    values.map((value, seed) => ({
      seed,
      failed: false,
      final_test_ce: value,
    }));
  return {
    ...feedback,
    candidate_metrics: {
      ...feedback.candidate_metrics,
      "candidate-C": {
        ...feedback.candidate_metrics["candidate-C"],
        n_seeds: 3,
        seed_results: seed_results([2.93, 2.94, 2.95]),
      },
      "candidate-B": {
        ...feedback.candidate_metrics["candidate-B"],
        n_seeds: 3,
        seed_results: seed_results([3.02, 3.04, 3.06]),
      },
    },
  };
}
it("uses only complete same-metric seed records to describe ranges and matching-number comparisons", () => {
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: repeatedFeedback() }}
      run={run}
      roundIndex={1}
    />,
  );
  const card = screen.getByRole("region", { name: "差距与重复训练波动" });
  expect(card.textContent).toContain("C：2.93–2.95");
  expect(card.textContent).toContain("B：3.02–3.06");
  expect(card.textContent).toContain("C 优于 B 3 / 3");
  expect(card.textContent).toContain("并列 0");
  expect(card.textContent).toContain("不是显著性检验");
  expect(card.textContent).not.toContain("p 值");
});
it("does not fabricate a seed win count when seed identities, counts, or failure flags are unreliable", () => {
  const modified = repeatedFeedback();
  modified.candidate_metrics["candidate-B"].seed_results[0].seed = 9;
  const { rerender } = render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: modified }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(
    screen.getByRole("region", { name: "差距与重复训练波动" }).textContent,
  ).not.toContain("C 优于 B ");
  const failed = repeatedFeedback();
  failed.candidate_metrics["candidate-C"].seed_results[0].failed = true;
  rerender(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: failed }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(
    screen.getByRole("region", { name: "差距与重复训练波动" }).textContent,
  ).not.toContain("C 优于 B ");
  expect(
    screen.getByRole("region", { name: "差距与重复训练波动" }).textContent,
  ).not.toContain("C：2.93");
  const mismatch = repeatedFeedback();
  mismatch.candidate_metrics["candidate-C"].n_seeds = 4;
  rerender(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: mismatch }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(screen.queryByText("查看逐次训练对照")).toBeNull();
});
it("suppresses top-two interpretation when metric direction is contradictory or metrics differ", () => {
  const { rerender } = render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: { ...feedback, higher_is_better: true } }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(
    screen.queryByRole("region", { name: "差距与重复训练波动" }),
  ).toBeNull();
  const mixed = {
    ...feedback,
    candidate_metrics: {
      ...feedback.candidate_metrics,
      "candidate-B": {
        selection_metric: "different_metric",
        mean_different_metric: 1,
        std_different_metric: 0.1,
        n_seeds: 10,
      },
    },
    reveal: {
      ...feedback.reveal,
      ranked: feedback.reveal.ranked.filter((r) => r.letter !== "B"),
    },
  };
  rerender(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{ [question.id]: mixed }}
      run={run}
      roundIndex={1}
    />,
  );
  expect(
    screen.queryByRole("region", { name: "差距与重复训练波动" }),
  ).toBeNull();
});

it("reads compact candidate metric aliases and explicit letters without requiring curves or ranked files", () => {
  const original = repeatedFeedback();
  const metrics = Object.fromEntries(
    Object.entries(original.candidate_metrics).map(([id, s]) => [
      id,
      {
        selection_metric: s.selection_metric,
        letter: id.slice(-1),
        mean: s.mean_test_ce,
        std: s.std_test_ce,
        n_seeds: s.n_seeds,
        ...("seed_results" in s ? { seed_results: s.seed_results } : {}),
      },
    ]),
  );
  render(
    <NodeStory
      nodeId="reveal"
      direction="output"
      value={{
        correct_letter: "C",
        selection_metric: "test_ce",
        higher_is_better: false,
        candidate_metrics: metrics,
      }}
    />,
  );
  const card = screen.getByRole("region", { name: "差距与重复训练波动" });
  expect(card.textContent).toContain("均值差距 0.1");
  expect(card.textContent).toContain("C 最差一次仍优于 B 最好一次");
  expect(screen.getByText("查看逐次训练对照").closest("details")?.open).toBe(
    false,
  );
  expect(screen.getByText(/本次反馈未记录训练曲线/)).toBeTruthy();
});
it('labels empirical evaluation arms as unverified memory rather than formal KB',()=>{
 render(<NodeStory nodeId="evaluate" direction="output" value={{scores:{experience_examples:{correct:1,total:2,covered_questions:2},experience_lessons:{correct:1,total:2},experience_combined:{correct:2,total:2}}}} run={{id:'r',kind:'workflow',created_at:1,status:'complete',config:{}}}/>);
 expect(screen.getByText('经验案例 · 未验证')).toBeTruthy();expect(screen.getByText('经验规律 · 未验证')).toBeTruthy();expect(screen.getByText('案例与规律 · 未验证')).toBeTruthy();
});

it('renders extracted experience and its provenance without treating it as verified science',()=>{
 const value={version:'v2',parent_version:'v1',scientific_status:'unverified',lessons:[{id:'lesson-1',revision:2,text:'有限预算下比较优化难度',conditions:['相同训练预算'],exceptions:['更长训练尚未检验'],source_episode_ids:['episode-1'],reason:'本轮反馈修订条件'}]};
 render(<NodeStory nodeId="experience_save" direction="output" value={value} run={run} roundIndex={2}/>);
 expect(screen.getByText('有限预算下比较优化难度')).toBeTruthy();
 expect(screen.getByText('相同训练预算')).toBeTruthy();
 expect(screen.getByText('更长训练尚未检验')).toBeTruthy();
 expect(screen.getByText(/待验证经验/)).toBeTruthy();
 expect(screen.getByText(/episode-1/)).toBeTruthy();
});
it('summarizes a basic round with saved experience instead of scientific experiment counters',()=>{
 render(<NodeStory nodeId="loop" direction="output" run={run} value={{round:1,practice:{kind:'same_question_practice'},answers:{q:{}},evidence_count:0,candidates:[],experience:{after:'v2',before:'v1',after_snapshot:{lessons:[{id:'l1',text:'本轮形成的经验'}]}}}}/>);
 expect(screen.getByText('本轮形成的经验')).toBeTruthy();
 expect(screen.getByText(/同题复盘/)).toBeTruthy();
 expect(screen.queryByText(/条实验记录/)).toBeNull();
});

const carriedLesson = {
  id: 'L-long-internal-id', revision: 1, text: '深层模型在这个预算下可能更合适。',
  conditions: ['小学习率、固定训练预算'], exceptions: ['仅在这道题观察到'],
  source_episode_ids: ['E-first-round'], scientific_status: 'unverified', status: 'active',
};
const priorEpisode = {
  id: 'E-first-round', round: 1, question,
  answer: { ranking: ['B', 'A', 'C'], rationale: '先前误判了优化速度。' },
  feedback: { correct_letter: 'C' },
};
it('shows selected initial experience separately without confusing foreign episode IDs with this run',()=>{
 render(<NodeStory nodeId="solver" direction="input" roundIndex={1}
  run={{...run,config:{initial_kb:{name:'前次回归学习',snapshot:{episodes:[priorEpisode]}}},node_observations:[{node_id:'experience_save',round_index:0,availability:'available',output:{episodes:[{...priorEpisode,round:99}]}}]}}
  value={{question,initial_experience:{lessons:[carriedLesson],examples:[],version:'chosen-version'},experience:{lessons:[],examples:[]}}}/>);
 expect(screen.getByText('来自起始 KB 的经验')).toBeTruthy();
 expect(screen.getByText(carriedLesson.text)).toBeTruthy();
 expect(screen.getByText('起始 KB · 第 1 轮 · 本题练习')).toBeTruthy();
 expect(screen.queryByText(/第 99 轮/)).toBeNull();
 expect(screen.queryByText('当时的正确选项：C')).toBeNull();
});
it('shows the lesson actually sent on a retry even when formal knowledge is empty', () => {
  render(<NodeStory nodeId="solver" direction="input" roundIndex={2}
    run={{...run, node_observations: [{node_id:'experience_save',round_index:1,availability:'available',output:{episodes:[priorEpisode]}}]}}
    value={{prompt:`Role\n\nDATA:\n${JSON.stringify({question,knowledge:[],experience:{practice:'same_question_practice',lessons:[carriedLesson],examples:[],version:'private-version',omitted:{examples:1,lessons:0}}})}`}}/>);
  expect(screen.getByText('本次带入的经验')).toBeTruthy();
  expect(screen.getByText('已带入 1 条经验规律 · 0 个历史案例')).toBeTruthy();
  expect(screen.getByText(carriedLesson.text)).toBeTruthy();
  expect(screen.getByText(carriedLesson.conditions[0])).toBeTruthy();
  expect(screen.getByText(carriedLesson.exceptions[0])).toBeTruthy();
  expect(screen.getByText('第 1 轮 · 本题练习')).toBeTruthy();
  expect(screen.getByText(/为控制输入长度，未带入 1 个历史案例/)).toBeTruthy();
  expect(screen.getByText(/尚未通过独立验证/)).toBeTruthy();
  expect(screen.queryByText('本次没有提供知识条目')).toBeNull();
  expect(screen.queryByText('本次实际请求没有包含经验条目。')).toBeNull();
});
it('renders only sent experience and distinguishes an empty first request from a previous snapshot', () => {
  render(<NodeStory nodeId="solver" direction="input" roundIndex={1} run={{...run,node_observations:[{node_id:'experience_save',round_index:2,availability:'available',output:{lessons:[carriedLesson]}}]}}
    value={{question,knowledge:[],experience:{lessons:[],examples:[],omitted:{examples:0,lessons:0}}}}/>);
  expect(screen.getByText('本次实际请求没有包含经验条目。')).toBeTruthy();
  expect(screen.queryByText(carriedLesson.text)).toBeNull();
});
it('shows actual historical examples as readable answer and feedback cards', () => {
  render(<NodeStory nodeId="solver" direction="input" value={{question,experience:{lessons:[],examples:[priorEpisode]}}}/>);
  expect(screen.getByText('已带入 0 条经验规律 · 1 个历史案例')).toBeTruthy();
  expect(screen.getByText('历史案例 1 · 第 1 轮')).toBeTruthy();
  expect(screen.getByText('先前误判了优化速度。')).toBeTruthy();
  expect(screen.getByText('当时的正确选项：C')).toBeTruthy();
});
it('does not invent source round details that are absent from stored observations', () => {
  render(<NodeStory nodeId="solver" direction="input" roundIndex={3}
    value={{experience:{lessons:[carriedLesson],examples:[]}}}/>);
  expect(screen.getByText('1 条来源记录 · 轮次信息未提供')).toBeTruthy();
  expect(screen.queryByText(/第 2 轮/)).toBeNull();
  expect(screen.queryByText(/尚无可读摘要/)).toBeNull();
});
it('reports budget omissions and retrieval exclusions without saying no experience exists', () => {
  render(<NodeStory nodeId="solver" direction="input" value={{knowledge:[],experience:{lessons:[],examples:[],omitted:{lessons:2,examples:1},excluded:{lessons_with_excluded_sources:1,related_or_other_family_examples:2}}}}/>);
  expect(screen.getByText(/为控制输入长度，未带入 1 个历史案例、2 条经验规律/)).toBeTruthy();
  expect(screen.getByText(/有 2 个案例与 1 条经验规律未通过本次检索条件/)).toBeTruthy();
});
it('keeps formal and empirical counts distinct for evaluation receipts', () => {
 render(<NodeStory nodeId="evaluate" direction="output" value={{ranking:['A','B'],knowledge_count:3,formal_knowledge_count:1,experience_count:2}}/>);
 expect(screen.getByText('正式知识 1 条')).toBeTruthy();
 expect(screen.getByText('带入经验 2 条')).toBeTruthy();
});
it('uses readable lesson headings and preserves technical identifiers in a disclosure', () => {
 render(<NodeStory nodeId="experience_save" direction="output" roundIndex={1} value={{version:'private-version',parent_version:'private-parent',lessons:[carriedLesson],episodes:[priorEpisode]}}/>);
 expect(screen.getByText('经验 1 · 修订 1')).toBeTruthy();
 expect(screen.getByText('第 1 轮 · 二元序列建模')).toBeTruthy();
 expect(screen.getByText('经验版本标识').closest('details')?.open).toBe(false);
 expect(screen.getByText('经验编号：L-long-internal-id').closest('details')?.open).toBe(false);
});
