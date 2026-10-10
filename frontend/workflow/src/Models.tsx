import { useState } from "react";
import { Activity, Box, Check, Cpu, Edit3, Plus, Server } from "lucide-react";
import { api, items } from "./api";
import { formatTimestamp } from "./time";
import { modelReady } from "./state";
import {
  Card,
  Drawer,
  Empty,
  ErrorBox,
  Field,
  JsonView,
  Loading,
  Status,
  Tabs,
  useResource,
} from "./ui";
import type { List, ModelProfile } from "./types";
import type { Action } from "./Questions";
const blank: ModelProfile = {
  id: "",
  name: "",
  model: "",
  base_url: "",
  parameters: { temperature: 0, top_p: 1, max_tokens: 2048, extra: {} },
  enabled: true,
  api_key_env: "",
  runtime_lock_path: "",
  context_size: 8192,
  connection_type: "self_hosted",
};
export function Models({ version, act }: { version: number; act: Action }) {
  const { data, error, loading } = useResource<List<ModelProfile>>(
    "/models",
    version,
  );
  const [edit, setEdit] = useState<ModelProfile>();
  const [runtime, setRuntime] = useState<ModelProfile>();
  const [extra, setExtra] = useState("{}");
  const [formError, setFormError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const close = () => { setApiKey(""); setEdit(undefined); };
  const open = (model: ModelProfile) => {
    setEdit({ ...model, parameters: { ...model.parameters } });
    setExtra(JSON.stringify(model.parameters.extra || {}, null, 2));
    setFormError("");
    setApiKey("");
  };
  const change = (key: string, value: any) =>
    setEdit(edit && { ...edit, [key]: value });
  const save = async () => {
    if (!edit) return;
    try {
      const parsed = JSON.parse(extra);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("附加参数必须为 JSON 对象");
      const {
        id,
        name,
        model,
        base_url,
        parameters,
        enabled,
        api_key_env,
        runtime_lock_path,
        context_size,
      } = edit;
      const result = await act(
        () =>
          api("/models", {
            id,
            name,
            model,
            base_url,
            parameters: { ...parameters, extra: parsed },
            enabled,
            api_key_env: api_key_env || undefined,
            runtime_lock_path: runtime_lock_path || undefined,
            context_size,
            connection_type: edit.connection_type || "self_hosted",
            ...(edit.connection_type === "api" && apiKey ? { api_key: apiKey } : {}),
          }),
        "模型配置已保存",
      );
      if (result) close();
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setSaving(false);
      setApiKey("");
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">MODEL REGISTRY</span>
          <h1>配置模型接入。</h1>
          <p>接入自部署模型或 API 服务；每次运行冻结模型配置。</p>
        </div>
        <button className="primary" onClick={() => open(blank)}>
          <Plus size={16} />
          登记模型
        </button>
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : items(data).length ? (
        <div className="model-grid">
          {items(data).map((m) => (
            <Card key={m.id} className="model-card">
              <div className="model-top">
                <div className="model-icon">
                  <Cpu size={24} />
                </div>
                <Status value={m.health?.status || m.status || "unchecked"} />
              </div>
              <h2>{m.name || m.model}</h2>
              <p className="mono model-id">{m.model}</p>
              <div className="model-line">
                <Server size={14} />
                <span>{m.base_url}</span>
              </div>
              <div className="parameter-grid">
                <div>
                  <small>Temperature</small>
                  <b>{m.parameters?.temperature ?? "未提供"}</b>
                </div>
                <div>
                  <small>Top P</small>
                  <b>{m.parameters?.top_p ?? "未提供"}</b>
                </div>
                <div>
                  <small>Max tokens</small>
                  <b>{m.parameters?.max_tokens ?? "未提供"}</b>
                </div>
              </div>
              <p className="model-note">
                {m.connection_type === "api"
                  ? "API 服务，权重身份未验证；检查通过后可用于单题学习"
                  : modelReady(m, true)
                  ? "权重 / 运行时身份已验证，可用于评测与 KB 研究"
                  : modelReady(m)
                    ? "服务可达，可用于普通评测；权重身份尚未验证"
                    : m.enabled === false
                      ? "此配置已停用"
                      : "需检查服务可达性后执行"}
              </p>
              {(m.updated_at !== undefined || m.created_at !== undefined) && (
                <p className="model-note">
                  配置更新：{formatTimestamp(m.updated_at ?? m.created_at)}
                </p>
              )}
              <div className="model-actions">
                <button onClick={() => open(m)}>
                  <Edit3 size={14} />
                  编辑
                </button>
                <button onClick={() => setRuntime(m)}>
                  <Box size={14} />
                  身份详情
                </button>
                <button
                  onClick={() =>
                    void act(
                      () =>
                        api(
                          "/models/" + encodeURIComponent(m.id) + "/check",
                          {},
                        ),
                      "模型检查完成",
                    )
                  }
                >
                  <Activity size={14} />
                  检查
                </button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <Empty title="尚未登记被测 LLM">
            选择自部署或 API 接入，填写服务地址与模型名。
          </Empty>
        </Card>
      )}
      {edit && (
        <Drawer
          title={edit.id ? "编辑模型配置" : "登记被测 LLM"}
          subtitle={edit.connection_type === "api" ? "密钥仅提交到服务端保存，不会回显；API 权重身份未验证。" : "使用自部署服务，可通过运行锁验证权重与运行时身份。"}
          onClose={close}
        >
          <ErrorBox error={formError} />
          <Field label="接入方式">
            <select value={edit.connection_type || "self_hosted"}
              onChange={(e) => {
                setApiKey("");
                setEdit({ ...edit, connection_type: e.target.value as "api" | "self_hosted", runtime_lock_path: "", api_key_env: "", credential_ref: undefined });
              }}>
              <option value="self_hosted">自部署模型</option>
              <option value="api">API 接入（兼容 OpenAI）</option>
            </select>
          </Field>
          <div className="form-grid">
            <Field label="配置 ID">
              <input
                required
                value={edit.id}
                onChange={(e) => change("id", e.target.value)}
                placeholder="例如 qwen-local"
              />
            </Field>
            <Field label="显示名称">
              <input
                value={edit.name}
                onChange={(e) => change("name", e.target.value)}
              />
            </Field>
          </div>
          <Field label="请求模型 ID">
            <input
              value={edit.model}
              onChange={(e) => change("model", e.target.value)}
              placeholder="服务实际接受的 model"
            />
          </Field>
          <Field label="OpenAI 兼容服务地址">
            <input
              type="url"
              value={edit.base_url}
              onChange={(e) => change("base_url", e.target.value)}
              placeholder={edit.connection_type === "api" ? "https://your-provider.example/v1" : "http://127.0.0.1:8000/v1"}
            />
          </Field>
          <div className="form-grid">
            <Field label="Temperature">
              <input
                type="number"
                min={0}
                step="0.1"
                value={edit.parameters.temperature ?? ""}
                onChange={(e) =>
                  change("parameters", {
                    ...edit.parameters,
                    temperature: Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="Top P">
              <input
                type="number"
                min={0}
                max={1}
                step="0.05"
                value={edit.parameters.top_p ?? ""}
                onChange={(e) =>
                  change("parameters", {
                    ...edit.parameters,
                    top_p: Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="Max tokens">
              <input
                type="number"
                min={1}
                value={edit.parameters.max_tokens ?? ""}
                onChange={(e) =>
                  change("parameters", {
                    ...edit.parameters,
                    max_tokens: Number(e.target.value),
                  })
                }
              />
            </Field>
            <Field label="Context size">
              <input
                type="number"
                min={1}
                value={edit.context_size ?? ""}
                onChange={(e) => change("context_size", Number(e.target.value))}
              />
            </Field>
          </div>
          {edit.connection_type === "api" && (
            <Field label="API Key" hint={edit.credential_ref ? "已保存密钥。留空保留；更换服务地址时需要重新填写。" : "填写服务商密钥，或使用下面的服务端环境变量。"}>
              <input type="password" autoComplete="off" value={apiKey}
                onChange={(e) => setApiKey(e.target.value)} placeholder={edit.credential_ref ? "已保存（不回显）" : "输入 API Key"} />
            </Field>
          )}
          <Field
            label="凭据环境变量名"
            hint="只填写引用名称，如 MODEL_API_KEY。"
          >
            <input
              value={edit.api_key_env || ""}
              onChange={(e) => change("api_key_env", e.target.value)}
            />
          </Field>
          {edit.connection_type !== "api" && <Field label="服务器 runtime lock 路径">
            <input
              value={edit.runtime_lock_path || ""}
              onChange={(e) => change("runtime_lock_path", e.target.value)}
            />
          </Field>}
          <Field label="附加请求参数（JSON）">
            <textarea
              className="mono"
              rows={5}
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
            />
          </Field>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={edit.enabled}
              onChange={(e) => change("enabled", e.target.checked)}
            />
            启用此配置
          </label>
          <button
            className="primary wide"
            disabled={saving || !edit.id || !edit.name || !edit.model || !edit.base_url || (edit.connection_type === "api" && !apiKey && !edit.credential_ref && !edit.api_key_env)}
            onClick={() => { setSaving(true); void save(); }}
          >
            <Check size={16} />
            保存模型配置
          </button>
        </Drawer>
      )}
      {runtime && (
        <Drawer
          title={runtime.name || runtime.id}
          subtitle="服务身份 · 真实检查结果"
          onClose={() => setRuntime(undefined)}
        >
          <Card title="检查与运行时信息">
            <JsonView
              value={runtime.health || runtime.check}
              empty="尚未检查，运行时身份未知"
            />
          </Card>
          <Card title="登记配置">
            <JsonView value={runtime} />
          </Card>
          <p className="muted">
            服务端 chat template 与隐含默认参数若不可读取，将显示为不可观测。
          </p>
        </Drawer>
      )}
    </>
  );
}
