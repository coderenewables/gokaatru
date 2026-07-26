// Workflow canvas (spec §5). React Flow surface showing the 8-stage DAG.
//
// Node click opens a params fly-out; "Run auto/step" POSTs the graph to
// /workflow/execute[/step]; the node-status coloring reflects
// workflowStatus.node_statuses. SSE live streaming is wired via the run action
// (the store polls refreshWorkflowStatus after each run; long runs can be
// stopped via the Stop control).
import { useMemo, useState, useCallback } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeProps,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { WorkflowCanvasNode, WorkflowCanvasEdge, StageKind } from "../lib/workflow";
import { RunButton } from "./common/RunButton";

const STAGE_COLORS: Record<StageKind, string> = {
  dataset: "#083434",
  cleaning: "#0b7a6f",
  explore: "#5f716a",
  shear: "#0b7a6f",
  extrapolate_hub: "#0b7a6f",
  era5_nodes: "#c86a2a",
  era5_extract: "#c86a2a",
  era5_interpolate: "#c86a2a",
  homogeneity: "#c86a2a",
  ltc: "#5f716a",
  ensemble: "#083434",
  uncertainty: "#083434",
  clipping: "#5f716a",
};

const STATUS_BORDER: Record<string, string> = {
  done: "#0b7a6f",
  running: "#c86a2a",
  error: "#b3261e",
  skipped: "#9aa3a0",
  pending: "#d8d2c4",
};

