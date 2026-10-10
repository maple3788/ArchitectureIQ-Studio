import { auditRecord } from "./audit";
import { Card, Empty, JsonView } from "./ui";
function SentMessages({ messages }: { messages: any }) {
  return Array.isArray(messages) ? (
    <>
      {messages.map((message: any, index: number) => (
        <section className="sent-message" key={index}>
          <span className="pill teal-pill">
            {index + 1} · {String(message.role || "角色未提供").toUpperCase()}
          </span>
          <JsonView value={message.content} />
          {message.tool_calls && <JsonView value={message.tool_calls} />}
        </section>
      ))}
    </>
  ) : (
    <Empty title="该收据未暴露完整 messages" />
  );
}
export function ReceiptContent({ record, tab }: { record: any; tab: string }) {
  const audit = auditRecord(record);
  const choices = audit.response?.choices;
  if (tab === "完整输入")
    return (
      <>
        <div className="record-warning">
          实际发送的 messages · 来自冻结 payload
        </div>
        <SentMessages messages={audit.messages} />
      </>
    );
  if (tab === "实际请求")
    return (
      <>
        <div className="record-warning">
          ACTUALLY SENT · 实际请求来自传输层收据
        </div>
        <Card title="发送地址与请求身份">
          <JsonView
            value={
              audit.request
                ? {
                    method: audit.request.method,
                    url: audit.request.url,
                    body_sha256: audit.request.body_sha256,
                    attempt: audit.request.attempt,
                    sent_at: record.sent_at,
                  }
                : undefined
            }
            empty="该条记录未提供实际发送请求"
          />
        </Card>
        <Card title="实际发送的完整 Prompt">
          <SentMessages messages={audit.messages} />
        </Card>
        <details>
          <summary>展开完整请求 JSON（含生效参数）</summary>
          <JsonView
            value={audit.request}
            empty="该条记录未提供实际发送 payload"
          />
        </details>
      </>
    );
  if (tab === "原始响应")
    return (
      <>
        <Card title="真实返回模型与 usage">
          <JsonView
            value={
              audit.response
                ? {
                    model: audit.response.model ?? "未提供",
                    finish_reason: audit.finishReason ?? "未提供",
                    usage: audit.usage ?? "未提供",
                    response_received_at: record.response_received_at,
                  }
                : undefined
            }
            empty="服务未提供原始响应"
          />
        </Card>
        {Array.isArray(choices) &&
          choices.map((choice: any, index: number) => (
            <div key={index}>
              <Card
                title="答案内容 · content"
                subtitle={`服务返回 choice ${choice.index ?? index}`}
              >
                <JsonView
                  value={choice.message?.content}
                  empty="服务未提供 content"
                />
              </Card>
              {choice.message?.reasoning_content !== undefined && (
                <Card
                  title="服务附加字段 · reasoning_content"
                  subtitle="服务显式返回的原始字段，答案解析仍遵守 scoring 协议。"
                >
                  <JsonView value={choice.message.reasoning_content} />
                </Card>
              )}
            </div>
          ))}
        <details>
          <summary>展开完整原始响应 JSON</summary>
          <JsonView value={audit.response} empty="服务未提供原始响应" />
        </details>
      </>
    );
  return (
    <>
      <Card title="解析与评分">
        <JsonView
          value={{
            interpretation:
              record?.interpretation ?? record?.parsed ?? record?.answer,
            correct: record?.correct,
            score: record?.score,
            feedback: record?.feedback,
            error: record?.error,
          }}
        />
      </Card>
      <Card title="调用身份与成本">
        <JsonView
          value={{
            question_key: audit.questionKey,
            model_id: audit.modelId,
            node_id: audit.nodeId,
            status: record?.status,
            finish_reason: audit.finishReason,
            usage: audit.usage,
            charged_tokens: record?.charged_tokens,
            elapsed_seconds: record?.elapsed_seconds,
            input_hash: record?.input_hash,
          }}
        />
      </Card>
    </>
  );
}
