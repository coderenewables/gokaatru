import { useMemo, useState } from "react";
import Plot from "react-plotly.js";

import type { WorkflowComparePlot } from "../lib/api";
import { buildScenarioComparison, type ScenarioComparisonEntry } from "../lib/scenarioCompare";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

const runSlots = [
  { slot: "baseline", label: "Run Baseline" },
  { slot: "run2", label: "Run 2" },
  { slot: "run3", label: "Run 3" },
] as const;

function PlotCard({ plot }: { plot: WorkflowComparePlot }) {
  const parsed = useMemo(() => {
    try {
      return JSON.parse(plot.plotly_json) as { data?: unknown[]; layout?: Record<string, unknown> };
    } catch {
      return null;
    }
  }, [plot.plotly_json]);

  return (
    <article className="plot-card">
      <h3>{plot.title}</h3>
      {parsed ? (
        <Plot
          config={{ displaylogo: false, responsive: true }}
          data={(parsed.data ?? []) as never[]}
          layout={{
            ...(parsed.layout ?? {}),
            autosize: true,
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            margin: { l: 40, r: 20, t: 48, b: 40 },
          }}
          style={{ width: "100%", height: "320px" }}
          useResizeHandler
        />
      ) : (
        <pre>{plot.plotly_json}</pre>
      )}
    </article>
  );
}

