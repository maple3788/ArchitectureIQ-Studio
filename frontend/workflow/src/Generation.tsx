import { runLabel } from "./displayNames";
import { useEffect, useState } from "react";
import { ArrowRight, FileCode2, FlaskConical, Play } from "lucide-react";
import { api, items } from "./api";
import { formatTimestamp } from "./time";
import {
  Card,
  Empty,
  ErrorBox,
  Field,
  JsonView,
  Loading,
  Status,
  useResource,
} from "./ui";
import type { Json, List, Run } from "./types";
import type { Action } from "./Questions";
export function Generation({
  capabilities,
  version,
  act,
  executionEnabled,
  onRun,
}: {
  capabilities?: Json;
  version: number;
  act: Action;
  executionEnabled: boolean;
  onRun: (id: string) => void;
}) {
  const profiles: any[] = capabilities?.profiles || [];
  const [profile, setProfile] = useState("");
  const [family, setFamily] = useState("");
  const [options, setOptions] = useState("{}");
  const [generationMode,setGenerationMode]=useState("single");
  const [split,setSplit]=useState("discovery");
  const [factor,setFactor]=useState("");
  const [originalValue,setOriginalValue]=useState("");
  const [counterValue,setCounterValue]=useState("");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [vary, setVary] = useState<string[]>(["model"]);
  const [form, setForm] = useState({
    seed: 1,
    candidate_count: 6,
    budget: 0,
    n_seeds: 2,
    num_questions: 3,
    num_choices: 3,
    question_type: "",
  });
  const [error, setError] = useState("");
  const [preflight, setPreflight] = useState<{
    signature: string;
    normalized: Json;
    submissionKey: string;
  }>();
  const signature = JSON.stringify({
    generationMode, split, factor, originalValue, counterValue,
    profile,
    family,
    options,
    counts,
    vary,
    form,
  });
  const normalized =
    preflight?.signature === signature ? preflight.normalized : undefined;
  const runs = useResource<List<Run>>("/runs", version, 5000);
  const chosen = profiles.find((p) => p.name === profile);
  const families: any[] = chosen?.families || [];
  const current = families.find((f) => f.name === family);
  const compatible: string[] = current?.model_types || [];
  const interventions: any[] = current?.data_interventions || [];
  const chooseFactor = (value:string) => {
    const config=interventions.find(i=>i.factor===value);
    setFactor(value);setOriginalValue(JSON.stringify(config?.original_value)??"");setCounterValue(JSON.stringify(config?.counterfactual_value)??"");
  };
  useEffect(()=>{chooseFactor(interventions[0]?.factor || "");},[family,profile]);
  const budgets: number[] = chosen?.budgets || [];
  useEffect(() => {
    if (profiles.length && !profile)
      setProfile(
        profiles.find((p) => p.name === "v1.5")?.name || profiles[0].name,
      );
  }, [capabilities]);
  useEffect(() => {
    if (chosen) {
      setFamily(chosen.families?.[0]?.name || "");
      setForm((f) => ({
        ...f,
        budget: chosen.budgets?.[0] || 0,
        n_seeds: chosen.n_seeds || 2,
        num_choices: chosen.num_choices || 3,
      }));
      setCounts({});
    }
  }, [profile]);
  useEffect(() => {
    setOptions("{}");
    setCounts({});
  }, [family]);
  const request = () => {
    let family_options;
    try {
      family_options = JSON.parse(options);
    } catch {
      throw new Error("家族参数必须是合法 JSON。");
    }
    if (
      !family_options ||
      typeof family_options !== "object" ||
      Array.isArray(family_options)
    )
      throw new Error("家族参数必须为 JSON 对象。");
    if (!profile || !family || !form.budget || !vary.length)
      throw new Error("请选择 Profile、Family、预算与变化轴。");
    let intervention;
    if(generationMode === "paired") {
      if(!interventions.some(i=>i.factor===factor))throw Error("当前数据家族尚不支持受控题对生成，请选择已登记因素的家族。");
      try {intervention={factor,original_value:JSON.parse(originalValue),counterfactual_value:JSON.parse(counterValue)};}
      catch {throw Error("因素值需要合法的数字或区间，例如 1.4 或 [0, 1]。");}
    }
    return {
      mode:generationMode, split, ...(intervention?{intervention}:{}),
      profile,
      family,
      seed: form.seed,
      family_options,
      candidate_count: form.candidate_count,
      model_type_counts: Object.keys(counts).length
        ? Object.fromEntries(Object.entries(counts).filter(([, n]) => n > 0))
        : undefined,
      vary,
      budget: form.budget,
      n_seeds: form.n_seeds,
      num_questions: form.num_questions,
      num_choices: form.num_choices,
      question_type: form.question_type || undefined,
    };
  };
  const preview = async () => {
    setError("");
    setPreflight(undefined);
    const frozenSignature = signature;
    const result = await act(() => api("/generations/preview", request()));
    if (result)
      setPreflight({
        signature: frozenSignature,
        normalized: result,
        submissionKey: crypto.randomUUID(),
      });
  };
  const submit = async () => {
    setError("");
    if (!normalized) {
      setError("请先完成服务器预检并查看完整批次成本。");
      return;
    }
    const result = await act(
      () =>
        api("/generations", normalized, undefined, {
          "Idempotency-Key": preflight!.submissionKey,
        }),
      "生成任务已提交",
    );
    if (result) onRun(result.id);
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">CANONICAL GENERATION PIPELINE</span>
          <h1>从规范，生成新证据。</h1>
          <p>沿用标准数据合成、候选训练与 GT 流水线，成功题目自动进入题库。</p>
        </div>
        <span className="pill teal-pill">
          <FlaskConical size={14} />
          真实代码执行
        </span>
      </div>
      <div className="generation-grid">
        <Card
          title="新建生成任务"
          subtitle="选项来自服务器 registry 与 active profile。"
        >
          <ErrorBox error={error} />
          {!profiles.length ? (
            <Empty title="尚未取得生成能力清单">
              连接 API 后选择真实支持的家族和模型类型。
            </Empty>
          ) : (
            <>
              <div className="form-grid">
                <Field label="生成单位"><select value={generationMode} onChange={e=>setGenerationMode(e.target.value)}><option value="single">单道题目</option><option value="paired">题目对 · 正常题 + DataFlip</option></select></Field>
                <Field label="题目用途" hint="生成前固定分区；研究与独立评测不混用。"><select value={split} onChange={e=>setSplit(e.target.value)}><option value="discovery">研究 · discovery</option><option value="development">独立开发评测 · development</option><option value="final">独立最终盲测 · final</option></select></Field>
                <Field label="Profile">
                  <select
                    value={profile}
                    onChange={(e) => setProfile(e.target.value)}
                  >
                    {profiles.map((p) => (
                      <option key={p.name}>{p.name}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Dataset family">
                  <select
                    value={family}
                    onChange={(e) => setFamily(e.target.value)}
                  >
                    {families.map((f) => (
                      <option key={f.name}>{f.name}</option>
                    ))}
                  </select>
                </Field>
                <Field label="数据 seed">
                  <input
                    type="number"
                    min={0}
                    value={form.seed}
                    onChange={(e) =>
                      setForm({ ...form, seed: Number(e.target.value) })
                    }
                  />
                </Field>
                <Field label="候选数量">
                  <input
                    type="number"
                    min={2}
                    value={form.candidate_count}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        candidate_count: Number(e.target.value),
                      })
                    }
                  />
                </Field>
                <Field label="训练预算 · samples seen">
                  <select
                    value={form.budget}
                    onChange={(e) =>
                      setForm({ ...form, budget: Number(e.target.value) })
                    }
                  >
                    {budgets.map((b) => (
                      <option key={b} value={b}>
                        {b.toLocaleString()}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="GT seeds">
                  <input
                    type="number"
                    min={1}
                    value={form.n_seeds}
                    onChange={(e) =>
                      setForm({ ...form, n_seeds: Number(e.target.value) })
                    }
                  />
                </Field>
                <Field label={generationMode === "paired" ? "请求题对数量" : "请求题目数量"}>
                  <input
                    type="number"
                    min={1}
                    aria-label={generationMode === "paired" ? "请求题对数量" : "请求题目数量"}
                    value={form.num_questions}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        num_questions: Number(e.target.value),
                      })
                    }
                  />
                </Field>
                <Field label="每题选项数量">
                  <input
                    type="number"
                    min={2}
                    value={form.num_choices}
                    onChange={(e) =>
                      setForm({ ...form, num_choices: Number(e.target.value) })
                    }
                  />
                </Field>
              </div>
              {generationMode === "paired" && <section className="pair-protocol-note">
                <h3>控制一个数据因素</h3>
                <p>每对使用相同候选配置、训练预算和种子，只修改下方因素。双侧执行真实训练；同时保留赢家改变和不变的有效题对。</p>
                {interventions.length ? <><Field label="干预因素"><select value={factor} onChange={e=>chooseFactor(e.target.value)}>{interventions.map(i=><option key={i.factor} value={i.factor}>{i.label || i.factor}</option>)}</select></Field>
                <div className="form-grid"><Field label="正常题因素值"><input value={originalValue} onChange={e=>setOriginalValue(e.target.value)}/></Field><Field label="DataFlip 因素值"><input value={counterValue} onChange={e=>setCounterValue(e.target.value)}/></Field></div></>
                : <p role="alert">此家族尚无已验证的受控干预，请更换数据家族。当前支持回归数据的 domain 与二元序列的 alpha，以服务器清单为准。</p>}
              </section>}
              <Field label="变化轴">
                <div className="inline-checks">
                  {["model", "optimizer", "loss"].map((axis) => (
                    <label className="checkbox-label" key={axis}>
                      <input
                        type="checkbox"
                        checked={vary.includes(axis)}
                        onChange={(e) =>
                          setVary(
                            e.target.checked
                              ? [...vary, axis]
                              : vary.filter((a) => a !== axis),
                          )
                        }
                      />
                      {axis}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="题型约束">
                <select
                  value={form.question_type}
                  onChange={(e) =>
                    setForm({ ...form, question_type: e.target.value })
                  }
                >
                  <option value="">由候选自动推断</option>
                  {[
                    "architecture_only",
                    "optimizer_only",
                    "loss_only",
                    "mixed",
                  ].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </Field>
              <h3>题内候选模型类型</h3>
              <p className="muted">
                留空由 Profile 抽样；填写各类型数量时，总和须等于候选数量。
              </p>
              <div className="form-grid">
                {compatible.map((type) => (
                  <Field key={type} label={type}>
                    <input
                      type="number"
                      min={0}
                      placeholder="自动"
                      value={counts[type] ?? ""}
                      onChange={(e) => {
                        const next = { ...counts };
                        if (e.target.value === "") delete next[type];
                        else next[type] = Number(e.target.value);
                        setCounts(next);
                      }}
                    />
                  </Field>
                ))}
              </div>
              <Field
                label="Family 参数（JSON）"
                hint={
                  (current?.options || []).length
                    ? "支持：" + current.options.join(", ")
                    : "仅接受此 Family 已登记的参数。"
                }
              >
                <textarea
                  className="mono"
                  rows={4}
                  value={options}
                  onChange={(e) => setOptions(e.target.value)}
                />
              </Field>
              <details>
                <summary>查看当前 Profile 的优化器、loss 与家族配置</summary>
                <JsonView
                  value={{
                    optimizers: chosen?.pools?.optimizers,
                    losses: current?.losses,
                    config: current?.config,
                    pools: chosen?.pools,
                  }}
                />
              </details>
              <div className="actions">
                <button onClick={() => void preview()}>
                  <FileCode2 size={16} />
                  冻结 spec 预览
                </button>
                <button
                  className="primary"
                  disabled={
                    !executionEnabled || !profile || !family || !normalized
                  }
                  onClick={() => void submit()}
                >
                  <Play size={15} />
                  提交生成任务
                </button>
              </div>
              {!normalized && (
                <p className="muted">
                  提交前需完成服务器预检，确认数据实例拆分、真实训练运行数与总样本预算。
                </p>
              )}
              {normalized && (
                <Card
                  title="服务器冻结 spec"
                  subtitle="归一化计划 · 修改任何生成设置后须重新预检"
                >
                  {normalized.mode === "paired" && <p>{normalized.pair_count} 对 · {normalized.requested_question_count} 道题 · 双侧共 {normalized.candidate_seed_runs} 次候选训练。只收录两侧均通过显著性筛选的题对，实际数量可能少于请求。</p>}
                  <details><summary>查看完整冻结规格与成本</summary><JsonView value={normalized} /></details>
                </Card>
              )}
            </>
          )}
        </Card>
        <div>
          <Card className="pipeline-card" title="执行路径">
            <div className="pipeline-step">
              <i>1</i>
              <div>
                <b>数据实例</b>
                <small>spec → synthesize.py → 执行合成</small>
              </div>
            </div>
            <div className="pipeline-step">
              <i>2</i>
              <div>
                <b>候选与 ground truth</b>
                <small>生成代码 → 标准 runner → summary</small>
              </div>
            </div>
            <div className="pipeline-step">
              <i>3</i>
              <div>
                <b>显著性筛选</b>
                <small>按存储 GT 选择题目与答案</small>
              </div>
            </div>
            <div className="pipeline-step">
              <i>4</i>
              <div>
                <b>导出与入库</b>
                <small>公开题面与来源身份自动登记</small>
              </div>
            </div>
          </Card>
          <Card title="预计工作量">
            <strong className="metric teal">
              {normalized?.candidate_seed_runs ?? "—"}
            </strong>
            <p>完整批次 candidate × seed 训练运行</p>
            {normalized ? (
              <>
                <b>{normalized.dataset_count} 个数据实例</b>
                <p className="muted">总 samples seen</p>
                <strong className="metric">
                  {normalized.total_samples_seen?.toLocaleString() ?? "未提供"}
                </strong>
                <span className="metric-label">冻结 Profile hash</span>
                <small className="mono wrap">
                  {normalized.profile_hash ?? "未提供"}
                </small>
                <div className="divider" />
                <h3>数据 seed 与题目拆分</h3>
                <JsonView value={normalized.dataset_plan} />
              </>
            ) : (
              <p className="muted">
                待服务器预检；不使用单数据实例估算冒充完整成本。
              </p>
            )}
            <div className="divider" />
            <p className="muted">
              生成不足时保留实际数量、原因和失败候选，不降低显著性门槛补齐。
            </p>
            {!executionEnabled && (
              <ErrorBox error="当前服务未启用执行，需在指定服务器启动任务。" />
            )}
          </Card>
        </div>
      </div>
      <Card
        title="生成任务"
        subtitle="显示真实阶段、失败和产物；点击任务查看详细事件。"
      >
        <ErrorBox error={runs.error} />
        {runs.loading ? (
          <Loading />
        ) : items(runs.data).filter((r) => r.kind === "generation").length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>阶段</th>
                  <th>创建时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items(runs.data)
                  .filter((r) => r.kind === "generation")
                  .map((r) => (
                    <tr key={r.id}>
                      <td>
                        <button
                          className="row-link"
                          onClick={() => onRun(r.id)}
                        >
                          {runLabel(r)}
                        </button>
                      </td>
                      <td>
                        <Status value={r.status} />
                      </td>
                      <td>{r.progress?.stage || "未提供"}</td>
                      <td>{formatTimestamp(r.created_at)}</td>
                      <td>
                        <button
                          className="icon-button"
                          onClick={() => onRun(r.id)}
                        >
                          <ArrowRight size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="尚无生成任务" />
        )}
      </Card>
    </>
  );
}
