// Workflow canvas (spec §5). React Flow surface showing the 8-stage DAG.
//
// Node click opens a params fly-out; "Run auto/step" POSTs the graph to
// /workflow/execute[/step]; the node-status coloring reflects
// workflowStatus.node_statuses. SSE live streaming is wired via the run action
// (the store polls refreshWorkflowStatus after each run; long runs can be
// stopped via the Stop control).
import { useMemo, useState, useCallback, useEffect } from "react";
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
import type { WorkflowExecutionStatusResponse } from "../types/analysis";
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

function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null || !Number.isFinite(milliseconds) || milliseconds < 0) return "-";
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

interface WorkflowProgress {
  total: number;
  completed: number;
  elapsedMs: number | null;
  etaMs: number | null;
  nodeDurations: Record<string, number | null>;
}

export function getWorkflowProgress(
  nodes: WorkflowCanvasNode[],
  status: WorkflowExecutionStatusResponse | null,
  now: number,
): WorkflowProgress {
  const executableNodes = nodes.filter((node) => node.data.executionKind !== "group");
  const events = status?.events ?? [];
  const runStarted = events.find((event) => event.event_type === "run_started");
  const runStartedAt = runStarted ? Date.parse(runStarted.timestamp) : Number.NaN;
  const startedAt = new Map<string, number>();
  const finishedAt = new Map<string, number>();
  for (const event of events) {
    if (!event.node_id) continue;
    const timestamp = Date.parse(event.timestamp);
    if (!Number.isFinite(timestamp)) continue;
    if (event.event_type === "node_started") startedAt.set(event.node_id, timestamp);
    if (event.event_type === "node_finished" || event.event_type === "node_failed") finishedAt.set(event.node_id, timestamp);
  }
  const nodeDurations: Record<string, number | null> = {};
  const completedDurations: number[] = [];
  for (const node of executableNodes) {
    const start = startedAt.get(node.id);
    const finish = finishedAt.get(node.id);
    const isRunning = status?.node_statuses[node.id] === "running";
    const ending = finish ?? (isRunning ? now : undefined);
    nodeDurations[node.id] = start === undefined || ending === undefined ? null : Math.max(0, ending - start);
    if (start !== undefined && finish !== undefined && status?.node_statuses[node.id] === "done") {
      completedDurations.push(Math.max(0, finish - start));
    }
  }
  const completed = executableNodes.filter((node) => status?.node_statuses[node.id] === "done").length;
  const averageDuration = completedDurations.length > 0
    ? completedDurations.reduce((total, duration) => total + duration, 0) / completedDurations.length
    : null;
  return {
    total: executableNodes.length,
    completed,
    elapsedMs: Number.isFinite(runStartedAt) ? Math.max(0, now - runStartedAt) : null,
    etaMs: averageDuration === null || completed >= executableNodes.length
      ? null
      : averageDuration * (executableNodes.length - completed),
    nodeDurations,
  };
}

