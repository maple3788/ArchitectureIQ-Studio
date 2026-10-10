import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useSharedWorkflowDraft } from './useSharedWorkflowDraft';
import { draftKey } from './state';
import type { Workflow } from './types';

const workflow = (name = '单题学习'): Workflow => ({schema_version: 1, name, nodes: [], edges: [], settings: {method_id: 'basic_learning'}});
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const response = (body: unknown, status = 200) => ({ok: status < 400, status, text: async () => JSON.stringify(body)}) as Response;
function server() {
  let current = {workflow: workflow(), advanced_backup: null as Workflow | null, revision: 1, updated_at: 1};
  let online = true;
  const backups: {id: string; workflow: Workflow; source: string; created_at: number}[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (!online) throw new Error('网络已断开');
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (url.endsWith('/backups')) {
      if (body && !backups.some(item => JSON.stringify(item.workflow) === JSON.stringify(body.workflow))) backups.push({id: 'backup-' + backups.length, workflow: clone(body.workflow), source: body.source, created_at: 1});
      return response(body ? backups.at(-1) : {items: clone(backups), total: backups.length});
    }
    if (init?.method === 'PUT') {
      if (body.expected_revision !== current.revision) return response({detail: '版本已变化'}, 409);
      current = {workflow: clone(body.workflow), advanced_backup: clone(body.advanced_backup), revision: current.revision + 1, updated_at: current.updated_at + 1};
    }
    return response(clone(current));
  });
  vi.stubGlobal('fetch', fetcher);
  return {fetcher, backups, get current() {return current;}, change(name: string) {current = {...current, workflow: workflow(name), revision: current.revision + 1};}, online(value: boolean) {online = value;}};
}
async function settle() {await act(async () => {for (let i = 0; i < 15; i++) await Promise.resolve();});}
async function advance(ms = 600) {await act(async () => {await vi.advanceTimersByTimeAsync(ms);});}
beforeEach(() => {
  vi.useFakeTimers();
  const storage = new Map<string, string>();
  vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key)});
});
afterEach(() => {cleanup(); vi.useRealTimers(); vi.unstubAllGlobals();});

it('loads the server draft in two clients, then saves and syncs an edit without reloading', async () => {
  const api = server();
  const a = renderHook(useSharedWorkflowDraft);
  const b = renderHook(useSharedWorkflowDraft);
  await settle();
  expect(a.result.current.workflow?.name).toBe('单题学习');
  act(() => a.result.current.setWorkflow(value => ({...value!, name: '来自 Chrome 的编辑'})));
  expect(a.result.current.status).toBe('pending');
  await advance();
  expect(api.current.workflow.name).toBe('来自 Chrome 的编辑');
  expect(a.result.current.status).toBe('saved');
  await advance(2500);
  expect(b.result.current.workflow?.name).toBe('来自 Chrome 的编辑');
  expect(b.result.current.revision).toBe(2);
});

it('preserves dirty input when another client saves and requires explicit conflict resolution', async () => {
  const api = server();
  const a = renderHook(useSharedWorkflowDraft);
  const b = renderHook(useSharedWorkflowDraft);
  await settle();
  act(() => {a.result.current.setWorkflow(workflow('Chrome')); b.result.current.setWorkflow(workflow('GPT'));});
  await advance();
  expect(a.result.current.status).toBe('saved');
  expect(b.result.current.status).toBe('conflict');
  expect(b.result.current.workflow?.name).toBe('GPT');
  await advance(3000);
  expect(b.result.current.workflow?.name).toBe('GPT');
  await act(async () => {await b.result.current.acceptRemote();});
  expect(b.result.current.workflow?.name).toBe('Chrome');
  expect(api.backups.some(item => item.workflow.name === 'GPT' && item.source === 'conflict')).toBe(true);
});

it('keeps offline edits and retries them against the last server revision', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  api.online(false);
  act(() => hook.result.current.setWorkflow(workflow('断网期间的编辑')));
  await advance();
  expect(hook.result.current.status).toBe('offline');
  expect(hook.result.current.workflow?.name).toBe('断网期间的编辑');
  api.online(true);
  await act(async () => {await hook.result.current.retry();});
  await advance();
  expect(api.current.workflow.name).toBe('断网期间的编辑');
  expect(hook.result.current.status).toBe('saved');
});

it('archives old browser drafts without letting them replace the shared single-question workflow', async () => {
  localStorage.setItem(draftKey, JSON.stringify(workflow('旧题对草稿')));
  localStorage.setItem(draftKey + '-advanced-backup', JSON.stringify(workflow('更早的高级草稿')));
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  expect(hook.result.current.workflow?.name).toBe('单题学习');
  expect(api.current.revision).toBe(1);
  expect(api.backups.map(item => item.workflow.name)).toEqual(['旧题对草稿', '更早的高级草稿']);
  expect(localStorage.getItem(draftKey)).toBeNull();
  expect(localStorage.getItem(draftKey + '-advanced-backup')).toBeNull();
});

