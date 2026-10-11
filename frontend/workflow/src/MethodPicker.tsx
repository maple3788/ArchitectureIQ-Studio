import type {MethodDefinition} from './types';
import {Field} from './ui';
export function MethodPicker({methods,methodId,onChange,paired}:{methods:MethodDefinition[];methodId?:string;onChange:(method:MethodDefinition)=>void;paired:boolean}) {
 const selected=methods.find(m=>m.id===methodId);
 return <section className="method-picker"><Field label="论文方法" hint="配方冻结方法版本、步骤与经验更新方式；论文来源不代表已经对照复现。"><select value={methodId??''} onChange={e=>{const method=methods.find(m=>m.id===e.target.value);if(method)onChange(method);}}><option value="" disabled>历史自定义流程 · 选择方法开始新草稿</option>{methods.map(method=><option key={method.id} value={method.id} disabled={method.status!=='available'||!(method.data_modes??[method.learning_protocol.startsWith('paired_')?'pairs':'single']).includes(paired?'pairs':'single')}>{method.name} · v{method.version}</option>)}</select></Field>{selected&&<div><p>{selected.description}</p><p>{selected.adaptation}</p><small>{selected.status==='available'?'可运行改编版':selected.status} · {selected.experience_mode==='expel_inspired'?'包含未验证经验记忆':'正式科学证据流程'}</small>{selected.paper_url&&<p><a href={selected.paper_url} target="_blank" rel="noreferrer">查看论文来源</a></p>}</div>}</section>;
}
