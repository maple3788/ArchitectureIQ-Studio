import { LiveWorkflowCanvas } from "./LiveWorkflowCanvas";
import { deriveLiveWorkflow, stageDefinitions } from "./liveWorkflow";
import type { Run } from "./types";
import type { NodeStatus } from "./runWorkflow";
export const pipelineStages = stageDefinitions.map(stage=>({...stage,nodes:stage.nodeIds}));
export function pipelineStatus(run:Run,stage:string):NodeStatus {
 return deriveLiveWorkflow({run}).stages.find(s=>s.id===stage)?.status??"unknown";
}
export function PipelineRunView({run,syncError}:{run:Run;syncError?:string}) {
 return <LiveWorkflowCanvas run={run} syncState={{error:syncError}}/>;
}
