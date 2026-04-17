import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { WorkflowNode } from "../../../stores/workflowStore";

export function GroupNode({ data }: NodeProps<WorkflowNode>) {
  return (
    <div className="workflow-node workflow-node-group" style={data.branchColor ? { borderLeft: `4px solid ${data.branchColor}` } : undefined}>
      <Handle className="workflow-handle" type="target" position={Position.Left} />
      <div className="workflow-node-header">
        <span className="workflow-node-kicker">Lane</span>
        {data.badge ? <span className="workflow-node-badge">{data.badge}</span> : null}
      </div>
      <h3>{data.label}</h3>
      <p>{data.description}</p>
      <span className="workflow-node-summary">{data.summary}</span>
      <Handle className="workflow-handle" type="source" position={Position.Right} />
    </div>
  );
}