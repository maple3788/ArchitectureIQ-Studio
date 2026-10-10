import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { api, ApiError } from './api';
import { draftKey, parseWorkflow } from './state';
import type { Workflow } from './types';

export type SharedDraftStatus = 'loading' | 'saved' | 'saving' | 'pending' | 'offline' | 'conflict';
export type WorkflowDraftBackup = {id: string; workflow: Workflow; advanced_backup?: Workflow | null; created_at: number; source: string};
type Snapshot = {workflow: Workflow; advanced_backup: Workflow | null; revision: number; updated_at: number};
type Payload = {workflow?: Workflow; advancedBackup?: Workflow};
type View = Payload & {
  loading: boolean;
  status: SharedDraftStatus;
  error: string;
  revision?: number;
  updatedAt?: number;
  backups: WorkflowDraftBackup[];
};
const conflictMessage = '另一浏览器已更新工作流。你的编辑已保留，请选择使用服务器版本，或保留当前编辑。';
function key(value: unknown): string {
  // JSON object key order does not constitute a configuration change.
  return JSON.stringify(value, (_name, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(name => [name, item[name]])) : item);
}
function payload(snapshot: Snapshot): Payload {
  return {workflow: snapshot.workflow, advancedBackup: snapshot.advanced_backup ?? undefined};
}
function message(error: unknown) {return error instanceof Error ? error.message : String(error);}

