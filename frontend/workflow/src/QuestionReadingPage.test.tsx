import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QuestionReadingPage} from './QuestionReadingPage';
import {bankFixtures,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('reads the exact version and navigates within the frozen Dataset filter',async()=>{
 const paths:string[]=[],onQuestion=vi.fn(),onAdd=vi.fn();
 vi.stubGlobal('fetch',async(path:string)=>{paths.push(path);return new Response(JSON.stringify(path.includes('/datasets/')?page(bankFixtures.map(x=>x.summary)):{metadata:{key:'q1@v1'},public:{id:'q1@v1',prompt:'Exact public prompt',choices:[]}}));});
 render(<QuestionReadingPage questionKey="q1@v1" context={{view:'dataset',ref:{collection_id:'ds_a',revision:'r1'},filters:{search:'public'},offset:0}} onBack={()=>{}} onQuestion={onQuestion} onAddToDataset={onAdd} onRag={()=>{}}/>);
 await screen.findByRole('tab',{name:'原始 Prompt'});
 expect(paths).toContain('/api/studio/questions/q1%40v1');
 expect(paths.some(p=>p.includes('revision=r1')&&p.includes('search=public'))).toBe(true);
 await waitFor(()=>expect((screen.getByRole('button',{name:'下一题'}) as HTMLButtonElement).disabled).toBe(false));
 fireEvent.click(screen.getByRole('button',{name:'下一题'}));expect(onQuestion).toHaveBeenCalledWith('q2@v1');
 fireEvent.click(screen.getByRole('button',{name:'加入 Dataset'}));expect(onAdd).toHaveBeenCalledWith('q1@v1');
});
