import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PairPicker } from './PairPicker';
afterEach(() => {cleanup();vi.unstubAllGlobals();});
const pair = (key:string) => ({pair_key:key,pair_id:key,family:'bigram_lm',type:'architecture_only',split:'discovery',ready:true,kb_ready:true,members:[{role:'original',key:key+'-o',id:'原题'+key},{role:'counterfactual',key:key+'-c',id:'反事实'+key}],intervention:{changes:[{path:'params.alpha',before:1,after:2,kind:'factor'}],controls:['model','optimizer','loss','budget'],notice:'控制数据因素'},candidate_mapping:[]});
it('retains whole pairs across filters, lists selected items and submits only pair keys', async()=>{
 const calls:any[]=[]; const onApply=vi.fn();
 vi.stubGlobal('fetch',async(path:string,init?:RequestInit)=>{
   if(init?.method==='POST'){const body=JSON.parse(String(init.body));calls.push(body);return new Response(JSON.stringify({id:'set',selection_mode:'pairs',pair_count:1,count:2,keys:['p-o','p-c']}));}
   return new Response(JSON.stringify({items:path.includes('search=none')?[]:[pair('p')],total:path.includes('search=none')?0:1}));
 });
 render(<PairPicker version={0} act={async f=>f()} onApply={onApply} onClose={()=>{}}/>);
 fireEvent.click(await screen.findByRole('checkbox',{name:'选择题对 p'}));
 fireEvent.change(screen.getByLabelText('搜索题对'),{target:{value:'none'}});
 fireEvent.click(screen.getByRole('button',{name:'已选 1 对'}));
 expect(await screen.findByTitle('p-o')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'应用 1 对 · 2 题'}));
 await waitFor(()=>expect(onApply).toHaveBeenCalled());
 expect(calls[0]).toEqual({name:expect.any(String),pair_keys:['p']});
});
it('blocks applying when previously saved pair set cannot load', async()=>{
 vi.stubGlobal('fetch',async(path:string)=>path.includes('/question-sets/')?new Response('{"detail":"读取失败"}',{status:500}):new Response(JSON.stringify({items:[pair('p')],total:1})));
 render(<PairPicker version={0} act={async f=>f()} questionSetId='old' onApply={()=>{}} onClose={()=>{}}/>);
 expect(await screen.findByText(/读取失败/)).toBeTruthy();
 expect((screen.getByRole('button',{name:'应用 0 对 · 0 题'}) as HTMLButtonElement).disabled).toBe(true);
});
