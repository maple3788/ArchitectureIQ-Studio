import {expect,it} from 'vitest';
import fixture from './ruleWorkflowFixture.json';
import {ruleLoopPresentation,rulePhaseStage} from './ruleLoopPresentation';
import type {Run,Workflow} from './types';

it('projects both learning loops without changing persisted routes or custom positions',()=>{
 const workflow:Workflow=structuredClone(fixture);workflow.nodes[0].position={x:1234,y:789};
 const before=structuredClone(workflow),view=ruleLoopPresentation({workflow});
 expect(workflow).toEqual(before);
 expect(view.nodes.find(node=>node.id==='input')!.position).not.toEqual({x:1234,y:789});
 expect(view.edges.some(edge=>edge.source==='verify'&&edge.target==='feedback')).toBe(true);
 expect(view.edges.some(edge=>edge.source==='feedback'&&edge.target==='revise')).toBe(true);
 expect(view.edges.some(edge=>edge.source==='revise'&&edge.target==='accept')).toBe(true);
 expect(view.edges.some(edge=>edge.source==='accept'&&edge.target==='verify'&&edge.loop)).toBe(true);
 expect(view.edges.some(edge=>edge.source==='verify'&&edge.target==='challenge')).toBe(true);
 expect(view.edges.some(edge=>edge.source==='challenge'&&edge.target==='verify'&&edge.loop)).toBe(true);
 expect(view.nodes.every(node=>node.status===undefined)).toBe(true);
});

it('maps persisted execution phases without turning earlier nodes into invented successes',()=>{
 const run:Run={id:'r',kind:'rule_refinement',status:'running',created_at:1,config:{},events:[{sequence:1,phase:'challenge',node_id:'challenge'},{sequence:2,phase:'first_test',node_id:'verify'}]};
 const view=ruleLoopPresentation({run});
 expect(view.nodes.filter(node=>node.status).map(node=>[node.id,node.status])).toEqual([['verify','running']]);
 const paused=ruleLoopPresentation({run:{...run,status:'paused',refinement:{phase:'accept'}}});
 expect(paused.nodes.find(node=>node.id==='accept')?.status).toBe('paused');
 expect(rulePhaseStage('candidate_check')).toBe('verify');
 expect(rulePhaseStage('promote')).toBe('input');
 expect(rulePhaseStage('unknown')).toBeUndefined();
});

it('uses result evidence for completion and never calls a budget stop a successful loop',()=>{
 const base:Run={id:'r',kind:'rule_refinement',status:'complete',created_at:1,config:{},refinement:{phase:'finish'},events:[]};
 const stopped=ruleLoopPresentation({run:{...base,result:{outcome:'stopped',stop_reason:'resource_limit'}}});
 expect(stopped.nodes.find(node=>node.id==='save')?.status).toBe('已停止');
 expect(stopped.nodes.some(node=>node.status==='complete')).toBe(false);
 const achieved=ruleLoopPresentation({run:{...base,result:{outcome:'target_reached',stop_reason:'target_reached'}}});
 expect(achieved.nodes.find(node=>node.id==='save')?.status).toBe('complete');
 const empty=ruleLoopPresentation({run:{...base,status:'running',refinement:undefined}});
 expect(empty.nodes.every(node=>node.status===undefined)).toBe(true);
});

it('never uses an editing draft to represent a frozen run',()=>{
 const workflow:Workflow=structuredClone(fixture);workflow.nodes[0].label='UNSAVED PRIVATE DRAFT';
 workflow.nodes[1].config.mode='model';
 const run:Run={id:'r',kind:'rule_refinement',status:'running',created_at:1,config:{},events:[]};
 const view=ruleLoopPresentation({workflow,run});
 expect(view.nodes.some(node=>node.label==='UNSAVED PRIVATE DRAFT')).toBe(false);
 expect(view.nodes.find(node=>node.id==='initialize')?.kind).toBe('program');
});
