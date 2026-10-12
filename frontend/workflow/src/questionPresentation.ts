import type {Json} from './types';
import {familyLabel as displayFamily} from './displayNames';

export type QuestionFact={key:string;label:string;value:string};
export type PublicQuestionPresentation={
 task:string;
 taskSource:'dataset'|'prompt'|'family'|'missing';
 family:string;
 familyLabel:string;
 facts:QuestionFact[];
 datasetNarrative:string;
 prompt?:string;
 examples:Array<{input:string;output:string}>;
};

const object=(value:unknown):Json=>value&&typeof value==='object'&&!Array.isArray(value)?value as Json:{};
const string=(value:unknown):string=>typeof value==='string'?value.trim():'';
function parsed(value:unknown):Json{
 if(typeof value==='string'){try{return object(JSON.parse(value));}catch{return {};}}
 return object(value);
}
const fields:Array<[string,string]>=[
 ['expression','目标函数'],['task','任务类型'],['input_dim','输入维度'],['output_dim','输出维度'],['domain','输入范围'],
 ['train_size','训练集样本数'],['test_size','测试集样本数'],['num_classes','类别数'],['rule_family','数据规则'],
 ['active_features','活跃特征索引'],['n_active_features','活跃特征数'],['spiral_turns','螺旋圈数'],
 ['vocab_size','词表大小'],['context_length','上下文长度'],['seq_len','序列长度'],['sequence_length','序列长度'],
 ['alpha','转移分布参数 α'],['noise_std','噪声标准差'],['instance_seed','数据实例种子'],
];
function valueText(value:unknown,depth=0):string|undefined{
 if(typeof value==='string')return value.trim()||undefined;
 if(typeof value==='number')return Number.isFinite(value)?String(value):undefined;
 if(typeof value==='boolean')return value?'开启':'关闭';
 if(Array.isArray(value)&&value.length&&value.length<=256&&depth<2){
  const values=value.map(item=>valueText(item,depth+1));
  if(values.every(item=>item!==undefined))return `[${values.join(', ')}]`;
 }
 return undefined;
}

