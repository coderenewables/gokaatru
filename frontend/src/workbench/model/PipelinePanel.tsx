import { useDroppable } from "@dnd-kit/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  type Edge as FlowEdge,
  Handle,
  type Node,
  type NodeChange,
  type NodeProps,
  Position,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";

import { api, unwrap } from "../api";
import type { PipelineDrop } from "../dnd";
import { useCampaign } from "../shell/context";
import { useAppliedTheme } from "../theme/theme";
import { STATUS_LABELS, layoutSteps, portsOf } from "./graph";
import { titleOf } from "./operations";
import { type StepReport, useOrder, useRunSteps } from "./order";
import { sweepAround } from "./scenario";
import { type Step, usePipeline } from "./store";
import "./model.css";

type StepNodeData = { step: Step; report?: StepReport; running: boolean };

const PORT_SPACING = 18;

function StepNode({ data, selected }: NodeProps<Node<StepNodeData>>) {
  const { step, report, running } = data;
  const status = running ? "running" : (report?.status ?? "pending");
  const { fromSteps, fromSession } = portsOf(step.id, report?.inputs);
  const outputs = report?.outputs ?? [];
  return (
    <div className="gk-step" data-status={status} data-selected={selected || undefined}>
      <div className="gk-step-title">{titleOf(step.operation)}</div>
      <div className="gk-step-status">{running ? "running" : (STATUS_LABELS[status] ?? status)}</div>
      {fromSteps.map((artifact, index) => (
        <Handle
          key={`in-${artifact}`}
          id={`in:${artifact}`}
          type="target"
          position={Position.Left}
          isConnectable={false}
          style={{ top: 44 + index * PORT_SPACING }}
          title={artifact}
        />
      ))}
      {outputs.map((artifact, index) => (
        <Handle
          key={`out-${artifact}`}
          id={`out:${artifact}`}
          type="source"
          position={Position.Right}
          isConnectable={false}
          style={{ top: 44 + index * PORT_SPACING }}
          title={artifact}
        />
      ))}
      <ul className="gk-step-ports" aria-label="Reads">
        {fromSteps.map((artifact) => (
          <li key={artifact}>{artifact.replace(/_/g, " ")}</li>
        ))}
      </ul>
      {fromSession.length > 0 && <p className="gk-step-session">from the session: {fromSession.join(", ").replace(/_/g, " ")}</p>}
    </div>
  );
}

const NODE_TYPES = { step: StepNode };
const FIT = { maxZoom: 1, padding: 0.2 };

/** Fits the view again when steps are added, removed or reordered, once React Flow has
 * measured them; a view fitted before that frames nothing. */
function FitWhenChanged({ signature }: { signature: string }) {
  const { fitView } = useReactFlow();
  const measured = useNodesInitialized();
  useEffect(() => {
    if (measured) void fitView(FIT);
  }, [fitView, measured, signature]);
  return null;
}

function NamedPipelines({ sessionId }: { sessionId: string }) {
  const client = useQueryClient();
  const { steps, replace } = usePipeline();
  const [name, setName] = useState("");
  const [said, setSaid] = useState("");
  const saved = useQuery({
    queryKey: ["pipelines", sessionId],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/list_pipelines", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
  });
  const save = async () => {
    try {
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/save_pipeline", {
          params: { path: { session_id: sessionId } },
          body: { name: name.trim(), steps: steps as unknown as Record<string, unknown>[] },
        }),
      );
      setSaid(`Saved as ${name.trim()}.`);
      await client.invalidateQueries({ queryKey: ["pipelines", sessionId] });
      await client.invalidateQueries({ queryKey: ["history", sessionId] });
    } catch (error) {
      setSaid(error instanceof Error ? error.message : String(error));
    }
  };
  return (
    <div className="gk-named">
      <label className="gk-field gk-inline">
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <button type="button" className="gk-button" disabled={!name.trim() || steps.length === 0} onClick={save}>
        Save
      </button>
      <label className="gk-field gk-inline">
        <span>Open</span>
        <select
          value=""
          onChange={(event) => {
            const chosen = saved.data?.pipelines.find((entry) => entry.name === event.target.value);
            if (chosen) replace(chosen.steps as unknown as Step[]);
          }}
        >
          <option value="">{saved.data?.pipelines.length ? "a saved pipeline" : "none saved"}</option>
          {saved.data?.pipelines.map((entry) => (
            <option key={entry.name} value={entry.name}>
              {entry.name}
            </option>
          ))}
        </select>
      </label>
      <span aria-live="polite" className="gk-muted">
        {said}
      </span>
    </div>
  );
}

/** The campaign's pipeline as a graph (plan §3.3 "Model", decisions/0015.1-0015.5): steps
 * dropped from the palette, wired by what they read and write as the server orders them, each
 * marked with whether its result is current; "Run stale" runs what is not, one step at a time. */
