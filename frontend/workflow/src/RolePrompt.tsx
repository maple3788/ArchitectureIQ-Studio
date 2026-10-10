import { useState } from "react";
import { ChevronDown, ChevronUp, ShieldCheck } from "lucide-react";
import { Empty, Field, JsonView } from "./ui";
export function RolePrompt({
  role,
  template,
  guidance,
  onGuidance,
}: {
  role: string;
  template?: string;
  guidance: string;
  onGuidance: (value: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <Field
        label="补充任务要求（可选）"
        hint="留空使用默认角色指令；填写的要求会附加进去，原有数据权限与回答格式保持一致。"
      >
        <textarea
          aria-label="角色任务补充指令"
          className="prompt-editor"
          rows={3}
          value={guidance}
          onChange={(e) => onGuidance(e.target.value)}
          placeholder="可选：添加此角色的具体任务要求…"
        />
      </Field>
      <div className="role-template">
        <button
          className="wide"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          <ShieldCheck size={14} />
          {expanded ? "收起默认角色完整指令" : "展开默认角色完整指令"}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {expanded && (
          <>
            <p className="muted">
              {role} 的固定角色协议与默认完整示意模板。DATA: &#123;&#125;
              为占位，实际输入请查看预览或已发送收据。
            </p>
            {template ? (
              <JsonView value={template} />
            ) : (
              <Empty title="服务未提供此角色的默认模板" />
            )}
          </>
        )}
      </div>

    </>
  );
}
