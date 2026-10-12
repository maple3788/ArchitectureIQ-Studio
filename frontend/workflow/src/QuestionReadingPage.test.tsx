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

it('reveals saved results for the exact catalog version only after the human submits an answer',async()=>{
 const posts:any[]=[];
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
  if(init?.method==='POST'){posts.push({path,body:JSON.parse(init.body as string)});return new Response(JSON.stringify({selected_answer:{id:'first',letter:'B'},correct_answer:{id:'other',letter:'A'},correct:false,feedback:{reveal:{curves:[]}}}));}
  return new Response(JSON.stringify(path.includes('/question-bank?')?page([]):{metadata:{key:'q1@v1'},public:{id:'q1',choices:[{id:'first',letter:'B'},{id:'other',letter:'A'}]}}));
 });
 render(<QuestionReadingPage questionKey="q1@v1" context={{view:'bank',filters:{search:''},offset:0}} onBack={()=>{}} onQuestion={()=>{}} onAddToDataset={()=>{}} onRag={()=>{}}/>);
 fireEvent.click(await screen.findByRole('radio',{name:'选择 B'}));expect(posts).toEqual([]);
 fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 await screen.findByText('正确答案 A');
 expect(posts).toEqual([{path:'/api/studio/questions/review',body:{source:{kind:'catalog',key:'q1@v1'},answer_id:'first'}}]);
});