function StageNode({ data, selected }: NodeProps) {
  const nodeData = data as WorkflowCanvasNode["data"];
  const color = STAGE_COLORS[nodeData.stage] ?? "#5f716a";
  return (
    <div
      className="wf-stage-node"
      style={{
        borderColor: selected ? "#083434" : "var(--color-border)",
        borderTopColor: color,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div className="wf-stage-node-label">{nodeData.label}</div>
      <div className="wf-stage-node-summary">{nodeData.summary}</div>
      {nodeData.templateId ? (
        <div className="wf-stage-node-template">{nodeData.templateId}</div>
      ) : null}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { stageNode: StageNode };

export function WorkflowView() {
  const nodes = useWorkspaceStore((state) => state.workflowNodes);
  const edges = useWorkspaceStore((state) => state.workflowEdges);
  const setWorkflowGraph = useWorkspaceStore((state) => state.setWorkflowGraph);
  const rebuildWorkflowGraph = useWorkspaceStore((state) => state.rebuildWorkflowGraph);
  const executeWorkflowGraph = useWorkspaceStore((state) => state.executeWorkflowGraph);
  const stopWorkflowGraph = useWorkspaceStore((state) => state.stopWorkflowGraph);
  const workflowStatus = useWorkspaceStore((state) => state.workflowStatus);
  const workflowSnapshots = useWorkspaceStore((state) => state.workflowSnapshots);
  const saveWorkflowSnapshot = useWorkspaceStore((state) => state.saveWorkflowSnapshot);
  const loadWorkflowSnapshot = useWorkspaceStore((state) => state.loadWorkflowSnapshot);
  const forkWorkflowBranch = useWorkspaceStore((state) => state.forkWorkflowBranch);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [snapshotName, setSnapshotName] = useState("");

  // React Flow local state mirrors the store; changes propagate back.
  const [rfNodes, setRfNodes] = useState(nodes);
  const [rfEdges, setRfEdges] = useState(edges);

  // Keep local RF state in sync when the store graph rebuilds.
  const graphSignature = useMemo(
    () => JSON.stringify({ n: nodes.length, e: edges.length, ids: nodes.map((n) => n.id).join(",") }),
    [nodes, edges],
  );
  useMemo(() => {
    setRfNodes(nodes);
    setRfEdges(edges);
  }, [graphSignature]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const next = applyNodeChanges(changes, rfNodes) as WorkflowCanvasNode[];
      setRfNodes(next);
      setWorkflowGraph(next, rfEdges);
    },
    [rfNodes, rfEdges, setWorkflowGraph],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const next = applyEdgeChanges(changes, rfEdges) as WorkflowCanvasEdge[];
      setRfEdges(next);
      setWorkflowGraph(rfNodes, next);
    },
    [rfNodes, rfEdges, setWorkflowGraph],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const next = addEdge(
        { ...connection, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } },
        rfEdges,
      ) as WorkflowCanvasEdge[];
      setRfEdges(next);
      setWorkflowGraph(rfNodes, next);
    },
    [rfNodes, rfEdges, setWorkflowGraph],
  );

  const selectedNode = rfNodes.find((n) => n.id === selectedNodeId) ?? null;
  const isRunning = workflowStatus?.is_running ?? false;

  return (
    <div className="workflow-view">
      <div className="workflow-toolbar">
        <RunButton
          label="Run auto"
          onClick={() => executeWorkflowGraph("auto")}
          disabled={isRunning}
        />
        <RunButton
          label="Step"
          variant="secondary"
          onClick={() => executeWorkflowGraph("manual")}
          disabled={isRunning}
        />
        <RunButton label="Stop" variant="secondary" onClick={stopWorkflowGraph} disabled={!isRunning} />
        <RunButton label="Rebuild from config" variant="secondary" onClick={rebuildWorkflowGraph} />
        <span className="muted workflow-run-status">
          {workflowStatus?.run_id ? `run ${workflowStatus.run_id.slice(0, 8)}` : "no run yet"}
        </span>
      </div>

      <div className="workflow-canvas-wrap">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_evt, node) => setSelectedNodeId(node.id)}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
          <MiniMap
            nodeColor={(n) => {
              const status = workflowStatus?.node_statuses?.[n.id];
              if (status && STATUS_BORDER[status]) return STATUS_BORDER[status];
              return STAGE_COLORS[(n.data as WorkflowCanvasNode["data"])?.stage] ?? "#5f716a";
            }}
          />
        </ReactFlow>

        {selectedNode ? (
          <NodeFlyout
            node={selectedNode}
            status={workflowStatus?.node_statuses?.[selectedNode.id]}
            onClose={() => setSelectedNodeId(null)}
          />
        ) : null}
      </div>

      <div className="workflow-snapshots">
        <h4>Snapshots</h4>
        <div className="form-grid">
          <label className="form-field">
            <span>Snapshot name</span>
            <input
              type="text"
              value={snapshotName}
              onChange={(e) => setSnapshotName(e.target.value)}
              placeholder="baseline"
            />
          </label>
        </div>
        <div className="path-actions">
          <RunButton
            label="Save snapshot"
            onClick={() => {
              if (snapshotName.trim()) {
                void saveWorkflowSnapshot(snapshotName.trim());
                setSnapshotName("");
              }
            }}
            disabled={!snapshotName.trim()}
          />
          <RunButton
            label="Fork branch"
            variant="secondary"
            onClick={() => {
              const name = snapshotName.trim() || "Fork";
              void forkWorkflowBranch(name, selectedNodeId ?? undefined);
            }}
          />
        </div>
        {workflowSnapshots.length === 0 ? (
          <p className="muted">No snapshots saved.</p>
        ) : (
          <ul className="snapshot-list">
            {workflowSnapshots.map((s) => (
              <li key={s.name}>
                <span>{s.name}</span>
                <time>{new Date(s.saved_at).toLocaleString()}</time>
                <button type="button" className="link-button" onClick={() => loadWorkflowSnapshot(s.name)}>
                  Load
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {workflowStatus && workflowStatus.events.length > 0 ? (
        <div className="workflow-events">
          <h4>Run events</h4>
          <ul>
            {workflowStatus.events.slice(-12).map((ev, i) => (
              <li key={i} className={`event-${ev.status ?? "info"}`}>
                <time>{new Date(ev.timestamp).toLocaleTimeString()}</time>
                <strong>{ev.event_type}</strong>
                {ev.node_id ? <span className="muted">{ev.node_id}</span> : null}
                {ev.message ? <span>{ev.message}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function NodeFlyout({
  node,
  status,
  onClose,
}: {
  node: WorkflowCanvasNode;
  status: string | undefined;
  onClose: () => void;
}) {
  const data = node.data;
  return (
    <aside className="wf-flyout">
      <header>
        <h5>{data.label}</h5>
        <button type="button" className="link-button" onClick={onClose}>
          Close
        </button>
      </header>
      <dl className="metrics-grid">
        <div className="metric-tile">
          <dt>Stage</dt>
          <dd>{data.stage}</dd>
        </div>
        <div className="metric-tile">
          <dt>Template</dt>
          <dd>{data.templateId || "—"}</dd>
        </div>
        <div className="metric-tile">
          <dt>Status</dt>
          <dd>{status ?? "idle"}</dd>
        </div>
      </dl>
      <p className="muted">{data.summary}</p>
      {data.requiredParams.length > 0 ? (
        <p className="muted">Required: {data.requiredParams.join(", ")}</p>
      ) : null}
      <pre className="wf-params">{data.paramsJson}</pre>
    </aside>
  );
}
