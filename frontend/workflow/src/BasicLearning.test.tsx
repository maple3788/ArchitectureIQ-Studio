import {afterEach,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import {BasicLearning} from './BasicLearning';
import type {Run,Workflow} from './types';

const ids=['input','solver','commit','reveal','experience_curator','experience_save','loop','end'];
const workflow:Workflow={schema_version:1,name:'单题学习',settings:{method_id:'basic_learning',model_id:'m',max_rounds:2,use_previous_experience:true,record_conditions:true},nodes:ids.map((id,i)=>({id,type:['solver','experience_curator'].includes(id)?'agent':'program',position:{x:0,y:i*100},config:{}})),edges:ids.slice(1).map((id,i)=>({id:`e${i}`,source:ids[i],target:id}))};
const model={id:'m',name:'真实模型',model:'m',enabled:true,base_url:'http://model',parameters:{},health:{status:'verified'}};
const props={workflow,models:[model],onResearch:vi.fn(),onSetting:vi.fn(),onPrompt:vi.fn(),version:0};
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.clearAllMocks();});
it('shows API identity limits in the selected model configuration',()=>{
 render(<BasicLearning {...props} models={[{...model,connection_type:'api'}]}/>);
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 expect(screen.getByText(/API 服务，权重身份未验证/)).toBeTruthy();
});
it('selects a node and changes only its real frozen-draft settings',()=>{
 render(<BasicLearning {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 expect(screen.getByRole('checkbox',{name:'后续轮次叠加本次学习的经验'})).toBeTruthy();
 fireEvent.click(screen.getByRole('checkbox',{name:'后续轮次叠加本次学习的经验'}));
 expect(props.onSetting).toHaveBeenCalledWith('use_previous_experience',false);
 expect(screen.queryByRole('tab',{name:'输出'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'提炼经验'}));
 expect(screen.getByRole('checkbox',{name:'记录适用条件与例外'})).toBeTruthy();
});
it('shows only the selected round and node output, with real SSE attribution',async()=>{
 const sources:any[]=[];
 class Source {listeners:Record<string,Function>={}; constructor(public url:string){sources.push(this);}addEventListener(k:string,f:Function){this.listeners[k]=f;}close(){} }
 vi.stubGlobal('EventSource',Source);
 const run:Run={id:'r',kind:'workflow',created_at:1,status:'running',transport:{stream:true},config:{workflow},progress:{node_id:'solver',step_id:'solve',round_index:2,state:'running',key:'q'},events:[{type:'stage',node_id:'solver',step_id:'solve',round_index:1,state:'complete',key:'q'},{type:'stage',node_id:'solver',step_id:'solve',round_index:2,state:'running',key:'q'}],node_observations:[{node_id:'solver',step_id:'solve',round_index:1,key:'q',availability:'available',input:{prompt:'earlier input'},output:{result:{rationale:'earlier output',ranking:['A']}}}]};
 render(<BasicLearning {...props} run={run}/>);
 await waitFor(()=>expect(sources.length).toBe(1));
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 fireEvent.click(screen.getByRole('tab',{name:'输出'}));
 sources[0].listeners.chunk({data:JSON.stringify({seq:1,wire_key:'w',node_id:'solver',round_index:2,operation_key:'q',kind:'chunk',chunk:{choices:[{delta:{content:'真实增量正文'}}]}})});
 await screen.findByText('真实增量正文');
 expect(screen.queryByText('earlier output')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'对照结果'}));
 expect(screen.queryByText('真实增量正文')).toBeNull();
});
it('renders frozen model and learning settings in Chinese and cannot edit the run',()=>{
 const run:Run={id:'sealed',kind:'workflow',created_at:1,status:'complete',config:{workflow,models:[model]},events:[]};
 const {rerender}=render(<BasicLearning {...props} run={run}/>);
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 fireEvent.click(screen.getByRole('tab',{name:'配置'}));
 expect(screen.getByText('作答模型')).toBeTruthy();
 expect(screen.getByText('起始知识')).toBeTruthy();
 expect(screen.getByText('叠加本次学习的经验')).toBeTruthy();
 expect(screen.queryByRole('checkbox',{name:'后续轮次叠加本次学习的经验'})).toBeNull();
 fireEvent.click(screen.getByRole('tab',{name:'输出'}));
 rerender(<BasicLearning {...props}/>);
 expect(screen.getByRole('checkbox',{name:'后续轮次叠加本次学习的经验'})).toBeTruthy();
});
it('shows the saved experience version and offers manual repeat using that setting',()=>{
 const run:Run={id:'waiting',kind:'workflow',created_at:1,status:'waiting_round',config:{workflow},round_decision:{round_index:1,kb_version:'formal-unchanged',next_round_available:true,next_round_index:2,next_question_ids:['q'],available_actions:['continue','finish'],status:'waiting'},node_observations:[{node_id:'experience_save',step_id:'experience_save',round_index:1,availability:'available',output:{version:'experience-v1'}}]};
 render(<BasicLearning {...props} run={run}/>);
 expect(screen.getByText(/当前经验版本/)).toBeTruthy();
 expect(screen.getByTitle('experience-v1')).toBeTruthy();
 expect(screen.getByRole('button',{name:'带着经验再试一次'})).toBeTruthy();
 expect(screen.queryByText('formal-unchanged')).toBeNull();
});

it('keeps the initial KB independent from the previous-round experience toggle',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{id:'selected',version:'v1',name:'已有学习经验',kind:'experience',counts:{active_lessons:1},snapshot:{lessons:[]}}]}))));
 render(<BasicLearning {...props} workflow={{...workflow,settings:{...workflow.settings,initial_kb:{id:'selected',version:'v1'}}}}/>);
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 await screen.findByText('已有学习经验');
 fireEvent.click(screen.getByRole('checkbox',{name:'后续轮次叠加本次学习的经验'}));
 expect(props.onSetting).toHaveBeenCalledTimes(1);
 expect(props.onSetting).toHaveBeenCalledWith('use_previous_experience',false);
 expect(screen.getByText('已有学习经验')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'清除起始 KB'}));
 expect(props.onSetting).toHaveBeenCalledWith('initial_kb',null);
});
it('shows the frozen initial KB without loading a newer server version',()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const run:Run={id:'frozen',kind:'workflow',created_at:1,status:'complete',config:{workflow,models:[model],initial_kb:{id:'selected',version:'v1',name:'已冻结学习经验',kind:'experience',counts:{active_lessons:1},snapshot:{lessons:[{id:'one',status:'active',text:'冻结经验正文',conditions:[],exceptions:[]}]}}},events:[]};
 render(<BasicLearning {...props} run={run}/>);
 fireEvent.click(screen.getByRole('button',{name:'作答'}));
 fireEvent.click(screen.getByRole('tab',{name:'配置'}));
 expect(screen.getByText('已冻结学习经验')).toBeTruthy();
 expect(screen.getByText('冻结经验正文')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'更换 KB'})).toBeNull();
 expect(fetch).not.toHaveBeenCalled();
});
