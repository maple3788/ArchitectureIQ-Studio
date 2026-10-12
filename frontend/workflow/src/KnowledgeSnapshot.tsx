import { useState } from "react";
import { JsonView } from "./ui";
import "./knowledge-snapshot.css";
const statuses: Record<string, string> = {
  legacy_unverified: "历史材料 · 尚未验证",
  proposed: "新假说 · 待检验",
  exploring: "探索中",
  replicated_in_scope: "已在记录范围内验证",
  retired: "已退役",
  refuted: "已被反驳",
};
const fields: Record<string, string> = {
  family: "数据类型",
  model_type: "模型类型",
  depth: "层数",
  width: "宽度",
  activation: "激活函数",
  budget: "训练样本预算",
  batch_size: "批大小",
  train_size: "训练集大小",
  input_dim: "输入维度",
  target_oscillatory: "目标是否振荡",
  lr: "学习率",
  profile_hash: "配置版本",
  scope_version: "范围版本",
  opt_key: "优化器配置",
  loss_key: "损失函数配置",
  arch_key: "模型结构配置",
  opt: "优化器",
  steps: "训练步数",
  residual: "残差连接",
  ln_any: "是否使用层归一化",
  ln_all: "是否全部使用层归一化",
  ln_count: "层归一化数量",
  context_length: "上下文长度",
  vocab_size: "词表大小",
};
const operators: Record<string, string> = {
  eq: "等于",
  ne: "不等于",
  in: "属于",
  nin: "不属于",
  not_in: "不属于",
  ge: "至少",
  gt: "大于",
  le: "至多",
  lt: "小于",
};
const plain = (v: any): string =>
  typeof v === "boolean"
    ? v
      ? "是"
      : "否"
    : Array.isArray(v)
      ? v.map(plain).join("、")
      : v === null
        ? "未提供"
        : typeof v === "object"
          ? "详见完整记录"
          : String(v);
