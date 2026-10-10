import type { Run } from "./types";
import { nodeLabel } from "./runWorkflow";

export function RunFailure({ run, nodeId }: { run: Run; nodeId?: string }) {
  if (!run.error) return null;
  const raw = typeof run.error === "string" ? run.error : JSON.stringify(run.error, null, 2);
  const tooLong = raw.includes("Role payload exceeds conservative context budget");
  const discovery = nodeId === "discoverer";
  const round = run.progress?.round_index;
  const finished = (id: string) => round !== undefined && run.events?.some(e =>
    (!e.type || e.type === "stage") && e.node_id === id && e.round_index === round && ["complete", "completed"].includes(e.state));
  const settings = run.config?.workflow?.settings;
  const model = run.config?.models?.find((m: any) => m.id === settings?.model_id) ?? run.config?.models?.[0];
  const context = settings?.context_size;
  const reservedOutput = model?.parameters?.max_tokens;
  return <section className="rw-error rw-failure-story" role="alert">
    <h4>{tooLong
      ? discovery ? "研究材料太长，Discoverer 尚未开始" : `${nodeLabel(nodeId ?? "当前节点")}的输入太长，发送前已停止`
      : `运行停在${nodeLabel(nodeId ?? "当前节点")}`}</h4>
    {tooLong ? <>
      <p>程序在发送前拦住了这一步，模型还没有收到这次请求。</p>
      {discovery && finished("solver") && finished("commit") && finished("reveal") &&
        <p className="rw-failure-progress">本轮已完成：解题、保存答案、对照标准答案。提出假说这一步尚未完成。</p>}
      <details className="rw-failure-help">
        <summary>{discovery ? "为什么一道题也会太长？怎么处理？" : "这是什么意思？怎么处理？"}</summary>
        <p>{discovery
          ? "Discoverer 读取的是题面、模型回答和真实训练反馈，不只是题目编号。训练过程中的大量数字、完整曲线和重复结果也会占用输入长度。"
          : "每一步需要同时容纳输入材料和模型将要写出的回答。输入材料太长时，即使题目很少，也可能无法通过发送前的长度检查。"}</p>
        <p>{discovery
          ? "新运行会将训练反馈整理为关键结果摘要，完整曲线和结果文件留在运行记录中。请回到编辑工作流重新预览后提交。这里保留本次运行当时的失败记录，更新后不会自动重跑。"
          : "重新运行前，缩短这一步的输入材料或自定义提示词，并重新预览。完整证据保留在运行记录中。"}</p>
      </details>
      <details className="rw-fold rw-failure-technical">
        <summary>技术详情：本次长度限制与原始错误</summary>
        <p>发送前检查用 UTF-8 字节数保守估算输入长度，再加回答预留和格式余量；这不是实际 token 用量，也不是模型返回的超限错误。</p>
        <dl>
          {typeof context === "number" && <div><dt>本次冻结的总长度上限</dt><dd>{context.toLocaleString("en-US")}</dd></div>}
          {typeof reservedOutput === "number" && <div><dt>为模型回答预留</dt><dd>{reservedOutput.toLocaleString("en-US")}</dd></div>}
        </dl>
        <pre>{raw}</pre>
      </details>
    </> : <>
      <p>这一步没有正常完成。查看下面的记录可以确认已保存的输入和结果。</p>
      <details className="rw-fold"><summary>原始失败原因</summary><pre>{raw}</pre></details>
    </>}
  </section>;
}
