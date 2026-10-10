import { questionLabel, familyLabel, typeLabel, readableName } from "./displayNames";
import { useState } from "react";
import {
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  Filter,
  FolderInput,
  Plus,
  Search,
  Upload,
} from "lucide-react";
import { api, items, uploadSource } from "./api";
import { toggleKeys } from "./state";
import {
  Card,
  Drawer,
  Empty,
  ErrorBox,
  Field,
  JsonView,
  Loading,
  Status,
  useResource,
} from "./ui";
import type { Json, List, Question } from "./types";
import { QuestionReader } from "./QuestionReader";
import "./question-picker.css";
export type Action = (
  operation: () => Promise<any>,
  success?: string,
) => Promise<any>;
export function Questions({
  version,
  act,
  onSet,
}: {
  version: number;
  act: Action;
  onSet: (id: string) => void;
}) {
  const [filters, setFilters] = useState({
    search: "",
    family: "",
    type: "",
    source_id: "",
  });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [detail, setDetail] = useState<string>();
  const [sourceOpen, setSourceOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [setName, setSetName] = useState("");
  const [importPath, setImportPath] = useState("");
  const [pairPath, setPairPath] = useState("");
  const [importName, setImportName] = useState("");
  const [report, setReport] = useState<Json>();
  const [sampling, setSampling] = useState({ limit: 50, seed: 0 });
  const query = new URLSearchParams({
    ...filters,
    offset: String(offset),
    limit: "25",
  });
  const questions = useResource<List<Question>>("/questions?" + query, version);
  const sources = useResource<List<Json>>("/sources", version);
  const rows = questions.data?.items || [];
  const total = questions.data?.total || 0;
  const change = (key: string, value: string) => {
    setFilters({ ...filters, [key]: value });
    setOffset(0);
  };
  const save = async (all = false, sample = false) => {
    const result = await act(
      () =>
        api("/question-sets", {
          name: setName || "题集 " + new Date().toLocaleString("zh-CN"),
          ...(all
            ? { filters, ...(sample ? sampling : {}) }
            : { keys: [...selected] }),
        }),
      "题集已冻结保存",
    );
    if (result) {
      onSet(result.id);
      setSaveOpen(false);
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">QUESTION CATALOG</span>
          <h1>每一道题，都有来源。</h1>
          <p>浏览登记题源的全部版本，将选择冻结为可复现的测试题集。</p>
        </div>
        <button onClick={() => setSourceOpen(true)}>
          <FolderInput size={16} />
          管理题源
        </button>
      </div>
      <div className="stat-grid">
        <Card>
          <span className="metric-label">当前筛选</span>
          <strong className="metric">
            {questions.loading ? "—" : total.toLocaleString()}
          </strong>
          <span className="metric-foot">题目版本</span>
        </Card>
        <Card>
          <span className="metric-label">已登记来源</span>
          <strong className="metric">
            {sources.data ? items(sources.data).length : "—"}
          </strong>
          <span className="metric-foot">以实际扫描报告为准</span>
        </Card>
        <Card>
          <span className="metric-label">已选择</span>
          <strong className="metric teal">{selected.length}</strong>
          <span className="metric-foot">跨页保留 · 按所选顺序冻结</span>
        </Card>
      </div>
      <Card className="catalog-card">
        <div className="filterbar">
          <div className="search">
            <Search size={17} />
            <input
              aria-label="搜索题目"
              placeholder="搜索 ID、family、数据实例…"
              value={filters.search}
              onChange={(e) => change("search", e.target.value)}
            />
          </div>
          <input
            aria-label="Family 筛选"
            placeholder="Family"
            value={filters.family}
            onChange={(e) => change("family", e.target.value)}
          />
          <select
            aria-label="题型筛选"
            value={filters.type}
            onChange={(e) => change("type", e.target.value)}
          >
            <option value="">所有题型</option>
            {["architecture_only", "optimizer_only", "loss_only", "mixed"].map(
              (x) => (
                <option key={x}>{x}</option>
              ),
            )}
          </select>
          <select
            aria-label="题源筛选"
            value={filters.source_id}
            onChange={(e) => change("source_id", e.target.value)}
          >
            <option value="">全部题源</option>
            {items(sources.data).map((s: Json) => (
              <option key={s.id || s.source_id} value={s.id || s.source_id}>
                {readableName(s.name, "导入题源")}
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            title="清除筛选"
            onClick={() => {
              setFilters({ search: "", family: "", type: "", source_id: "" });
              setOffset(0);
            }}
          >
            <Filter size={17} />
          </button>
        </div>
        <div className="selectionbar">
          <span>
            <CheckSquare size={15} />
            已选 {selected.length} 题
          </span>
          <div>
            <button
              className="text-button"
              onClick={() => setSelected([])}
              disabled={!selected.length}
            >
              清空选择
            </button>
            <button onClick={() => setSaveOpen(true)}>
              <Plus size={15} />
              保存题集
            </button>
          </div>
        </div>
        <ErrorBox error={questions.error} />
        {questions.loading ? (
          <Loading />
        ) : rows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="选择当前页"
                      checked={
                        rows.length > 0 &&
                        rows.every((q) => selected.includes(q.key))
                      }
                      onChange={(e) =>
                        setSelected(
                          toggleKeys(
                            selected,
                            rows.map((q) => q.key),
                            e.target.checked,
                          ),
                        )
                      }
                    />
                  </th>
                  <th>题目 / 来源</th>
                  <th>Family / 题型</th>
                  <th>候选模型类型</th>
                  <th>选项 / 预算</th>
                  <th>指标</th>
                  <th>验证状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((q, index) => (
                  <tr
                    key={q.key}
                    className={selected.includes(q.key) ? "selected-row" : ""}
                  >
                    <td>
                      <input
                        type="checkbox"
                        aria-label={"选择 " + q.id}
                        checked={selected.includes(q.key)}
                        onChange={(e) =>
                          setSelected(
                            toggleKeys(selected, [q.key], e.target.checked),
                          )
                        }
                      />
                    </td>
                    <td>
                      <button
                        className="row-link"
                        onClick={() => setDetail(q.key)}
                      >
                        {questionLabel(q, offset + index + 1)}
                      </button>
                      <small>
                        {q.source_count} 个来源 · {q.profile || "profile 未知"}
                      </small>
                      {q.pair_id && (
                        <span className="pill">DataFlip 题对</span>
                      )}
                    </td>
                    <td>
                      <b>{familyLabel(q.family)}</b>
                      <small>{typeLabel(q.type)}</small>
                      <details><summary>数据标识</summary><small className="mono wrap">{q.dataset_id || "数据实例未记录"}</small><small className="mono wrap">{q.key}</small></details>
                    </td>
                    <td>
                      <div className="tags">
                        {(q.model_types || []).map((m, i) => (
                          <span className="pill" key={m + i}>
                            {m}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <b>{q.choices} 个选项</b>
                      <small>
                        {typeof q.budget === "object"
                          ? JSON.stringify(q.budget)
                          : q.budget || "预算未记录"}
                      </small>
                    </td>
                    <td className="mono">{q.metric || "—"}</td>
                    <td>
                      <Status value={q.ready ? "ready" : "待补全"} />
                      {q.issues?.length > 0 && (
                        <small>{q.issues.length} 项问题</small>
                      )}
                    </td>
                    <td>
                      <button
                        aria-label={"打开 " + q.id}
                        className="icon-button"
                        onClick={() => setDetail(q.key)}
                      >
                        <ChevronRight size={17} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !questions.error && (
            <Empty title="没有匹配的题目">
              调整筛选，或登记服务器题源。这里显示实际入库记录。
            </Empty>
          )
        )}
        <div className="pagination">
          <span>
            {total
              ? `${offset + 1}–${Math.min(offset + 25, total)} / ${total}`
              : "0 条记录"}
          </span>
          <div>
            <button
              className="icon-button"
              aria-label="上一页"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              <ChevronLeft size={17} />
            </button>
            <span>第 {Math.floor(offset / 25) + 1} 页</span>
            <button
              className="icon-button"
              aria-label="下一页"
              disabled={offset + 25 >= total}
              onClick={() => setOffset(offset + 25)}
            >
              <ChevronRight size={17} />
            </button>
          </div>
        </div>
      </Card>
      {detail && (
        <QuestionDetail key={detail} id={detail} version={version} onClose={() => setDetail(undefined)} />
      )}
      {saveOpen && (
        <Drawer
          title="冻结题集"
          subtitle="保存精确题目版本与顺序，执行时不会重新查询题库。"
          onClose={() => setSaveOpen(false)}
        >
          <Field label="题集名称">
            <input
              value={setName}
              onChange={(e) => setSetName(e.target.value)}
              placeholder="例如：架构对比 · 第一次评测"
            />
          </Field>
          <div className="summary-box">
            <b>{selected.length} 个已选择版本</b>
            <p>保留跨页选择，保存后可前往测试运行。</p>
          </div>
          <button
            className="primary wide"
            disabled={!selected.length}
            onClick={() => void save()}
          >
            保存所选 {selected.length} 题
          </button>
          <div className="divider" />
          <h3>使用当前筛选</h3>
          <p className="muted">服务器现在解析筛选并冻结结果。</p>
          <button
            className="wide"
            disabled={!total}
            onClick={() => void save(true)}
          >
            冻结全部 {total} 条筛选结果
          </button>
          <div className="form-grid">
            <Field label="抽样数量">
              <input
                type="number"
                min={1}
                value={sampling.limit}
                onChange={(e) =>
                  setSampling({ ...sampling, limit: Number(e.target.value) })
                }
              />
            </Field>
            <Field label="固定 seed">
              <input
                type="number"
                value={sampling.seed}
                onChange={(e) =>
                  setSampling({ ...sampling, seed: Number(e.target.value) })
                }
              />
            </Field>
          </div>
          <button
            className="wide"
            disabled={!total}
            onClick={() => void save(true, true)}
          >
            按固定 seed 抽样并保存
          </button>
        </Drawer>
      )}
      {sourceOpen && (
        <Drawer
          title="数据源"
          subtitle="服务器路径必须位于允许的题源范围。"
          onClose={() => setSourceOpen(false)}
        >
          <Card title="登记服务器题源">
            <Field label="来源名称">
              <input
                value={importName}
                onChange={(e) => setImportName(e.target.value)}
                placeholder="用于区分 release / 原始产物"
              />
            </Field>
            <Field label="服务器路径">
              <input
                value={importPath}
                onChange={(e) => setImportPath(e.target.value)}
                placeholder="/server/path/to/questions"
              />
            </Field>
            <Field label="DataFlip pairmap 路径（可选）">
              <input
                value={pairPath}
                onChange={(e) => setPairPath(e.target.value)}
              />
            </Field>
            <button
              className="primary"
              disabled={!importPath}
              onClick={async () => {
                const r = await act(
                  () =>
                    api("/sources/import", {
                      path: importPath,
                      name: importName || undefined,
                      pairmap_path: pairPath || undefined,
                    }),
                  "题源扫描完成",
                );
                if (r) setReport(r);
              }}
            >
              <Database size={16} />
              扫描并导入
            </button>
          </Card>
          <Card
            title="上传本地 JSON 题包"
            subtitle="上传实际题包并保留来源身份。"
          >
            <label className="upload-button">
              <Upload size={17} />
              选择 JSON 文件
              <input
                type="file"
                accept=".json,application/json"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    const r = await act(() => uploadSource(f), "题包导入完成");
                    if (r) setReport(r);
                  }
                  e.target.value = "";
                }}
              />
            </label>
          </Card>
          {report && (
            <Card title="本次扫描报告">
              <JsonView value={report} />
            </Card>
          )}
          <Card title="已登记来源">
            <ErrorBox error={sources.error} />
            {sources.loading ? (
              <Loading />
            ) : items(sources.data).length ? (
              items(sources.data).map((s: Json) => (
                <div className="source-row" key={s.id || s.source_id}>
                  <Database size={17} />
                  <div>
                    <b>{readableName(s.name, "导入题源")}</b>
                    <small>{s.path || s.root || "路径未提供"}</small>
                    <JsonView value={s.report || s.import_report || s} />
                  </div>
                </div>
              ))
            ) : (
              <Empty title="尚无题源" />
            )}
          </Card>
        </Drawer>
      )}
    </>
  );
}
function QuestionDetail({ id, version, onClose }: { id: string; version: number; onClose: () => void }) {
  const { data, error, loading } = useResource<Json>(
    "/questions/" + encodeURIComponent(id),
    version,
  );
  return (
    <div className="catalog-question-reader">
    <Drawer
      title={questionLabel(data)}
      subtitle="公开题目 · 数据规则、配置、代码与来源可展开核对"
      onClose={onClose}
    >
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        data ? <QuestionReader key={id} record={data}/> : null
      )}
    </Drawer>
    </div>
  );
}