/** The server is authoritative. Unsent edits stay in memory and never overwrite a newer revision silently. */
export function useSharedWorkflowDraft() {
  const local = useRef<Payload>({});
  const base = useRef<Snapshot | undefined>(undefined);
  const status = useRef<SharedDraftStatus>('loading');
  const syncError = useRef('');
  const archiveError = useRef('');
  const backups = useRef<WorkflowDraftBackup[]>([]);
  const mounted = useRef(false);
  const epoch = useRef(0);
  const readSequence = useRef(0);
  const writeBusy = useRef(false);
  const resolving = useRef(false);
  const migrating = useRef<number | null>(null);
  const [view, setView] = useState<View>({loading: true, status: 'loading', error: '', backups: []});
  const dirty = useCallback(() => !!local.current.workflow && (!base.current || key(local.current) !== key(payload(base.current))), []);
  const publish = useCallback(() => {
    if (!mounted.current) return;
    setView({...local.current, loading: status.current === 'loading', status: status.current,
      error: [syncError.current, archiveError.current].filter(Boolean).join(' '),
      revision: base.current?.revision, updatedAt: base.current?.updated_at, backups: backups.current});
  }, []);
  const accept = useCallback((snapshot: Snapshot) => {
    base.current = snapshot;
    const next = payload(snapshot);
    local.current = {
      workflow: key(local.current.workflow) === key(next.workflow) ? local.current.workflow : next.workflow,
      advancedBackup: key(local.current.advancedBackup) === key(next.advancedBackup) ? local.current.advancedBackup : next.advancedBackup,
    };
    status.current = 'saved';
    syncError.current = '';
    publish();
  }, [publish]);
  const refreshBackups = useCallback(async () => {
    const started = epoch.current;
    try {
      const result = await api<{items: WorkflowDraftBackup[]}>('/workflow/draft/backups');
      if (mounted.current && started === epoch.current) {backups.current = result.items; publish();}
    } catch (error) {
      if (mounted.current && started === epoch.current) {archiveError.current = '备份列表暂时无法读取：' + message(error); publish();}
    }
  }, [publish]);
  const archive = useCallback(async (workflow: Workflow | undefined, source: 'legacy_browser' | 'conflict') => {
    if (workflow) await api('/workflow/draft/backups', {workflow, source});
  }, []);
  const migrateLegacy = useCallback(async () => {
    const started = epoch.current;
    if (migrating.current === started) return;
    migrating.current = started;
    const failures: string[] = [];
    try {
      for (const name of [draftKey, draftKey + '-advanced-backup']) {
        if (!mounted.current || started !== epoch.current) return;
        try {
          const old = localStorage.getItem(name);
          if (!old) continue;
          await archive(parseWorkflow(old), 'legacy_browser');
          // Do not delete a newer legacy draft written during this request by an older tab.
          if (localStorage.getItem(name) === old) localStorage.removeItem(name);
        } catch (error) {failures.push(message(error));}
      }
      if (mounted.current && started === epoch.current) {
        archiveError.current = failures.length ? '旧浏览器草稿尚未备份，原稿已保留：' + failures.join('；') : '';
        publish();
        await refreshBackups();
      }
    } finally {if (migrating.current === started) migrating.current = null;}
  }, [archive, publish, refreshBackups]);

  const read = useCallback(async () => {
    if (writeBusy.current || resolving.current) return;
    const sequence = ++readSequence.current;
    const started = epoch.current;
    try {
      const snapshot = await api<Snapshot>('/workflow/draft');
      if (!mounted.current || started !== epoch.current || sequence !== readSequence.current || writeBusy.current || resolving.current) return;
      if (base.current && snapshot.revision < base.current.revision) return;
      if (key(local.current) === key(payload(snapshot))) {accept(snapshot); return;}
      if (status.current === 'conflict') {publish(); return;}
      if (dirty()) {
        if (!base.current || snapshot.revision !== base.current.revision) {
          status.current = 'conflict'; syncError.current = conflictMessage;
        } else {status.current = 'pending'; syncError.current = '';}
        publish();
      } else accept(snapshot);
    } catch (error) {
      if (!mounted.current || started !== epoch.current || sequence !== readSequence.current) return;
      if (status.current !== 'conflict') status.current = 'offline';
      syncError.current = '无法同步服务器草稿：' + message(error);
      publish();
    }
  }, [accept, dirty, publish]);

  const write = useCallback(async (expectedRevision?: number) => {
    if (writeBusy.current || !local.current.workflow || (!base.current && expectedRevision === undefined)) return;
    const sent = local.current;
    const signature = key(sent);
    const started = epoch.current;
    writeBusy.current = true;
    ++readSequence.current;
    status.current = 'saving'; syncError.current = ''; publish();
    try {
      const snapshot = await api<Snapshot>('/workflow/draft', {
        expected_revision: expectedRevision ?? base.current!.revision,
        workflow: sent.workflow, advanced_backup: sent.advancedBackup ?? null,
      }, 'PUT');
      if (!mounted.current || started !== epoch.current) return;
      base.current = snapshot;
      if (key(local.current) === signature) accept(snapshot);
      else {status.current = dirty() ? 'pending' : 'saved'; publish();}
    } catch (error) {
      if (!mounted.current || started !== epoch.current) return;
      if (error instanceof ApiError && error.status === 409) {
        status.current = 'conflict'; syncError.current = conflictMessage;
      } else {status.current = 'offline'; syncError.current = '修改尚未保存到服务器：' + message(error);}
      publish();
    } finally {
      if (started === epoch.current) writeBusy.current = false;
    }
  }, [accept, dirty, publish]);

  const setWorkflow: Dispatch<SetStateAction<Workflow | undefined>> = useCallback(value => {
    const next = typeof value === 'function' ? value(local.current.workflow) : value;
    if (key(next) === key(local.current.workflow)) return;
    local.current = {...local.current, workflow: next};
    if (status.current !== 'conflict' && status.current !== 'offline' && !writeBusy.current)
      status.current = dirty() ? 'pending' : 'saved';
    publish();
  }, [dirty, publish]);
  const setAdvancedBackup: Dispatch<SetStateAction<Workflow | undefined>> = useCallback(value => {
    const next = typeof value === 'function' ? value(local.current.advancedBackup) : value;
    if (key(next) === key(local.current.advancedBackup)) return;
    local.current = {...local.current, advancedBackup: next};
    if (status.current !== 'conflict' && status.current !== 'offline' && !writeBusy.current)
      status.current = dirty() ? 'pending' : 'saved';
    publish();
  }, [dirty, publish]);

  const acceptRemote = useCallback(async () => {
    if (resolving.current || writeBusy.current) return;
    resolving.current = true;
    ++readSequence.current;
    const started = epoch.current;
    const captured = local.current;
    try {
      await archive(captured.workflow, 'conflict');
      if (key(captured.advancedBackup) !== key(captured.workflow)) await archive(captured.advancedBackup, 'conflict');
      const snapshot = await api<Snapshot>('/workflow/draft');
      if (!mounted.current || started !== epoch.current) return;
      if (key(local.current) !== key(captured)) {
        status.current = 'conflict'; syncError.current = '备份期间你又修改了配置，当前编辑已保留，请再次选择。'; publish();
      } else {archiveError.current = ''; accept(snapshot);}
      await refreshBackups();
    } catch (error) {
      if (mounted.current && started === epoch.current) {
        status.current = 'conflict'; syncError.current = '尚未切换服务器版本，当前编辑已保留。备份或读取失败：' + message(error); publish();
      }
    } finally {if (started === epoch.current) resolving.current = false;}
  }, [accept, archive, publish, refreshBackups]);
  const keepLocal = useCallback(async () => {
    if (resolving.current || writeBusy.current) return;
    resolving.current = true;
    ++readSequence.current;
    const started = epoch.current;
    try {
      const latest = await api<Snapshot>('/workflow/draft');
      await archive(latest.workflow, 'conflict');
      if (key(latest.advanced_backup) !== key(latest.workflow)) await archive(latest.advanced_backup ?? undefined, 'conflict');
      if (!mounted.current || started !== epoch.current) return;
      archiveError.current = '';
      // A writer racing this choice must still cause a 409; never force an unconditional overwrite.
      await write(latest.revision);
      await refreshBackups();
    } catch (error) {
      if (mounted.current && started === epoch.current) {
        status.current = 'conflict'; syncError.current = '尚未覆盖服务器版本，当前编辑已保留。备份或读取失败：' + message(error); publish();
      }
    } finally {if (started === epoch.current) resolving.current = false;}
  }, [archive, publish, refreshBackups, write]);
  const retry = useCallback(async () => {await Promise.all([read(), migrateLegacy()]);}, [read, migrateLegacy]);

  useEffect(() => {
    mounted.current = true;
    ++epoch.current;
    void read();
    void migrateLegacy();
    const interval = window.setInterval(() => void read(), 2500);
    const focus = () => void read();
    const visible = () => {if (document.visibilityState === 'visible') void read();};
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty() || writeBusy.current) {event.preventDefault(); event.returnValue = '';}
    };
    window.addEventListener('focus', focus);
    document.addEventListener('visibilitychange', visible);
    window.addEventListener('beforeunload', beforeUnload);
    return () => {
      mounted.current = false;
      ++epoch.current;
      ++readSequence.current;
      writeBusy.current = false;
      resolving.current = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', focus);
      document.removeEventListener('visibilitychange', visible);
      window.removeEventListener('beforeunload', beforeUnload);
    };
  }, [dirty, migrateLegacy, read]);
  useEffect(() => {
    if (view.status !== 'pending' || !view.workflow) return;
    const timer = window.setTimeout(() => {
      if (!resolving.current && status.current === 'pending' && dirty()) void write();
    }, 500);
    return () => window.clearTimeout(timer);
  }, [view.status, view.workflow, view.advancedBackup, view.revision, dirty, write]);

  return {...view, setWorkflow, setAdvancedBackup, retry, acceptRemote, keepLocal, refreshBackups};
}
