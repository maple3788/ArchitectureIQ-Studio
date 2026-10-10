import { afterEach, it, expect } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { RolePrompt } from "./RolePrompt";
afterEach(cleanup);
it("expands the server default template separately from editable task guidance", () => {
  let edited = "";
  render(
    <RolePrompt
      role="solver"
      template={"Complete server role contract\nDATA:\n{}"}
      guidance=""
      onGuidance={(value) => (edited = value)}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "展开默认角色完整指令" }));
  expect(screen.getByText(/Complete server role contract/)).toBeTruthy();
  expect(screen.getByText(/示意模板/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("角色任务补充指令"), {
    target: { value: "custom task exactly" },
  });
  expect(edited).toBe("custom task exactly");
});
it("explicitly marks a missing default template rather than inventing role instructions", () => {
  render(<RolePrompt role="solver" guidance="" onGuidance={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "展开默认角色完整指令" }));
  expect(screen.getByText("服务未提供此角色的默认模板")).toBeTruthy();
});
