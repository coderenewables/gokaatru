import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { WorkflowNodeData } from "../../../lib/nodeRegistry";
import type { WorkflowNode } from "../../../stores/workflowStore";

function getConfigPreview(config: WorkflowNodeData["config"]) {
  if (!config) {
    return [];
  }

  return Object.entries(config).slice(0, 2);
}

export function OperationNode({ data, selected }: NodeProps<WorkflowNode>) {
  const configPreview = getConfigPreview(data.config);

  return (
    <div
      className={`workflow-node workflow-node-operation ${selected ? "workflow-node-selected" : ""}`}
      style={data.branchColor ? { borderLeft: `4px solid ${data.branchColor}` } : undefined}
    >
      <Handle className="workflow-handle" type="target" position={Position.Left} />
      <div className="workflow-node-header">
        <span className="workflow-node-kicker">{data.category ?? "Operation"}</span>
        <span className={`workflow-node-status workflow-node-status-${data.status}`}>
          {data.stale ? "stale" : data.status}
        </span>
      </div>
      <h3>{data.label}</h3>
      <p>{data.description}</p>
      {configPreview.length ? (
        <dl className="workflow-config-preview">
          {configPreview.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <span className="workflow-node-summary">Drop in and wire to start configuring.</span>
      )}
      <Handle className="workflow-handle" type="source" position={Position.Right} />
    </div>
  );
}