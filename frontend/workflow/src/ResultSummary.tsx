import { ArrowRight } from "lucide-react";
import { auditRecord } from "./audit";
import { Empty, JsonView, Status } from "./ui";
export function ResultSummary({
  result,
  records = [],
  onRecord,
}: {
  result: any;
  records?: any[];
  onRecord?: (index: number) => void;
}) {
  if (!result) return <Empty title="尚未产生结果" />;
  const outputs =
    result.outputs && typeof result.outputs === "object"
      ? Object.entries(result.outputs).flatMap(
          ([modelId, questions]: [string, any]) =>
            Object.entries(questions || {}).map(
              ([questionKey, answer]: [string, any]) => ({
                modelId,
                questionKey,
                answer,
                recordIndex: records.findIndex((r) => {
                  const view = auditRecord(r);
                  return (
                    view.modelId === modelId && view.questionKey === questionKey
                  );
                }),
              }),
            ),
        )
      : [];
  const questionOrder = Array.from(new Set(outputs.map(o=>o.questionKey)));
  return (
    <>
      {Object.keys(result.scores || {}).length > 0 && (
        <>
          <h3>模型对照 · 服务器评分</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>模型</th>
                  <th>Top-1 正确 / 全体</th>
                  <th>无效</th>
                  <th>可判定候选对</th>
                  <th>DataFlip 共同正确</th>
                  <th>KB 覆盖</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(result.scores).map(
                  ([modelId, score]: [string, any]) => (
                    <tr key={modelId}>
                      <td className="mono">{modelId}</td>
                      <td>
                        {score.correct ?? "—"} / {score.total ?? "—"}
                      </td>
                      <td>{score.invalid ?? "—"}</td>
                      <td>
                        {score.pairwise_correct ?? "—"} /{" "}
                        {score.pairwise_total ?? "—"}
                        <small>未判定 {score.pairwise_unresolved ?? "—"}</small>
                      </td>
                      <td>
                        {score.pair_joint_correct ?? "—"} /{" "}
                        {score.pair_total ?? "—"}
                        <small>
                          不完整谱系 {score.incomplete_pair_groups ?? "—"}
                        </small>
                        {score.pair_winner_change_total !== undefined && <small>赢家变化判断 {score.pair_winner_change_correct} / {score.pair_winner_change_total} · 按候选身份</small>}
                      </td>
                      <td>
                        {score.covered_questions ?? "—"} / {score.total ?? "—"}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      {(result.calls !== undefined || result.charged_tokens !== undefined) && (
        <div className="result-metrics">
          <div>
            <small>请求数</small>
            <b>{result.calls ?? "未提供"}</b>
          </div>
          <div>
            <small>计费 tokens</small>
            <b>{result.charged_tokens?.toLocaleString() ?? "未提供"}</b>
          </div>
          <div>
            <small>耗时（秒）</small>
            <b>
              {typeof result.elapsed_seconds === "number"
                ? result.elapsed_seconds.toFixed(2)
                : "未提供"}
            </b>
          </div>
        </div>
      )}
      {outputs.length > 0 && (
        <>
          <h3>逐题输出</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>题目版本</th>
                  <th>模型</th>
                  <th>候选排序</th>
                  <th>正确性</th>
                  <th>状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {outputs.map(
                  ({ modelId, questionKey, answer, recordIndex }) => {
                    const record = records[recordIndex];
                    return (
                      <tr key={modelId + questionKey}>
                        <td title={questionKey}>题目 {questionOrder.indexOf(questionKey) + 1}</td>
                        <td className="mono">{modelId}</td>
                        <td>
                          {Array.isArray(answer?.ranking)
                            ? answer.ranking.join(" → ")
                            : "未提供排序"}
                        </td>
                        <td>
                          {record?.correct === true
                            ? "正确"
                            : record?.correct === false
                              ? "错误"
                              : "未提供评分"}
                        </td>
                        <td>
                          <Status
                            value={
                              record?.status ??
                              (answer?.valid === false
                                ? "invalid"
                                : answer?.valid === true
                                  ? "complete"
                                  : "未记录")
                            }
                          />
                        </td>
                        <td>
                          {onRecord && recordIndex >= 0 && (
                            <button
                              className="icon-button"
                              aria-label={`查看逐题收据 ${questionKey} ${modelId}`}
                              onClick={() => onRecord(recordIndex)}
                            >
                              <ArrowRight size={15} />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      {result.metrics && <JsonView value={result.metrics} />}
      <details>
        <summary>展开完整结果与产物 JSON</summary>
        <JsonView value={result} />
      </details>
    </>
  );
}
