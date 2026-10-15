import {useMemo,useState} from 'react';
import {ArrowLeft,ArrowUpRight,GitBranch,Leaf,Minus,Plus} from 'lucide-react';
import {buildKnowledgeForest,type ForestNode,type KnowledgeGrove} from './knowledgeForestModel';
import {entryState,entryStateLabels,entryText,revisionKey,type KnowledgeContentSource,type KnowledgeEntry} from './knowledgeEntries';
import {knowledgeSupport,supportLabel} from './knowledgeSupport';
import {ruleConditions} from './ruleKnowledgePresentation';
import {KnowledgeQuestions} from './KnowledgeQuestions';
import {KnowledgeEntryHistory} from './KnowledgeRevisionHistory';
import {Tabs} from './ui';
import {ConsistencyAuditView} from './ConsistencyAudit';
import './knowledge-forest.css';

type Selection={key:string;version:string};
type Props={entries:KnowledgeEntry[];matches:KnowledgeContentSource[];onRead:(selection:Selection)=>void};
function nodeState(node:ForestNode){
 const state=node.sourceClaim?.status;
 if(state)return {tone:state,label:({verified:'来源已验证',candidate:'候选',flagged:'来源已标记',retired:'已停用'} as Record<string,string>)[state]??state};
 const value=entryState(node.revision);return {tone:value,label:entryStateLabels[value]};
}
function conditions(node:ForestNode){
 return node.revision.parts.flatMap(part=>{try{return ruleConditions(part.rule);}catch{return [];}});
}
function nodeTitle(node:ForestNode){
 if(node.revision.parts.filter(part=>part.rule).length>1)return entryText(node.revision);
 const values=conditions(node);
 return values.find(([label])=>label==='结论')?.[1]??values.find(([label])=>label==='胜者条件')?.[1]??entryText(node.revision);
}
function versionLabel(node:ForestNode){
 return node.sourceClaim?`第 ${node.sourceClaim.version} 版`:node.revision.record.library?.version_label??'保存版本';
}
function Badge({node}:{node:ForestNode}){
 const state=nodeState(node);return <span className={`kf-state is-${state.tone}`}>{state.label}</span>;
}

