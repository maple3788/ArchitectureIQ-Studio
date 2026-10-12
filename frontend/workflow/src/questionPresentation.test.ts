import {expect,it} from 'vitest';
import {questionPresentation} from './questionPresentation';

it('uses the effective public dataset for the task and facts instead of conflicting prompt or candidate metadata',()=>{
 const value=questionPresentation({metadata:{family:'bigram_lm',metric:'test_ce'},
  public:{prompt:'## Dataset\nWRONG prompt description\n## Choices\nCandidate A',choices:[{view:{input_dim:99,train_size:999}}]},
  detail:{dataset:{files:{'dataset_spec.json':JSON.stringify({family:'univariate_regression',selection_metric:'test_mse',params:{
   expression:'sin(2*pi*x) + x*x',input_dim:1,domain:[-1,1],train_size:128,test_size:256,noise_std:0,
  }})}}}});
 expect(value.task).toContain('sin(2*pi*x) + x*x');
 expect(value.task).toContain('test_mse');expect(value.task).toContain('越低越好');
 expect(value.task).not.toMatch(/WRONG|token|test_ce/);
 expect(value.taskSource).toBe('dataset');expect(value.family).toBe('univariate_regression');
 expect(value.facts).toContainEqual({key:'input_dim',label:'输入维度',value:'1'});
 expect(value.facts).toContainEqual({key:'domain',label:'输入范围',value:'[-1, 1]'});
 expect(value.facts).toContainEqual({key:'noise_std',label:'噪声标准差',value:'0'});
 expect(value.facts.some(fact=>fact.value==='999')).toBe(false);
});

it('describes recorded sequence prediction conditions without treating training budget as dataset size',()=>{
 const value=questionPresentation({public:{family:'bigram_lm',choices:[{view:{budget:16384,steps:512,batch_size:32}}]},
  detail:{dataset:{files:{'dataset_spec.json':{family:'bigram_lm',selection_metric:'test_ce',params:{vocab_size:64,context_length:12}}}}}});
 expect(value.task).toContain('下一个 token');expect(value.task).toContain('12');expect(value.task).toContain('64');
 expect(value.task).toContain('越低越好');
 expect(value.facts).toContainEqual({key:'context_length',label:'上下文长度',value:'12'});
 expect(value.facts.some(fact=>['train_size','test_size','training_steps','total_samples_seen'].includes(fact.key))).toBe(false);
 expect(value.examples).toEqual([]);
});

it('uses recorded classification rules and known metric direction without guessing unknown metric semantics',()=>{
 const known=questionPresentation({detail:{dataset:{family:'synthetic_tabular_classification',selectionMetric:'test_accuracy',params:{input_dim:8,num_classes:3,rule_family:'threshold',active_features:[0,2]}}}});
 expect(known.task).toContain('分类');expect(known.task).toContain('8');expect(known.task).toContain('3');
 expect(known.task).toContain('越高越好');
 expect(known.facts).toContainEqual({key:'rule_family',label:'数据规则',value:'threshold'});
 const unknown=questionPresentation({metadata:{family:'xor_classification',metric:'custom_score'}});
 expect(unknown.task).toContain('异或');expect(unknown.task).toContain('custom_score');
 expect(unknown.task).not.toMatch(/越低|越高/);
});

it('extracts actual dataset prose while retaining the full section for disclosure and never summarizing code or later sections',()=>{
 const prompt='Read the training setups.\n## Dataset\nPredict the temperature from the three sensor measurements.\n\n### Synthesis\n```python\n# ## Choices\nSECRET_CODE\n```\n\n### Rules\nUse the recorded timestamps.\n## Choices\nSECRET_CHOICES';
 const value=questionPresentation({public:{prompt}});
 expect(value.task).toBe('Predict the temperature from the three sensor measurements.');
 expect(value.taskSource).toBe('prompt');expect(value.task).not.toContain('SECRET_');
 expect(value.datasetNarrative).toContain('Use the recorded timestamps.');
 expect(value.datasetNarrative).toContain('SECRET_CODE');expect(value.datasetNarrative).not.toContain('SECRET_CHOICES');
 expect(value.prompt).toBe(prompt);
});

it('prioritizes a recorded task section and specific dataset prose over generic family definitions',()=>{
 const fromDataset=questionPresentation({public:{family:'spiral_classification',prompt:'## Dataset\nPredict a scalar from five input features.\n## Choices\nA'}});
 expect(fromDataset.task).toBe('Predict a scalar from five input features.');
 expect(fromDataset.taskSource).toBe('prompt');
 const fromTask=questionPresentation({public:{prompt:'## Problem description\nEstimate the sensor response on the held-out interval.\n## Dataset\nUniform scalar inputs.'},
  detail:{dataset:{files:{'dataset_spec.json':{family:'univariate_regression',params:{expression:'x*x'}}}}}});
 expect(fromTask.task).toBe('Estimate the sensor response on the held-out interval.');
 expect(fromTask.facts).toContainEqual({key:'expression',label:'目标函数',value:'x*x'});
});

