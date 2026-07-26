// Scenario compare (spec §7). Side-by-side metrics + config diff + Plotly figures.
//
// The backend POST /workflow/compare returns metrics, config_diff, and plots.
// Slots (baseline / run2 / run3) map to scenario names saved in Stage 8.
import { useEffect, useMemo } from "react";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { PlotFrame } from "./common/PlotFrame";
import { RunButton } from "./common/RunButton";
import { flattenConfigDiff, formatMetricValue, toMetricRows } from "../lib/scenarioCompare";
import type { WorkflowComparePlot } from "../lib/api";

const SLOT_LABELS = ["Baseline", "Run 2", "Run 3"];

export function CompareView() {
  const scenarios = useWorkspaceStore((state) => state.scenarios);
  const compareSlotNames = useWorkspaceStore((state) => state.compareSlotNames);
  const setCompareSlot = useWorkspaceStore((state) => state.setCompareSlot);
  const runCompare = useWorkspaceStore((state) => state.runCompare);
  const compareResult = useWorkspaceStore((state) => state.compareResult);

  // Auto-assign saved scenarios to empty slots on load.
  useEffect(() => {
    const used = new Set(compareSlotNames.filter(Boolean));
    scenarios.forEach((s, i) => {
      if (i < SLOT_LABELS.length && !used.has(s.name) && !compareSlotNames[i]) {
        setCompareSlot(i, s.name);
        used.add(s.name);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarios]);

  const metricRows = useMemo(
    () => (compareResult ? toMetricRows(compareResult.metrics) : []),
    [compareResult],
  );
  const configDiff = useMemo(
    () => (compareResult ? flattenConfigDiff(compareResult.config_diff) : []),
    [compareResult],
  );

  return (
    <div className="compare-view">
      <section className="path-panel">
        <h3>Scenario slots</h3>
        <p className="muted">
          Map saved scenarios (from Stage 8) into comparison slots. The backend forks branches and
          returns metrics, config diffs, and plots.
        </p>
        <div className="form-grid">
          {SLOT_LABELS.map((label, i) => (
            <label key={label} className="form-field">
              <span>{label}</span>
              <select
                value={compareSlotNames[i] ?? ""}
                onChange={(e) => setCompareSlot(i, e.target.value || null)}
              >
                <option value="">— none —</option>
                {scenarios.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <div className="path-actions">
          <RunButton
            label="Run compare"
            onClick={() => runCompare()}
            disabled={compareSlotNames.filter(Boolean).length < 2}
          />
        </div>
      </section>

      {!compareResult ? (
        <p className="muted">No comparison result yet. Select ≥2 scenarios and run compare.</p>
      ) : (
        <>
          <section className="path-panel">
            <h3>Metrics</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  {compareResult.session_ids.map((id) => (
                    <th key={id}>{id.slice(0, 8)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {metricRows.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name} ({row.unit})</td>
                    {compareResult.session_ids.map((id) => (
                      <td key={id}>{formatMetricValue(row.values[id], row.unit)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {configDiff.length > 0 ? (
            <section className="path-panel">
              <h3>Config diff</h3>
              {configDiff.map((group) => (
                <details key={group.pair} className="preview-details">
                  <summary>{group.pair}</summary>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Key</th>
                        <th>A</th>
                        <th>B</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.entries.map((entry) => (
                        <tr key={entry.key}>
                          <td>{entry.key}</td>
                          <td>{formatDiffValue(entry.a)}</td>
                          <td>{formatDiffValue(entry.b)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              ))}
            </section>
          ) : null}

          <section className="plot-grid">
            {compareResult.plots.weibull ? (
              <PlotCell title="Weibull" plot={compareResult.plots.weibull} />
            ) : null}
            {compareResult.plots.ltc_scatter ? (
              <PlotCell title="LTC scatter" plot={compareResult.plots.ltc_scatter} />
            ) : null}
            {compareResult.plots.uncertainty_tornado ? (
              <PlotCell title="Uncertainty tornado" plot={compareResult.plots.uncertainty_tornado} />
            ) : null}
            {compareResult.plots.windrose.map((p, i) => (
              <PlotCell key={i} title={`Wind rose ${i + 1}`} plot={p} />
            ))}
          </section>
        </>
      )}
    </div>
  );
}

function formatDiffValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function PlotCell({ title, plot }: { title: string; plot: WorkflowComparePlot }) {
  let isParsable = false;
  try {
    JSON.parse(plot.plotly_json);
    isParsable = true;
  } catch {
    isParsable = false;
  }
  return (
    <div className="plot-cell">
      <h4>{title}</h4>
      {isParsable ? (
        <PlotFrame
          plotName="annual_means"
          params={{}}
          result={{
            plotly_json: plot.plotly_json,
            png_base64: null,
            title: plot.title,
          }}
          height={320}
        />
      ) : (
        <pre className="preview-payload">{plot.plotly_json.slice(0, 400)}</pre>
      )}
    </div>
  );
}
