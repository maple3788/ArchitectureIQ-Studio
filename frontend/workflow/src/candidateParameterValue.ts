/** Format an already-public JSON parameter without inferring missing values or layers. */
export function candidateParameterValue(value:unknown):string{
 if(value===undefined)return '未记录';
 if(value===null)return 'null';
 if(typeof value==='boolean')return value?'yes':'no';
 if(typeof value==='string')return value.trim()?value:JSON.stringify(value);
 if(Array.isArray(value))return `(${Array.from(value,item=>
  typeof item==='string'&&/[(),\r\n]/.test(item)?JSON.stringify(item):candidateParameterValue(item)
 ).join(', ')})`;
 if(typeof value==='object')return JSON.stringify(value);
 return String(value);
}
