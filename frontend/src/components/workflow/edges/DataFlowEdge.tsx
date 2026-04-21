import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";

export function DataFlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style }: EdgeProps) {
  const [edgePath] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });

  return <BaseEdge id={id} path={edgePath} className="workflow-edge-path" style={style} />;
}