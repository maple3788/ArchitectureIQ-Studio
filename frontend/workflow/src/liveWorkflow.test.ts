import { expect, it } from 'vitest';
import { deriveLiveWorkflow } from './liveWorkflow';
import type { Run, Workflow, MethodDefinition } from './types';
const draft:Workflow={schema_version:1,name:'Draft',settings:{method_id:'expel'},nodes:['input','solver','publish','evaluate'].map((id,i)=>({id,type:'program',position:{x:0,y:i*100},config:{}})),edges:[{id:'a',source:'input',target:'solver'},{id:'b',source:'solver',target:'publish'}]};
const method:MethodDefinition={id:'scientific',version:1,name:'Frozen method',description:'Research',adaptation:'Adapted',paper_url:null,status:'runnable_adaptation',learning_protocol:'single',experience_mode:'off',hash:'abc',steps:[{id:'solve',stage_id:'harness',label:'Blind solve',node_ids:['solver']}]};
const run:Run={id:'r',kind:'workflow',status:'running',created_at:1,config:{workflow:{...draft,name:'Frozen graph'},method},events:[{type:'stage',node_id:'solver',state:'complete',round_index:1},{type:'stage',node_id:'input',state:'complete',round_index:2}],progress:{node_id:'input',state:'complete',round_index:2}};
it('projects frozen run and method independently from edited draft or current catalog',()=>{
 const view=deriveLiveWorkflow({draft,run,methodDefinition:{...method,name:'Changed catalog'},syncState:{error:'offline'}});
 expect(view.source).toBe('run');expect(view.method?.name).toBe('Frozen method');expect(view.workflow?.name).toBe('Frozen graph');expect(view.stages.map(s=>s.id)).toEqual(['data','harness','kb','task']);expect(view.syncState?.error).toBe('offline');
});
it('does not carry a completed prior round into the current round or scheduled Task',()=>{
 const view=deriveLiveWorkflow({draft,run});expect(view.round).toBe(2);expect(view.stages.find(s=>s.id==='harness')?.status).toBe('not_run');expect(view.stages.find(s=>s.id==='task')?.status).toBe('skipped');
});
it('does not guess method step identity for legacy events, and preserves current failure',()=>{
 const legacy={...run,config:{workflow:draft},status:'failed',progress:{node_id:'solver',state:'failed',round_index:2},events:[{type:'stage',node_id:'solver',state:'failed',round_index:2}]};
 const view=deriveLiveWorkflow({draft,run:legacy,methodDefinition:method});expect(view.method).toBeUndefined();expect(view.legacy).toBe(true);expect(view.current?.stepId).toBeUndefined();expect(view.stages.find(s=>s.id==='harness')?.status).toBe('failed');
});
it('uses explicit substep identity rather than attributing shared discoverer events to all steps',()=>{
 const paired={...method,steps:[{id:'induce',stage_id:'harness',label:'Induce',node_ids:['discoverer']},{id:'experience_consolidate',stage_id:'harness',label:'Consolidate',node_ids:['discoverer']}]};
 const view=deriveLiveWorkflow({draft,run:{...run,config:{workflow:draft,method:paired},progress:{node_id:'discoverer',step_id:'experience_consolidate',state:'running',round_index:1},events:[{type:'stage',node_id:'discoverer',step_id:'experience_consolidate',state:'running',round_index:1}]}});
 expect(view.stages[1].steps.map(s=>s.status)).toEqual(['not_run','running']);expect(view.current?.stepId).toBe('experience_consolidate');
});
it('maps a terminal failure to an unfinished explicit method step',()=>{
 const view=deriveLiveWorkflow({run:{...run,status:'failed',events:[{type:'stage',step_id:'solve',node_id:'solver',round_index:1,state:'running'}],progress:{node_id:'solver',step_id:'solve',round_index:1,state:'running'}}});
 expect(view.stages.find(s=>s.id==='harness')?.steps[0].status).toBe('failed');
});
it('retains earlier-round explicit step events for historical inspection without carrying its status forward',()=>{
 const value={...run,config:{workflow:draft,method},events:[{type:'stage',node_id:'solver',step_id:'solve',round_index:1,state:'complete'},{type:'stage',node_id:'input',step_id:'assemble',round_index:2,state:'running'}],progress:{node_id:'input',step_id:'assemble',round_index:2,state:'running'}};
 const view=deriveLiveWorkflow({run:value});expect(view.stages[1].steps[0].status).toBe('not_run');expect(view.stages[1].steps[0].events[0]?.round_index).toBe(1);
});

it('attests completed Harness through sealed publication without completing unused experiments',()=>{
 const recipe={...method,steps:[...method.steps,{id:'experiment',stage_id:'harness' as const,label:'Experiment',node_ids:['experiment']},{id:'confirmation',stage_id:'harness' as const,label:'Confirmation',node_ids:['confirmation']}]};
 const value={...run,status:'waiting_round',config:{workflow:draft,method:recipe},progress:{node_id:'publish',round_index:1,state:'complete'},events:[{type:'stage',node_id:'solver',step_id:'solve',round_index:1,state:'complete'},{type:'stage',node_id:'publish',step_id:'publish',round_index:1,state:'complete'}]};
 const view=deriveLiveWorkflow({run:value});expect(view.stages[1].status).toBe('complete');expect(view.stages[1].steps.slice(1).map(s=>s.status)).toEqual(['not_run','not_run']);
});
