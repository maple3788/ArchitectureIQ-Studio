import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {DatasetBrowser} from './DatasetBrowser';
import {bankFixtures,datasetFixture,page} from './dataTestFixtures';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('uses the same compact summary inside a Dataset and preserves source keys and search',async()=>{
 const requests:string[]=[],onRead=vi.fn(),prompt='## Dataset\n'+ 'candidate code '.repeat(1000);
 const row={...bankFixtures[0].summary,prompt,metric:'test_mse',budget:{training_steps:200},type:'optimizer_only'};
 vi.stubGlobal('fetch',async(input:string)=>{requests.push(input);return new Response(JSON.stringify(input.includes('/questions?')?page([row]):datasetFixture));});
 render(<DatasetBrowser refValue={{collection_id:'ds_a',revision:'r1'}} version={0} onBack={()=>{}} onChanged={()=>{}} onRead={onRead}/>);
 const title=await screen.findByRole('button',{name:'阅读 Q1'});
 expect(title.textContent).toBe('一元回归 · 优化器选择');expect(screen.getByText('训练 200 步')).toBeTruthy();expect(screen.getByText('MLP')).toBeTruthy();expect(screen.queryByText(prompt)).toBeNull();
 fireEvent.change(screen.getByLabelText('搜索 Dataset 题目'),{target:{value:'candidate code'}});await waitFor(()=>expect(requests.some(input=>new URL(input,'http://studio').searchParams.get('search')==='candidate code')).toBe(true));
 fireEvent.click(await screen.findByRole('button',{name:'阅读 Q1'}));expect(onRead).toHaveBeenCalledWith('q1@v1');
});
