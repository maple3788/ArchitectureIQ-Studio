import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {WorkflowStages} from './WorkflowStages';
import {LiveRunContext} from './LiveWorkflowCanvas';
import type {MethodDefinition,Run,Workflow} from './types';

vi.mock('./ResearchPathCanvas',()=>({ResearchPathCanvas:({nodes,selectedId,onSelect,inspector,toolbar,footer}:any)=><div>{toolbar}<nav aria-label="研究步骤">{nodes.map((node:any)=><button key={node.id} aria-pressed={node.id===selectedId} onClick={()=>onSelect(node.id)}>{node.label}</button>)}</nav><section aria-label="节点详情">{inspector}</section>{footer}</div>}));
afterEach(cleanup);
const workflow:Workflow={schema_version:1,name:'Study',settings:{method_id:'paired_progressive',model_id:'m',max_rounds:2},nodes:['input','solver','discoverer','experiment','confirmation','publish','loop','evaluate'].map(id=>({id,type:['solver','discoverer'].includes(id)?'agent':'program',position:{x:0,y:0},config:{}})),edges:[]};
const method:MethodDefinition={id:'paired_progressive',version:1,name:'反事实',description:'',adaptation:'',status:'available',learning_protocol:'paired_progressive',experience_mode:'off',hash:'frozen',steps:[{id:'assemble',stage_id:'data',label:'组装题目与材料',node_ids:['input']},{id:'pair_induction',stage_id:'harness',label:'从正常题归纳',node_ids:['discoverer']},{id:'pair_revision',stage_id:'harness',label:'修订条件与例外',node_ids:['discoverer']},{id:'experiment',stage_id:'harness',label:'执行受控实验',node_ids:['experiment']},{id:'loop',stage_id:'kb',label:'决定是否继续',node_ids:['loop']},{id:'evaluate',stage_id:'task',label:'独立新题效果验证',node_ids:['evaluate']}]};
const props=()=>({workflow,methods:[method],models:[{id:'m',name:'Model',model:'m',base_url:'',parameters:{},enabled:true}],onResearch:vi.fn(),onTask:vi.fn(),onDataset:vi.fn(),onSetting:vi.fn(),onPhase:vi.fn(),onRoute:vi.fn(),onPrompt:vi.fn(),children:<details><summary>内部流程与高级配置</summary><span>Legacy settings</span></details>});

it('configures only the selected research step and retains paired actor, Dataset, and evaluation callbacks',()=>{
 const p=props();render(<WorkflowStages {...p}/>);
 const inspector=()=>within(screen.getByRole('region',{name:'节点详情'}));
 expect(inspector().getByRole('button',{name:'从 Dataset 选择'})).toBeTruthy();
 expect(screen.queryByLabelText('安排独立评测')).toBeNull();
 fireEvent.click(inspector().getByRole('button',{name:'从 Dataset 选择'}));expect(p.onDataset).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByRole('button',{name:'从正常题归纳'}));
 fireEvent.change(inspector().getByLabelText('角色任务补充指令'),{target:{value:'只看正常题'}});
 expect(p.onPrompt).toHaveBeenCalledWith('discoverer','只看正常题');
 fireEvent.click(screen.getByRole('button',{name:'决定是否继续'}));
 fireEvent.change(inspector().getByLabelText('研究轮数'),{target:{value:'3'}});expect(p.onSetting).toHaveBeenCalledWith('max_rounds',3);
 fireEvent.click(screen.getByRole('button',{name:'独立新题效果验证'}));
 fireEvent.click(inspector().getByLabelText('安排独立评测'));expect(p.onRoute).toHaveBeenCalledWith('evaluation',true);
 fireEvent.click(inspector().getByRole('button',{name:'选择独立评测题目'}));expect(p.onTask).toHaveBeenCalledOnce();
 expect(screen.getByText('内部流程与高级配置').tagName).toBe('SUMMARY');
});

it('keeps user focus across live updates and restores following only on request',()=>{
 const p=props();
 const run:Run={id:'r',kind:'workflow',status:'running',created_at:1,config:{workflow,method},progress:{step_id:'pair_induction',stage_id:'harness',node_id:'discoverer',round_index:1,state:'running'},events:[]};
 const view=render(<LiveRunContext.Provider value={{run}}><WorkflowStages {...p}/></LiveRunContext.Provider>);
 expect(screen.getByRole('button',{name:'从正常题归纳'}).getAttribute('aria-pressed')).toBe('true');
 fireEvent.click(screen.getByRole('button',{name:'组装题目与材料'}));
 view.rerender(<LiveRunContext.Provider value={{run:{...run,progress:{...run.progress,step_id:'pair_revision'}}}}><WorkflowStages {...p}/></LiveRunContext.Provider>);
 expect(screen.getByRole('button',{name:'组装题目与材料'}).getAttribute('aria-pressed')).toBe('true');
 fireEvent.click(screen.getByRole('button',{name:'跟随当前步骤'}));
 expect(screen.getByRole('button',{name:'修订条件与例外'}).getAttribute('aria-pressed')).toBe('true');
 expect(screen.queryByLabelText('角色任务补充指令')).toBeNull();
});
