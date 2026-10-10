import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Models } from "./Models";
import { modelReady, workflowModelReady } from "./state";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("submits API credentials once and clears them when the form closes", async () => {
  const submitted: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.body) { submitted.push(JSON.parse(String(init.body))); }
    return new Response(JSON.stringify(init?.body ? { id: "api" } : { items: [] }));
  }));
  render(<Models version={0} act={async (fn) => await fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "登记模型" }));
  fireEvent.change(screen.getByLabelText("接入方式"), { target: { value: "api" } });
  expect(screen.queryByLabelText("服务器 runtime lock 路径")).toBeNull();
  fireEvent.change(screen.getByLabelText("配置 ID"), { target: { value: "api" } });
  fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "API model" } });
  fireEvent.change(screen.getByLabelText("请求模型 ID"), { target: { value: "glm" } });
  fireEvent.change(screen.getByLabelText("OpenAI 兼容服务地址"), { target: { value: "https://example.test/v1" } });
  const key = screen.getByLabelText("API Key") as HTMLInputElement;
  expect(key.type).toBe("password");
  fireEvent.change(key, { target: { value: "ui-private-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存模型配置" }));
  await waitFor(() => expect(screen.queryByLabelText("API Key")).toBeNull());
  expect(submitted[0].connection_type).toBe("api");
  expect(submitted[0].api_key).toBe("ui-private-key");
  expect(submitted[0].runtime_lock_path).toBeUndefined();
  expect(Object.values(localStorage).join(" ")).not.toContain("ui-private-key");
  expect(Object.values(sessionStorage).join(" ")).not.toContain("ui-private-key");
  fireEvent.click(screen.getByRole("button", { name: "登记模型" }));
  fireEvent.change(screen.getByLabelText("接入方式"), { target: { value: "api" } });
  expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe("");
});

it("allows reachable API models only in basic learning without granting attestation", () => {
  const model = { connection_type: "api", enabled: true, health: { status: "reachable", verified: false } };
  expect(workflowModelReady(model, "basic_learning")).toBe(true);
  expect(workflowModelReady(model, "scientific")).toBe(false);
  expect(workflowModelReady({ ...model, enabled: false }, "basic_learning")).toBe(false);
  expect(modelReady(model, true)).toBe(false);
});
