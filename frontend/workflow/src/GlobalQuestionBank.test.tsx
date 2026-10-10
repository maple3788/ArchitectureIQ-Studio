import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {GlobalQuestionBank} from './GlobalQuestionBank';
import {bankFixtures,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('uses server equivalence groups and lets incomplete questions remain readable',async()=>{
 const onRead=vi.fn();vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(page(bankFixtures))));
 render(<GlobalQuestionBank version={0} onRead={onRead}/>);
 expect(await screen.findByText('Public research question 2')).toBeTruthy();
 expect(screen.getByText('A')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'阅读 Q2'}));
 expect(onRead).toHaveBeenCalledWith('q2@v1');
 expect(screen.getAllByRole('article')).toHaveLength(2);
});
it('retains cross-page selection and can recover a failed read',async()=>{
 const selected=['q1@v1'];const onSelect=vi.fn();let failed=true;
 vi.stubGlobal('fetch',async(input:string)=>{if(failed){failed=false;return new Response('{"detail":"offline"}',{status:503});}const second=input.includes('offset=25');return new Response(JSON.stringify({...page([bankFixtures[second?1:0]]),total:26}));});
 render(<GlobalQuestionBank version={0} selected={selected} onSelect={onSelect}/>);
 fireEvent.click(await screen.findByRole('button',{name:'重试读取题库'}));await screen.findByRole('checkbox',{name:'Q1'});
 fireEvent.click(screen.getByRole('button',{name:'总题库下一页'}));fireEvent.click(await screen.findByRole('checkbox',{name:'Q2'}));
 expect(onSelect).toHaveBeenCalledWith(['q1@v1','q2@v1']);
});
