import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {KB} from './KB';

beforeEach(()=>{const storage=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(key:string)=>storage.get(key)??null,setItem:(key:string,value:string)=>storage.set(key,value)});});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const item={id:'evolution-a',version:'frozen-a',kind:'research_rules',source_kind:'knowledge_evolution',
 provenance:{source_identity:'experiment-a'},library:{id:'evolution-a',name:'知识演化',version_order:1},
 snapshot:{source_document:{source_claims:[
  {id:'C1',version:1,status:'retired',parent:null},
  {id:'C2',version:1,status:'verified',parent:{id:'C1',version:1}},
  {id:'C3',version:1,status:'candidate',parent:null},
 ]},rules:[['C2','更窄范围内的学习率规律'],['C3','独立的深度规律']].map(([id,text])=>({
  rule_id:id,revision:'rule-fixed',text,state:'active',rule:{scope:['model_type','eq','mlp'],predict:{higher_better:'lr'}},
  metadata:{claim_id:id,validity_status:'proposed',validation_origin:'source_reported'},
 }))},reading_claims:[{id:'C1',version:1,status:'retired',text:'最初的宽范围规律',rules:[],parent:null}],
};
function inventory(){
 const paths:string[]=[];
 vi.stubGlobal('fetch',async(path:string)=>{paths.push(path);return new Response(JSON.stringify(path.endsWith('/kb')?{items:[item]}:
  {items:[],counts:{applicable:0,inapplicable:0,unknown:0},total:0,offset:0,limit:25}));});
 return paths;
}
it('reads the selected forest node audit from its saved record',async()=>{
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[{...item,consistency_audits:{C2:{status:'needs_review',issues:[{code:'missing_condition',message:'正则化范围未进入执行规则'}]}}}]})));
 render(<KB version={0}/>);
 await screen.findByRole('button',{name:'阅读 C2 更窄范围内的学习率规律'});
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));
 fireEvent.click(screen.getByRole('button',{name:/展开谱系 C1/}));
 fireEvent.click(screen.getByRole('button',{name:/查看知识 C2/}));
 const inspector=within(screen.getByRole('complementary',{name:'森林知识详情'}));
 const audit=within(inspector.getByRole('region',{name:'文字与规则一致性审计'}));
 fireEvent.click(audit.getByText('审计详情'));
 expect(audit.getByText('正则化范围未进入执行规则')).toBeTruthy();
});
it('switches between the retained list and a real lineage, reading exact evidence and Task references',async()=>{
 const paths=inventory(),onEvaluate=vi.fn();render(<KB version={0} onEvaluate={onEvaluate}/>);
 await screen.findByRole('button',{name:'阅读 C2 更窄范围内的学习率规律'});
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));
 fireEvent.click(screen.getByRole('button',{name:/展开谱系 C1/}));
 fireEvent.click(screen.getByRole('button',{name:/查看知识 C2/}));
 const inspector=screen.getByRole('complementary',{name:'森林知识详情'});
 expect(within(inspector).getByText('更窄范围内的学习率规律')).toBeTruthy();
 expect(within(inspector).getByText('来源已验证')).toBeTruthy();
 fireEvent.click(within(inspector).getByRole('tab',{name:'证据'}));
 await waitFor(()=>expect(paths.some(path=>path.includes('/kb/questions?')&&path.includes('kb_id=evolution-a')&&path.includes('kb_version=frozen-a')&&path.includes('claim_id=C2'))).toBe(true));
 fireEvent.click(within(inspector).getByRole('button',{name:'打开完整知识详情'}));
 const dialog=screen.getByRole('dialog',{name:'知识详情'});
 expect(within(dialog).getByRole('heading',{name:'更窄范围内的学习率规律'})).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('button',{name:'在 Task 中检查此知识所在 KB'}));
 expect(onEvaluate).toHaveBeenCalledWith({id:'evolution-a',version:'frozen-a'});
 fireEvent.click(within(dialog).getByRole('button',{name:'关闭详情'}));
 fireEvent.click(screen.getByRole('button',{name:'列表'}));
 expect(screen.getByRole('button',{name:'阅读 C2 更窄范围内的学习率规律'})).toBeTruthy();
 expect(screen.queryByRole('complementary',{name:'森林知识详情'})).toBeNull();
});
it('keeps ancestor context when searching, preserves filters between views and remembers the chosen view',async()=>{
 inventory();const page=render(<KB version={0}/>);
 await screen.findByRole('button',{name:'阅读 C2 更窄范围内的学习率规律'});
 fireEvent.change(screen.getByRole('searchbox'),{target:{value:'更窄范围'}});
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));
 fireEvent.click(screen.getByRole('button',{name:/展开谱系 C1/}));
 expect(screen.getByRole('button',{name:/查看知识 C1/})).toBeTruthy();
 expect(screen.queryByRole('button',{name:/查看知识 C3/})).toBeNull();
 expect(screen.getByText('祖先上下文')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'列表'}));
 expect(screen.getByRole('searchbox').getAttribute('value')).toBe('更窄范围');
 expect(screen.queryByRole('button',{name:'阅读 C3 独立的深度规律'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));page.unmount();
 render(<KB version={0}/>);
 await screen.findByRole('button',{name:/展开谱系 C1/});
 expect(screen.getByRole('button',{name:'知识森林'}).getAttribute('aria-pressed')).toBe('true');
});
it('keeps standalone knowledge readable without inventing a parent',async()=>{
 inventory();render(<KB version={0}/>);
 await screen.findByRole('button',{name:'阅读 C3 独立的深度规律'});
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));
 fireEvent.click(screen.getByText(/独立知识 · 1/));
 fireEvent.click(screen.getByRole('button',{name:/查看知识 C3/}));
 expect(within(screen.getByRole('complementary',{name:'森林知识详情'})).getByText('独立的深度规律')).toBeTruthy();
});
it('keeps alternative executable branches separate in the inspector',async()=>{
 const base=item.snapshot.rules[0];
 const multi={...item,snapshot:{...item.snapshot,rules:[base,{...base,rule_id:'C2:second',rule:{scope:['model_type','eq','cnn'],predict:{lower_better:'lr'}}}]}};
 vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({items:[multi]})));
 render(<KB version={0}/>);
 await screen.findByRole('button',{name:'阅读 C2 更窄范围内的学习率规律'});
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));
 fireEvent.click(screen.getByRole('button',{name:/展开谱系 C1/}));
 fireEvent.click(screen.getByRole('button',{name:/查看知识 C2/}));
 const inspector=screen.getByRole('complementary',{name:'森林知识详情'});
 const first=within(inspector).getByRole('region',{name:'执行分支 1'}),second=within(inspector).getByRole('region',{name:'执行分支 2'});
 expect(within(first).getByText('模型类型 = mlp')).toBeTruthy();
 expect(within(first).getByText('学习率更高的候选更好')).toBeTruthy();
 expect(within(second).getByText('模型类型 = cnn')).toBeTruthy();
 expect(within(second).getByText('学习率更低的候选更好')).toBeTruthy();
});
it('opens populated evidence questions at full reading width rather than squeezing them into the inspector',async()=>{
 vi.stubGlobal('fetch',async(path:string)=>new Response(JSON.stringify(path.endsWith('/kb')?{items:[item]}:path.includes('/kb/questions?')?{
  items:[{key:'question-1',id:'q1',family:'bigram_lm',type:'mixed',relation:'applicable',reason:{code:'matched',message:'满足模型范围'},prediction_status:'answered',matched_rules:1,matched_pairs:2}],counts:{applicable:1,inapplicable:0,unknown:0},total:1,offset:0,limit:25,
 }:{id:'q1',question:'比较候选方案',choices:[]})));
 render(<KB version={0}/>);await screen.findByRole('button',{name:'阅读 C2 更窄范围内的学习率规律'});
 fireEvent.click(screen.getByRole('button',{name:'知识森林'}));fireEvent.click(screen.getByRole('button',{name:/展开谱系 C1/}));fireEvent.click(screen.getByRole('button',{name:/查看知识 C2/}));
 const inspector=screen.getByRole('complementary',{name:'森林知识详情'});
 fireEvent.click(within(inspector).getByRole('tab',{name:'证据'}));
 fireEvent.click(await within(inspector).findByRole('button',{name:/q1/}));
 expect(screen.getByRole('dialog',{name:'完整题目'})).toBeTruthy();
});
