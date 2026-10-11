import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {DataWorkspace} from './DataWorkspace';
import {datasetFixture,summaryFixture,bankFixtures,dataProps,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('shows server-grouped Datasets once, preserves every identity, and folds historical selections',async()=>{
 const same={...summaryFixture,collection_id:'ds_same',revision:'r9',name:'Same questions',origin:{kind:'set'}};
 const source={...summaryFixture,origin:{kind:'source'},equivalent_datasets:[summaryFixture,same]};
 const historical={...summaryFixture,collection_id:'ds_history',revision:'r3',name:'Older selection',origin:{kind:'set'}};
 const requested:string[]=[];
 vi.stubGlobal('fetch',async(input:string)=>{
  const url=new URL(input,'http://studio');requested.push(input);
  if(url.pathname.endsWith('/datasets'))return new Response(JSON.stringify({...page(url.searchParams.get('search')?[historical]:[source,historical]),dataset_total:3}));
  return new Response(JSON.stringify(url.pathname.endsWith('/questions')?page([]):{...datasetFixture,collection_id:'ds_same',revision:'r9',name:'Same questions'}));
 });
 render(<DataWorkspace {...dataProps}/>);
 await screen.findByRole('button',{name:'打开 Dataset A'});
 expect(requested.some(url=>new URL(url,'http://studio').searchParams.get('grouped')==='true')).toBe(true);
 expect(screen.getByRole('button',{name:'打开 Dataset Same questions'}).closest('details')?.open).toBe(false);
 expect(screen.getByRole('button',{name:'打开 Dataset Older selection'}).closest('details')?.open).toBe(false);
 fireEvent.click(screen.getByText('历史研究选集 · 1'));
 expect(screen.getByRole('button',{name:'打开 Dataset Older selection'}).closest('details')?.open).toBe(true);
 fireEvent.click(screen.getByText('相同题目 · 2 个集合'));
 fireEvent.click(screen.getByRole('button',{name:'打开 Dataset Same questions'}));
 await screen.findByRole('heading',{name:'Same questions'});
 expect(requested.some(url=>url.endsWith('/datasets/ds_same?revision=r9'))).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'所有 Datasets'}));
 fireEvent.change(await screen.findByLabelText('搜索 Dataset'),{target:{value:'Older'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'打开 Dataset Older selection'}).closest('details')?.open).toBe(true));
});

it('keeps only Dataset and question-bank views in the primary navigation',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(page([]))));
 const onTool=vi.fn();render(<DataWorkspace {...dataProps} onTool={onTool}/>);
 const nav=within(screen.getByRole('navigation',{name:'Data 工作空间'}));
 expect(nav.getAllByRole('button').filter(b=>!b.closest('details')).map(b=>b.textContent)).toEqual(['Datasets','总题库']);
 fireEvent.click(nav.getByText('更多'));
 fireEvent.click(nav.getByRole('button',{name:'生成任务'}));
 expect(onTool).toHaveBeenCalledWith('generation');
});

it('keeps Dataset additions and maintenance inside their two menus',async()=>{
 vi.stubGlobal('fetch',async(input:string)=>new Response(JSON.stringify(new URL(input,'http://studio').pathname.endsWith('/datasets')?page([summaryFixture]):input.includes('/questions?')?page([]):datasetFixture)));
 render(<DataWorkspace {...dataProps}/>);fireEvent.click(await screen.findByRole('button',{name:'打开 Dataset A'}));
 await screen.findByRole('heading',{name:'A'});
 expect(screen.getByRole('button',{name:'构建题目'}).closest('details')?.open).toBe(false);
 expect(screen.getByRole('button',{name:'整理成员'}).closest('details')?.open).toBe(false);
 fireEvent.click(screen.getByText('添加题目'));
 expect(screen.getByRole('button',{name:'构建题目'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'从总题库选入'})).toBeTruthy();
 fireEvent.click(screen.getByText('管理题库'));
 fireEvent.click(screen.getByRole('button',{name:'题库信息与归档'}));
 expect(screen.getByLabelText('Dataset 名称')).toBeTruthy();
 expect(screen.getByRole('button',{name:'归档题库'})).toBeTruthy();
});