it('keeps the losing remote draft as a backup before explicitly keeping local edits', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  api.change('另一浏览器保存的草稿');
  act(() => hook.result.current.setWorkflow(workflow('我要保留的编辑')));
  await advance();
  expect(hook.result.current.status).toBe('conflict');
  await act(async () => {await hook.result.current.keepLocal();});
  expect(api.current.workflow.name).toBe('我要保留的编辑');
  expect(hook.result.current.status).toBe('saved');
  expect(api.backups.some(item => item.workflow.name === '另一浏览器保存的草稿')).toBe(true);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => {resolve = done;});
  return {promise, resolve};
}

it('saves edits made while an earlier PUT is still in flight', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  const send = api.fetcher.getMockImplementation()!;
  const gate = deferred<void>();
  let delay = true;
  api.fetcher.mockImplementation(async (url, init) => {
    const result = await send(url, init);
    if (init?.method === 'PUT' && delay) {delay = false; await gate.promise;}
    return result;
  });
  act(() => hook.result.current.setWorkflow(workflow('首次编辑')));
  await advance();
  expect(hook.result.current.status).toBe('saving');
  act(() => hook.result.current.setWorkflow(value => ({...value!, name: '继续输入的新内容'})));
  await act(async () => {gate.resolve();});
  expect(hook.result.current.workflow?.name).toBe('继续输入的新内容');
  await advance();
  expect(api.current.workflow.name).toBe('继续输入的新内容');
  expect(hook.result.current.status).toBe('saved');
  expect(hook.result.current.revision).toBe(3);
});

it('ignores an old GET arriving after a newer save', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  const send = api.fetcher.getMockImplementation()!;
  const gate = deferred<void>();
  let delay = true;
  api.fetcher.mockImplementation(async (url, init) => {
    const result = await send(url, init);
    if (url.endsWith('/workflow/draft') && init?.method === 'GET' && delay) {delay = false; await gate.promise;}
    return result;
  });
  act(() => {window.dispatchEvent(new Event('focus'));});
  await settle();
  act(() => hook.result.current.setWorkflow(workflow('已保存的新稿')));
  await advance();
  await act(async () => {gate.resolve();});
  expect(hook.result.current.workflow?.name).toBe('已保存的新稿');
  expect(hook.result.current.revision).toBe(2);
  expect(hook.result.current.status).toBe('saved');
});

it('does not replace unsent edits with a delayed poll response', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  const send = api.fetcher.getMockImplementation()!;
  const gate = deferred<void>();
  api.fetcher.mockImplementation(async (url, init) => {
    const result = await send(url, init);
    if (url.endsWith('/workflow/draft') && init?.method === 'GET') await gate.promise;
    return result;
  });
  act(() => {window.dispatchEvent(new Event('focus')); hook.result.current.setWorkflow(workflow('正在输入'));});
  await act(async () => {gate.resolve();});
  expect(hook.result.current.workflow?.name).toBe('正在输入');
  expect(hook.result.current.status).toBe('pending');
  await advance();
  expect(api.current.workflow.name).toBe('正在输入');
});

it('keeps local edits when backup fails during conflict resolution', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  api.change('服务器的最新编辑');
  act(() => hook.result.current.setWorkflow(workflow('待保存编辑')));
  await advance();
  const send = api.fetcher.getMockImplementation()!;
  api.fetcher.mockImplementation(async (url, init) => init?.method === 'POST' && url.endsWith('/backups') ? response({detail: '磁盘不可写'}, 503) : send(url, init));
  await act(async () => {await hook.result.current.acceptRemote();});
  expect(hook.result.current.status).toBe('conflict');
  expect(hook.result.current.error).toContain('备份或读取失败');
  expect(hook.result.current.workflow?.name).toBe('待保存编辑');
  expect(api.current.workflow.name).toBe('服务器的最新编辑');
});

it('requires another decision if a third save races an explicit keep-local decision', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  api.change('远端二版');
  act(() => hook.result.current.setWorkflow(workflow('我的编辑')));
  await advance();
  const send = api.fetcher.getMockImplementation()!;
  api.fetcher.mockImplementation(async (url, init) => {
    const result = await send(url, init);
    if (url.endsWith('/backups') && init?.method === 'POST') api.change('远端第三版');
    return result;
  });
  await act(async () => {await hook.result.current.keepLocal();});
  expect(api.current.workflow.name).toBe('远端第三版');
  expect(hook.result.current.workflow?.name).toBe('我的编辑');
  expect(hook.result.current.status).toBe('conflict');
});