function conditionText(value: any, depth = 0): string | undefined {
  if (depth > 12) return undefined;
  if (Array.isArray(value)) {
    if (typeof value[0] === "string") {
      if (value.length !== 3 || !operators[value[1]]) return undefined;
      const literal = value[2];
      if (
        literal === null ||
        (typeof literal === "object" && !Array.isArray(literal))
      )
        return undefined;
      return `${fields[value[0]] ?? value[0]} ${operators[value[1]]} ${plain(literal)}`;
    }
    if (!value.length) return undefined;
    const children = value.map((v) => conditionText(v, depth + 1));
    return children.every((v) => v !== undefined)
      ? `同时满足（${children.join("；")}）`
      : undefined;
  }
  if (value && typeof value === "object" && Object.keys(value).length === 1) {
    if ("not" in value) {
      const child = conditionText(value.not, depth + 1);
      return child === undefined ? undefined : `不满足（${child}）`;
    }
    const op = "all" in value ? "all" : "any" in value ? "any" : undefined;
    if (!op || !Array.isArray(value[op]) || !value[op].length) return undefined;
    const children = value[op].map((v: any) => conditionText(v, depth + 1));
    return children.every((v: any) => v !== undefined)
      ? `${op === "all" ? "同时满足" : "至少满足一项"}（${children.join("；")}）`
      : undefined;
  }
  return undefined;
}
export function KnowledgeSnapshot({ snapshot, single=false }: { snapshot: any; single?:boolean }) {
  const [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [limit, setLimit] = useState(8);
  const claims: any[] = Array.isArray(snapshot?.claims) ? snapshot.claims : [];
  const usable = (c: any) =>
    c.enabled === true && c.status === "replicated_in_scope";
  const grouped = new Map<string, any[]>();
  claims.forEach((claim, index) => {
    const id = claim.source_claim_id || claim.id || `record-${index}`;
    grouped.set(id, [...(grouped.get(id) ?? []), claim]);
  });
  const groups = [...grouped].map(([id, clauses]) => ({id, clauses}));
  const shown = groups.filter(group => group.clauses.some(c =>
    (filter !== "usable" || usable(c)) &&
    (filter !== "research" || !usable(c)) &&
    `${group.id} ${c.id} ${c.text ?? ""}`.toLowerCase().includes(search.toLowerCase()),
  ));
  return (
    <div className="knowledge-reader">
      {!single&&<div className="knowledge-counts">
        <strong>{groups.length} 条知识 · {claims.length} 个规则子项</strong>
        <span>{claims.filter(usable).length} 条已验证且启用</span>
        <span>
          {claims.filter((c) => !usable(c)).length} 条暂不用于正式解题
        </span>
      </div>}
      <p className="knowledge-note">
        知识是否适用于一道新题，还需要匹配它的条件与已验证范围。
      </p>
      {!single && !!claims.length && (
        <div className="knowledge-filters">
          <input
            aria-label="查找知识"
            placeholder="搜索知识内容或编号"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setLimit(8);
            }}
          />
          <select
            aria-label="知识使用状态"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setLimit(8);
            }}
          >
            <option value="all">全部知识</option>
            <option value="usable">已验证且启用</option>
            <option value="research">待验证 / 未启用</option>
          </select>
        </div>
      )}
      {!shown.length && (
        <p className="knowledge-note">
          {claims.length ? "没有符合筛选的知识。" : "这个版本尚无知识条目。"}
        </p>
      )}
      {shown.slice(0, limit).map((group) => {
        const sameText = group.clauses.every(claim => claim.text === group.clauses[0].text);
        return <article key={group.id} className="knowledge-claim">
          <header><strong title={group.id}>知识 {groups.indexOf(group) + 1}</strong>{group.clauses.length > 1 && <span>{group.clauses.length} 个条件分支</span>}</header>
          {sameText && <p className="knowledge-statement">{group.clauses[0].text || "未提供知识正文"}</p>}
          {group.clauses.map((claim, index) => {
        const evidence = (Array.isArray(snapshot.evidence) ? snapshot.evidence : []).filter((e: any) =>
          claim.evidence_ids?.includes(e.id),
        );
        const scope = claim.rule?.scope,
          condition = conditionText(scope);
        return (
          <section key={`${claim.id}-${index}`} className="knowledge-clause">
            <header>
              {group.clauses.length > 1 && <strong title={claim.id}>分支 {index + 1}</strong>}
              <span>
                {statuses[claim.status] ?? claim.status ?? "状态未提供"}
              </span>
            </header>
            {!sameText && <p className="knowledge-statement">
              {claim.text || "未提供知识正文"}
            </p>}
            <small>
              {usable(claim)
                ? "允许在匹配范围内检索使用"
                : "当前不用于正式解题"}{" "}
              · {claim.evidence_ids?.length ?? 0} 条关联证据
            </small>
            <details>
              <summary>适用于什么条件 · 证据</summary>
              {scope === undefined || scope === null ? (
                <p>规则未记录额外的题目条件；仍需核对控制条件和已验证范围。</p>
              ) : (
                <p className="knowledge-condition">
                  {condition ??
                    "已记录适用条件，简明视图暂不能解释，请查看完整规则。"}
                </p>
              )}
              {Array.isArray(claim.rule?.same) &&
                claim.rule.same.length > 0 && (
                  <p>
                    保持相同：
                    {claim.rule.same
                      .map((key: string) => fields[key] ?? key)
                      .join("、")}
                    。
                  </p>
                )}
              {Array.isArray(claim.rule?.differ) &&
                claim.rule.differ.length > 0 && (
                  <p>
                    需要不同：
                    {claim.rule.differ
                      .map((key: string) => fields[key] ?? key)
                      .join("、")}
                    。
                  </p>
                )}
              {!claim.validated_scope && (
                <p>尚无已验证范围，条件描述仍是待检验的主张。</p>
              )}
              {claim.validated_scope && (
                <p>
                  已记录验证范围；实际检索还会核对配置版本、数据分布及控制条件。
                </p>
              )}
              {!!evidence.length && (
                <p>
                  支持{" "}
                  {evidence.filter((e: any) => e.outcome === "support").length}{" "}
                  · 反驳{" "}
                  {evidence.filter((e: any) => e.outcome === "refute").length} ·
                  不确定{" "}
                  {
                    evidence.filter((e: any) => e.outcome === "inconclusive")
                      .length
                  }
                </p>
              )}
              {!!claim.evidence_ids?.length && !evidence.length && (
                <p>此视图只有证据引用，具体结果请查看来源运行。</p>
              )}
              <details>
                <summary>完整规则、验证范围与证据记录</summary>
                <JsonView value={{ claim, evidence }} />
              </details>
            </details>
          </section>
        );
      })}</article>;
      })}
      {shown.length > limit && (
        <button onClick={() => setLimit((v) => v + 8)}>
          再看 {Math.min(8, shown.length - limit)} 条知识
        </button>
      )}
      <details className="knowledge-origin">
        <summary>版本与完整快照</summary>
        <p>
          版本：{snapshot?.version ?? "未提供"}
          <br />
          上一版：{snapshot?.parent_version ?? "未提供"}
        </p>
        <JsonView value={snapshot} />
      </details>
    </div>
  );
}
