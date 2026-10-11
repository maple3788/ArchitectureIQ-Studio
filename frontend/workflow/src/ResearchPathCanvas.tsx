import {useMemo, useState, type ReactNode} from 'react';
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow,
  type Connection, type Node, type NodeChange, type NodeProps,
} from '@xyflow/react';
import {BookOpen, Database, GitBranch, Sparkles, Workflow} from 'lucide-react';
import {nodeStatusLabel, type NodeStatus} from './runWorkflow';
import '@xyflow/react/dist/style.css';
import './research-path.css';

export type PathPortSide = 'left' | 'right' | 'top' | 'bottom';
export type PathNode = {
  id: string;
  label: string;
  description?: string;
  stage?: 'data' | 'harness' | 'kb' | 'task';
  kind?: 'model' | 'program' | 'decision';
  status?: string;
  position?: {x: number; y: number};
  inputs?: string[];
  outputs?: string[];
  inputSides?: Record<string,PathPortSide>;
  outputSides?: Record<string,PathPortSide>;
};
export type PathEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  sourceHandle?: string;
  targetHandle?: string;
  loop?: boolean;
  optional?: boolean;
};
type PositionMap = Record<string, {x: number; y: number}>;
type CardNode = Node<{
  item: PathNode;
  index: number;
  reverse: boolean;
  select: (id: string) => void;
}, 'researchPath'>;

const stageNames = {data: 'Data', harness: 'Harness', kb: 'KB', task: 'Task'};

function PathCard({data, selected, isConnectable}: NodeProps<CardNode>) {
  const {item, index, reverse, select} = data;
  const Icon = item.stage === 'data' ? Database : item.stage === 'kb' ? BookOpen
    : item.kind === 'decision' ? GitBranch : item.kind === 'model' ? Sparkles : Workflow;
  const inputs = item.inputs?.length ? item.inputs : ['in'];
  const outputs = item.outputs?.length ? item.outputs : ['out'];
  const portPosition=(side:PathPortSide)=>({left:Position.Left,right:Position.Right,top:Position.Top,bottom:Position.Bottom})[side];
  const portStyle=(ports:string[],sides:Record<string,PathPortSide>|undefined,port:string,fallback:PathPortSide)=>{
    const side=sides?.[port]??fallback,siblings=ports.filter(id=>(sides?.[id]??fallback)===side);
    return {[side==='top'||side==='bottom'?'left':'top']:`${(siblings.indexOf(port)+1)*100/(siblings.length+1)}%`};
  };
  return <div className={`research-path-card ${selected ? 'is-selected' : ''} stage-${item.stage ?? 'harness'}`}>
    {inputs.map((port, i) => <Handle key={`in-${port}`} id={port} type="target"
      position={portPosition(item.inputSides?.[port]??(reverse?'right':'left'))} isConnectable={isConnectable}
      style={portStyle(inputs,item.inputSides,port,reverse?'right':'left')}/>)}
    <button type="button" className="research-path-card-button" aria-label={item.label}
      aria-pressed={selected} onClick={() => select(item.id)}>
      <span className="research-path-card-top"><span className="research-path-icon"><Icon size={16}/></span>
        <span>{stageNames[item.stage ?? 'harness']}</span><span className="research-path-index">{String(index + 1).padStart(2, '0')}</span>
      </span>
      <strong>{item.label}</strong>
      {item.description && <span className="research-path-description">{item.description}</span>}
      {item.status && <span className={`research-path-status status-${item.status}`}>
        <i aria-hidden="true"/>{nodeStatusLabel[item.status as NodeStatus] ?? item.status}
      </span>}
    </button>
    {outputs.map((port, i) => <Handle key={`out-${port}`} id={port} type="source"
      position={portPosition(item.outputSides?.[port]??(reverse?'left':'right'))} isConnectable={isConnectable}
      style={portStyle(outputs,item.outputSides,port,reverse?'left':'right')}/>)}
  </div>;
}
const nodeTypes = {researchPath: PathCard};

/** Positions only describe the view; they never create or rewrite execution routes. */
export function researchPathPositions(nodes: PathNode[]): PositionMap {
  const columns = nodes.length > 10 ? 4 : 3;
  return Object.fromEntries(nodes.map((node, index) => {
    const row = Math.floor(index / columns), column = row % 2 ? columns - 1 - index % columns : index % columns;
    return [node.id, node.position ?? {x: column * 270, y: row * 190}];
  }));
}

