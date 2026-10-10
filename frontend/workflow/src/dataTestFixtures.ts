import type {DatasetRevision, DatasetSummary, BankItem} from './dataTypes';
import type {Bootstrap} from './types';
export const datasetFixture:DatasetRevision={collection_id:'ds_a',revision:'r1',parent_revision:null,name:'A',description:'Research questions',archived:false,selection_mode:'single',keys:['q1@v1'],pairs:[],created_at:'2026-10-11T00:00:00Z'};
export const summaryFixture:DatasetSummary={...datasetFixture,count:1,pair_count:0,families:['univariate_regression'],updated_at:datasetFixture.created_at};
export const bankFixtures:BankItem[]=[1,2].map(n=>({equivalence_id:`eq${n}`,representative_key:`q${n}@v1`,keys:[`q${n}@v1`],summary:{key:`q${n}@v1`,id:`Q${n}`,family:'univariate_regression',type:'architecture_only',model_types:['mlp'],choices:3,budget:4096,ready:n===1,rag_ready:true,issues:[],source_count:1,prompt:`Public research question ${n}`},sources:[],datasets:n===1?[summaryFixture]:[]}));
export const dataBootstrap:Bootstrap={service:{execution_enabled:false,host:'local',state_root:'fixture'},stats:{},capabilities:{profiles:[]}};
export const dataProps={version:0,act:async(fn:()=>Promise<any>)=>fn(),bootstrap:dataBootstrap,onRag:()=>{},onRun:()=>{}};
export const page=<T,>(items:T[])=>({items,total:items.length,offset:0,limit:25});
