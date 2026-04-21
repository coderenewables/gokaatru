import type { WorkflowCompareResponse } from "../../lib/types";

type ExportComparisonProps = {
  comparison: WorkflowCompareResponse;
  sessionLabels: Record<string, string>;
};

function downloadText(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function toCsv(comparison: WorkflowCompareResponse, sessionLabels: Record<string, string>): string {
  const header = ["Metric", "Unit", ...comparison.session_ids.map((sessionId) => sessionLabels[sessionId] ?? sessionId)].join(",");
  const rows = comparison.metrics.map((metric) => {
    const values = comparison.session_ids.map((sessionId) => {
      const value = metric.values[sessionId];
      return value === null || value === undefined ? "" : String(value);
    });
    return [metric.name, metric.unit, ...values].map((value) => `"${value.split('"').join('""')}"`).join(",");
  });
  return [header, ...rows].join("\n");
}

function printAsPdf(comparison: WorkflowCompareResponse, sessionLabels: Record<string, string>) {
  const popup = window.open("", "_blank", "width=1200,height=900");
  if (!popup) {
    return;
  }

  const headerCells = comparison.session_ids
    .map((sessionId) => `<th>${sessionLabels[sessionId] ?? sessionId}</th>`)
    .join("");

  const rows = comparison.metrics
    .map((metric) => {
      const valueCells = comparison.session_ids
        .map((sessionId) => `<td>${metric.values[sessionId] ?? "-"}</td>`)
        .join("");
      return `<tr><td>${metric.name}</td><td>${metric.unit}</td>${valueCells}</tr>`;
    })
    .join("");

  popup.document.write(`
    <html>
      <head>
        <title>Workflow Comparison Export</title>
        <style>
          body { font-family: Segoe UI, sans-serif; padding: 24px; }
          table { width: 100%; border-collapse: collapse; margin-top: 16px; }
          th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
          h1 { margin-bottom: 0; }
          p { color: #666; }
        </style>
      </head>
      <body>
        <h1>Workflow Comparison</h1>
        <p>Generated ${new Date().toISOString()}</p>
        <table>
          <thead><tr><th>Metric</th><th>Unit</th>${headerCells}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </body>
    </html>
  `);
  popup.document.close();
  popup.focus();
  popup.print();
}

export function ExportComparison({ comparison, sessionLabels }: ExportComparisonProps) {
  return (
    <div className="workflow-compare-export-row">
      <button
        className="secondary-button"
        type="button"
        onClick={() => downloadText("workflow-comparison.json", JSON.stringify(comparison, null, 2), "application/json")}
      >
        Export JSON
      </button>
      <button className="secondary-button" type="button" onClick={() => downloadText("workflow-comparison.csv", toCsv(comparison, sessionLabels), "text/csv")}>
        Export CSV
      </button>
      <button className="ghost-button" type="button" onClick={() => printAsPdf(comparison, sessionLabels)}>
        Export PDF
      </button>
    </div>
  );
}
