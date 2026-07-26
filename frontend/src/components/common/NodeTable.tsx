// Node table (spec §2.6): ERA5 / MERRA-2 node list with distance/bearing.
import type { EraNode } from "../../types/analysis";

interface NodeTableProps {
  nodes: EraNode[];
  provider?: "ERA5" | "MERRA-2";
  emptyHint?: string;
}

export function NodeTable({ nodes, provider, emptyHint }: NodeTableProps) {
  if (nodes.length === 0) {
    return <p className="muted">{emptyHint ?? "No nodes loaded."}</p>;
  }

  return (
    <table className="node-table">
      <thead>
        <tr>
          <th>#</th>
          {provider ? <th>{provider}</th> : <th>Source</th>}
          <th>Latitude</th>
          <th>Longitude</th>
          <th>Distance (km)</th>
          <th>Bearing</th>
        </tr>
      </thead>
      <tbody>
        {nodes.map((node, index) => (
          <tr key={`${node.latitude},${node.longitude},${index}`}>
            <td>{index + 1}</td>
            <td>{provider ?? "Node"}</td>
            <td>{node.latitude.toFixed(3)}</td>
            <td>{node.longitude.toFixed(3)}</td>
            <td>{node.distance_km != null ? node.distance_km.toFixed(1) : "—"}</td>
            <td>{node.bearing ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
