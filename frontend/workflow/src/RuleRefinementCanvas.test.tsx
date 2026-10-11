import {it,expect} from 'vitest';
import fixture from './ruleWorkflowFixture.json';
import {addGrouping,removeGrouping,connectFeedback,groupOrder} from './RuleRefinementCanvas';
import {parseWorkflow} from './state';
import {migrateWorkflowLayout} from './workflowLayout';
it('adds and orders actual material routes while protecting validation gates',()=>{
 let flow=addGrouping(structuredClone(fixture),'type');flow=addGrouping(flow,'rule');
 expect(groupOrder(flow)).toEqual(['group_type','group_rule']);
 flow=connectFeedback(flow,{source:'verify',target:'group_rule',sourceHandle:'sealed_feedback',targetHandle:'sealed_feedback'});
 expect(groupOrder(flow)).toEqual(['group_rule','group_type']);
 expect(()=>connectFeedback(flow,{source:'initialize',target:'revise',sourceHandle:'rule_kb',targetHandle:'sealed_feedback'})).toThrow();
 flow=removeGrouping(flow,'group_rule');expect(groupOrder(flow)).toEqual(['group_type']);expect(flow.edges.some(e=>e.source==='verify'&&e.target==='accept')).toBe(true);
});
it('roundtrips v2 mappings and preserves user layout and selection',()=>{
 const flow=structuredClone(fixture);flow.nodes[0].position={x:198,y:399};
 expect(parseWorkflow(JSON.stringify(flow))).toEqual(flow);expect(migrateWorkflowLayout(flow)).toEqual(flow);
 expect(()=>parseWorkflow(JSON.stringify({...flow,settings:{method_id:'scientific'}}))).toThrow();
});
