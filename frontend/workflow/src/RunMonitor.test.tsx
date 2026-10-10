import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { RunConnection, useRunMonitor } from "./RunMonitor";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

function Monitor() {
  const resource = useRunMonitor("run-1");
  return <><RunConnection lastSyncedAt={resource.lastSyncedAt} error={resource.error}/><p data-testid="state">{resource.data?.status}</p></>;
}

it("does not imply cached records exist when the initial connection fails", () => {
  render(<RunConnection error="API unavailable"/>);
  expect(screen.getByRole("status").textContent).toContain("尚未取得运行记录");
  expect(screen.getByRole("status").textContent).not.toContain("上次记录");
});

it("polls actual status and marks retained data as stale during a connection failure", async () => {
  vi.useFakeTimers();
  let request = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    request++;
    if (request === 2) throw new Error("API unreachable");
    return new Response(JSON.stringify({ id: "run-1", status: request === 1 ? "running" : "failed" }));
  }));
  await act(async () => { render(<Monitor/>); });
  expect(screen.getByTestId("state").textContent).toBe("running");
  expect(screen.getByRole("status").textContent).toContain("连接正常");
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(screen.getByTestId("state").textContent).toBe("running");
  expect(screen.getByRole("status").textContent).toContain("同步中断");
  expect(screen.getByRole("status").textContent).toContain("上次记录");
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(screen.getByTestId("state").textContent).toBe("failed");
  expect(screen.getByRole("status").textContent).toContain("连接正常");
});
