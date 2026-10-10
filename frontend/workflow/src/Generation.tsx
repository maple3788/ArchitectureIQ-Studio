import {QuestionBuilder} from './QuestionBuilder';
import type {Json} from './types';
import type {Action} from './Questions';
// Keep the established generation route and submission callback behavior.
export function Generation(props:{capabilities?:Json;version:number;act:Action;executionEnabled:boolean;onRun:(id:string)=>void}){
 return <QuestionBuilder {...props}/>;
}
