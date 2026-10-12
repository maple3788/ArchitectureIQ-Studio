import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {HumanQuestionPractice} from './HumanQuestionPractice';
const source={kind:'catalog' as const,key:'source::q_one@sealed'};
const question={id:'q_one',family:'bigram_lm',choices:[{id:'small-source',letter:'C'},{id:'large-source',letter:'A'}]};
const revealed={selected_answer:{id:'large-source',letter:'A'},correct_answer:{id:'small-source',letter:'C'},correct:false,feedback:{correct_letter:'C',candidate_metrics:{'small-source':{letter:'C',selection_metric:'test_ce',mean_test_ce:0.6,n_seeds:2},'large-source':{letter:'A',selection_metric:'test_ce',mean_test_ce:0.8,n_seeds:2}},reveal:{curves:[{candidateId:'small-source',letter:'C',metric:'test_ce',steps:[0,20],mean:[1.2,0.6]},{candidateId:'large-source',letter:'A',metric:'test_ce',steps:[0,20],mean:[1.1,0.8]}]}}};
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('does not read GT before submission and then displays the saved answer and real curves',async()=>{
 const fetch=vi.fn(async()=>new Response(JSON.stringify(revealed)));vi.stubGlobal('fetch',fetch);
 render(<HumanQuestionPractice source={source} question={question}/>);
 expect(fetch).not.toHaveBeenCalled();expect(screen.queryByText(/正确答案/)).toBeNull();
 fireEvent.click(screen.getByRole('radio',{name:'选择 A'}));expect(fetch).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 expect(await screen.findByText('正确答案 C')).toBeTruthy();
 expect(screen.getByText('你的选择 A')).toBeTruthy();
 const chart=await screen.findByRole('img',{name:/训练曲线/});
 const statistics=screen.getByText('候选最终指标与统计信息').closest('details')!;
 expect(statistics.open).toBe(false);expect(chart.compareDocumentPosition(statistics)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 const [path,options]=fetch.mock.calls[0] as unknown as [string,RequestInit];
 expect(path).toBe('/api/studio/questions/review');
 expect(JSON.parse(options.body as string)).toEqual({source,answer_id:'large-source'});
 expect(screen.getByRole('radio',{name:'选择 A'}).matches(':disabled')).toBe(true);
});
it('keeps observed evolution identity and content hash on reveal and states missing curves honestly',async()=>{
 const evolution={kind:'knowledge_evolution' as const,question_id:'q_one',observation:{source_identity:'a'.repeat(64),sequence:8},expected_question_hash:'b'.repeat(64)};
 const fetch=vi.fn(async()=>new Response(JSON.stringify({...revealed,selected_answer:{id:'small-source',letter:'C'},correct:true,feedback:{correct_letter:'C',reveal:{curves:[]}},notice:'来源没有保存训练曲线。'})));vi.stubGlobal('fetch',fetch);
 render(<HumanQuestionPractice source={evolution} question={question}/>);
 fireEvent.click(screen.getByRole('radio',{name:'选择 C'}));fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 expect(await screen.findByText('来源没有保存训练曲线。')).toBeTruthy();
 expect(await screen.findByText('本次反馈未记录训练曲线')).toBeTruthy();expect(screen.getByText('候选最终指标与统计信息').closest('details')!.open).toBe(true);expect(screen.queryByRole('img',{name:/训练曲线/})).toBeNull();
 expect(JSON.parse((fetch.mock.calls[0] as unknown as [string,RequestInit])[1].body as string).source).toEqual(evolution);
});
it('prevents duplicate submissions and ignores a late response after changing question',async()=>{
 let resolve:(response:Response)=>void=()=>{};const fetch=vi.fn(()=>new Promise<Response>(done=>{resolve=done;}));vi.stubGlobal('fetch',fetch);const onRevealed=vi.fn();
 const view=render(<HumanQuestionPractice source={source} question={question} onRevealed={onRevealed}/>);
 fireEvent.click(screen.getByRole('radio',{name:'选择 A'}));fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 fireEvent.click(screen.getByRole('button',{name:'正在读取已保存结果…'}));expect(fetch).toHaveBeenCalledTimes(1);
 view.rerender(<HumanQuestionPractice source={{kind:'catalog',key:'source::q_other@sealed'}} question={{...question,id:'q_other'}} onRevealed={onRevealed}/>);
 resolve(new Response(JSON.stringify(revealed)));await waitFor(()=>expect(screen.getByRole('button',{name:'提交并查看结果'})).toBeTruthy());
 expect(screen.queryByText('正确答案 C')).toBeNull();expect(onRevealed).not.toHaveBeenCalled();
});
it('preserves a submitted selection after a source error and permits explicit retry without preloading feedback',async()=>{
 let failures=true;const fetch=vi.fn(async()=>failures?new Response(JSON.stringify({detail:'阅读快照已变化，请重新打开题目。'}),{status:409}):new Response(JSON.stringify({...revealed,selected_answer:{id:'small-source',letter:'C'},correct_answer:null,correct:null,feedback:{reveal:{curves:[]}}})));vi.stubGlobal('fetch',fetch);
 render(<HumanQuestionPractice source={source} question={question}/>);
 fireEvent.click(screen.getByRole('radio',{name:'选择 C'}));fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.queryByText(/正确答案/)).toBeNull();
 expect((screen.getByRole('radio',{name:'选择 C'}) as HTMLInputElement).checked).toBe(true);
 failures=false;fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 expect(await screen.findByText('来源未提供可确认的正确答案')).toBeTruthy();
});
it('does not let ambiguous candidate identities be submitted',()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 render(<HumanQuestionPractice source={source} question={{...question,choices:[{id:'duplicate',letter:'A'},{id:'duplicate',letter:'B'}]}}/>);
 expect((screen.getByRole('button',{name:'提交并查看结果'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getByText(/候选标识不完整或重复/)).toBeTruthy();expect(fetch).not.toHaveBeenCalled();
});

it('keeps the final metrics open when saved curves cannot be plotted without guessing an axis',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({...revealed,feedback:{...revealed.feedback,reveal:{curves:[{letter:'C',metric:'test_ce',mean:[1.2,0.6]}]}}})));
 render(<HumanQuestionPractice source={source} question={question}/>);
 fireEvent.click(screen.getByRole('radio',{name:'选择 A'}));fireEvent.click(screen.getByRole('button',{name:'提交并查看结果'}));
 await screen.findByText('正确答案 C');expect(screen.queryByRole('img',{name:/训练曲线/})).toBeNull();
 expect(screen.getByText('候选最终指标与统计信息').closest('details')!.open).toBe(true);
 expect(screen.getByRole('table',{name:'候选指标对比'})).toBeTruthy();
});
