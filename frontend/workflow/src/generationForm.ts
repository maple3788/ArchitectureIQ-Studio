import type {Json} from './types';
import type {DatasetRef} from './dataTypes';
export type GenerationFormState={generationMode:string;split:string;factor:string;originalValue:string;counterValue:string;profile:string;family:string;options:Json;counts:Record<string,number>;vary:string[];form:{seed:number;candidate_count:number;budget:number;n_seeds:number;num_questions:number;num_choices:number;question_type:string}};
export type GenerationRequest=Json & {profile:string;family:string;family_options:Json;dataset_target?:DatasetRef};
export function buildGenerationRequest(state:GenerationFormState,capabilities:Json|undefined,target?:DatasetRef):GenerationRequest{
 const {generationMode,split,factor,originalValue,counterValue,profile,family,options,counts,vary,form}=state;
 const current=capabilities?.profiles?.find((p:Json)=>p.name===profile)?.families.find((f:Json)=>f.name===family);
 if(!profile||!family||!form.budget||!vary.length||!current)throw Error('请选择 Profile、Family、预算与变化轴。');
 const fields=current.form_schema?.editable_fields||[];
 const family_options:Json={};
 for(const [name,value] of Object.entries(options)){
  const field=fields.find((f:Json)=>f.name===name);if(!field)throw Error('生成参数不在当前服务端能力清单中。');
  if(value!==''&&value!==undefined)family_options[name]=value;
 }
 let intervention;
 if(generationMode==='paired'){
  if(!current.data_interventions?.some((i:Json)=>i.factor===factor))throw Error('当前数据家族尚不支持受控题对生成，请选择已登记因素的家族。');
  try{intervention={factor,original_value:JSON.parse(originalValue),counterfactual_value:JSON.parse(counterValue)};}catch{throw Error('因素值需要合法的数字或区间，例如 1.4 或 [0, 1]。');}
 }
 return {mode:generationMode,split,...(intervention?{intervention}:{}),profile,family,...form,question_type:form.question_type||undefined,family_options,vary,
 model_type_counts:Object.keys(counts).length?Object.fromEntries(Object.entries(counts).filter(([,n])=>n>0)):undefined,...(target?{dataset_target:target}:{})};
}
export function generationSignature(value:unknown):string{
 return JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
}
