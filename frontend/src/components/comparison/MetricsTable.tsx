import type { WorkflowCompareMetric } from "../../lib/types";

type MetricsTableProps = {
  metrics: WorkflowCompareMetric[];
  sessionOrder: string[];
  sessionLabels: Record<string, string>;
};

function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return Math.abs(value) >= 100 ? value.toFixed(2) : value.toFixed(3);
}

export function MetricsTable({ metrics, sessionOrder, sessionLabels }: MetricsTableProps) {
  if (metrics.length === 0) {
    return <p className="muted-text">No metrics available yet.</p>;
  }

  return (
    <div className="table-wrap">
      <table className="data-table workflow-compare-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Unit</th>
            {sessionOrder.map((sessionId) => (
              <th key={sessionId}>{sessionLabels[sessionId] ?? sessionId}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <tr key={metric.name}>
              <td>{metric.name}</td>
              <td>{metric.unit}</td>
              {sessionOrder.map((sessionId) => (
                <td key={`${metric.name}-${sessionId}`}>{formatValue(metric.values[sessionId])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
