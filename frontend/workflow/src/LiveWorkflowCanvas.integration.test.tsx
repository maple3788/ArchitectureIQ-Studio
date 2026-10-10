import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {LiveWorkflowCanvas} from './LiveWorkflowCanvas';
import type {Run} from './types';
afterEach(cleanup);
it('shows the real final Task score from evaluation round1000 without applying the research-round filter',()=>{
 const run:Run={id:'final-task',kind:'workflow',created_at:1,status:'complete',config:{workflow:{schema_version:1,name:'final',settings:{},nodes:['input','solver','publish','evaluate'].map((id,i)=>({id,type:'program',position:{x:0,y:i*100},config:{}})),edges:[{id:'a',source:'input',target:'solver'},{id:'b',source:'solver',target:'publish'},{id:'c',source:'publish',target:'evaluate'}]}},events:[{type:'stage',node_id:'publish',round_index:1,state:'complete'},{type:'stage',node_id:'evaluate',round_index:1000,state:'complete'}],node_observations:[{node_id:'evaluate',round_index:1000,availability:'partial',output:{scores:{current:{correct:1,total:2}}}}]};
 render(<LiveWorkflowCanvas run={run}/>);fireEvent.click(screen.getByRole('button',{name:'查看 Task · 新题解答与效果验证'}));expect(screen.getByText('独立评测对照')).toBeTruthy();expect(screen.getByText('当前知识条件')).toBeTruthy();expect(screen.queryByLabelText('查看研究轮次')).toBeNull();
});
