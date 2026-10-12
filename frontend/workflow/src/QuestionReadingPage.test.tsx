import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
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

it('automatically inspects saved results for the exact catalog version without submitting an answer',async()=>{
 const posts:any[]=[];
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
  if(path.endsWith('/applicable-knowledge'))return new Response(JSON.stringify({items:[],total:0,feedback_released:false}));
  if(init?.method==='POST'){posts.push({path,body:JSON.parse(init.body as string)});return new Response(JSON.stringify({scope:'human_inspection',correct_answer:{id:'other',letter:'A'},feedback:{correct_letter:'A',reveal:{curves:[]}}}));}
  return new Response(JSON.stringify(path.includes('/question-bank?')?page([]):{metadata:{key:'q1@v1'},public:{id:'q1',choices:[{id:'first',letter:'B'},{id:'other',letter:'A'}]}}));
 });
 render(<QuestionReadingPage questionKey="q1@v1" context={{view:'bank',filters:{search:''},offset:0}} onBack={()=>{}} onQuestion={()=>{}} onAddToDataset={()=>{}} onRag={()=>{}}/>);
 await screen.findByText('正确答案');
 expect(within(screen.getByRole('article',{name:'候选 A'})).getByText('正确答案')).toBeTruthy();
 expect(within(screen.getByRole('article',{name:'候选 B'})).queryByText('正确答案')).toBeNull();
 expect(screen.queryByRole('radio')).toBeNull();expect(screen.queryByRole('button',{name:'提交并查看结果'})).toBeNull();
 expect(screen.getByText('训练曲线与结果').closest('details')?.open).toBe(false);
 expect(posts).toEqual([{path:'/api/studio/questions/inspect',body:{source:{kind:'catalog',key:'q1@v1'}}}]);
});
