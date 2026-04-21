import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { WorkflowNode } from "../../../stores/workflowStore";

export function DatasetNode({ data }: NodeProps<WorkflowNode>) {
  return (
    <div className="workflow-node workflow-node-dataset" style={data.branchColor ? { borderLeft: `4px solid ${data.branchColor}` } : undefined}>
      <div className="workflow-node-header">
        <span className="workflow-node-kicker">Dataset</span>
        {data.badge ? <span className="workflow-node-badge">{data.badge}</span> : null}
      </div>
      <h3>{data.label}</h3>
      <p>{data.description}</p>
      <span className="workflow-node-summary">{data.summary}</span>
      <Handle className="workflow-handle" type="source" position={Position.Right} />
    </div>
  );
}