import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {DatasetBrowser} from './DatasetBrowser';
import {bankFixtures,datasetFixture,page} from './dataTestFixtures';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('uses the same compact summary inside a Dataset and preserves source keys and search',async()=>{
 const requests:string[]=[],onRead=vi.fn(),prompt='## Dataset\n'+ 'candidate code '.repeat(1000);
 const row={...bankFixtures[0].summary,prompt,metric:'test_mse',budget:{training_steps:200},type:'optimizer_only',candidate_configs:[
  {letter:'A',model:{type:'mlp'},optimizer:{type:'SGD'}},{letter:'B',model:{type:'mlp'},optimizer:{type:'Adam'}},{letter:'C',model:{type:'mlp'},optimizer:{type:'AdamW'}}]};
 vi.stubGlobal('fetch',async(input:string)=>{requests.push(input);return new Response(JSON.stringify(input.includes('/questions?')?{...page([row]),type_counts:{optimizer_only:1}}:datasetFixture));});
 render(<DatasetBrowser refValue={{collection_id:'ds_a',revision:'r1'}} version={0} onBack={()=>{}} onChanged={()=>{}} onRead={onRead}/>);
 const title=await screen.findByRole('button',{name:'阅读 Q1'});
 expect(title.textContent).toBe('MLP · 优化器 SGD / Adam / AdamW');expect(screen.queryByText('训练 200 步')).toBeNull();expect(screen.getByText('MLP · 优化器 SGD')).toBeTruthy();expect(screen.getByText('MLP · 优化器 Adam')).toBeTruthy();expect(screen.getByText('MLP · 优化器 AdamW')).toBeTruthy();expect(screen.getByText('优化器对比 1 题')).toBeTruthy();expect(screen.queryByText(prompt)).toBeNull();
 const problem=screen.getByText(/测试均方误差最低？/);
 expect(problem.compareDocumentPosition(title)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 fireEvent.change(screen.getByLabelText('搜索 Dataset 题目'),{target:{value:'candidate code'}});await waitFor(()=>expect(requests.some(input=>new URL(input,'http://studio').searchParams.get('search')==='candidate code')).toBe(true));
 fireEvent.click(await screen.findByRole('button',{name:'阅读 Q1'}));expect(onRead).toHaveBeenCalledWith('q1@v1');
});