it('preserves pending single-question choices when a concurrent generation changes the Dataset mode',async()=>{
 const empty={...datasetFixture,keys:[]};
 const latest={...empty,revision:'r2',selection_mode:'pairs',keys:['orig@v1','cf@v1'],pairs:[{pair_key:'paired',members:[{key:'orig@v1',role:'original'},{key:'cf@v1',role:'counterfactual'}]}]};
 let writes=0;
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{
  const url=new URL(input,'http://studio');
  if(url.pathname.endsWith('/revisions')){writes++;return new Response(JSON.stringify({detail:{code:'dataset_revision_conflict',message:'changed'}}),{status:409});}
  const value=url.pathname.endsWith('/datasets')?page([{...summaryFixture,count:0}]):url.pathname.endsWith('/question-bank')?page(bankFixtures):url.pathname.endsWith('/questions')?page([]):url.searchParams.has('revision')?empty:latest;
  return new Response(JSON.stringify(value));
 });
 render(<DataWorkspace {...dataProps}/>);
 fireEvent.click(await screen.findByRole('button',{name:'打开 Dataset A'}));
 fireEvent.click(await screen.findByText('添加题目'));fireEvent.click(screen.getByRole('button',{name:'从总题库选入'}));
 fireEvent.click(await screen.findByRole('checkbox',{name:'Q2'}));
 fireEvent.click(screen.getByRole('button',{name:'保存题目选择'}));
 fireEvent.click(await screen.findByRole('button',{name:'保留我的选择并载入新版本'}));
 await screen.findByText(/题库模式已更改/);
 expect((screen.getByRole('checkbox',{name:'Q2'}) as HTMLInputElement).checked).toBe(true);
 expect((screen.getByRole('button',{name:'保存题目选择'}) as HTMLButtonElement).disabled).toBe(true);
 expect(writes).toBe(1);
 fireEvent.click(screen.getByRole('button',{name:'取消'}));
 fireEvent.click(screen.getByRole('button',{name:'保留我的选择并载入新版本'}));
 await waitFor(()=>expect(screen.queryByText(/题库模式已更改/)).toBeNull());
 fireEvent.click(screen.getByText('管理题库'));fireEvent.click(screen.getByRole('button',{name:'整理成员'}));
 expect(await screen.findByRole('checkbox',{name:'题对 paired'})).toBeTruthy();
});

it('keeps membership choices after a revision conflict and rebases without dropping concurrent additions',async()=>{
 let writes:any[]=[];
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{
  const url=new URL(input,'http://studio');let value:any;
  if(url.pathname.endsWith('/revisions')) {const body=JSON.parse(String(init?.body));writes.push(body);if(writes.length===1)return new Response(JSON.stringify({detail:{code:'dataset_revision_conflict',message:'changed',current_revision:'r2'}}),{status:409});value={...datasetFixture,revision:'r3',keys:body.changes.keys};}
  else if(url.pathname.endsWith('/datasets'))value=page([summaryFixture]);
  else if(url.pathname.endsWith('/question-bank'))value=page(bankFixtures);
  else if(url.pathname.endsWith('/questions'))value=page(bankFixtures.slice(0,1).map(x=>x.summary));
  else value=url.searchParams.has('revision')?datasetFixture:{...datasetFixture,revision:'r2',keys:['q1@v1','concurrent@v1']};
  return new Response(JSON.stringify(value));
 });
 render(<DataWorkspace {...dataProps}/>);
 fireEvent.click(await screen.findByRole('button',{name:'打开 Dataset A'}));
 fireEvent.click(await screen.findByText('添加题目'));fireEvent.click(screen.getByRole('button',{name:'从总题库选入'}));
 fireEvent.click(await screen.findByRole('checkbox',{name:'Q2'}));
 fireEvent.click(screen.getByRole('button',{name:'保存题目选择'}));
 await screen.findByText('题库已在其他窗口更新');
 expect((screen.getByRole('checkbox',{name:'Q2'}) as HTMLInputElement).checked).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'保留我的选择并载入新版本'}));
 await waitFor(()=>expect(screen.queryByText('题库已在其他窗口更新')).toBeNull());
 fireEvent.click(screen.getByRole('button',{name:'保存题目选择'}));
 await waitFor(()=>expect(writes).toHaveLength(2));
 expect(writes[1]).toMatchObject({expected_revision:'r2',changes:{keys:['q1@v1','concurrent@v1','q2@v1']}});
});