export function CompareView() {
  const workflowBranches = useWorkspaceStore((state) => state.workflowBranches);
  const compareResult = useWorkspaceStore((state) => state.compareResult);
  const compareBranches = useWorkspaceStore((state) => state.compareBranches);
  const scenarios = useWorkspaceStore((state) => state.scenarios);
  const scenarioCompareSlots = useWorkspaceStore((state) => state.scenarioCompareSlots);
  const setScenarioCompareSlot = useWorkspaceStore((state) => state.setScenarioCompareSlot);
  const saveScenario = useWorkspaceStore((state) => state.saveScenario);
  const deleteScenario = useWorkspaceStore((state) => state.deleteScenario);

  const [selectedBranchIds, setSelectedBranchIds] = useState<string[]>([]);
  const [manualIds, setManualIds] = useState("");
  const [scenarioName, setScenarioName] = useState("");

  const allBranchIds = useMemo(
    () => workflowBranches.map((branch) => branch.branch_session_id),
    [workflowBranches],
  );
  const scenarioEntries = useMemo(
    () =>
      runSlots.reduce<ScenarioComparisonEntry[]>((entries, { slot, label }) => {
        const selectedScenarioName = scenarioCompareSlots[slot];
        const scenario = scenarios.find((item) => item.name === selectedScenarioName);
        if (scenario) {
          entries.push({ label, scenario });
        }
        return entries;
      }, []),
    [scenarioCompareSlots, scenarios],
  );
  const scenarioComparison = useMemo(() => buildScenarioComparison(scenarioEntries), [scenarioEntries]);

  return (
    <div className="compare-layout">
      <section className="panel panel-span-2">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 4</p>
            <h2>Named run history</h2>
          </div>
        </div>

        <div className="form-grid form-grid-compact">
          <label className="field-span-2">
            <span>Save current session as scenario</span>
            <input onChange={(event) => setScenarioName(event.target.value)} placeholder="Run Baseline" type="text" value={scenarioName} />
          </label>
        </div>
        <div className="button-row">
          <button
            className="primary-button"
            onClick={() => {
              void saveScenario(scenarioName.trim() || `Run ${scenarios.length + 1}`);
              setScenarioName("");
            }}
            type="button"
          >
            Save current run snapshot
          </button>
        </div>

        <div className="form-grid form-grid-compact">
          {runSlots.map(({ slot, label }) => (
            <label key={slot}>
              <span>{label}</span>
              <select onChange={(event) => setScenarioCompareSlot(slot, event.target.value || null)} value={scenarioCompareSlots[slot] ?? ""}>
                <option value="">Unassigned</option>
                {scenarios.map((scenario) => (
                  <option key={scenario.name} value={scenario.name}>
                    {scenario.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>

        <div className="dataset-list">
          {scenarios.length === 0 ? <p className="muted-text">Save one or more scenario snapshots to compare Baseline, Run 2, and Run 3 side by side.</p> : null}
          {scenarios.map((scenario, index) => (
            <article className="dataset-card" key={`${scenario.name}-${scenario.created_at}`}>
              <div>
                <h3>{scenario.name}</h3>
                <p>{new Date(scenario.created_at).toLocaleString()}</p>
              </div>
              <div className="button-row">
                <button className="secondary-button" onClick={() => setScenarioCompareSlot("baseline", scenario.name)} type="button">
                  Set baseline
                </button>
                <button className="secondary-button" onClick={() => void deleteScenario(index)} type="button">
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel compare-metrics-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Scenario metrics</p>
            <h2>Run Baseline vs Run 2 vs Run 3</h2>
          </div>
        </div>
        {scenarioComparison ? (
          <div className="preview-table-wrapper">
            <table className="preview-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  {scenarioComparison.labels.map((label) => (
                    <th key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarioComparison.metrics.map((metric) => (
                  <tr key={metric.key}>
                    <td>
                      {metric.label} {metric.unit ? `(${metric.unit})` : ""}
                    </td>
                    {scenarioComparison.labels.map((label) => (
                      <td key={`${metric.key}-${label}`}>{metric.values[label] ?? "-"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted-text">Assign at least two saved scenarios to the named run slots to build the run-history comparison.</p>
        )}
      </section>

      <section className="panel compare-diff-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Scenario config diff</p>
            <h2>What changed between saved runs</h2>
          </div>
        </div>
        {scenarioComparison ? (
          <div className="diff-groups">
            {Object.entries(scenarioComparison.diffs).map(([pair, entries]) => (
              <article className="diff-card" key={pair}>
                <h3>{pair}</h3>
                {entries.length === 0 ? <p className="muted-text">No config differences.</p> : null}
                {entries.map((entry) => (
                  <div className="diff-entry" key={`${pair}-${entry.key}`}>
                    <strong>{entry.key}</strong>
                    <pre>{JSON.stringify({ baseline: entry.baseline, compare: entry.compare }, null, 2)}</pre>
                  </div>
                ))}
              </article>
            ))}
          </div>
        ) : (
          <p className="muted-text">Diffs will render here once the named run slots are populated.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Branch sessions</p>
            <h2>Overlay current session against workflow branches</h2>
          </div>
        </div>

        <div className="selection-list">
          {allBranchIds.length === 0 ? <p className="muted-text">Create one or more workflow branches from the workflow tab to compare them here.</p> : null}
          {allBranchIds.map((branchId) => (
            <label className="checkbox-row" key={branchId}>
              <input
                checked={selectedBranchIds.includes(branchId)}
                onChange={(event) =>
                  setSelectedBranchIds((current) =>
                    event.target.checked ? [...current, branchId] : current.filter((item) => item !== branchId),
                  )
                }
                type="checkbox"
              />
              <span>{branchId}</span>
            </label>
          ))}
        </div>

        <label>
          <span>Manual session IDs</span>
          <textarea onChange={(event) => setManualIds(event.target.value)} placeholder="Optional branch session ids separated by commas or whitespace" rows={3} value={manualIds} />
        </label>
        <button
          className="primary-button"
          onClick={() => {
            const manual = manualIds
              .split(/[\s,]+/)
              .map((value) => value.trim())
              .filter(Boolean);
            void compareBranches(Array.from(new Set([...selectedBranchIds, ...manual])));
          }}
          type="button"
        >
          Compare against current session
        </button>
      </section>

      <section className="panel compare-metrics-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Branch metrics</p>
            <h2>Session overlay summary</h2>
          </div>
        </div>
        {compareResult ? (
          <div className="preview-table-wrapper">
            <table className="preview-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  {compareResult.session_ids.map((sessionId) => (
                    <th key={sessionId}>{sessionId}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compareResult.metrics.map((metric) => (
                  <tr key={metric.name}>
                    <td>
                      {metric.name} {metric.unit ? `(${metric.unit})` : ""}
                    </td>
                    {compareResult.session_ids.map((sessionId) => (
                      <td key={sessionId}>{metric.values[sessionId] ?? "-"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted-text">Run a branch comparison to populate backend-generated overlay metrics and plots.</p>
        )}
      </section>

      <section className="panel compare-plot-panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Plots</p>
            <h2>Backend-generated visual overlays</h2>
          </div>
        </div>
        {compareResult ? (
          <div className="plot-grid">
            {compareResult.plots.weibull ? <PlotCard plot={compareResult.plots.weibull} /> : null}
            {compareResult.plots.ltc_scatter ? <PlotCard plot={compareResult.plots.ltc_scatter} /> : null}
            {compareResult.plots.uncertainty_tornado ? <PlotCard plot={compareResult.plots.uncertainty_tornado} /> : null}
            {compareResult.plots.windrose.map((plot) => (
              <PlotCard key={plot.title} plot={plot} />
            ))}
          </div>
        ) : (
          <p className="muted-text">No comparison plots yet.</p>
        )}
      </section>
    </div>
  );
}