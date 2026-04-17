import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { WorkflowNode } from "../../../stores/workflowStore";

export function ForkNode({ data }: NodeProps<WorkflowNode>) {
  return (
    <div className="workflow-node workflow-node-fork">
      <Handle className="workflow-handle" type="target" position={Position.Left} />
      <span className="workflow-node-kicker">Branching</span>
      <h3>{data.label}</h3>
      <p>{data.description}</p>
      <Handle className="workflow-handle" type="source" position={Position.Right} />
    </div>
  );
}