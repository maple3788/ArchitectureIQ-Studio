import type {ReactNode} from 'react';
import type {Json} from './types';
import {Field} from './ui';
export function GenerationBlock({number,title,summary,children}:{number:string;title:string;summary:string;children:ReactNode}){
 return <details className="generation-block" open><summary><span>{number}</span><div><b>{title}</b><small>{summary}</small></div></summary><div className="generation-block-body">{children}</div></details>;
}
export function GenerationBlocks({schema,value,onChange}:{schema?:Json;value:Json;onChange:(value:Json)=>void}){
 const fields:Json[]=schema?.editable_fields||[];
 return <div>{!fields.length&&<p className="muted">此类型按服务端规则采样，无额外可编辑参数。</p>}<div className="form-grid">{fields.map(field=><Field label={field.label} key={field.name} hint={field.unit||undefined}><select value={value[field.name]??''} onChange={e=>{const next={...value};if(e.target.value==='')delete next[field.name];else next[field.name]=field.type==='integer'?Number(e.target.value):e.target.value;onChange(next);}}><option value="">自动采样</option>{(field.enum||[]).map((option:string|number)=><option value={option} key={String(option)}>{option}</option>)}</select></Field>)}</div>{!!schema?.read_only_facts?.length&&<details className="generation-readonly"><summary>数据规则与固定条件</summary><dl>{schema.read_only_facts.map((fact:Json)=><div key={fact.name}><dt>{fact.label}</dt><dd>{typeof fact.value==='string'?fact.value:JSON.stringify(fact.value)}</dd></div>)}</dl></details>}</div>;
}
