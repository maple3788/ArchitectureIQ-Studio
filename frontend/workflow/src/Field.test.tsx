import { afterEach, it, expect } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { Field } from "./ui";
afterEach(cleanup);
it("associates a select with the exact label independently of its options and help", () => {
  render(
    <Field label="Profile" hint="选择可用的服务端 Profile">
      <select defaultValue="v1.5">
        <option value="v1.5">v1.5 · several option words</option>
      </select>
    </Field>,
  );
  expect(screen.getByLabelText("Profile").tagName).toBe("SELECT");
  expect(
    screen
      .getByRole("combobox", { name: "Profile" })
      .getAttribute("aria-describedby"),
  ).toBeTruthy();
});
it("preserves a caller control ID and associates the visible label", () => {
  render(
    <Field label="模型地址">
      <input id="existing-endpoint" />
    </Field>,
  );
  expect(screen.getByLabelText("模型地址").id).toBe("existing-endpoint");
});
