import { useEffect, useMemo } from "react";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { RunButton } from "./common/RunButton";
import { flattenConfigDiff, formatMetricValue, toMetricRows } from "../lib/scenarioCompare";

function runLabel(runId: string): string {
  return `Run ${runId.slice(0, 8)}`;
}

export function CompareView() {
  const workflowRuns = useWorkspaceStore((state) => state.workflowRuns);
  const selectedRunIds = useWorkspaceStore((state) => state.selectedWorkflowRunIds);
  const comparison = useWorkspaceStore((state) => state.workflowRunComparison);
  const refreshWorkflowRuns = useWorkspaceStore((state) => state.refreshWorkflowRuns);
  const setSelectedWorkflowRunIds = useWorkspaceStore((state) => state.setSelectedWorkflowRunIds);
  const compareWorkflowRuns = useWorkspaceStore((state) => state.compareWorkflowRuns);

  useEffect(() => {
    void refreshWorkflowRuns();
  }, [refreshWorkflowRuns]);

  useEffect(() => {
    if (selectedRunIds.length === 0 && workflowRuns.length >= 2) {
      setSelectedWorkflowRunIds(workflowRuns.slice(0, 2).map((run) => run.run_id));
    }
  }, [selectedRunIds.length, setSelectedWorkflowRunIds, workflowRuns]);

  const metricRows = useMemo(() => comparison ? toMetricRows(comparison.metrics) : [], [comparison]);
  const configDiff = useMemo(() => comparison ? flattenConfigDiff(comparison.config_diff) : [], [comparison]);
  const toggleRun = (runId: string) => {
    const selected = selectedRunIds.includes(runId);
    setSelectedWorkflowRunIds(selected ? selectedRunIds.filter((id) => id !== runId) : [...selectedRunIds, runId]);
  };

  return (
    <div className="compare-view">
      <section className="path-panel">
        <h3>Saved workflow runs</h3>
        {workflowRuns.length === 0 ? <p className="muted">No completed canvas runs are available yet.</p> : (
          <div className="workflow-run-list">
            {workflowRuns.map((run) => (
              <label key={run.run_id} className="workflow-run-option">
                <input
                  type="checkbox"
                  checked={selectedRunIds.includes(run.run_id)}
                  onChange={() => toggleRun(run.run_id)}
                  disabled={!selectedRunIds.includes(run.run_id) && selectedRunIds.length >= 4}
                />
                <span>
                  <strong>{runLabel(run.run_id)}</strong>
                  <small>{run.completed_node_count}/{run.node_count} steps complete · {run.status} · {run.finished_at ? new Date(run.finished_at).toLocaleString() : "in progress"}</small>
                </span>
              </label>
            ))}
          </div>
        )}
        <div className="path-actions">
          <RunButton label="Refresh" variant="secondary" onClick={() => void refreshWorkflowRuns()} />
          <RunButton label="Compare runs" onClick={() => void compareWorkflowRuns()} disabled={selectedRunIds.length < 2} />
        </div>
      </section>

      {!comparison ? <p className="muted">Select two to four saved canvas runs to compare their configuration and results.</p> : (
        <>
          <section className="path-panel">
            <h3>Analysis results</h3>
            <table className="data-table">
              <thead><tr><th>Metric</th>{comparison.run_ids.map((runId) => <th key={runId}>{runLabel(runId)}</th>)}</tr></thead>
              <tbody>{metricRows.map((row) => <tr key={row.name}><td>{row.name} ({row.unit})</td>{comparison.run_ids.map((runId) => <td key={runId}>{formatMetricValue(row.values[runId], row.unit)}</td>)}</tr>)}</tbody>
            </table>
          </section>

          <section className="path-panel">
            <h3>Step-wise results</h3>
            <table className="data-table workflow-step-results">
              <thead><tr><th>Step</th>{comparison.run_ids.map((runId) => <th key={runId}>{runLabel(runId)}</th>)}</tr></thead>
              <tbody>{comparison.steps.map((step) => <tr key={step.node_id}><td><strong>{step.label}</strong><br /><small>{step.template_id ?? step.node_id}</small></td>{comparison.run_ids.map((runId) => <td key={runId}><strong className={`status-${step.statuses[runId]}`}>{step.statuses[runId]}</strong>{step.results[runId] ? <small>{step.results[runId]}</small> : null}</td>)}</tr>)}</tbody>
            </table>
          </section>

          {configDiff.length > 0 ? <section className="path-panel"><h3>Configuration differences</h3>{configDiff.map((group) => <details key={group.pair} className="preview-details"><summary>{group.pair}</summary><table className="data-table"><thead><tr><th>Key</th><th>Baseline</th><th>Compared</th></tr></thead><tbody>{group.entries.map((entry) => <tr key={entry.key}><td>{entry.key}</td><td>{formatDiffValue(entry.a)}</td><td>{formatDiffValue(entry.b)}</td></tr>)}</tbody></table></details>)}</section> : null}
        </>
      )}
    </div>
  );
}

function formatDiffValue(value: unknown): string {
  if (value == null) return "-";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