it('loads the server draft even if a legacy backup fails, retaining the old local key', async () => {
  const legacy = JSON.stringify(workflow('未备份旧稿'));
  localStorage.setItem(draftKey, legacy);
  const api = server();
  const send = api.fetcher.getMockImplementation()!;
  api.fetcher.mockImplementation(async (url, init) => init?.method === 'POST' && url.endsWith('/backups') ? response({detail: '保存失败'}, 500) : send(url, init));
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  expect(hook.result.current.workflow?.name).toBe('单题学习');
  expect(hook.result.current.status).toBe('saved');
  expect(hook.result.current.error).toContain('旧浏览器草稿尚未备份');
  expect(localStorage.getItem(draftKey)).toBe(legacy);
});


it('retains legacy migration warnings and backup history through StrictMode effect remounts', async () => {
  localStorage.setItem(draftKey, JSON.stringify(workflow('StrictMode 旧稿')));
  const api = server();
  api.backups.push({id: 'existing', workflow: workflow('已存在的备份'), source: 'manual', created_at: 1});
  const hook = renderHook(useSharedWorkflowDraft, {reactStrictMode: true});
  await settle();
  expect(hook.result.current.workflow?.name).toBe('单题学习');
  expect(hook.result.current.backups.some(item => item.workflow.name === '已存在的备份')).toBe(true);
  expect(hook.result.current.backups.some(item => item.workflow.name === 'StrictMode 旧稿')).toBe(true);
});

it('preserves configuration object identity when an unchanged draft is polled', async () => {
  server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  const original = hook.result.current.workflow;
  await advance(3000);
  expect(hook.result.current.workflow).toBe(original);
});

it('warns before closing an unsaved draft and removes the warning after saving', async () => {
  server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  act(() => hook.result.current.setWorkflow(workflow('尚未同步')));
  const pending = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(pending);
  expect(pending.defaultPrevented).toBe(true);
  await advance();
  const saved = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(saved);
  expect(saved.defaultPrevented).toBe(false);
});

it('surfaces a failed StrictMode legacy migration and succeeds when retried', async () => {
  const legacy = JSON.stringify(workflow('必须保留的旧稿'));
  localStorage.setItem(draftKey, legacy);
  const api = server();
  const send = api.fetcher.getMockImplementation()!;
  let fail = true;
  api.fetcher.mockImplementation(async (url, init) => fail && init?.method === 'POST' && url.endsWith('/backups') ? response({detail: '暂时失败'}, 503) : send(url, init));
  const hook = renderHook(useSharedWorkflowDraft, {reactStrictMode: true});
  await settle();
  expect(hook.result.current.workflow?.name).toBe('单题学习');
  expect(hook.result.current.error).toContain('旧浏览器草稿尚未备份');
  expect(localStorage.getItem(draftKey)).toBe(legacy);
  fail = false;
  await act(async () => {await hook.result.current.retry();});
  expect(hook.result.current.error).toBe('');
  expect(localStorage.getItem(draftKey)).toBeNull();
  expect(hook.result.current.backups.some(item => item.workflow.name === '必须保留的旧稿')).toBe(true);
});

it('ignores a late initial response after a newer focus request has loaded the shared draft', async () => {
  const api = server();
  const send = api.fetcher.getMockImplementation()!;
  const gate = deferred<void>();
  let first = true;
  api.fetcher.mockImplementation(async (url, init) => {
    const result = await send(url, init);
    if (url.endsWith('/workflow/draft') && first) {first = false; await gate.promise;}
    return result;
  });
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  expect(hook.result.current.loading).toBe(true);
  api.change('其他浏览器新配置');
  act(() => {window.dispatchEvent(new Event('focus'));});
  await settle();
  await act(async () => {gate.resolve();});
  expect(hook.result.current.workflow?.name).toBe('其他浏览器新配置');
  expect(hook.result.current.revision).toBe(2);
});

it('does not start an autosave or further polling after unmount', async () => {
  const api = server();
  const hook = renderHook(useSharedWorkflowDraft);
  await settle();
  act(() => hook.result.current.setWorkflow(workflow('尚未发出')));
  hook.unmount();
  const before = api.fetcher.mock.calls.length;
  await advance(6000);
  expect(api.fetcher.mock.calls.length).toBe(before);
  expect(api.current.workflow.name).toBe('单题学习');
});

it('saves the active workflow and advanced backup together and synchronizes both clients', async () => {
  const api = server();
  const a = renderHook(useSharedWorkflowDraft);
  const b = renderHook(useSharedWorkflowDraft);
  await settle();
  act(() => {
    a.result.current.setAdvancedBackup(workflow('之前的题对方案'));
    a.result.current.setWorkflow(workflow('当前单题方案'));
  });
  await advance();
  expect(api.current.revision).toBe(2);
  expect(api.current.advanced_backup?.name).toBe('之前的题对方案');
  await advance(2500);
  expect(b.result.current.workflow?.name).toBe('当前单题方案');
  expect(b.result.current.advancedBackup?.name).toBe('之前的题对方案');
  const currentBackup = b.result.current.advancedBackup;
  await advance(2500);
  expect(b.result.current.advancedBackup).toBe(currentBackup);
});
