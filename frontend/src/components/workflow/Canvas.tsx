import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type NodeMouseHandler,
  type OnEdgesChange,
  type OnNodesChange,
  ReactFlow,
  ReactFlowProvider,
  applyEdgeChanges,
  applyNodeChanges,
  type NodeTypes,
  ViewportPortal,
  useReactFlow,
} from "@xyflow/react";
import { useEffect, useRef, useState } from "react";

import { foundationLaneGroups } from "../../lib/workflowCanvasModel";
import { useWorkflowUiStore } from "../../stores/workflowUiStore";
import { useWorkflowStore, type WorkflowEdge, type WorkflowNode } from "../../stores/workflowStore";
import { DataFlowEdge } from "./edges/DataFlowEdge";
import { DatasetNode } from "./nodes/DatasetNode";
import { ForkNode } from "./nodes/ForkNode";
import { GroupNode } from "./nodes/GroupNode";
import { OperationNode } from "./nodes/OperationNode";

const nodeTypes: NodeTypes = {
  groupNode: GroupNode,
  operationNode: OperationNode,
  datasetNode: DatasetNode,
  forkNode: ForkNode,
};

const edgeTypes = {
  dataFlowEdge: DataFlowEdge,
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || tagName === "input" || tagName === "textarea" || tagName === "select";
}

type CanvasSurfaceProps = {
  onForkFromNode?: (nodeId: string) => void;
  canFork: boolean;
  isForking: boolean;
  defaultBrightHubUuid?: string | null;
};

function CanvasSwimLanes() {
  return (
    <ViewportPortal>
      <div className="workflow-swimlanes-layer" aria-hidden>
        {foundationLaneGroups.map((lane, index) => (
          <div
            key={lane.id}
            className={`workflow-swimlane workflow-swimlane-${index + 1}`}
          >
            <div className="workflow-swimlane-header">
              <span className="workflow-swimlane-kicker">Lane {index + 1}</span>
              <h3>{lane.label}</h3>
              <p>{lane.description}</p>
            </div>
          </div>
        ))}
      </div>
    </ViewportPortal>
  );
}

function CanvasSurface({ onForkFromNode, canFork, isForking, defaultBrightHubUuid = null }: CanvasSurfaceProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const { fitView, screenToFlowPosition } = useReactFlow<WorkflowNode, WorkflowEdge>();
  const [contextNodeId, setContextNodeId] = useState<string | null>(null);
  const [contextNodeLabel, setContextNodeLabel] = useState<string | null>(null);
  const activeBranchId = useWorkflowUiStore((state) => state.activeBranchId);
  const setSelectedNodeId = useWorkflowUiStore((state) => state.setSelectedNodeId);
  const branchState = useWorkflowStore((state) => state.branchStates[activeBranchId]);
  const setNodes = useWorkflowStore((state) => state.setNodes);
  const setEdges = useWorkflowStore((state) => state.setEdges);
  const connectNodes = useWorkflowStore((state) => state.connectNodes);
  const addOperationNode = useWorkflowStore((state) => state.addOperationNode);
  const addDatasetNode = useWorkflowStore((state) => state.addDatasetNode);
  const largeWorkflowMode = branchState.nodes.length >= 120;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) {
        return;
      }

      if (event.key === "Escape") {
        setContextNodeId(null);
        setContextNodeLabel(null);
        return;
      }

      if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        void fitView({ duration: 240, padding: 0.2 });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fitView]);

  useEffect(() => {
    setContextNodeId(null);
    setContextNodeLabel(null);
  }, [activeBranchId]);

  const handleNodesChange: OnNodesChange<WorkflowNode> = (changes) => {
    setNodes(activeBranchId, applyNodeChanges<WorkflowNode>(changes, branchState.nodes));
  };

  const handleEdgesChange: OnEdgesChange<WorkflowEdge> = (changes) => {
    setEdges(activeBranchId, applyEdgeChanges<WorkflowEdge>(changes, branchState.edges));
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const templateId = event.dataTransfer.getData("application/gokaatru-node-template");
    const datasetId = event.dataTransfer.getData("application/gokaatru-dataset");
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });

    if (templateId) {
      setSelectedNodeId(addOperationNode(activeBranchId, templateId, position, defaultBrightHubUuid));
    }

    if (datasetId) {
      setSelectedNodeId(addDatasetNode(activeBranchId, datasetId, position));
    }
  };

  const handleNodeContextMenu: NodeMouseHandler<WorkflowNode> = (event, node) => {
    event.preventDefault();
    setSelectedNodeId(node.id);
    if ((node.data.kind === "operation" || node.data.kind === "dataset") && node.data.status === "done") {
      setContextNodeId(node.id);
      setContextNodeLabel(node.data.label);
      return;
    }
    setContextNodeId(null);
    setContextNodeLabel(null);
  };

  const closeContextMenu = () => {
    setContextNodeId(null);
    setContextNodeLabel(null);
  };

  return (
    <div ref={wrapperRef} className="workflow-canvas-shell" onDragOver={handleDragOver} onDrop={handleDrop}>
      <ReactFlow
        fitView
        onlyRenderVisibleElements
        deleteKeyCode={["Backspace", "Delete"]}
        nodes={branchState.nodes}
        edges={branchState.edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={(connection) => connectNodes(activeBranchId, connection)}
        onNodeContextMenu={handleNodeContextMenu}
        onNodeClick={(_, node) => setSelectedNodeId(node.id)}
        onPaneClick={() => {
          setSelectedNodeId(null);
          closeContextMenu();
        }}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        proOptions={{ hideAttribution: true }}
      >
        <CanvasSwimLanes />
        {!largeWorkflowMode ? <MiniMap pannable zoomable className="workflow-minimap" /> : null}
        <Controls className="workflow-controls" />
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
      </ReactFlow>
      {largeWorkflowMode ? (
        <div className="workflow-performance-chip">Performance mode: rendering visible nodes only</div>
      ) : null}
      {contextNodeId ? (
        <div className="workflow-canvas-context-menu" role="region" aria-label="Node actions">
          <p className="workflow-canvas-context-title">Node: {contextNodeLabel ?? contextNodeId}</p>
          <button
            className="secondary-button"
            type="button"
            disabled={!canFork || isForking}
            onClick={() => {
              onForkFromNode?.(contextNodeId);
              closeContextMenu();
            }}
          >
            {isForking ? "Forking..." : "Fork from this node"}
          </button>
          <button className="ghost-button" type="button" onClick={closeContextMenu}>
            Close
          </button>
        </div>
      ) : null}
    </div>
  );
}

type CanvasProps = {
  onForkFromNode?: (nodeId: string) => void;
  canFork?: boolean;
  isForking?: boolean;
  defaultBrightHubUuid?: string | null;
};

export function Canvas({ onForkFromNode, canFork = false, isForking = false, defaultBrightHubUuid = null }: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasSurface
        onForkFromNode={onForkFromNode}
        canFork={canFork}
        isForking={isForking}
        defaultBrightHubUuid={defaultBrightHubUuid}
      />
    </ReactFlowProvider>
  );
}