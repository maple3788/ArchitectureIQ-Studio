import { expect, it } from 'vitest';
import { migrateWorkflowLayout } from './workflowLayout';
import type { Workflow } from './types';
const stages = ['input','solver','commit','reveal','discoverer','skeptic','experiment','confirmation','analyst','curator','publish','loop','evaluate','end'];
const old: Workflow = {schema_version:1,name:'Saved draft',nodes:stages.map((id,i)=>({id,type:id==='solver'?'agent':'program',position:{x:(i%7)*230,y:Math.floor(i/7)*190},config:id==='solver'?{role:'solver',prompt:'Keep my exact guidance'}:{}})),edges:[{id:'route',source:'loop',target:'input',condition:'continue',source_handle:'out',target_handle:'in',mapping:{}}],settings:{model_id:'model-v7',question_set_id:'frozen-v3',max_rounds:3,discovery_per_round:2,custom_reference:'/server/saved'}};
it('migrates a legacy horizontal draft vertically without changing execution identity',()=>{
 const next=migrateWorkflowLayout(old);
 expect(next.nodes.find(n=>n.id==='input')!.position.y).toBeLessThan(next.nodes.find(n=>n.id==='solver')!.position.y);
 expect(next.nodes.find(n=>n.id==='solver')!.position.x).toBe(next.nodes.find(n=>n.id==='input')!.position.x);
 expect(next.nodes.find(n=>n.id==='confirmation')!.position.x).toBeGreaterThan(next.nodes.find(n=>n.id==='input')!.position.x);
 expect(next.nodes.find(n=>n.id==='confirmation')!.position.y).toBeGreaterThan(next.nodes.find(n=>n.id==='experiment')!.position.y);
 expect(next.nodes.find(n=>n.id==='analyst')!.position.y).toBeGreaterThan(next.nodes.find(n=>n.id==='confirmation')!.position.y);
 expect(next.settings).toEqual(old.settings);expect(next.edges).toEqual(old.edges);
 expect(next.nodes.map(({position,...node})=>node)).toEqual(old.nodes.map(({position,...node})=>node));
 expect(old.nodes[1].position).toEqual({x:230,y:0});
});
it('keeps a customized vertical arrangement unchanged across repeated loads',()=>{
 const vertical=migrateWorkflowLayout(old);
 const custom={...vertical,nodes:vertical.nodes.map(node=>node.id==='solver'?{...node,position:{x:106,y:231}}:node)};
 expect(migrateWorkflowLayout(custom)).toBe(custom);
});
it('handles a short imported horizontal graph without inventing stages or routes',()=>{
 const short={...old,nodes:old.nodes.slice(0,2),edges:[]};const next=migrateWorkflowLayout(short);
 expect(next.nodes).toHaveLength(2);expect(next.edges).toEqual([]);
 expect(next.nodes[1].position.y).toBeGreaterThan(next.nodes[0].position.y);
});
