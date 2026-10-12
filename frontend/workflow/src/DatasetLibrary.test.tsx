import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {DatasetLibrary} from './DatasetLibrary';
import {summaryFixture,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('shows recorded type counts and preserves the selected Dataset revision',async()=>{
 const onOpen=vi.fn();
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(page([{...summaryFixture,count:8,type_counts:{architecture_only:3,optimizer_only:4,'':1}}]))));
 render(<DatasetLibrary version={0} onOpen={onOpen}/>);
 expect(await screen.findByText('架构对比 3 题')).toBeTruthy();
 expect(screen.getByText('优化器对比 4 题')).toBeTruthy();
 expect(screen.getByText('题型未记录 1 题')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'打开 Dataset A'}));
 expect(onOpen).toHaveBeenCalledWith({collection_id:'ds_a',revision:'r1'});
});
