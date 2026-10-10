import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {Rag} from './Rag';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const model:any={id:'glm',name:'GLM',enabled:true};
const hit:any={citation_id:'rag_one',text:'ReLU 经验',kind:'experience',verified:false,score:1,condition_score:0,reasons:['同题型'],source_refs:[{id:'kb',version:'v',name:'知识库',record_id:'lesson',revision:1,sources:[]}]};
export const preview:any={preview_hash:'hash',can_answer:true,sent:false,blocked_reason:null,question:{id:'q1',family:'regression',prompt:'题面',choices:[]},models:[model],reserved_tokens:100,
 retrieval:{selected_kb:{id:'kb',name:'知识库',version:'v',kind:'experience'},candidates:[{kb:{id:'kb',name:'知识库',version:'v',kind:'experience'},hits:[hit]}],knowledge:[{id:'rag_one',text:'ReLU 经验'}],provenance:[hit],omitted:{budget:0,limit:0},warnings:[],excluded:{}},request:{payload:{messages:[{role:'user',content:'真实预览输入'}]}}};
function setup(enabled=true, p=preview){
 const calls:any[]=[];const onRun=vi.fn();
 vi.stubGlobal('fetch',async (path:string,init?:RequestInit)=>{
  calls.push({path,init});if(path.endsWith('/rag/preview'))return new Response(JSON.stringify(p));
  if(path.endsWith('/rag/runs'))return new Response(JSON.stringify({id:'run1'}));
  return new Response(JSON.stringify({public:preview.question,metadata:{key:'q1@rev',rag_ready:true}}));
 });
 const props={version:0,act:async(fn:any)=>fn(),models:[model],executionEnabled:enabled,questionKey:'q1@rev',onQuestion:vi.fn(),onRun};
 const view=render(<Rag {...props}/>);return {calls,onRun,props,...view};
}
it('previews knowledge and exact input, then starts once with frozen hash',async()=>{
 const c=setup();fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));
 expect(await screen.findByText('真实预览输入')).toBeTruthy();expect(screen.getAllByText('经验 · 待验证').length).toBeGreaterThan(0);
 fireEvent.click(screen.getByRole('button',{name:'启动 RAG 作答'}));fireEvent.click(screen.getByRole('button',{name:'启动 RAG 作答'}));
 await waitFor(()=>expect(c.onRun).toHaveBeenCalledWith('run1'));
 const posts=c.calls.filter(c=>c.path.endsWith('/rag/runs'));expect(posts.length).toBe(1);expect(JSON.parse(posts[0].init.body).preview_hash).toBe('hash');
});
it.each(['empty_library','no_match'])('blocks %s with accurate message',async reason=>{
 setup(true,{...preview,can_answer:false,request:null,blocked_reason:reason,retrieval:{...preview.retrieval,candidates:[],knowledge:[],provenance:[]}});
 fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));
 expect(await screen.findByText(reason==='empty_library'?'知识库目录为空':'没有适用的匹配知识')).toBeTruthy();
 expect((screen.getByRole('button',{name:'启动 RAG 作答'}) as HTMLButtonElement).disabled).toBe(true);
});
it('local mode allows preview but disables execution and selection change clears it',async()=>{
 setup(false);fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));await screen.findByText('真实预览输入');
 expect((screen.getByRole('button',{name:'启动 RAG 作答'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('知识条数'),{target:{value:'2'}});expect(screen.queryByText('真实预览输入')).toBeNull();
});
it('ignores preview returned after selection changes',async()=>{
 const c=setup();let resolve:any;
 vi.stubGlobal('fetch',async(path:string)=>path.endsWith('/rag/preview')?new Promise(r=>{resolve=r;}):new Response(JSON.stringify({public:preview.question,metadata:{key:'q1@rev'}})));
 fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));
 fireEvent.change(screen.getByLabelText('知识条数'),{target:{value:'2'}});resolve(new Response(JSON.stringify(preview)));
 await waitFor(()=>expect((screen.getByRole('button',{name:'匹配 KB 并预览'}) as HTMLButtonElement).disabled).toBe(false));
 expect(screen.queryByText('真实预览输入')).toBeNull();expect(c.onRun).not.toHaveBeenCalled();
});
it('409 clears preview and requires matching again',async()=>{
 setup();fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));await screen.findByText('真实预览输入');
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({detail:'预览已失效'}),{status:409}));
 fireEvent.click(screen.getByRole('button',{name:'启动 RAG 作答'}));await screen.findByText('预览已失效');expect(screen.queryByText('真实预览输入')).toBeNull();
});

it('shows alternate candidate hit explanations and source exclusion counts',async()=>{
 setup(true,{...preview,retrieval:{...preview.retrieval,candidates:[...preview.retrieval.candidates,{kb:{id:'other',name:'另一个 KB',version:'v2',kind:'experience'},hits:[{...hit,citation_id:'other-id',text:'另一个候选的知识',reasons:['另一个候选的匹配理由']}]}],excluded:{ineligible_lesson_sources:4,unusable_source:1}}});
 fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));
 expect(await screen.findByText('另一个候选的匹配理由')).toBeTruthy();expect(screen.getByText('来源不符合经验准入要求：4')).toBeTruthy();expect(screen.getByText('来源不可用：1')).toBeTruthy();
});
it('explains why no-match knowledge was excluded',async()=>{
 setup(true,{...preview,can_answer:false,request:null,blocked_reason:'no_match',retrieval:{...preview.retrieval,candidates:[],knowledge:[],provenance:[],excluded:{outside_validated_scope:3}}});
 fireEvent.click(screen.getByRole('button',{name:'匹配 KB 并预览'}));expect(await screen.findByText('超出已验证范围：3')).toBeTruthy();
});