it('rejects explicitly conflicting legacy dataset family prose without suppressing specific compatible prose',()=>{
 const value=questionPresentation({public:{family:'bigram_lm',prompt:'## Dataset\nUnivariate regression on [0, 1].\n## Choices\nA'},
  detail:{dataset:{family:'bigram_lm',params:{vocab_size:64,context_length:12}}}});
 expect(value.task).toContain('下一个 token');expect(value.task).not.toContain('Univariate');
 const compatible=questionPresentation({public:{family:'bigram_lm',prompt:'## Dataset\nBigram language modeling with a recorded sparse transition table.\n## Choices\nA'}});
 expect(compatible.task).toContain('recorded sparse transition table');expect(compatible.taskSource).toBe('prompt');
});

it('reads explicit root dataset fields and examples with effective params taking precedence',()=>{
 const value=questionPresentation({detail:{dataset:{files:{'dataset_spec.json':{family:'multivariate_regression',task:'regression',
  input_dim:5,train_size:64,test_size:128,examples:[{input:[1,2,3,4,5],output:15}],params:{train_size:96}}}}}});
 expect(value.facts).toContainEqual({key:'input_dim',label:'输入维度',value:'5'});
 expect(value.facts).toContainEqual({key:'train_size',label:'训练集样本数',value:'96'});
 expect(value.facts).toContainEqual({key:'test_size',label:'测试集样本数',value:'128'});
 expect(value.facts).toContainEqual({key:'task',label:'任务类型',value:'regression'});
 expect(value.examples).toEqual([{input:'[1, 2, 3, 4, 5]',output:'15'}]);
});

it('does not backfill absent authoritative dataset fields from candidate views',()=>{
 const value=questionPresentation({public:{family:'univariate_regression',choices:[{view:{train_size:999,input_dim:55}}]},
  detail:{dataset:{files:{'dataset_spec.json':{family:'univariate_regression',params:{expression:'x*x'}}}}}});
 expect(value.facts.map(fact=>fact.key)).not.toContain('train_size');
 expect(value.facts.map(fact=>fact.key)).not.toContain('input_dim');
});

it('accepts only shared dataset facts from public candidate views when no dataset record exists',()=>{
 const value=questionPresentation({public:{family:'multivariate_regression',choices:[
  {view:{input_dim:4,train_size:128,noise_std:0,depth:2}},
  {view:{input_dim:4,train_size:256,noise_std:0,depth:4}},
 ]}});
 expect(value.facts).toContainEqual({key:'input_dim',label:'输入维度',value:'4'});
 expect(value.facts).toContainEqual({key:'noise_std',label:'噪声标准差',value:'0'});
 expect(value.facts.map(fact=>fact.key)).not.toContain('train_size');
 expect(value.facts.map(fact=>fact.key)).not.toContain('depth');
});

it('displays only explicitly recorded public examples and ignores result-shaped data',()=>{
 const value=questionPresentation({detail:{dataset:{params:{input_dim:2},examples:[
  {input:[1,2],output:3,answer:'SECRET_ANSWER'},
  {x:[0,0],y:0},
  {input:{winner:'SECRET_NESTED'},output:7},
  {question:'unrelated',answer:'SECRET_OPTION'},
 ]}},feedback:{examples:[{input:'SECRET_INPUT',output:'SECRET_OUTPUT'}]}});
 expect(value.examples).toEqual([{input:'[1, 2]',output:'3'},{input:'[0, 0]',output:'0'}]);
 expect(JSON.stringify(value)).not.toContain('SECRET_');
});

it('keeps missing and unfamiliar public data explicit without consulting private artifacts or executing synthesis',()=>{
 const record={metadata:{family:'future_dataset',winner:'SECRET_WINNER'},
  detail:{dataset:{files:{'synthesize.py':'SECRET_CODE','summary.json':{expression:'SECRET_EXPRESSION'}},params:{
   train_size:null,test_size:Infinity,examples:[{x:1,y:2}],ground_truth:'SECRET_GT',
  }}},feedback:{correct_letter:'SECRET_ANSWER'},provenance:{source_dataset_spec:{params:{expression:'SECRET_SOURCE'}}}};
 const before=JSON.stringify(record),value=questionPresentation(record);
 expect(value.task).toContain('future_dataset');expect(value.facts.map(fact=>fact.key)).toEqual(['family']);
 expect(value.examples).toEqual([{input:'1',output:'2'}]);
 expect(JSON.stringify(value)).not.toContain('SECRET_');expect(JSON.stringify(record)).toBe(before);
 expect(questionPresentation({}).taskSource).toBe('missing');
 expect(questionPresentation({}).facts).toEqual([]);
});
