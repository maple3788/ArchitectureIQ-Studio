import type {Workflow,Json} from './types';
import type {DatasetRef,Selection} from './dataTypes';
export type KBRef={id:string;version:string};
export type RuleRevision={rule_id:string;revision:string;parents:Json[];text:string;rationale:string;rule:Json;state:string;source_refs:Json[];metadata?:Json};
export type RuleKB={kind:string;schema_version:number;version:string;parent_version:string|null;rules:RuleRevision[];executable_hash:string;import_issues:Json[];source_document?:Json;confirmation_protocol?:Json};
export type PublicCase={ref:{key:string;hash:string};question:Json;dataset_spec:Json;candidate_specs:Json[];objective:string};
export type RulePrediction={question_ref:PublicCase['ref'];kb_version:string;status:string;answer_id?:string;edges:Json[];paths:Record<string,string[]>;issues?:Json[]};
export type RuleContextMatch={question_ref:PublicCase['ref'];kb_version:string;status:string;matches:Json[];rule_ids:string[];claim_ids:string[];issues?:Json[]};
export type RuleMatch={items:RulePrediction[];cases:PublicCase[];total:number;matched_count:number;offset:number;limit:number;context_matches?:RuleContextMatch[]};
export type RefinementRequest={workflow:Workflow;dataset_ref:DatasetRef;selection:Selection;initial_kb_ref?:KBRef};
export type RulePreview={preview_hash:string;can_run:boolean;blockers:{code:string;message:string}[];counts:{questions:number;pairs:number};cost?:Json;limits?:Json;independence?:string};
export type EvaluationRequest={kb_ref:KBRef;dataset_ref:DatasetRef;selection:Selection;phase:'development'|'final'};
export type RuleScore={selected:number;scorable:number;unscorable:number;correct:number;answered:number;conflicts:number;wrong_assertions:number;all_pass:boolean;accuracy:number;answer_coverage:number;per_question:Record<string,Json>;per_rule:Record<string,Json>;problems:Json[];[key:string]:any};
export type RuleArtifact={id:string;kind:string;label:string;value?:Json};

export type RuleRefinementView={phase:string;phaseId?:string;success:boolean;status:string;score?:RuleScore;batches:Json[];kb?:RuleKB;kbVersion?:string;poolVersion?:string;events:Json[];budget?:Json;revision:number};
