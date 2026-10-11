import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {RuleEvaluation} from './RuleEvaluation';
import type {KBRef} from './ruleRefinementTypes';

vi.mock('./DatasetInputPicker', () => ({
 DatasetInputPicker: ({onApply}:any) => <button onClick={() => onApply({dataset_binding:{
  collection_id:'evaluation-dataset', revision:'dataset-revision', keys:['q1'], selection:{question_keys:['q1']},
 }})}>使用评测题集</button>,
}));

afterEach(() => {cleanup();vi.unstubAllGlobals();});

function setup(kbRef?:KBRef) {
 const requests:{path:string;body:any}[]=[];
 const items=[9,10].map(order => ({
  id:`builtin:kb-v${order}`, version:`hash-v${order}`, name:`KB v${order}`, kind:'research_rules',
  library:{id:'builtin:architecture-rules', name:'架构与优化器规则', version_label:`v${order}`, version_order:order},
 }));
 vi.stubGlobal('fetch',async (path:string,init?:RequestInit) => {
  if(init?.body)requests.push({path,body:JSON.parse(String(init.body))});
  if(path.endsWith('/kb'))return new Response(JSON.stringify({items}));
  if(path.endsWith('/evaluations/preview'))return new Response(JSON.stringify({
   can_run:true, preview_hash:'evaluation-preview', blockers:[], independence:'independent',
  }));
  throw Error(`Unexpected request: ${path}`);
 });
 const onStarted=vi.fn();
 render(<RuleEvaluation kbRef={kbRef} onStarted={onStarted}/>);
 return {requests,onStarted};
}

it.each([
 ['a new evaluation',undefined,{id:'builtin:kb-v10',version:'hash-v10'}],
 ['an existing selection',{id:'builtin:kb-v9',version:'hash-v9'},{id:'builtin:kb-v9',version:'hash-v9'}],
] as const)('presents one knowledge choice for %s and previews its exact stored reference',async (_case,kbRef,expected) => {
 const {requests,onStarted}=setup(kbRef);
 const select=screen.getByRole('combobox',{name:'待评测规则 KB'}) as HTMLSelectElement;
 await waitFor(() => expect(Array.from(select.options).filter(option => option.value)).toHaveLength(1));
 const choice=Array.from(select.options).find(option => option.value)!;
 expect(choice.value).toBe(`${expected.id}@${expected.version}`);
 expect(choice.textContent).not.toMatch(/\bv(?:9|10)\b|hash-/i);
 if(kbRef)expect(select.value).toBe(`${kbRef.id}@${kbRef.version}`);
 else fireEvent.change(select,{target:{value:choice.value}});
 fireEvent.click(screen.getByRole('button',{name:'选择评测 Dataset'}));
 fireEvent.click(screen.getByRole('button',{name:'使用评测题集'}));
 fireEvent.click(screen.getByRole('button',{name:'预览规则评测'}));
 await waitFor(() => expect(requests).toHaveLength(1));
 expect(requests[0]).toEqual({
  path:'/api/studio/rule-refinement/evaluations/preview',
  body:{kb_ref:expected,phase:'final',dataset_ref:{collection_id:'evaluation-dataset',revision:'dataset-revision'},selection:{question_keys:['q1']}},
 });
 expect(onStarted).not.toHaveBeenCalled();
});
