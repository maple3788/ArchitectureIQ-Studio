import {afterEach,it,expect,vi} from 'vitest';
import {render,cleanup,screen,fireEvent} from '@testing-library/react';
import type {Workflow} from './types';
import fixture from './ruleWorkflowFixture.json';
import {RuleRefinementCanvas,addGrouping,removeGrouping,connectFeedback,groupOrder} from './RuleRefinementCanvas';
import {parseWorkflow} from './state';
import {migrateWorkflowLayout} from './workflowLayout';
const view=vi.hoisted(()=>({props:{} as any}));
vi.mock('./ResearchPathCanvas',()=>({ResearchPathCanvas:(props:any)=>{view.props=props;return <>{props.toolbar}{props.nodes.map((node:any)=><button key={node.id} onClick={()=>props.onSelect(node.id)}>{node.label}</button>)}{props.inspector}</>;}}));
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

it('starts with the feedback loop and no inspector, while preserving the frozen material graph',()=>{
 const workflow:Workflow=structuredClone(fixture),before=structuredClone(workflow),onChange=vi.fn();
 render(<RuleRefinementCanvas workflow={workflow} onChange={onChange} renderConfig={node=><p>配置 {node.id}</p>}/>);
 expect(screen.queryByText('配置 input')).toBeNull();
 expect(screen.getByRole('button',{name:'错题反馈'})).toBeTruthy();
 expect(view.props.edges.some((edge:any)=>edge.source==='verify'&&edge.target==='feedback')).toBe(true);
 expect(view.props.onMove).toBeUndefined();
 fireEvent.click(screen.getByRole('button',{name:'研究题池'}));expect(screen.getByText('配置 input')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'关闭节点详情'}));expect(screen.queryByText('配置 input')).toBeNull();
 expect(workflow).toEqual(before);expect(onChange).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'材料连线'}));
 view.props.onMove('verify',{x:600,y:100});
 const next=onChange.mock.calls[0][0];expect(next.edges).toEqual(before.edges);expect(next.nodes.find((node:any)=>node.id==='verify').position).toEqual({x:600,y:100});
 expect(view.props.nodes.find((node:any)=>node.id==='initialize').kind).toBe('program');
 expect(view.props.nodes.find((node:any)=>node.id==='revise').kind).toBe('model');
});

it('keeps feedback grouping available without writing the display-only feedback node',()=>{
 const onChange=vi.fn();render(<RuleRefinementCanvas workflow={structuredClone(fixture)} onChange={onChange}/>);
 fireEvent.click(screen.getByRole('button',{name:'错题反馈'}));
 fireEvent.change(screen.getByLabelText('添加问题分组'),{target:{value:'rule'}});
 const next=onChange.mock.calls[0][0];expect(next.nodes.some((node:any)=>node.id==='feedback')).toBe(false);
 expect(groupOrder(next)).toEqual(['group_rule']);
 expect(next.edges.some((edge:any)=>edge.source==='verify'&&edge.target==='group_rule')).toBe(true);
});
