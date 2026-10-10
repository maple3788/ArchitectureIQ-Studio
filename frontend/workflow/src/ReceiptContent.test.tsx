import { afterEach, it, expect } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import { ReceiptContent } from "./ReceiptContent";
afterEach(cleanup);
const record = {
  actual_request: {
    method: "POST",
    url: "http://service/v1/chat/completions",
    payload: {
      model: "model-actual",
      messages: [
        { role: "system", content: "exact sent system prompt" },
        { role: "user", content: "exact sent question prompt" },
      ],
    },
    body_sha256: "frozen-body-hash",
    attempt: 1,
  },
  raw: {
    model: "returned-model",
    choices: [
      {
        message: {
          content: "returned answer text",
          reasoning_content: "explicit service reasoning field",
        },
        finish_reason: "stop",
      },
    ],
  },
  finish_reason: "stop",
  usage: { prompt_tokens: 18, completion_tokens: 9 },
  inputs: { question_key: "q1", model_id: "m1" },
};
it("renders the actual system and user messages on the request pane", () => {
  render(<ReceiptContent record={record} tab="实际请求" />);
  expect(screen.getByText("exact sent system prompt")).toBeTruthy();
  expect(screen.getByText("exact sent question prompt")).toBeTruthy();
  expect(
    within(
      screen
        .getByRole("heading", { name: "发送地址与请求身份" })
        .closest("section")!,
    ).getByText(/frozen-body-hash/),
  ).toBeTruthy();
});
it("renders real answer and service reasoning separately with response metadata", () => {
  render(<ReceiptContent record={record} tab="原始响应" />);
  expect(screen.getByText("returned answer text")).toBeTruthy();
  expect(screen.getByText("explicit service reasoning field")).toBeTruthy();
  expect(screen.getByText("答案内容 · content")).toBeTruthy();
  expect(screen.getByText("服务附加字段 · reasoning_content")).toBeTruthy();
  expect(
    within(
      screen
        .getByRole("heading", { name: "真实返回模型与 usage" })
        .closest("section")!,
    ).getByText(/returned-model/),
  ).toBeTruthy();
});
