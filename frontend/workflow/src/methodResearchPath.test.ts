import { expect, it } from 'vitest';
import { deriveMethodResearchPath } from './methodResearchPath';
import type { MethodDefinition, Run, Workflow } from './types';

const workflow:Workflow={schema_version:1,name:'Research',settings:{method_id:'paired_expel',max_rounds:2},nodes:['input','solver','commit','reveal','discoverer','skeptic','experiment','confirmation','analyst','curator','publish','loop','evaluate'].map(id=>({id,type:['solver','discoverer','skeptic','analyst','curator'].includes(id)?'agent':'program',position:{x:0,y:0},config:{}})),edges:[{id:'base',source:'experiment',target:'analyst'}]};
const step=(id:string,node:string,stage_id:'data'|'harness'|'kb'|'task'='harness')=>({id,label:id,stage_id,node_ids:[node]});
const method:MethodDefinition={id:'paired_expel',version:1,name:'Frozen paired method',description:'Research',adaptation:'',status:'available',learning_protocol:'paired_progressive',experience_mode:'expel_inspired',hash:'frozen',steps:[step('assemble','input','data'),step('solve','solver'),step('commit','commit'),step('feedback','reveal'),step('pair_induction','discoverer'),step('pair_transfer','solver'),step('pair_revision','discoverer'),step('experiment','experiment'),step('confirmation','confirmation'),step('analysis','analyst'),step('experience_consolidate','discoverer'),step('curate','curator','kb'),step('publish','publish','kb'),step('loop','loop','kb'),step('evaluate','evaluate','task')]};

it('keeps separate research steps when paired inference and experience reuse model actors',()=>{
 const path=deriveMethodResearchPath({workflow,methodDefinition:method});
 expect(path.nodes.map(n=>n.id)).toEqual(method.steps.map(s=>s.id));
 expect(path.nodes.filter(n=>n.step.node_ids.includes('discoverer')).map(n=>n.id)).toEqual(['pair_induction','pair_revision','experience_consolidate']);
 expect(path.nodes.find(n=>n.id==='pair_transfer')?.kind).toBe('model');
 expect(path.edges.some(e=>e.source==='pair_induction'&&e.target==='pair_transfer')).toBe(true);
 expect(path.edges.some(e=>e.source==='pair_transfer'&&e.target==='pair_revision')).toBe(true);
});

it('keeps unarranged confirmation and Task inspectable without presenting a required route',()=>{
 const path=deriveMethodResearchPath({workflow,methodDefinition:method});
 expect(path.nodes.find(n=>n.id==='confirmation')?.arranged).toBe(false);
 expect(path.nodes.find(n=>n.id==='evaluate')?.arranged).toBe(false);
 expect(path.edges.some(e=>e.target==='confirmation'||e.target==='evaluate')).toBe(false);
 expect(path.edges.some(e=>e.source==='experiment'&&e.target==='analysis')).toBe(true);
 const enabled=deriveMethodResearchPath({workflow:{...workflow,edges:[...workflow.edges,{id:'confirmation',source:'experiment',target:'confirmation'},{id:'evaluation',source:'loop',target:'evaluate'}]},methodDefinition:method});
 expect(enabled.edges.find(e=>e.target==='confirmation')?.optional).toBe(true);
 expect(enabled.edges.find(e=>e.target==='evaluate')?.optional).toBe(true);
 expect(enabled.edges.find(e=>e.loop)?.target).toBe('assemble');
 expect(workflow.edges).toHaveLength(1);
});

it('uses frozen method identity and explicit events without borrowing catalog labels or shared actor status',()=>{
 const run:Run={id:'run',kind:'workflow',status:'running',created_at:1,config:{workflow,method},progress:{node_id:'discoverer',step_id:'experience_consolidate',stage_id:'harness',round_index:2,state:'running'},events:[{type:'stage',node_id:'discoverer',step_id:'experience_consolidate',stage_id:'harness',round_index:2,state:'running'}]};
 const path=deriveMethodResearchPath({workflow,run,methodDefinition:{...method,name:'Changed catalog',steps:[step('rewritten','solver')]}});
 expect(path.view.method?.name).toBe('Frozen paired method');
 expect(path.nodes.find(n=>n.id==='experience_consolidate')?.status).toBe('running');
 expect(path.nodes.find(n=>n.id==='pair_induction')?.status).toBe('not_run');
 expect(path.nodes.some(n=>n.id==='rewritten')).toBe(false);
 const legacy=deriveMethodResearchPath({workflow,methodDefinition:method,run:{...run,config:{workflow}}});
 expect(legacy.view.method).toBeUndefined();
 expect(legacy.nodes.some(n=>n.id==='pair_induction')).toBe(false);
 expect(legacy.nodes.some(n=>n.id==='discoverer')).toBe(true);
});
