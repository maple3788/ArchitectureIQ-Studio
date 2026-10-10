import type { Timestamp } from "./time";
export type Json = Record<string, any>;
export type List<T> = { items: T[]; total: number };
export type Question = {
  key: string;
  id: string;
  family: string;
  type: string;
  dataset_id?: string;
  profile?: string;
  model_types: string[];
  choices: number;
  budget: any;
  metric?: string;
  pair_id?: string;
  lineage_id?: string;
  ready: boolean;
  rag_ready?: boolean;
  issues: any[];
  source_count: number;
};
export type QuestionSet = {
  selection_mode?: "single" | "pairs";
  pair_keys?: string[];
  pairs?: any[];
  pair_count?: number;
  id: string;
  name: string;
  keys?: string[];
  questions?: any[];
  count?: number;
  created_at?: Timestamp;
};
export type ModelProfile = {
  id: string;
  name: string;
  model: string;
  base_url: string;
  parameters: {
    temperature?: number;
    top_p?: number;
    max_tokens?: number;
    extra?: Json;
  };
  runtime_lock_path?: string;
  api_key_env?: string;
  connection_type?: "self_hosted" | "api";
  credential_ref?: string;
  enabled: boolean;
  status?: string;
  check?: Json;
  verified?: boolean;
  [key: string]: any;
};
export type WorkflowNode = {
  id: string;
  type: string;
  label?: string;
  position: { x: number; y: number };
  config: Json;
};
export type WorkflowEdge = {
  id: string;
  source: string;
  target: string;
  source_handle?: string;
  target_handle?: string;
  condition?: string;
  mapping?: Json;
};
export type Workflow = {
  schema_version: number;
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  settings: Json;
};
export type Run = {
  id: string;
  kind: string;
  status: string;
  created_at: Timestamp;
  updated_at?: Timestamp;
  config: Json;
  progress?: Json;
  events?: any[];
  records?: any[];
  result?: any;
  error?: any;
  name?: string;
  [key: string]: any;
};
export type Bootstrap = {
  role_prompts?: Record<string, string>;
  service: { execution_enabled: boolean; host: string; state_root: string };
  stats: Json;
  capabilities: Json;
  workflow?: Workflow;
  models?: ModelProfile[];
};

export type StageId = 'data' | 'harness' | 'kb' | 'task';
export type MethodStep = { id: string; stage_id: StageId; label: string; node_ids: string[] };
export type MethodDefinition = {
  id: string; version: string | number; name: string; description: string;
  paper_url?: string | null; adaptation: string; status: string;
  learning_protocol: string; experience_mode: 'off' | 'expel_inspired' | 'basic_learning';
  steps: MethodStep[]; hash: string;
};
export type RoundDecision = {
  round_index: number; kb_version: string; available_actions: ('continue' | 'finish' | 'evaluate')[];
  next_round_available: boolean; next_round_index?: number; next_question_ids?: string[];
  next_round_reason?: string; status: 'waiting' | 'decided' | 'consumed'; action?: string;
};
