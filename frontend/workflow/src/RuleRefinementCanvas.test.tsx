import {afterEach,it,expect,vi} from 'vitest';
import {render,cleanup} from '@testing-library/react';
import type {Workflow} from './types';
import fixture from './ruleWorkflowFixture.json';
import {RuleRefinementCanvas,addGrouping,removeGrouping,connectFeedback,groupOrder} from './RuleRefinementCanvas';
import {parseWorkflow} from './state';
import {migrateWorkflowLayout} from './workflowLayout';
const view=vi.hoisted(()=>({props:{} as any}));
vi.mock('./ResearchPathCanvas',()=>({ResearchPathCanvas:(props:any)=>{view.props=props;return <>{props.inspector}</>;}}));
afterEach(cleanup);
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

it('shows control loops without adding them to the persisted material routes',()=>{
 const workflow:Workflow=structuredClone(fixture),before=structuredClone(workflow),onChange=vi.fn();
 render(<RuleRefinementCanvas workflow={workflow} onChange={onChange}/>);
 expect(view.props.edges.filter((edge:any)=>edge.loop).map((edge:any)=>[edge.source,edge.target])).toEqual([['accept','verify'],['challenge','verify']]);
 expect(workflow).toEqual(before);expect(onChange).not.toHaveBeenCalled();
 view.props.onMove('verify',{x:600,y:100});
 const next=onChange.mock.calls[0][0];expect(next.edges).toEqual(before.edges);expect(next.nodes.find((node:any)=>node.id==='verify').position).toEqual({x:600,y:100});
 expect(view.props.nodes.find((node:any)=>node.id==='initialize').kind).toBe('program');
 expect(view.props.nodes.find((node:any)=>node.id==='revise').kind).toBe('model');
});
