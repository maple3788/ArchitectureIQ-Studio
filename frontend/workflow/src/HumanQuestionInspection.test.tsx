import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {HumanQuestionInspection} from './HumanQuestionInspection';
import type {InspectedAnswer} from './HumanQuestionInspection';

const source={kind:'catalog' as const,key:'source::q_one@sealed'};
const question={id:'q_one',family:'bigram_lm',choices:[{id:'small-source',letter:'C'},{id:'large-source',letter:'A'}]};
const inspected={scope:'human_inspection',correct_answer:{id:'small-source',letter:'C'},feedback:{correct_letter:'C',candidate_metrics:{'small-source':{letter:'C',selection_metric:'test_ce',mean_test_ce:.6,n_seeds:2}},reveal:{correctLetter:'C',curves:[{candidateId:'small-source',letter:'C',metric:'test_ce',steps:[0,20],mean:[1.2,.6]}]}}};
const cards=(answer:InspectedAnswer|null)=><div>{answer?`候选 ${answer.letter} 正确答案`:'候选尚未标记'}</div>;
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('automatically reads saved feedback without submitting an answer and leaves training curves collapsed',async()=>{
 const fetch=vi.fn(async()=>new Response(JSON.stringify(inspected)));vi.stubGlobal('fetch',fetch);const onInspected=vi.fn();
 render(<HumanQuestionInspection source={source} question={question} renderChoices={cards} onInspected={onInspected}/>);
 expect(await screen.findByText('候选 C 正确答案')).toBeTruthy();expect(onInspected).toHaveBeenCalledTimes(1);
 const [path,options]=fetch.mock.calls[0] as unknown as [string,RequestInit];
 expect(path).toBe('/api/studio/questions/inspect');expect(JSON.parse(options.body as string)).toEqual({source});
 expect(screen.queryByRole('radio')).toBeNull();expect(screen.queryByRole('button')).toBeNull();expect(screen.queryByText(/你的选择/)).toBeNull();
 const details=screen.getByText('训练曲线与结果').closest('details')!;expect(details.open).toBe(false);
 expect(screen.queryByRole('img',{name:/训练曲线/})).toBeNull();
 fireEvent.click(screen.getByText('训练曲线与结果'));expect(await screen.findByRole('img',{name:/训练曲线/})).toBeTruthy();
});

it('keeps observation identity exact and invokes the inspection callback even when GT is missing',async()=>{
 const evolution={kind:'knowledge_evolution' as const,question_id:'q_one',observation:{source_identity:'a'.repeat(64),sequence:8},expected_question_hash:'b'.repeat(64)};
 const fetch=vi.fn(async()=>new Response(JSON.stringify({...inspected,correct_answer:null,feedback:{reveal:{curves:[]}},notice:'尚未保存正确答案与训练曲线。'})));vi.stubGlobal('fetch',fetch);const onInspected=vi.fn();
 render(<HumanQuestionInspection source={evolution} question={question} renderChoices={cards} onInspected={onInspected}/>);
 expect(await screen.findByText('尚未保存正确答案与训练曲线。')).toBeTruthy();expect(screen.getByText('候选尚未标记')).toBeTruthy();
 expect(onInspected).toHaveBeenCalledTimes(1);expect(JSON.parse((fetch.mock.calls[0] as unknown as [string,RequestInit])[1].body as string)).toEqual({source:evolution});
});

it('discards late results when source or candidate mapping changes and does not repeat equal source reads',async()=>{
 const resolvers:((response:Response)=>void)[]=[];const fetch=vi.fn(()=>new Promise<Response>(done=>resolvers.push(done)));vi.stubGlobal('fetch',fetch);const onInspected=vi.fn();
 const view=render(<HumanQuestionInspection source={source} question={question} renderChoices={cards} onInspected={onInspected}/>);
 view.rerender(<HumanQuestionInspection source={{...source}} question={{...question}} renderChoices={cards} onInspected={onInspected}/>);expect(fetch).toHaveBeenCalledTimes(1);
 view.rerender(<HumanQuestionInspection source={{...source,key:'source::q_other@sealed'}} question={question} renderChoices={cards} onInspected={onInspected}/>);
 expect(fetch).toHaveBeenCalledTimes(2);await act(async()=>resolvers[0](new Response(JSON.stringify(inspected))));
 expect(screen.queryByText('候选 C 正确答案')).toBeNull();expect(onInspected).not.toHaveBeenCalled();
 const changed={...question,choices:[{id:'small-source',letter:'A'},{id:'large-source',letter:'C'}]};
 view.rerender(<HumanQuestionInspection source={{...source,key:'source::q_other@sealed'}} question={changed} renderChoices={cards} onInspected={onInspected}/>);
 expect(fetch).toHaveBeenCalledTimes(3);await act(async()=>resolvers[1](new Response(JSON.stringify(inspected))));
 expect(screen.queryByText('候选 C 正确答案')).toBeNull();expect(onInspected).not.toHaveBeenCalled();
});

it('shows source errors and retries reads without an answer commitment',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:'题目来源已变化。'}),{status:409})).mockResolvedValueOnce(new Response(JSON.stringify(inspected)));vi.stubGlobal('fetch',fetch);
 render(<HumanQuestionInspection source={source} question={question} renderChoices={cards}/>);
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.queryByText('候选 C 正确答案')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'重新读取保存结果'}));expect(await screen.findByText('候选 C 正确答案')).toBeTruthy();
 expect(fetch).toHaveBeenCalledTimes(2);
});

it.each([
 {...inspected,correct_answer:{id:'small-source',letter:'A'}},
 {...inspected,scope:'task_review'},
 {...inspected,feedback:{correct_letter:'A'}},
 {...inspected,correct_answer:null},
])('rejects a response with an inconsistent answer or scope',async result=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(result)));const onInspected=vi.fn();
 render(<HumanQuestionInspection source={source} question={question} renderChoices={cards} onInspected={onInspected}/>);
 expect(await screen.findByRole('alert')).toBeTruthy();expect(screen.queryByText('候选 C 正确答案')).toBeNull();expect(onInspected).not.toHaveBeenCalled();
});

it('does not fetch for ambiguous candidate ids',async()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 render(<HumanQuestionInspection source={source} question={{...question,choices:[{id:'duplicate',letter:'A'},{id:'duplicate',letter:'B'}]}} renderChoices={cards}/>);
 expect(screen.getByText(/候选标识不完整或重复/)).toBeTruthy();await waitFor(()=>expect(fetch).not.toHaveBeenCalled());
});
