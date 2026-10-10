import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {DatasetInputPicker} from './DatasetInputPicker';
import {datasetFixture,summaryFixture,bankFixtures,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('rejects multi-question Dataset without truncation and freezes an explicit question',async()=>{
 const onApply=vi.fn(),bodies:any[]=[];
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{const path=new URL(input,'http://studio').pathname;let value:any;
  if(path.endsWith('/selection-preview')){const body=JSON.parse(String(init?.body));bodies.push(body);const keys=body.selection.keys||['q1@v1','q2@v1'];value={preview_hash:'hash',can_apply:keys.length===1,count:keys.length,pair_count:0,questions:[],binding:{collection_id:'ds_a',revision:'r1',keys,hashes:[],pair_keys:[],selection:body.selection},blockers:keys.length===1?[]:[{key:'',code:'basic_requires_one_question',message:'单题学习需要明确选择一道题'}]};}
  else if(path.endsWith('/question-set'))value={id:'frozen',name:'A',count:1,keys:['q2@v1'],dataset_binding:{collection_id:'ds_a',revision:'r1'}};
  else if(path.endsWith('/datasets'))value=page([{...summaryFixture,count:2}]);else if(path.endsWith('/questions'))value=page(bankFixtures.map(x=>x.summary));else value={...datasetFixture,keys:['q1@v1','q2@v1']};
  return new Response(JSON.stringify(value));});
 render(<DatasetInputPicker purpose="research" methodId="basic_learning" selectionMode="single" single onApply={onApply} onClose={()=>{}}/>);
 fireEvent.change(await screen.findByLabelText('选择 Dataset'),{target:{value:'ds_a'}});
 fireEvent.click(await screen.findByRole('button',{name:'使用整个 Dataset'}));await screen.findByText('单题学习需要明确选择一道题');expect(onApply).not.toHaveBeenCalled();
 fireEvent.click(await screen.findByRole('checkbox',{name:'Q2'}));fireEvent.click(screen.getByRole('button',{name:'预览选择'}));
 await waitFor(()=>expect((screen.getByRole('button',{name:'应用到工作流'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'应用到工作流'}));
 await waitFor(()=>expect(onApply).toHaveBeenCalledWith(expect.objectContaining({id:'frozen',dataset_binding:{collection_id:'ds_a',revision:'r1'}})));
 expect(bodies[1]).toMatchObject({revision:'r1',selection:{keys:['q2@v1']},method_id:'basic_learning'});
});
it('preserves paired evaluation selection when freezing fails',async()=>{
 const onApply=vi.fn(),requests:any[]=[];
 const pair={pair_key:'p1',members:[{key:'q1@v1',role:'original'},{key:'q2@v1',role:'counterfactual'}]};
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{const path=new URL(input,'http://studio').pathname;let value:any;
  if(path.endsWith('/question-set'))return new Response('{"detail":{"message":"preview changed"}}',{status:409});
  if(path.endsWith('/selection-preview')){const body=JSON.parse(String(init?.body));requests.push(body);value={can_apply:true,preview_hash:'h',blockers:[],count:2,pair_count:1,questions:[],binding:{}};}
  else if(path.endsWith('/datasets'))value=page([{...summaryFixture,selection_mode:'pairs',count:2,pair_count:1}]);else if(path.endsWith('/questions'))value=page(bankFixtures.map(x=>x.summary));else value={...datasetFixture,selection_mode:'pairs',pairs:[pair],keys:['q1@v1','q2@v1']};
  return new Response(JSON.stringify(value));});
 render(<DatasetInputPicker purpose="evaluation" phase="final" methodId="paired_progressive" selectionMode="pairs" single={false} onApply={onApply} onClose={()=>{}}/>);
 fireEvent.change(await screen.findByLabelText('选择 Dataset'),{target:{value:'ds_a'}});fireEvent.click(await screen.findByRole('checkbox',{name:'题对 p1'}));fireEvent.click(screen.getByRole('button',{name:'预览选择'}));
 await waitFor(()=>expect((screen.getByRole('button',{name:'应用到工作流'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'应用到工作流'}));
 await screen.findByText('preview changed');expect((screen.getByRole('checkbox',{name:'题对 p1'}) as HTMLInputElement).checked).toBe(true);expect(onApply).not.toHaveBeenCalled();
 expect(requests[0]).toMatchObject({purpose:'evaluation',phase:'final',selection:{pair_keys:['p1']}});
});