/** Extract a public Markdown section while respecting fenced code boundaries. */
function sectionText(prompt:string,names:RegExp):string{
 const lines=prompt.split(/\r?\n/),selected:string[]=[];
 let level=0,fence='';
 for(const line of lines){
  const marker=line.trim().match(/^(`{3,}|~{3,})/);
  if(marker){
   if(!fence)fence=marker[1];else if(marker[1][0]===fence[0]&&marker[1].length>=fence.length)fence='';
   if(level)selected.push(line);
   continue;
  }
  const heading=!fence&&line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
  if(heading){
   if(level&&heading[1].length<=level)break;
   if(!level&&names.test(heading[2])){level=heading[1].length;continue;}
  }
  if(level)selected.push(line);
 }
 return selected.join('\n').trim();
}

function prosePreview(value:string):string{
 const selected:string[]=[];let fence='';
 for(const raw of value.split(/\r?\n/)){
  const line=raw.trim(),marker=line.match(/^(`{3,}|~{3,})/);
  if(marker){if(!fence)fence=marker[1];else if(marker[1][0]===fence[0]&&marker[1].length>=fence.length)fence='';continue;}
  if(fence)continue;
  if(!line||/^#{1,6}\s/.test(line)){if(selected.length)break;continue;}
  // Code, tables and HTML are retained only in the full public source.
  if(/^(?:\||<|import\s|from\s|def\s|class\s|return\s)/.test(line))continue;
  selected.push(line.replace(/^[-*]\s+/,'').replace(/\*\*([^*]+)\*\*|`([^`]+)`/g,'$1$2'));
 }
 const text=selected.join(' ').replace(/\s+/g,' ').trim();
 return text.length>320?text.slice(0,319)+'…':text;
}

function taskDefinition(family:string,params:Json):string{
 const expression=string(params.expression),dimension=valueText(params.input_dim),classes=valueText(params.num_classes);
 if(expression)return `学习输入与目标值之间的函数关系，拟合目标函数：${expression}。`;
 if(family==='bigram_lm'){
  const context=valueText(params.context_length),vocabulary=valueText(params.vocab_size);
  return `根据${context?`长度为 ${context} 的 `:''}token 上下文预测下一个 token${vocabulary?`，词表包含 ${vocabulary} 个 token`:''}。`;
 }
 if(family==='univariate_regression')return '学习标量输入与连续目标值之间的函数关系，完成一元回归。';
 if(family==='multivariate_regression')return `根据${dimension?`${dimension} 维`: '多维'}输入预测连续目标值，完成多元回归。`;
 if(family==='spiral_classification')return `根据输入坐标判断样本所属的螺旋类别${classes?`，共有 ${classes} 个类别`:''}。`;
 if(family==='xor_classification')return `学习输入特征间的异或关系，判断样本类别${classes?`，共有 ${classes} 个类别`:''}。`;
 if(family==='synthetic_tabular_classification')return `根据${dimension?`${dimension} 维`:''}表格特征进行分类${classes?`，判断样本属于 ${classes} 个类别中的哪一类`:''}${string(params.rule_family)?`；数据规则为 ${params.rule_family}`:''}。`;
 const task=string(params.task);
 if(task==='regression')return `根据${dimension?`${dimension} 维`:''}输入预测连续目标值。`;
 if(task==='classification')return `根据${dimension?`${dimension} 维`:''}输入判断样本类别${classes?`，共有 ${classes} 个类别`:''}。`;
 return task?`数据任务：${task}。`:'';
}

// The legacy prompt renderer used a univariate fallback even for other datasets.
// Reject only an explicitly named conflicting family, not inferred semantics.
const namedFamilies:Array<[string,RegExp]>=[
 ['univariate_regression',/\bunivariate(?:[_ -]+)regression\b|一元回归/i],
 ['multivariate_regression',/\bmultivariate(?:[_ -]+)regression\b|多元回归/i],
 ['bigram_lm',/\bbigram(?:[_ -]+)(?:lm|language(?:[_ -]+)model(?:ing)?)\b|二元语言模型/i],
 ['spiral_classification',/\bspiral(?:[_ -]+)classification\b|螺旋分类/i],
 ['xor_classification',/\bxor(?:[_ -]+)classification\b|异或分类/i],
 ['synthetic_tabular_classification',/\bsynthetic(?:[_ -]+)tabular(?:[_ -]+)classification\b|合成表格分类/i],
];
function compatibleProse(value:string,family:string):boolean{
 return !family||!namedFamilies.some(([name,pattern])=>name!==family&&pattern.test(value));
}
function datasetParams(dataset:Json):Json{
 const recorded:Json={};
 for(const [key] of fields)if(Object.hasOwn(dataset,key))recorded[key]=dataset[key];
 return {...recorded,...object(dataset.params)};
}

/** Display only recorded public task data; never inspect feedback, results, or source provenance. */
export function questionPresentation(record:Json):PublicQuestionPresentation{
 const detail=object(record.detail),pub=object(record.public),metadata=object(record.metadata);
 const dataset=object(detail.dataset),spec=parsed(object(dataset.files)['dataset_spec.json']);
 const family=[spec.family,dataset.family,pub.family,metadata.family].map(string).find(Boolean)||'';
 const prompt=typeof detail.prompt==='string'?detail.prompt:typeof pub.prompt==='string'?pub.prompt:undefined;
 const datasetNarrative=sectionText(prompt||'',/^(?:Dataset|Data|数据集|数据与规则|数据说明)$/i);
 const authoritative=Object.keys(spec).length>0||Object.keys(dataset).length>0;
 let params:Json;
 if(Object.keys(spec).length)params=datasetParams(spec);
 else if(Object.keys(dataset).length)params=datasetParams(dataset);
 else{
  const choices=Array.isArray(pub.choices)?pub.choices:[],views=choices.map(choice=>object(object(choice).view));
  params={};
  for(const [key] of fields){
   const value=views[0]?.[key];
   if(valueText(value)!==undefined&&views.every(view=>JSON.stringify(view[key])===JSON.stringify(value)))params[key]=value;
  }
 }
 const facts:QuestionFact[]=family?[{key:'family',label:'数据类型',value:displayFamily(family)}]:[];
 for(const [key,label] of fields){const value=valueText(params[key]);if(value!==undefined)facts.push({key,label,value});}
 const explicitTask=prosePreview(sectionText(prompt||'',/^(?:Task(?: description)?|Problem(?: description| statement)?|任务|题目任务|任务描述|问题描述)$/i));
 const datasetProse=prosePreview(datasetNarrative);
 let task=explicitTask;
 let taskSource:PublicQuestionPresentation['taskSource']=task?'prompt':'missing';
 if(!task&&string(params.expression)){
  task=taskDefinition(family,params);taskSource='dataset';
 }
 if(!task&&datasetProse&&compatibleProse(datasetProse,family)){
  task=datasetProse;taskSource='prompt';
 }
 if(!task){task=taskDefinition(family,params);if(task)taskSource=authoritative||Object.keys(params).length?'dataset':'family';}
 if(!task&&family){task=`数据任务：${displayFamily(family)}。`;taskSource='family';}
 if(!task)task='公开记录未提供具体的数据任务说明。';
 const metric=[spec.selection_metric,dataset.selectionMetric,metadata.metric].map(string).find(Boolean);
 const direction:Record<string,string>={test_mse:'越低越好',test_ce:'越低越好',test_loss:'越低越好',test_accuracy:'越高越好',test_acc:'越高越好'};
 if(metric&&taskSource!=='prompt')task+=` 评价指标：${metric}${direction[metric]?`，${direction[metric]}`:''}。`;
 const rawExamples=spec.examples??params.examples??dataset.examples??(dataset.example?[dataset.example]:[]);
 const examples:Array<{input:string;output:string}>=[];
 if(Array.isArray(rawExamples))for(const raw of rawExamples.slice(0,5)){
  const example=object(raw),input=valueText(example.input??example.x),output=valueText(example.output??example.y);
  if(input!==undefined&&output!==undefined)examples.push({input,output});
 }
 return {task,taskSource,family,familyLabel:family?displayFamily(family):'',facts,datasetNarrative,prompt,examples};
}