/** Layer a saved DAG without duplicating a shared child; all dimensions stay inside its scroll area. */
function layout(nodes:ForestNode[]){
 const depths=new Map<string,number>();
 let pending=[...nodes];
 while(pending.length){
  const ready=pending.filter(node=>node.parentKeys.every(key=>depths.has(key)));
  if(!ready.length)break;
  for(const node of ready)depths.set(node.key,node.parentKeys.length?1+Math.max(...node.parentKeys.map(key=>depths.get(key)!)):0);
  pending=pending.filter(node=>!depths.has(node.key));
 }
 const columns=new Map<number,ForestNode[]>();
 for(const node of nodes){const depth=depths.get(node.key)??0;columns.set(depth,[...(columns.get(depth)??[]),node]);}
 const height=Math.max(340,...[...columns.values()].map(column=>column.length*202+30));
 const points=new Map(nodes.map(node=>{
  const depth=depths.get(node.key)??0,column=columns.get(depth)!;
  return [node.key,{x:24+depth*300,y:(height-column.length*202)/2+column.indexOf(node)*202}];
 }));
 return {points,width:(Math.max(0,...depths.values())+1)*300+10,height};
}
function MiniTree({grove}:{grove:KnowledgeGrove}){
 const {points,width,height}=layout(grove.nodes);
 const position=(key:string)=>{const point=points.get(key)!;return {x:18+(point.x+110)/width*184,y:8+(point.y+80)/height*54};};
 return <svg viewBox="0 0 220 70" aria-hidden="true" className="kf-mini-tree">
  {grove.nodes.flatMap(node=>node.parentKeys.map(key=>{const p=position(key),c=position(node.key);return <path key={`${key}:${node.key}`} d={`M${p.x},${p.y} C${(p.x+c.x)/2},${p.y} ${(p.x+c.x)/2},${c.y} ${c.x},${c.y}`}/>;}))}
  {grove.nodes.map(node=>{const p=position(node.key);return <circle key={node.key} cx={p.x} cy={p.y} r={grove.roots.includes(node.key)?4.5:3.5} className={`is-${nodeState(node).tone}`}/>;})}
 </svg>;
}
function Tree({grove,selected,onSelect}:{grove:KnowledgeGrove;selected?:string;onSelect:(key:string)=>void}){
 const [zoom,setZoom]=useState(1);
 const {points,width,height}=useMemo(()=>layout(grove.nodes),[grove]);
 const highlighted=new Set<string>();
 const pending=selected?[selected]:[];
 while(pending.length){const key=pending.pop()!;if(highlighted.has(key))continue;highlighted.add(key);pending.push(...(grove.nodes.find(node=>node.key===key)?.parentKeys??[]));}
 return <div className="kf-tree-shell">
  <div className="kf-tree-scroll" tabIndex={0} aria-label="知识谱系画布，可滚动查看">
   <div style={{width:width*zoom,height:height*zoom}}><div className="kf-tree" style={{width,height,transform:`scale(${zoom})`}}>
    <svg width={width} height={height} aria-hidden="true">{grove.nodes.flatMap(node=>node.parentKeys.map(key=>{
     const from=points.get(key)!,to=points.get(node.key)!,sx=from.x+236,sy=from.y+87,tx=to.x,ty=to.y+87;
     return <path key={`${key}:${node.key}`} className={highlighted.has(key)&&highlighted.has(node.key)?'is-selected':''} d={`M${sx},${sy} C${sx+32},${sy} ${tx-32},${ty} ${tx},${ty}`}/>;
    }))}</svg>
    {grove.nodes.map(node=>{const point=points.get(node.key)!;return <button key={node.key} type="button" className={`kf-node${node.context?' is-context':''}`} style={{left:point.x,top:point.y}} aria-label={`查看知识 ${node.entry.claimId} · ${versionLabel(node)}`} aria-pressed={selected===node.key} onClick={()=>onSelect(node.key)}>
     <span className="kf-node-meta"><span>{node.entry.claimId}</span><Badge node={node}/></span>
     <strong>{nodeTitle(node)}</strong><span className="kf-node-excerpt">{entryText(node.revision)}</span>
     <span className="kf-node-foot">{node.context?'祖先上下文':versionLabel(node)}<span>{knowledgeSupport(node.entry.claimId,node.revision).support===null?'':`${knowledgeSupport(node.entry.claimId,node.revision).support} 题支持`}</span></span>
    </button>;})}
   </div></div>
  </div>
  <div className="kf-zoom" aria-label="画布缩放"><button aria-label="缩小知识树" disabled={zoom<=.6} onClick={()=>setZoom(value=>Math.max(.6,value-.1))}><Minus size={15}/></button><button aria-label="重置知识树缩放" onClick={()=>setZoom(1)}>{Math.round(zoom*100)}%</button><button aria-label="放大知识树" disabled={zoom>=1.3} onClick={()=>setZoom(value=>Math.min(1.3,value+.1))}><Plus size={15}/></button></div>
 </div>;
}
function Inspector({node,onRead}:{node?:ForestNode;onRead:Props['onRead']}){
 const [tab,setTab]=useState('知识');
 if(!node)return <aside className="kf-inspector kf-inspector-empty" aria-label="森林知识详情"><Leaf size={30}/><h3>从一条知识开始</h3><p>选择一棵知识树，查看原始命题如何生长出更具体的规律。</p><span>知识内容 · 题目证据 · 修订版本</span></aside>;
 const support=knowledgeSupport(node.entry.claimId,node.revision),saved=node.sourceClaim;
 return <aside className="kf-inspector" aria-label="森林知识详情">
  <header><span>{node.entry.claimId} · {versionLabel(node)}</span><Badge node={node}/></header>
  <h3>{nodeTitle(node)}</h3>
  <p className="kf-origin">{node.entry.library.name}{saved?.parent?` · 来自 ${saved.parent.id} 第 ${saved.parent.version} 版`:''}</p>
  <Tabs tabs={['知识','证据','版本']} value={tab} onChange={setTab}/>
  <div className="kf-inspector-content">
   {tab==='知识'?<><p className="kf-statement">{entryText(node.revision)}</p>
    {node.revision.parts.filter(part=>part.rule).map((part,index)=>{let rows:[string,string][]=[];try{rows=ruleConditions(part.rule);}catch{/* Full saved syntax remains in the detail reader. */}return <section className="kf-rule-branch" key={index} aria-label={`执行分支 ${index+1}`}>
     {node.revision.parts.filter(part=>part.rule).length>1&&<h4>分支 {index+1}</h4>}<dl className="kf-conditions">{rows.map(([label,value],row)=><div key={row}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </section>;})}
    <div className="kf-evidence-summary"><strong>{supportLabel(support)}</strong><p>{support.notice}</p></div>
    <ConsistencyAuditView audit={node.revision.record.consistency_audits?.[node.entry.claimId]}/>
    {saved?.consistency?.consistent===false&&<p className="kf-notice">文字与执行规则仍需复核，完整记录保留在详情中。</p>}
   </>:tab==='证据'?<><p className="kf-evidence-summary">{supportLabel(support)}</p>{node.revision.parts.every(part=>part.library_only)?<p className="kf-notice">这条知识未进入可执行规则库，保留的来源记录可在完整详情中查看。</p>:<KnowledgeQuestions compact kbRef={{id:node.revision.record.id,version:node.revision.record.version}} claimId={node.entry.claimId} relation="applicable"/>}</>:<KnowledgeEntryHistory entry={node.entry} selected={node.revision} onRead={onRead}/>}
   {node.missingParents.length>0&&<p className="kf-notice">父版本暂不可连线：{node.missingParents.join('；')}</p>}
  </div>
  <button className="kf-open-detail" onClick={()=>onRead({key:node.entry.key,version:revisionKey(node.revision)})}>打开完整知识详情<ArrowUpRight size={15}/></button>
 </aside>;
}
export function KnowledgeForest({entries,matches,onRead}:Props){
 const forest=useMemo(()=>buildKnowledgeForest(entries,matches),[entries,matches]);
 const [groveKey,setGroveKey]=useState<string>(),[selectedKey,setSelectedKey]=useState<string>();
 const grove=forest.groves.find(item=>item.key===groveKey);
 const selected=[...forest.groves.flatMap(item=>item.nodes),...forest.independent].find(node=>node.key===selectedKey);
 const standalone=forest.independent.filter(node=>!node.missingParents.length),unresolved=forest.independent.filter(node=>node.missingParents.length);
 const open=(item:KnowledgeGrove)=>{setGroveKey(item.key);setSelectedKey(item.roots[0]);};
 const singleList=(nodes:ForestNode[])=><div className="kf-single-list">{nodes.map(node=><button key={node.key} aria-label={`查看知识 ${node.entry.claimId} · ${versionLabel(node)}`} aria-pressed={selectedKey===node.key} onClick={()=>setSelectedKey(node.key)}><span>{node.entry.claimId}<Badge node={node}/></span><strong>{entryText(node.revision)}</strong></button>)}</div>;
 return <div className="knowledge-forest">
  <div className="kf-overview-heading"><div><h2><GitBranch size={18}/>知识森林</h2><p>{forest.groves.length} 个知识谱系 · {forest.matchedCount} 条来源知识{unresolved.length?` · ${unresolved.length} 条父版本待补全`:''}</p></div>
   <div className="kf-legend"><span><i className="is-verified"/>来源已验证</span><span><i className="is-candidate"/>候选</span><span><i className="is-retired"/>停用</span></div>
  </div>
  <div className="kf-workspace">
   <div className="kf-main">
    {grove?<><div className="kf-branch-heading"><button onClick={()=>setGroveKey(undefined)}><ArrowLeft size={15}/>全部知识谱系</button><span>{grove.nodes.length} 个节点 · 连线指向修订后的知识</span></div><Tree key={grove.key} grove={grove} selected={selected?.key} onSelect={setSelectedKey}/></>:<>
     <div className="kf-forest-grid">{forest.groves.map(item=>{const root=item.nodes.find(node=>node.key===item.roots[0])!;return <button key={item.key} className="kf-grove" aria-label={`展开谱系 ${root.entry.claimId} · ${nodeTitle(root)}`} onClick={()=>open(item)}><span className="kf-grove-id">{root.entry.claimId}<GitBranch size={14}/></span><strong>{nodeTitle(root)}</strong><MiniTree grove={item}/><span className="kf-grove-footer">{item.nodes.length} 个节点<span>{root.entry.library.name}</span></span></button>;})}</div>
     {!forest.groves.length&&<p className="kf-notice">当前筛选下暂无可连接的知识谱系，可在下方阅读知识。</p>}
     {standalone.length>0&&<details className="kf-independent" open={!forest.groves.length}><summary>独立知识 · {standalone.length}<span>尚无父子关系记录</span></summary>{singleList(standalone)}</details>}
     {unresolved.length>0&&<details className="kf-independent"><summary>父版本待补全 · {unresolved.length}</summary>{singleList(unresolved)}</details>}
    </>}
   </div>
   <Inspector key={selected?.key??'empty'} node={selected} onRead={onRead}/>
  </div>
  <p className="kf-footnote">连线依据保存的父知识与版本引用。相同内容在列表中折叠，森林按来源保留谱系，支持题数不跨来源相加。</p>
 </div>;
}
