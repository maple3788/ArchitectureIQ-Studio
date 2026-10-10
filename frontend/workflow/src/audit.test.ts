import { expect, it } from "vitest";
import { auditRecord } from "./audit";
it("prioritizes the frozen transport input over a logical preview", () => {
  const actual = {
    payload: { messages: [{ role: "user", content: "clipped and sent" }] },
  };
  const record = {
    messages: [{ role: "user", content: "logical preview" }],
    request: { messages: [{ role: "user", content: "old input" }] },
    actual_request: actual,
    raw_response: "actual response",
  };
  const view = auditRecord(record);
  expect(view.request).toBe(actual);
  expect(view.messages).toEqual(actual.payload.messages);
  expect(view.response).toBe("actual response");
});
it("preserves an explicitly empty raw service response", () =>
  expect(
    auditRecord({ raw_response: "", response: { logical: "fallback" } })
      .response,
  ).toBe(""));
it("reads the persisted raw response and identifies the nested call inputs", () => {
  const raw = {
    model: "service-id",
    choices: [
      {
        message: {
          content: '{"ranking":["B","A"]}',
          reasoning_content: "service supplied explanation",
        },
        finish_reason: "stop",
      },
    ],
    usage: { completion_tokens: 40 },
  };
  const view = auditRecord({
    actual_request: {
      method: "POST",
      url: "http://service/chat",
      payload: { messages: [{ role: "system", content: "exact system" }] },
      body_sha256: "sha",
      attempt: 1,
    },
    raw,
    inputs: { question_key: "q-version", model_id: "selected-model" },
    finish_reason: "stop",
    usage: { completion_tokens: 40 },
  });
  expect(view.response).toBe(raw);
  expect(view.questionKey).toBe("q-version");
  expect(view.modelId).toBe("selected-model");
  expect(view.finishReason).toBe("stop");
  expect(view.usage).toEqual({ completion_tokens: 40 });
});
