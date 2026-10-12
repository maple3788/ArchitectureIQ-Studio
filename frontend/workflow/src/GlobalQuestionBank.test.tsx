import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {GlobalQuestionBank} from './GlobalQuestionBank';
import {bankFixtures,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('uses server equivalence groups and lets incomplete questions remain readable',async()=>{
 const onRead=vi.fn();vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(page(bankFixtures))));
 render(<GlobalQuestionBank version={0} onRead={onRead}/>);
 expect(await screen.findByRole('button',{name:'阅读 Q2'})).toBeTruthy();
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
it('shows a compact semantic question card while retaining full-text search and exact navigation',async()=>{
 const requests:string[]=[],onRead=vi.fn(),prompt='You are taking the benchmark. '+ 'huge_candidate_code '.repeat(500);
 const item={...bankFixtures[0],representative_key:'q_bcb233@fixed',summary:{...bankFixtures[0].summary,id:'q_bcb233',family:'bigram_lm',type:'mixed',model_types:['gru_lm','transformer_lm'],metric:'test_ce',budget:{total_samples_seen:16384},prompt,candidate_configs:[{letter:'A',model:{type:'gru_lm'}},{letter:'B',model:{type:'transformer_lm'}},{letter:'C',model:{type:'gru_lm'}}]}};
 vi.stubGlobal('fetch',async(input:string)=>{requests.push(input);return new Response(JSON.stringify(page([item])));});
 render(<GlobalQuestionBank version={0} onRead={onRead}/>);
 const button=await screen.findByRole('button',{name:'阅读 q_bcb233'}),article=button.closest('article')!;
 expect(button.textContent).toBe('GRU vs Transformer');expect(article.textContent?.length).toBeLessThan(300);expect(within(article).getAllByText('GRU')).toHaveLength(2);expect(within(article).getByText('Transformer')).toBeTruthy();expect(within(article).getByText('q_bcb233')).toBeTruthy();expect(article.textContent).not.toMatch(/训练总量|16,384|测试交叉熵/);expect(screen.queryByText(prompt)).toBeNull();
 fireEvent.change(screen.getByLabelText('搜索总题库'),{target:{value:'huge_candidate_code'}});await waitFor(()=>expect(requests.some(input=>new URL(input,'http://studio').searchParams.get('search')==='huge_candidate_code')).toBe(true));
 fireEvent.click(await screen.findByRole('button',{name:'阅读 q_bcb233'}));expect(onRead).toHaveBeenCalledWith('q_bcb233@fixed');
});