function StageNode({ data, selected }: NodeProps) {
  const nodeData = data as WorkflowCanvasNode["data"];
  const color = STAGE_COLORS[nodeData.stage] ?? "#5f716a";
  const status = typeof nodeData.runStatus === "string" ? nodeData.runStatus : "idle";
  const duration = typeof nodeData.runDuration === "string" ? nodeData.runDuration : null;
  return (
    <div
      className={`wf-stage-node wf-node-${status}`}
      style={{
        borderColor: selected ? "#083434" : "var(--color-border)",
        borderTopColor: color,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div className="wf-stage-node-label">{nodeData.label}</div>
      <div className="wf-stage-node-summary">{nodeData.summary}</div>
      <div className="wf-stage-node-runtime">
        <span className={`wf-node-status status-${status}`}>{status}</span>
        {duration ? <span>{duration}</span> : null}
      </div>
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
  const serverRunconfig = useWorkspaceStore((state) => state.serverRunconfig);
  const replaceWorkflowRunConfig = useWorkspaceStore((state) => state.replaceWorkflowRunConfig);
  const refreshWorkflowRuns = useWorkspaceStore((state) => state.refreshWorkflowRuns);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [snapshotName, setSnapshotName] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [configEditorOpen, setConfigEditorOpen] = useState(false);
  const [configText, setConfigText] = useState("");
  const [configError, setConfigError] = useState<string | null>(null);

  // React Flow local state mirrors the store; changes propagate back.
  const [rfNodes, setRfNodes] = useState(nodes);
  const [rfEdges, setRfEdges] = useState(edges);

  const isRunning = workflowStatus?.is_running ?? false;
  const progress = useMemo(() => getWorkflowProgress(nodes, workflowStatus, now), [nodes, workflowStatus, now]);
  const displayNodes = useMemo(
    () => nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        runStatus: workflowStatus?.node_statuses[node.id] ?? "idle",
        runDuration: formatDuration(progress.nodeDurations[node.id] ?? null),
      },
    })),
    [nodes, workflowStatus, progress.nodeDurations],
  );

  useEffect(() => {
    if (!isRunning) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    void refreshWorkflowRuns();
  }, [refreshWorkflowRuns]);

  // Keep local RF state in sync when the store graph rebuilds or status changes.
  const graphSignature = useMemo(
    () => JSON.stringify({
      n: displayNodes.length,
      e: edges.length,
      ids: displayNodes.map((node) => node.id).join(","),
      status: workflowStatus?.node_statuses,
      durations: displayNodes.map((node) => node.data.runDuration),
    }),
    [displayNodes, edges, workflowStatus?.node_statuses],
  );
  useMemo(() => {
    setRfNodes(displayNodes);
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
  const canvasEmpty = rfNodes.length === 0;

  const openConfigEditor = () => {
    setConfigText(JSON.stringify(serverRunconfig, null, 2));
    setConfigError(null);
    setConfigEditorOpen(true);
  };

  const saveConfigAndRun = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(configText);
    } catch {
      setConfigError("Configuration must be valid JSON.");
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setConfigError("Configuration must be a JSON object.");
      return;
    }
    const saved = await replaceWorkflowRunConfig(parsed as Record<string, unknown>);
    if (!saved) return;
    setConfigEditorOpen(false);
    await rebuildWorkflowGraph();
    await executeWorkflowGraph("auto");
  };

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
        <RunButton label="Edit config" variant="secondary" onClick={openConfigEditor} disabled={isRunning} />
        <RunButton label="Rebuild from config" variant="secondary" onClick={rebuildWorkflowGraph} />
        <span className="muted workflow-run-status">
          {isRunning ? "running" : workflowStatus?.run_id ? `run ${workflowStatus.run_id.slice(0, 8)}` : "no run yet"}
        </span>
      </div>

      {(isRunning || workflowStatus?.events.length) ? (
        <div className="workflow-progress" role="status">
          <span><strong>{progress.completed}/{progress.total}</strong> nodes complete</span>
          <span>Elapsed <strong>{formatDuration(progress.elapsedMs)}</strong></span>
          <span>Estimated remaining <strong>{progress.etaMs === null ? "calculating" : formatDuration(progress.etaMs)}</strong></span>
        </div>
      ) : null}

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

        {canvasEmpty ? (
          <div className="workflow-empty-hint">
            <p>
              The canvas is empty. Load measurement data and save a hub height in <strong>Data import</strong>;
              GoKaatru will prepare a default workflow here for you to edit and run.
            </p>
            <p className="muted">
              Use <strong>Rebuild from config</strong> to load the current configuration manually.
            </p>
          </div>
        ) : null}

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

      {configEditorOpen ? (
        <div className="modal-overlay" role="presentation">
          <section className="modal-card workflow-config-modal" role="dialog" aria-modal="true" aria-labelledby="workflow-config-title">
            <header className="modal-head">
              <h2 id="workflow-config-title">Edit run configuration</h2>
              <button type="button" className="link-button" onClick={() => setConfigEditorOpen(false)}>Close</button>
            </header>
            <div className="modal-body">
              <label className="form-field">
                <span>Run configuration JSON</span>
                <textarea
                  className="workflow-config-editor"
                  value={configText}
                  onChange={(event) => {
                    setConfigText(event.target.value);
                    setConfigError(null);
                  }}
                  spellCheck={false}
                />
              </label>
              {configError ? <p className="error-text">{configError}</p> : null}
              <div className="path-actions">
                <RunButton label="Save and run" onClick={() => void saveConfigAndRun()} />
                <RunButton label="Cancel" variant="secondary" onClick={() => setConfigEditorOpen(false)} />
              </div>
            </div>
          </section>
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
