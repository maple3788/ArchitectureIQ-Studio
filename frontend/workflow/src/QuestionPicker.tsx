import {publicRagReady} from './ragTypes';
import { questionLabel, familyLabel } from "./displayNames";
import { useEffect, useRef, useState } from "react";
import {
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
} from "lucide-react";
import { api } from "./api";
import { toggleKeys } from "./state";
import { Empty, ErrorBox, Field, Loading, useResource } from "./ui";
import { QuestionReader } from "./QuestionReader";
import type { Action } from "./Questions";
import type { Json, List, Question, QuestionSet } from "./types";
import "./question-picker.css";

const TYPE_LABELS: Record<string, string> = {
  architecture_only: "架构对比",
  optimizer_only: "优化器对比",
  loss_only: "损失函数对比",
  mixed: "混合对比",
};
export function questionTypeLabel(type: string) {
  return TYPE_LABELS[type] || (type ? `其他题型 · ${type}` : "题型未记录");
}
type PickerQuestion = Question & {
  split?: string;
  kb_ready?: boolean;
  evaluation_ready?: boolean;
};
function selectionIssueFor(
  question: Partial<PickerQuestion> | undefined,
  purpose: "research" | "evaluation" | "rag",
  phase: "development" | "final",
) {
  if (purpose === "rag") return question?.rag_ready === false ? "题目公开输入不可用" : "";
  if (purpose === "evaluation") {
    if (!question?.split) return "此题未记录评测分区，暂不能选用";
    if (question.split !== phase)
      return `此题不属于${phase === "final" ? "最终盲测" : "开发评测"}分区，不能用于本次独立评测`;
    if (question.evaluation_ready === false || question.ready === false)
      return "此题资料尚未满足独立评测要求";
    return "";
  }
  if (!question) return "";
  if (question.split && question.split !== "discovery") {
    if (question.split === "final") return "最终评估集题目不能用于知识学习";
    if (question.split === "development")
      return "开发评估集题目不能用于知识学习";
    return "此题不属于发现集，不能用于知识学习";
  }
  if (question.kb_ready === false)
    return "此题不具备 KB 学习所需的完整公开配置";
  if (question.ready === false) return "题目资料尚未完整，暂不能选用";
  return "";
}
const PAGE_SIZE = 25;
export function QuestionPicker({
  version,
  act,
  questionSetId,
  purpose = "research",
  phase = "final",
  single = false,
  onApply,
  onSelectQuestion,
  onClose,
}: {
  version: number;
  act: Action;
  questionSetId?: string;
  purpose?: "research" | "evaluation" | "rag";
  phase?: "development" | "final";
  single?: boolean;
  onApply?: (set: QuestionSet) => void;
  onSelectQuestion?: (key:string) => void;
  onClose: () => void;
}) {
  const selectionIssue = (q?: Partial<PickerQuestion>) =>
    selectionIssueFor(q, purpose, phase);
  const title =
    purpose === "rag" ? "选择 RAG 题目" : purpose === "evaluation" ? "选择独立评测题目" : "选择工作流题目";
  const dialog = useRef<HTMLElement>(null);
  const detailPanel = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);
  const mounted = useRef(true);
  const [filters, setFilters] = useState({ search: "", type: "", family: "" });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [setName, setSetName] = useState("");
  const [loadedFor, setLoadedFor] = useState<string | undefined | null>(null);
  const [initLoading, setInitLoading] = useState(!!questionSetId);
  const [initError, setInitError] = useState("");
  const [retry, setRetry] = useState(0);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [detailKey, setDetailKey] = useState<string>();
  const [reading, setReading] = useState(false);
  const [selectedView, setSelectedView] = useState(false);
  const [knownQuestions, setKnownQuestions] = useState<
    Record<string, Partial<PickerQuestion>>
  >({});
  const [detailRetry, setDetailRetry] = useState(0);
  const [types, setTypes] = useState(Object.keys(TYPE_LABELS));
  const [initialIssues, setInitialIssues] = useState<Record<string, string>>(
    {},
  );
  const [observedIssues, setObservedIssues] = useState<Record<string, string>>(
    {},
  );
  const query = new URLSearchParams({
    ...filters,
    ...(purpose === "evaluation" ? { split: phase } : single && purpose !== "rag" ? {split:"discovery"} : {}),
    offset: String(offset),
    limit: String(PAGE_SIZE),
  });
  const questions = useResource<List<PickerQuestion>>(
    "/questions?" + query,
    version + reload,
  );
  const detail = useResource<Json>(
    detailKey ? "/questions/" + encodeURIComponent(detailKey) : null,
    version + detailRetry,
  );
  const rows = questions.data?.items || [];
  const activeDetail =
    detail.data &&
    (!detail.data.metadata?.key || detail.data.metadata.key === detailKey)
      ? detail.data
      : undefined;
  const total = questions.data?.total;
  const ready = loadedFor === questionSetId && !initLoading && !initError;
  const issueFor = (key: string) =>
    initialIssues[key] ||
    selectionIssue(rows.find((q) => q.key === key) || knownQuestions[key]) ||
    observedIssues[key] ||
    "";
  const selectableRows = rows.filter((q) => !issueFor(q.key));
  const toggleSelection=(current:string[],keys:string[],checked:boolean)=>(single || purpose === "rag")?(checked?keys.slice(0,1):current.filter(k=>!keys.includes(k))):toggleKeys(current,keys,checked);
  const excludedSelected = selected.filter((key) => !!issueFor(key));
  const change = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setOffset(0);
  };
  useEffect(() => {
    if (reading && detailPanel.current) {
      detailPanel.current.scrollTop = 0;
      detailPanel.current.focus({ preventScroll: true });
    }
  }, [detailKey, reading]);
  const returnToList = () => {
    setReading(false);
    requestAnimationFrame(() =>
      returnFocus.current?.focus({ preventScroll: true }),
    );
  };
  useEffect(() => {
    mounted.current = true;
    const prior = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    return () => {
      mounted.current = false;
      prior?.focus();
    };
  }, []);
  useEffect(() => {
    let active = true;
    setLoadedFor(null);
    setInitError("");
    setInitLoading(!!questionSetId);
    setSelected([]);
    setSetName("");
    setInitialIssues({});
    setKnownQuestions({});
    if (!questionSetId) {
      setLoadedFor(undefined);
      setInitLoading(false);
      return;
    }
    void api<QuestionSet>("/question-sets/" + encodeURIComponent(questionSetId))
      .then((set) => {
        if (!active) return;
        if (
          !Array.isArray(set.keys) ||
          !set.keys.every((key) => typeof key === "string" && key.length > 0) ||
          new Set(set.keys).size !== set.keys.length
        )
          throw Error("原题集未返回完整题目版本 keys，暂不能应用新选择。");
        setInitialIssues(
          Object.fromEntries(
            (set.questions || [])
              .map((question) => [
                question.key || question.id,
                purpose === "evaluation" && !question.split
                  ? ""
                  : selectionIssue(question),
              ])
              .filter(([key, issue]) => set.keys!.includes(key) && !!issue),
          ),
        );
        setSelected([...set.keys]);
        setKnownQuestions((current) => ({
          ...current,
          ...Object.fromEntries(
            (set.questions || [])
              .filter((question) =>
                set.keys!.includes(question.key || question.id),
              )
              .map((question) => {
                const key = question.key || question.id;
                return [
                  key,
                  {
                    ...question,
                    key,
                    id: String(question.id || key).split("@")[0],
                  },
                ];
              }),
          ),
        }));
        setSetName(set.name || "");
        setLoadedFor(questionSetId);
      })
      .catch((e) => {
        if (active) setInitError((e as Error).message);
      })
      .finally(() => {
        if (active) setInitLoading(false);
      });
    return () => {
      active = false;
    };
  }, [questionSetId, retry, purpose, phase]);
  useEffect(() => {
    if (!questions.data) return;
    setKnownQuestions((current) => ({
      ...current,
      ...Object.fromEntries(
        questions.data!.items.map((question) => [question.key, question]),
      ),
    }));
    const found = questions.data.items.map((q) => q.type).filter(Boolean);
    setObservedIssues((current) => {
      const next = { ...current };
      for (const question of questions.data!.items) {
        const issue = selectionIssue(question);
        if (issue) next[question.key] = issue;
        else delete next[question.key];
      }
      return next;
    });
    setTypes((current) =>
      found.some((type) => !current.includes(type))
        ? [...new Set([...current, ...found])]
        : current,
    );
  }, [questions.data, purpose, phase]);
  useEffect(() => {
    if (!detailKey || detail.loading) return;
    if (detail.error) {
      setObservedIssues((current) => ({
        ...current,
        [detailKey]: "题目资料暂不可用，请重试读取或移除。",
      }));
      return;
    }
    if (!detail.data) return;
    const metadata = detail.data.metadata
      ? {
          ...knownQuestions[detailKey],
          ...detail.data.metadata,
          split:
            detail.data.metadata.split ??
            detail.data.public?.split ??
            knownQuestions[detailKey]?.split,
        }
      : undefined;
    if (metadata?.key && metadata.key !== detailKey) return;
    if (metadata)
      setKnownQuestions((current) => ({
        ...current,
        [detailKey]: { ...current[detailKey], ...metadata, key: detailKey },
      }));
    setObservedIssues((current) => {
      const next = { ...current };
      const issue = selectionIssue(metadata);
      if (issue) next[detailKey] = issue;
      else if (
        (metadata &&
          ["ready", "kb_ready", "split"].some((field) => field in metadata)) ||
        next[detailKey] === "题目资料暂不可用，请重试读取或移除。"
      )
        delete next[detailKey];
      return next;
    });
  }, [detailKey, detail.loading, detail.error, detail.data, purpose, phase]);
  const apply = async () => {
    if (!ready || !selected.length || saving || excludedSelected.length) return;
    setSaving(true);
    setError("");
    if (purpose === "rag") {
      try {
        const key = selected[0];
        const record = await api<Json>("/questions/" + encodeURIComponent(key));
        if (record.metadata?.rag_ready === false || !publicRagReady(record)) throw Error("题目公开输入不可用");
        if (mounted.current) onSelectQuestion?.(key);
      } catch (e) { if (mounted.current) setError((e as Error).message); }
      finally { if (mounted.current) setSaving(false); }
      return;
    }
    try {
      const result = await act(async () => {
        try {
          return await api<QuestionSet>("/question-sets", {
            name:
              setName.trim() ||
              `${purpose === "evaluation" ? "独立评测题集" : "工作流题集"} · ${selected.length} 题 · ${new Date().toLocaleString("zh-CN")}`,
            keys: [...selected],
          });
        } catch (e) {
          if (mounted.current) setError((e as Error).message);
          throw e;
        }
      }, "题目选择已冻结保存");
      if (result && mounted.current) onApply?.(result);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setSaving(false);
    }
  };
  const detailIssue = detailKey
    ? issueFor(detailKey) ||
      selectionIssue(
        activeDetail?.metadata
          ? {
              ...knownQuestions[detailKey!],
              ...activeDetail.metadata,
              split:
                activeDetail.metadata.split ??
                activeDetail.public?.split ??
                knownQuestions[detailKey!]?.split,
            }
          : knownQuestions[detailKey!],
      )
    : "";
  const detailTitle = questionLabel(activeDetail ?? rows.find(q=>q.key===detailKey));
  return (
    <div className="question-picker-backdrop" onClick={onClose}>
      <section
        ref={dialog}
        className={`question-picker ${reading ? "is-reading" : ""} ${selectedView ? "is-selected-list" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
          if (e.key === "Tab") {
            const controls = dialog.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]',
            );
            if (!controls?.length) return;
            const first = controls[0],
              last = controls[controls.length - 1];
            if (
              e.shiftKey &&
              (document.activeElement === first ||
                document.activeElement === dialog.current)
            ) {
              e.preventDefault();
              last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <header className="question-picker-header">
          <div>
            <span className="eyebrow">QUESTION SELECTION</span>
            <h2>{title}</h2>
            <p>
              {purpose === "evaluation"
                ? `${phase === "final" ? "最终盲测" : "开发评测"}分区 · 只用于解答与验证，不用于知识学习`
                : single ? "选择一道真实题目 · 点击另一题即可替换选择" : "按题型浏览 · 多选跨页保留 · 查看题面再应用"}
            </p>
          </div>
          <button
            className="icon-button"
            aria-label="关闭题目选择器"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        <div className="question-picker-filters">
          <div className="question-picker-search">
            <Search size={17} />
            <input
              aria-label="搜索题目"
              placeholder="搜索题目 ID、数据实例或模型类型"
              value={filters.search}
              onChange={(e) => change("search", e.target.value)}
            />
          </div>
          <select
            aria-label="题型筛选"
            value={filters.type}
            onChange={(e) => change("type", e.target.value)}
          >
            <option value="">全部题型</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {questionTypeLabel(type)}
              </option>
            ))}
          </select>
          <input
            aria-label="数据家族筛选"
            placeholder="数据家族（可选）"
            value={filters.family}
            onChange={(e) => change("family", e.target.value)}
          />
        </div>
        {(initLoading || initError) && (
          <div className="question-picker-initialization">
            {initLoading ? (
              <p role="status">正在读取原题集的全部选题，完成后即可调整。</p>
            ) : (
              <>
                <ErrorBox error={initError} />
                <button onClick={() => setRetry((n) => n + 1)}>
                  重试读取原题集
                </button>
                <p>原选择尚未完整读取，暂不能修改或应用。</p>
              </>
            )}
          </div>
        )}
        <div className="question-picker-body">
          <div className="question-picker-catalog">
            {selectedView ? (
              <>
                <div className="question-picker-list-head">
                  <span>选题清单 · {selected.length} 题</span>
                  <button
                    className="text-button"
                    onClick={() => setSelectedView(false)}
                  >
                    返回题库
                  </button>
                </div>
                <p className="question-picker-selected-note">
                  按下列顺序冻结；此清单包含筛选外及其他页面的全部已选版本。
                </p>
                <div className="question-picker-rows">
                  {selected.length ? (
                    <ol
                      className="question-picker-selected-items"
                      aria-label="已选题目"
                    >
                      {selected.map((key, index) => {
                        const question = knownQuestions[key],
                          issue = issueFor(key);
                        return (
                          <li
                            className={`question-picker-selected-item ${issue ? "has-issue" : ""}`}
                            key={key}
                            data-question-key={key}
                          >
                            <span className="question-picker-selected-order">
                              {index + 1}
                            </span>
                            <button
                              className="question-picker-row-content"
                              aria-label={`查看已选题目 ${key}`}
                              onClick={(event) => {
                                returnFocus.current = event.currentTarget;
                                setDetailKey(key);
                                setReading(true);
                              }}
                            >
                              <strong>
                                {questionLabel(question, selected.indexOf(key) + 1)}
                              </strong>
                              <p>
                                {[
                                  question?.family,
                                  question?.type
                                    ? questionTypeLabel(question.type)
                                    : undefined,
                                ]
                                  .filter(Boolean)
                                  .join(" · ") || "题目配置未加载，点击查看"}
                              </p>
                              <small className="question-picker-selected-key">
                                {key}
                              </small>
                              {issue && (
                                <small className="question-picker-exclusion">
                                  {issue}
                                </small>
                              )}
                            </button>
                            <button
                              className="question-picker-remove"
                              aria-label={`移除已选题目 ${key}`}
                              disabled={!ready || saving}
                              onClick={() =>
                                setSelected((current) =>
                                  current.filter((value) => value !== key),
                                )
                              }
                            >
                              <X size={15} />
                              移除
                            </button>
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <Empty title="还没有选择题目">
                      返回题库勾选题目，再来这里核对。
                    </Empty>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="question-picker-list-head">
                  <span>
                    {questions.loading
                      ? "正在读取题库…"
                      : total === undefined
                        ? "题库暂不可用"
                        : `匹配 ${total.toLocaleString()} 题`}
                  </span>
                  <label>
                    <input
                      type="checkbox"
                      aria-label="选择当前页"
                      disabled={single || purpose === "rag" || !ready || saving || !selectableRows.length}
                      checked={
                        !!selectableRows.length &&
                        selectableRows.every((q) => selected.includes(q.key))
                      }
                      onChange={(e) =>
                        setSelected((current) =>
                          toggleSelection(
                            current,
                            selectableRows.map((q) => q.key),
                            e.target.checked,
                          ),
                        )
                      }
                    />
                    选择本页
                  </label>
                </div>
                <ErrorBox error={questions.error} />
                {questions.error && (
                  <button
                    className="question-picker-retry"
                    onClick={() => setReload((n) => n + 1)}
                  >
                    重新读取题库
                  </button>
                )}
                <div className="question-picker-rows">
                  {questions.loading ? (
                    <Loading />
                  ) : rows.length ? (
                    rows.map((question, index) => (
                      <div
                        className={`question-picker-row ${selected.includes(question.key) ? "chosen" : ""} ${detailKey === question.key ? "previewing" : ""}`}
                        key={question.key}
                      >
                        <input
                          type="checkbox"
                          aria-label={"选择 " + question.id}
                          checked={selected.includes(question.key)}
                          disabled={
                            !ready ||
                            saving ||
                            (!!issueFor(question.key) &&
                              !selected.includes(question.key))
                          }
                          onChange={(e) =>
                            setSelected((current) =>
                              toggleSelection(
                                current,
                                [question.key],
                                e.target.checked,
                              ),
                            )
                          }
                        />
                        <button
                          className="question-picker-row-content"
                          aria-label={"查看题目 " + question.id}
                          aria-pressed={detailKey === question.key}
                          onClick={(event) => {
                            returnFocus.current = event.currentTarget;
                            setDetailKey(question.key);
                            setReading(true);
                          }}
                        >
                          <div>
                            <strong title={question.key}>{familyLabel(question.family)} · 第 {offset + index + 1} 题</strong>
                            <span>{questionTypeLabel(question.type)}</span>
                          </div>
                          <p>
                            {familyLabel(question.family)} ·{" "}
                            {question.choices} 个选项 ·{" "}
                            {(question.model_types || []).join(" / ") ||
                              "模型类型未记录"}
                          </p>
                          <small>
                            {question.profile || "Profile 未记录"} ·{" "}
                            {question.source_count} 个来源
                            {!question.ready ? " · 待补全" : ""}
                          </small>
                          {issueFor(question.key) && (
                            <small className="question-picker-exclusion">
                              {issueFor(question.key)}
                            </small>
                          )}
                        </button>
                        <ChevronRight size={15} aria-hidden="true" />
                      </div>
                    ))
                  ) : !questions.error ? (
                    <Empty title={purpose === "evaluation" && !filters.search && !filters.type && !filters.family ? "这个独立评测分区还没有题目" : "没有匹配的题目"}>
                      {purpose === "evaluation" && !filters.search && !filters.type && !filters.family
                        ? `请先在题库导入已划分为 ${phase} 的独立题包，再来选择。现有研究题不会自动改为评测题；已生成的研究题也不能直接用于最终盲测。`
                        : "调整搜索或题型筛选。已选题目仍会保留。"}
                    </Empty>
                  ) : null}
                </div>
                <div className="question-picker-pagination">
                  <span>
                    {total === undefined
                      ? "—"
                      : total
                        ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} / ${total}`
                        : "0 条记录"}
                  </span>
                  <div>
                    <button
                      aria-label="上一页"
                      className="icon-button"
                      disabled={questions.loading || offset === 0}
                      onClick={() =>
                        setOffset((n) => Math.max(0, n - PAGE_SIZE))
                      }
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span>
                    <button
                      aria-label="下一页"
                      className="icon-button"
                      disabled={
                        questions.loading ||
                        total === undefined ||
                        offset + PAGE_SIZE >= total
                      }
                      onClick={() => setOffset((n) => n + PAGE_SIZE)}
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
          <aside
            ref={detailPanel}
            tabIndex={-1}
            className="question-picker-detail"
            aria-label="题目公开预览"
          >
            {!detailKey ? (
              <Empty title="查看题目，再决定是否选用">
                点击列表中的题目打开完整公开题面。勾选状态始终保留。
              </Empty>
            ) : (
              <>
                <div className="question-picker-reading-toolbar">
                  <button
                    className="question-picker-back"
                    onClick={returnToList}
                  >
                    <ChevronLeft size={16} />
                    {selectedView ? "返回已选题目" : "返回题目列表"}
                  </button>
                  <span className="question-picker-reading-id">
                    {detailTitle}
                  </span>
                  <label className="question-picker-current-choice">
                    <input
                      type="checkbox"
                      aria-label="选用当前题目"
                      checked={selected.includes(detailKey)}
                      disabled={
                        !ready ||
                        saving ||
                        !activeDetail ||
                        (!!detailIssue && !selected.includes(detailKey))
                      }
                      onChange={(event) =>
                        setSelected((current) =>
                          toggleSelection(
                            current,
                            [detailKey],
                            event.target.checked,
                          ),
                        )
                      }
                    />
                    {selected.includes(detailKey) ? "已加入选择" : "加入选择"}
                  </label>
                </div>
                {detailIssue && (
                  <p className="question-picker-exclusion">{detailIssue}</p>
                )}
                <ErrorBox error={detail.error} />
                {detail.error && (
                  <button
                    className="question-picker-retry"
                    onClick={() => setDetailRetry((value) => value + 1)}
                  >
                    重试读取当前题目
                  </button>
                )}
                {detail.loading ? (
                  <Loading />
                ) : activeDetail ? (
                  <QuestionReader key={detailKey} record={activeDetail} />
                ) : null}
              </>
            )}
          </aside>
        </div>
        <footer className="question-picker-footer">
          <div className="question-picker-selection">
            <button
              className="question-picker-selected-toggle"
              aria-label={`查看已选 ${selected.length} 题`}
              aria-pressed={selectedView && !reading}
              disabled={!ready}
              onClick={() => {
                setSelectedView(true);
                setReading(false);
              }}
            >
              <CheckSquare size={17} />
              已选 {selected.length} 题<span>查看与移除</span>
            </button>
            <small>跨筛选与分页保留 · 按选择顺序冻结版本</small>
            <button
              className="text-button"
              disabled={!ready || !selected.length || saving}
              onClick={() => setSelected([])}
            >
              清空选择
            </button>
          </div>
          {purpose !== "rag" && <Field label="题集名称">
            <input
              value={setName}
              disabled={!ready || saving}
              placeholder="可选，应用时自动命名"
              onChange={(e) => setSetName(e.target.value)}
            />
          </Field>}
          {excludedSelected.length > 0 && (
            <div className="question-picker-excluded-selection" role="alert">
              <p>
                已保留 {excludedSelected.length} 道不符合
                {purpose === "evaluation" ? "本次评测" : "知识学习"}
                要求的选题，请核对或移除后应用。
              </p>
              <button
                className="text-button"
                disabled={saving}
                onClick={() =>
                  setSelected((current) =>
                    current.filter((key) => !issueFor(key)),
                  )
                }
              >
                {purpose === "evaluation"
                  ? "移除不可用于本次评测的已选题目"
                  : "移除不可用于学习的已选题目"}
              </button>
            </div>
          )}
          <div className="question-picker-apply">
            <ErrorBox error={error} />
            <button
              className="primary"
              aria-label="应用所选题目"
              disabled={
                !ready ||
                !selected.length ||
                saving ||
                !!excludedSelected.length
              }
              onClick={() => void apply()}
            >
              {saving ? "正在保存…" : "应用所选题目"}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
