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
  useReactFlow,
} from "@xyflow/react";
import { useEffect, useRef, useState } from "react";

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
};

function CanvasSurface({ onForkFromNode, canFork, isForking }: CanvasSurfaceProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const { fitView, screenToFlowPosition } = useReactFlow<WorkflowNode, WorkflowEdge>();
  const [contextNodeId, setContextNodeId] = useState<string | null>(null);
  const [contextNodeLabel, setContextNodeLabel] = useState<string | null>(null);
  const activeBranchId = useWorkflowStore((state) => state.activeBranchId);
  const branchState = useWorkflowStore((state) => state.branchStates[state.activeBranchId]);
  const setNodes = useWorkflowStore((state) => state.setNodes);
  const setEdges = useWorkflowStore((state) => state.setEdges);
  const connectNodes = useWorkflowStore((state) => state.connectNodes);
  const addOperationNode = useWorkflowStore((state) => state.addOperationNode);
  const addDatasetNode = useWorkflowStore((state) => state.addDatasetNode);
  const selectNode = useWorkflowStore((state) => state.selectNode);
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
      addOperationNode(templateId, position);
    }

    if (datasetId) {
      addDatasetNode(datasetId, position);
    }
  };

  const handleNodeContextMenu: NodeMouseHandler<WorkflowNode> = (event, node) => {
    event.preventDefault();
    selectNode(node.id);
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
        onConnect={connectNodes}
        onNodeContextMenu={handleNodeContextMenu}
        onNodeClick={(_, node) => selectNode(node.id)}
        onPaneClick={() => {
          selectNode(null);
          closeContextMenu();
        }}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        proOptions={{ hideAttribution: true }}
      >
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
};

export function Canvas({ onForkFromNode, canFork = false, isForking = false }: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasSurface onForkFromNode={onForkFromNode} canFork={canFork} isForking={isForking} />
    </ReactFlowProvider>
  );
}