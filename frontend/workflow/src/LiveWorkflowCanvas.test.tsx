import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {LiveWorkflowCanvas,LiveWorkflowStage} from './LiveWorkflowCanvas';
import type {Workflow,Run} from './types';
vi.mock('./RunWorkflowView',()=>({RunWorkflowView:({nodeIds}:any)=><div data-testid="inspect">{nodeIds?.join(',')}</div>}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const draft:Workflow={schema_version:1,name:'draft',settings:{},nodes:['input','solver','publish','evaluate'].map((id,i)=>({id,type:'program',position:{x:0,y:i*100},config:{}})),edges:[{id:'a',source:'input',target:'solver'},{id:'b',source:'solver',target:'publish'}]};
const run:Run={id:'r',kind:'workflow',created_at:1,status:'running',config:{workflow:draft},progress:{node_id:'solver',round_index:1,state:'running'}};
function canvas(value?:Run){return <LiveWorkflowCanvas draft={draft} run={value} act={async op=>op()}>{(['data','harness','kb','task'] as const).map(id=><LiveWorkflowStage key={id} stageId={id} title={id} number={id} description={id} icon={null}><input aria-label={'draft-'+id}/></LiveWorkflowStage>)}</LiveWorkflowCanvas>;}
it('retains the same canvas and stage DOM when Start attaches a frozen run',()=>{const v=render(canvas());const c=screen.getByTestId('live-workflow-canvas'),stage=screen.getByTestId('live-stage-data');v.rerender(canvas(run));expect(screen.getByTestId('live-workflow-canvas')).toBe(c);expect(screen.getByTestId('live-stage-data')).toBe(stage);});
it('preserves user focus during updates and provides explicit follow-current',()=>{const v=render(canvas(run));fireEvent.click(screen.getByRole('button',{name:'查看 data'}));expect(screen.getByTestId('inspect').textContent).toBe('input');v.rerender(canvas({...run,progress:{node_id:'publish',state:'running',round_index:2}}));expect(screen.getByTestId('inspect').textContent).toBe('input');fireEvent.click(screen.getByRole('button',{name:'跟随当前步骤'}));expect(screen.getByTestId('inspect').textContent).toBe('publish');});
it('sends one server-owned decision with exact round identity while double clicked',async()=>{
 let resolve!:(v:Response)=>void;const calls:any[]=[];vi.stubGlobal('fetch',vi.fn((url,init)=>{calls.push({url,body:JSON.parse(init.body)});return new Promise(r=>resolve=r);}));
 render(canvas({...run,status:'waiting_round',round_decision:{round_index:1,kb_version:'kb2',available_actions:['continue','finish'],next_round_available:true,next_round_index:2,next_question_ids:['next'],next_round_reason:'ready',status:'waiting'}}));
 const button=screen.getByRole('button',{name:'继续下一轮'});fireEvent.click(button);fireEvent.click(button);expect(calls).toHaveLength(1);expect(calls[0].body).toEqual({round_index:1,action:'continue'});resolve(new Response(JSON.stringify({status:'running'})));await waitFor(()=>expect(screen.getByText('决定已提交，等待服务器同步')).toBeTruthy());expect((button as HTMLButtonElement).disabled).toBe(true);
});
it('shows frozen empirical lessons and provenance separately from verified scientific knowledge',()=>{
 const value={...run,node_observations:[{node_id:'loop',round_index:1,availability:'partial',output:{experience:{before:'mem1',after:'mem2',operations:[{op:'add',lesson_id:'L1'}],after_snapshot:{scientific_status:'unverified',lessons:[{id:'L1',text:'Check the budget before comparing',conditions:['Equal budget'],exceptions:['Different datasets'],source_episode_ids:['episode1'],status:'active',scientific_status:'unverified',reason:'Different sizes changed the outcome'}]}}}}]};
 render(canvas(value));fireEvent.click(screen.getByRole('button',{name:'查看 kb'}));expect(screen.getByText('Check the budget before comparing')).toBeTruthy();expect(screen.getByText('Equal budget',{selector:'dd'})).toBeTruthy();expect(screen.getByText('关联 1 次作答记录')).toBeTruthy();expect(screen.getByText('经验记忆 · 未验证')).toBeTruthy();
});
