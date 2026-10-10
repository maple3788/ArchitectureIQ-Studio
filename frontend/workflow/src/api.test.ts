import { afterEach, describe, it, expect, vi } from "vitest";
import { api } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("Studio transport", () => {
  it("sends the exact edited prompt and a fixed model selection to same-origin API", async () => {
    let received: RequestInit | undefined;
    let url = "";
    vi.stubGlobal("fetch", async (input: string, options: RequestInit) => {
      url = input;
      received = options;
      return new Response('{"id":"run1"}', { status: 200 });
    });
    const prompt = "  完整 prompt\n";
    const result = await api(
      "/runs",
      {
        kind: "evaluation",
        question_set_id: "frozen1",
        model_ids: ["m1", "m2"],
        prompt,
      },
      undefined,
      { "Idempotency-Key": "stable-preview-key" },
    );
    expect(url).toBe("/api/studio/runs");
    expect(received?.method).toBe("POST");
    expect(received?.headers).toMatchObject({
      "Content-Type": "application/json",
      "Idempotency-Key": "stable-preview-key",
    });
    expect(JSON.parse(received?.body as string)).toMatchObject({
      prompt,
      model_ids: ["m1", "m2"],
      question_set_id: "frozen1",
    });
    expect(result.id).toBe("run1");
  });
  it("exposes backend rejection instead of showing successful empty records", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response('{"detail":{"reason":"identity drift"}}', { status: 409 }),
    );
    await expect(api("/runs", {})).rejects.toMatchObject({ status: 409 });
  });
  it("reports a proxy HTML error as an API connectivity error", async () => {
    vi.stubGlobal(
      "fetch",
      async () => new Response("<html>bad gateway</html>", { status: 502 }),
    );
    await expect(api("/bootstrap")).rejects.toThrow("非 JSON");
  });
});
