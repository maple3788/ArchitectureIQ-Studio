import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {DataWorkspace} from './DataWorkspace';
import {datasetFixture,summaryFixture,bankFixtures,dataProps,page} from './dataTestFixtures';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

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
 fireEvent.click(await screen.findByRole('button',{name:'从总题库选入'}));
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
 render(<DataWorkspace {...dataProps}/>);fireEvent.click(await screen.findByRole('button',{name:'打开 Dataset A'}));fireEvent.click(await screen.findByRole('button',{name:'整理成员'}));
 fireEvent.click(await screen.findByRole('checkbox',{name:'Q1'}));fireEvent.click(screen.getByRole('button',{name:'保存题目选择'}));
 await waitFor(()=>expect(writes).toHaveLength(1));expect(writes[0]).toMatchObject({path:'/api/studio/datasets/ds_a/revisions',body:{changes:{keys:[]}}});
});
