import { expect, it } from "vitest";
import { formatTimestamp } from "./time";
it("formats Unix seconds and equivalent ISO timestamps as the same 2026 time", () => {
  const iso = "2026-10-09T00:00:00Z";
  const seconds = Date.parse(iso) / 1000;
  expect(formatTimestamp(seconds)).toBe(formatTimestamp(iso));
  expect(formatTimestamp(seconds)).toContain("2026");
});
it("also accepts browser milliseconds without multiplying them again", () => {
  const iso = "2026-10-09T12:34:56Z";
  expect(formatTimestamp(Date.parse(iso))).toBe(formatTimestamp(iso));
});
it("marks absent and invalid times explicitly while retaining the valid Unix epoch", () => {
  expect(formatTimestamp(undefined)).toBe("未记录");
  expect(formatTimestamp("not-a-date")).toBe("时间格式无效");
  expect(formatTimestamp(0)).toContain("1970");
});
