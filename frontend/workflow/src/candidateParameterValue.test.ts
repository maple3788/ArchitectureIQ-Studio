import {expect,it} from 'vitest';
import {candidateParameterValue} from './candidateParameterValue';

it('renders ordered per-layer boolean tuples without collapsing or duplicating values',()=>{
 expect(candidateParameterValue([true,false])).toBe('(yes, no)');
 expect(candidateParameterValue([false,true,false])).toBe('(no, yes, no)');
 expect(candidateParameterValue([true,true])).toBe('(yes, yes)');
 expect(candidateParameterValue([false])).toBe('(no)');
 expect(candidateParameterValue(true)).toBe('yes');
 expect(candidateParameterValue(false)).toBe('no');
});

it('keeps recorded numeric and string tuples readable without treating them as boolean switches',()=>{
 expect(candidateParameterValue([0.9,0.999])).toBe('(0.9, 0.999)');
 expect(candidateParameterValue(['relu','gelu'])).toBe('(relu, gelu)');
 expect(candidateParameterValue([1,0])).toBe('(1, 0)');
 expect(candidateParameterValue(['true','false'])).toBe('(true, false)');
 expect(candidateParameterValue([[true,false],[0,2]])).toBe('((yes, no), (0, 2))');
});

it('distinguishes missing, null, zero, false and explicitly empty values',()=>{
 const displayed=[undefined,null,0,false,'',[],{}].map(candidateParameterValue);
 expect(displayed).toEqual(['未记录','null','0','no','""','()','{}']);
 expect(new Set(displayed).size).toBe(displayed.length);
 expect(candidateParameterValue([undefined,null,0,false,'',[]])).toBe('(未记录, null, 0, no, "", ())');
 expect(candidateParameterValue(Array(2))).toBe('(未记录, 未记录)');
 expect(candidateParameterValue('  ')).toBe('"  "');
});

it('preserves public parameter content and does not infer additional architecture values',()=>{
 const value={type:'mlp',layer_norm:[true,false],residual:false,width:0};
 const before=structuredClone(value);
 expect(candidateParameterValue(value)).toBe(JSON.stringify(value));
 expect(candidateParameterValue('unchanged option')).toBe('unchanged option');
 expect(candidateParameterValue(['<tag>','a, b'])).toBe('(<tag>, "a, b")');
 expect(value).toEqual(before);
});
