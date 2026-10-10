import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,render,screen} from '@testing-library/react';
import {LiveOutput,useLiveOutput,RunStreamProvider} from './LiveOutput';
import type {Run} from './types';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('shows an arriving delta while the run is pending and never presents it as parsed final output',()=>{
  let source:any;
  class FakeSource{listeners:Record<string,Function>={};close=vi.fn();onerror:any;constructor(public url:string){source=this;}addEventListener(name:string,fn:Function){this.listeners[name]=fn;}}
  vi.stubGlobal('EventSource',FakeSource);
  const run:Run={id:'live',kind:'workflow',status:'running',created_at:1,config:{transport:{stream:true}}};
  function Reader(){return <LiveOutput live={useLiveOutput(run)} nodeId="solver" round={1} operationKey="q1"/>;}
  const view=render(<Reader/>);
  expect(source.url).toContain('/runs/live/stream?after=0');
  act(()=>source.listeners.chunk({data:JSON.stringify({seq:1,wire_key:'wire0',node_id:'solver',round_index:1,operation_key:'q1',kind:'chunk',chunk:{choices:[{index:0,delta:{content:'{"rank'}}]}})}));
  expect(screen.getByText('{"rank')).toBeTruthy();
  expect(screen.getByText('生成中 · 尚未提交')).toBeTruthy();
  act(()=>source.onerror());
  expect(screen.getByText(/服务器任务继续运行/)).toBeTruthy();
  act(()=>source.listeners.terminal({data:'{"status":"complete"}'}));
  expect(source.close).toHaveBeenCalledTimes(1);
  view.unmount();
});

it('shares one stream across stage and advanced readers',()=>{
  const opened=vi.fn(),closed=vi.fn();
  class Source{constructor(){opened();}addEventListener(){}close=closed;onerror:any;}
  vi.stubGlobal('EventSource',Source);
  const run:Run={id:'shared',kind:'workflow',status:'running',created_at:1,config:{transport:{stream:true}}};
  function Reader(){useLiveOutput(run);return null;}
  const view=render(<RunStreamProvider run={run}><Reader/><Reader/></RunStreamProvider>);
  expect(opened).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(closed).toHaveBeenCalledTimes(1);
});