export function PipelinePanel() {
  const { sessionId } = useCampaign();
  const { steps, selected, select, move, open, origin } = usePipeline();
  const [aroundError, setAroundError] = useState("");
  useEffect(() => open(sessionId), [open, sessionId]);
  const order = useOrder(sessionId, steps);
  const { run, running } = useRunSteps(sessionId);
  const drop: PipelineDrop = { kind: "pipeline" };
  const { setNodeRef, isOver } = useDroppable({ id: "pipeline", data: drop });
  const theme = useAppliedTheme();
  // The nodes are controlled, so React Flow's measurements come back as changes and must be
  // kept: without them no node counts as measured and the view is never fitted again.
  const [sizes, setSizes] = useState<Record<string, { width: number; height: number }>>({});

  const report = order.data;
  const edges = useMemo(() => report?.edges ?? [], [report]);
  const placed = useMemo(() => layoutSteps(steps, report?.order ?? [], edges), [steps, report, edges]);
  const nodes: Node<StepNodeData>[] = steps.map((step) => ({
    id: step.id,
    type: "step",
    position: placed[step.id] ?? { x: 0, y: 0 },
    measured: sizes[step.id],
    selected: step.id === selected,
    data: { step, report: report?.steps[step.id], running: running === step.id },
  }));
  const flowEdges: FlowEdge[] = edges.map((edge) => ({
    id: `${edge.source}->${edge.target}:${edge.artifact}`,
    source: edge.source,
    target: edge.target,
    sourceHandle: `out:${edge.artifact}`,
    targetHandle: `in:${edge.artifact}`,
    label: edge.artifact.replace(/_/g, " "),
  }));
  const onNodesChange = (changes: NodeChange<Node<StepNodeData>>[]) => {
    for (const change of changes) {
      if (change.type === "position" && change.position && !change.dragging) move(change.id, change.position);
      if (change.type === "dimensions" && change.dimensions) {
        const { id, dimensions } = change;
        setSizes((current) => ({ ...current, [id]: dimensions }));
      }
    }
  };
  const toRun = report?.to_run ?? [];

  return (
    <div className="gk-panel gk-pipeline" ref={setNodeRef} data-over={isOver || undefined}>
      <div className="gk-pipeline-bar">
        <button
          type="button"
          className="gk-button gk-button-primary"
          disabled={toRun.length === 0 || running !== null}
          onClick={() => run(toRun)}
        >
          {running ? `Running ${running}` : toRun.length ? `Run stale (${toRun.length})` : "Nothing to run"}
        </button>
        <button
          type="button"
          className="gk-button"
          disabled={steps.length === 0}
          onClick={() => {
            setAroundError("");
            sweepAround(sessionId, steps).catch((error: Error) => setAroundError(error.message));
          }}
        >
          Sweep around this
        </button>
        <NamedPipelines sessionId={sessionId} />
      </div>
      {origin && (
        <p className={origin.prefixMatches ? "gk-muted gk-origin" : "gk-warning gk-origin"} role="status">
          Loaded from sweep {origin.sweepId}, scenario {origin.configHash.slice(0, 8)}.
          {origin.prefixMatches ? " Run, it reproduces that scenario's row." : ` ${origin.prefixNote ?? ""}`}
        </p>
      )}
      {aroundError && (
        <p role="alert" className="gk-warning">
          {aroundError}
        </p>
      )}
      {order.isError && (
        <p role="alert" className="gk-warning">
          {order.error.message}
        </p>
      )}
      {steps.length === 0 ? (
        <div className="gk-panel-empty">
          <p>Drag a method from Methods, or add one with its + button. The order follows what each step reads and writes.</p>
        </div>
      ) : (
        <div className="gk-flow" aria-label={`Pipeline: ${(report?.order ?? steps.map((step) => step.id)).join(", ")}`} role="group">
          <ReactFlow
            nodes={nodes}
            edges={flowEdges}
            nodeTypes={NODE_TYPES}
            nodesConnectable={false}
            onNodesChange={onNodesChange}
            onNodeClick={(_, node) => select(node.id)}
            onPaneClick={() => select(null)}
            fitView
            fitViewOptions={FIT}
            colorMode={theme}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <FitWhenChanged signature={`${steps.length}:${(report?.order ?? []).join(",")}`} />
          </ReactFlow>
        </div>
      )}
      <ol className="gk-pipeline-list" aria-label="Steps in order" tabIndex={0}>
        {(report?.order ?? steps.map((step) => step.id)).map((id) => {
          const entry = report?.steps[id];
          return (
            <li key={id}>
              <button type="button" className="gk-link" aria-current={id === selected || undefined} onClick={() => select(id)}>
                {id}
              </button>{" "}
              <span className="gk-step-badge" data-status={entry?.status}>
                {running === id ? "running" : STATUS_LABELS[entry?.status ?? ""] ?? "…"}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
