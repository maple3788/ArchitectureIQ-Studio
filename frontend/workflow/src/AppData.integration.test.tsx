import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import App from './App';
import {datasetFixture, summaryFixture, page} from './dataTestFixtures';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); location.hash = ''; });

it.each([false, true])('keeps the Dataset builder through App refreshes (offline=%s)', async (offline) => {
  location.hash = '#data';
  let bootstraps = 0;
  let releaseRefresh: (() => void) | undefined;
  const bootstrap = {
    service: {execution_enabled: true, host: 'mock server'}, stats: {},
    capabilities: {profiles: [{name: 'v1.5', budgets: [64], n_seeds: 2, num_choices: 3,
      families: [{name: 'test-family', model_types: ['mlp'], options: []}]}]},
  };
  vi.stubGlobal('fetch', async (path: string, init?: RequestInit) => {
    const url = new URL(path, 'http://localhost');
    let value: unknown;
    if (url.pathname.endsWith('/bootstrap')) {
      if (++bootstraps > 1) await new Promise<void>(resolve => { releaseRefresh = resolve; });
      if (bootstraps > 1 && offline) return new Response('{"detail":"Disconnected"}', {status:503});
      value = bootstrap;
    } else if (url.pathname.endsWith('/generations/preview')) {
      value = {...JSON.parse(String(init?.body)), dataset_count: 3, candidate_seed_runs: 180,
        dataset_preview_hash: 'preview', total_samples_seen: 11520};
    } else if (url.pathname.endsWith('/datasets')) value = page([summaryFixture]);
    else if (url.pathname.endsWith('/datasets/ds_a')) value = datasetFixture;
    else value = page([]);
    return new Response(JSON.stringify(value));
  });
  render(<App/>);
  fireEvent.click(await screen.findByRole('button', {name: '打开 Dataset A'}));
  fireEvent.click(await screen.findByRole('button', {name: '构建题目'}));
  fireEvent.change(await screen.findByLabelText('请求题目数量'), {target: {value: '7'}});
  fireEvent.click(screen.getByRole('button', {name: '冻结 spec 预览'}));
  await waitFor(() => expect(bootstraps).toBe(2));
  expect(screen.getByRole('heading', {name: '构建研究题目'})).toBeTruthy();
  expect((screen.getByLabelText('请求题目数量') as HTMLInputElement).value).toBe('7');
  expect(screen.getByText('180')).toBeTruthy();
  expect((screen.getByRole('button', {name:'提交生成任务'}) as HTMLButtonElement).disabled).toBe(true);
  releaseRefresh?.();
  if (offline) {
    expect(await screen.findByText('API 离线')).toBeTruthy();
    expect((screen.getByRole('button', {name:'提交生成任务'}) as HTMLButtonElement).disabled).toBe(true);
  } else {
    await waitFor(() => expect((screen.getByRole('button', {name:'提交生成任务'}) as HTMLButtonElement).disabled).toBe(false));
  }
  expect((screen.getByLabelText('请求题目数量') as HTMLInputElement).value).toBe('7');
  expect(screen.getByText('180')).toBeTruthy();
});