it('creates an empty named Dataset and opens its dedicated workspace',async()=>{
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>new Response(JSON.stringify(
  new URL(input,'http://studio').pathname.endsWith('/datasets')?(init?.method==='POST'?{...datasetFixture,keys:[],name:JSON.parse(String(init.body)).name}:page([])):
  input.includes('/questions?')?page([]):{...datasetFixture,name:'My dataset',keys:[]})));
 render(<DataWorkspace {...dataProps}/>);
 fireEvent.click(await screen.findByRole('button',{name:'新建 Dataset'}));
 fireEvent.change(screen.getByLabelText('Dataset 名称'),{target:{value:'My dataset'}});
 fireEvent.click(screen.getByRole('button',{name:'创建题库'}));
 expect(await screen.findByRole('heading',{name:'My dataset'})).toBeTruthy();
 expect(await screen.findByText('这个 Dataset 还没有题目')).toBeTruthy();
});
it('retries Dataset creation with the same operation key after a lost response',async()=>{
 const operationKeys:string[]=[];
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{
  const path=new URL(input,'http://studio').pathname;
  if(path.endsWith('/datasets')&&init?.method==='POST') {operationKeys.push((init.headers as Record<string,string>)['Idempotency-Key']);if(operationKeys.length===1)throw new Error('connection lost');return new Response(JSON.stringify(datasetFixture));}
  return new Response(JSON.stringify(path.endsWith('/datasets')?page([]):path.endsWith('/questions')?page([]):datasetFixture));
 });
 render(<DataWorkspace {...dataProps}/>);fireEvent.click(await screen.findByRole('button',{name:'新建 Dataset'}));
 fireEvent.change(screen.getByLabelText('Dataset 名称'),{target:{value:'A'}});
 fireEvent.click(screen.getByRole('button',{name:'创建题库'}));await screen.findByText('connection lost');
 fireEvent.click(screen.getByRole('button',{name:'创建题库'}));await screen.findByRole('heading',{name:'A'});
 expect(operationKeys).toHaveLength(2);expect(operationKeys[1]).toBe(operationKeys[0]);
});
it('removes membership through a revision without deleting the shared question',async()=>{
 const writes:Array<{path:string;body:any}>=[];
 vi.stubGlobal('fetch',async(input:string,init?:RequestInit)=>{
  const path=new URL(input,'http://studio').pathname;
  if(init?.method==='POST'){const body=JSON.parse(String(init.body));writes.push({path,body});return new Response(JSON.stringify({...datasetFixture,revision:'r2',keys:[]}));}
  return new Response(JSON.stringify(path.endsWith('/datasets')?page([summaryFixture]):path.endsWith('/question-bank')?page(bankFixtures):path.endsWith('/questions')?page(bankFixtures.slice(0,1).map(x=>x.summary)):datasetFixture));
 });
 render(<DataWorkspace {...dataProps}/>);fireEvent.click(await screen.findByRole('button',{name:'打开 Dataset A'}));fireEvent.click(await screen.findByText('管理题库'));fireEvent.click(screen.getByRole('button',{name:'整理成员'}));
 fireEvent.click(await screen.findByRole('checkbox',{name:'Q1'}));fireEvent.click(screen.getByRole('button',{name:'保存题目选择'}));
 await waitFor(()=>expect(writes).toHaveLength(1));expect(writes[0]).toMatchObject({path:'/api/studio/datasets/ds_a/revisions',body:{changes:{keys:[]}}});
});