export function ResearchPathCanvas(props: {
  nodes: PathNode[];
  edges: PathEdge[];
  selectedId: string;
  onSelect: (id: string) => void;
  inspector?: ReactNode;
  inspectorPresentation?: 'sidebar' | 'overlay';
  toolbar?: ReactNode;
  footer?: ReactNode;
  ariaLabel?: string;
  onMove?: (id: string, position: {x: number; y: number}) => void;
  onConnect?: (connection: Connection) => void;
}) {
  // A method change resets only local view state, never the caller's draft.
  const signature = props.nodes.map(node => node.id).join('|');
  return <ResearchPathSurface key={signature} {...props}/>;
}

function ResearchPathSurface({nodes, edges, selectedId, onSelect, inspector, inspectorPresentation='sidebar', toolbar, footer,
  ariaLabel = '研究路径画布', onMove, onConnect}: Parameters<typeof ResearchPathCanvas>[0]) {
  const [arrangement, setArrangement] = useState<PositionMap>({});
  const [measurements, setMeasurements] = useState<Record<string, {width: number; height: number}>>({});
  const positions = useMemo(() => researchPathPositions(nodes), [nodes]);
  const columns = nodes.length > 10 ? 4 : 3;
  const renderedNodes: CardNode[] = nodes.map((item, index) => ({
    id: item.id, type: 'researchPath', position: arrangement[item.id] ?? positions[item.id],
    measured: measurements[item.id],
    selected: item.id === selectedId, deletable: false,
    data: {item, index, reverse: !item.position && Math.floor(index / columns) % 2 === 1, select: onSelect},
  }));
  const move = (changes: NodeChange<CardNode>[]) => {
    const dimensions = changes.filter(change => change.type === 'dimensions' && change.dimensions);
    if (dimensions.length) setMeasurements(previous => {
      const next = {...previous};
      for (const change of dimensions) if (change.type === 'dimensions' && change.dimensions) next[change.id] = change.dimensions;
      return next;
    });
    const moves = changes.filter(change => change.type === 'position' && change.position);
    if (moves.length) setArrangement(previous => {
      const next = {...previous};
      for (const change of moves) if (change.type === 'position' && change.position) next[change.id] = change.position;
      return next;
    });
  };
  return <section className="research-path" aria-label={ariaLabel}>
    {toolbar && <div className="research-path-toolbar">{toolbar}</div>}
    <div className={`research-path-layout ${!inspector?'without-inspector':''} ${inspectorPresentation==='overlay'?'overlay-inspector':''}`}>
      <div className="research-path-board">
        <ReactFlow<CardNode> nodes={renderedNodes} nodeTypes={nodeTypes}
          edges={edges.map(edge => ({...edge, type: 'smoothstep',
            sourceHandle: edge.sourceHandle ?? nodes.find(node => node.id === edge.source)?.outputs?.[0] ?? 'out',
            targetHandle: edge.targetHandle ?? nodes.find(node => node.id === edge.target)?.inputs?.[0] ?? 'in',
            markerEnd: {type: MarkerType.ArrowClosed, width: 16, height: 16},
            deletable: false, selectable: false,
            className: edge.loop ? 'research-path-loop' : edge.optional ? 'research-path-optional' : undefined,
            labelStyle: {fontSize: 11, fill: '#587069'},
            labelBgStyle: {fill: '#f5f8f7', fillOpacity: 0.96},
            labelBgPadding: [6, 4] as [number, number],
          }))}
          fitView fitViewOptions={{padding: 0.12, maxZoom: 0.9, minZoom: 0.2}}
          defaultViewport={{x: 34, y: 48, zoom: 0.82}} minZoom={0.2} maxZoom={1.4}
          zoomOnScroll={inspectorPresentation!=='overlay'} preventScrolling={inspectorPresentation!=='overlay'}
          nodesDraggable nodesConnectable={!!onConnect} nodesFocusable={false}
          edgesFocusable={false} deleteKeyCode={null} onNodesChange={move}
          onNodeDragStop={(_, node) => {
            if (!onMove) return;
            onMove(node.id, node.position);
            // The saved draft owns positions once a drag is committed, including
            // positions subsequently restored from a backup or another window.
            setArrangement(previous => {
              const next = {...previous};
              delete next[node.id];
              return next;
            });
          }} onConnect={onConnect}
          >
          <Background color="#dce5df" gap={20} size={1}/>
          <Controls showInteractive={false} fitViewOptions={{padding: 0.16, maxZoom: 0.95, minZoom: 0.2}}/>
        </ReactFlow>
        <span className="research-path-board-hint">拖动画布 · 点击节点配置</span>
      </div>
      {inspector&&<aside className="research-path-inspector" aria-label="节点详情">{inspector}</aside>}
    </div>
    {footer && <div className="research-path-footer">{footer}</div>}
  </section>;
}
