// Stage 8 — Ensemble & uncertainty (spec §4 / Stage 8).
//
// Blend LTC outputs into one authoritative long-term series, compute total
// EYA uncertainty + P-factors, and save named scenarios for comparison.
import { useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { Disclosure } from "../common/Disclosure";
import { PlotFrame } from "../common/PlotFrame";
import { RunButton } from "../common/RunButton";

export function EnsembleView() {
  const config = useWorkspaceStore((state) => state.config);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const ltcResults = useWorkspaceStore((state) => state.ltcResults);
  const ensembleSummary = useWorkspaceStore((state) => state.ensembleSummary);
  const uncertaintyResult = useWorkspaceStore((state) => state.uncertaintyResult);
  const scenarios = useWorkspaceStore((state) => state.scenarios);
  const runEnsembleAnalysis = useWorkspaceStore((state) => state.runEnsembleAnalysis);
  const runUncertaintyAnalysis = useWorkspaceStore((state) => state.runUncertaintyAnalysis);
  const saveScenarioSnapshot = useWorkspaceStore((state) => state.saveScenarioSnapshot);
  const deleteScenarioSnapshot = useWorkspaceStore((state) => state.deleteScenarioSnapshot);

  const [measuredCol, setMeasuredCol] = useState(config.ltc.measuredColumn || config.ltc.shortColumn);
  const [scenarioName, setScenarioName] = useState("");

  const u = config.ltc.uncertainty;

  const runEnsemble = async () => {
    if (!measuredCol) return;
    updateConfigValue("ltc.measuredColumn", measuredCol);
    await runEnsembleAnalysis(measuredCol);
  };

  const runUncertainty = async () => {
    await runUncertaintyAnalysis({
      measurement_uncertainty_pct: u.measurementUncertaintyPct,
      measurement_height_m: u.measurementHeightM,
      hub_height_m: u.hubHeightM,
      shear_method: u.shearMethod,
      mcp_r_squared: u.mcpRSquared,
      concurrent_hours: u.concurrentHours,
      algorithm: u.algorithm,
      iav_pct: u.iavPct,
      shear_std: u.shearStd,
      is_interpolation: u.isInterpolation,
    });
  };

  const save = async () => {
    if (!scenarioName.trim()) return;
    await saveScenarioSnapshot(scenarioName.trim());
    setScenarioName("");
  };

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Ensemble</h3>
        <p className="muted">
          Inverse-RMSE weighting with per-component bias correction. Requires ≥2 LTC results.
        </p>
        {ltcResults.length < 2 ? (
          <p className="muted">Run ≥2 LTC algorithms (Stage 6) to enable the ensemble.</p>
        ) : null}
        <div className="form-grid">
          <label className="form-field">
            <span>Measured column</span>
            <input
              type="text"
              value={measuredCol}
              onChange={(e) => setMeasuredCol(e.target.value)}
              placeholder="Spd_120m_hub"
            />
          </label>
        </div>
        <div className="path-actions">
          <RunButton label="Run ensemble" onClick={runEnsemble} disabled={ltcResults.length < 2 || !measuredCol} />
        </div>
        {ensembleSummary?.available ? (
          <p className="status-ok">
            ✓ Ensemble ready · {ensembleSummary.rows ?? 0} rows · {(ensembleSummary.columns ?? []).length} columns
          </p>
        ) : null}
      </section>

      {ensembleSummary?.available ? (
        <Disclosure source={ensembleSummary} title="What this blend assumes" />
      ) : null}

      {ensembleSummary?.available ? (
        <section className="plot-grid">
          <div className="plot-cell">
            <h4>Annual means</h4>
            <PlotFrame plotName="annual_means" params={{}} height={320} />
          </div>
          <div className="plot-cell">
            <h4>Timeseries</h4>
            <PlotFrame plotName="timeseries" params={{}} height={320} />
          </div>
        </section>
      ) : null}

      <section className="path-panel">
        <h3>Uncertainty</h3>
        <p className="muted">
          RSS combination of measurement, vertical extrapolation, MCP, and future variability (IAV).
        </p>
        <div className="form-grid">
          <NumberField label="Measurement uncertainty (%)" value={u.measurementUncertaintyPct}
            onChange={(v) => updateConfigValue("ltc.uncertainty.measurementUncertaintyPct", v)} />
          <NumberField label="Measurement height (m)" value={u.measurementHeightM}
            onChange={(v) => updateConfigValue("ltc.uncertainty.measurementHeightM", v)} />
          <NumberField label="Hub height (m)" value={u.hubHeightM}
            onChange={(v) => updateConfigValue("ltc.uncertainty.hubHeightM", v)} />
          <label className="form-field">
            <span>Shear method</span>
            <select
              value={u.shearMethod}
              onChange={(e) => updateConfigValue("ltc.uncertainty.shearMethod", e.target.value)}
            >
              <option value="calculate_shear">calculate_shear</option>
              <option value="simple_power_law">simple_power_law</option>
              <option value="power_law">power_law</option>
            </select>
          </label>
          <NumberField label="MCP R²" value={u.mcpRSquared} step="0.01" min={0} max={1}
            onChange={(v) => updateConfigValue("ltc.uncertainty.mcpRSquared", v)} />
          <NumberField label="Concurrent hours" value={u.concurrentHours}
            onChange={(v) => updateConfigValue("ltc.uncertainty.concurrentHours", v)} />
          <label className="form-field">
            <span>Algorithm</span>
            <select
              value={u.algorithm}
              onChange={(e) => updateConfigValue("ltc.uncertainty.algorithm", e.target.value)}
            >
              <option value="speedsort">speedsort</option>
              <option value="linear_least_squares">linear_least_squares</option>
              <option value="total_least_squares">total_least_squares</option>
              <option value="variance_ratio">variance_ratio</option>
              <option value="xgboost">xgboost</option>
            </select>
          </label>
          <NumberField label="IAV (%)" value={u.iavPct}
            onChange={(v) => updateConfigValue("ltc.uncertainty.iavPct", v)} />
          <NumberField label="Shear std" value={u.shearStd}
            onChange={(v) => updateConfigValue("ltc.uncertainty.shearStd", v)} />
          <label className="form-check">
            <input
              type="checkbox"
              checked={u.isInterpolation}
              onChange={(e) => updateConfigValue("ltc.uncertainty.isInterpolation", e.target.checked)}
            />
            <span>Hub height was interpolated (not extrapolated)</span>
          </label>
        </div>
        <div className="path-actions">
          <RunButton label="Calculate uncertainty" onClick={runUncertainty} />
        </div>

        {uncertaintyResult ? (
          <div className="uncertainty-result">
            <dl className="metrics-grid">
              <Tile label="Total uncertainty" value={`${uncertaintyResult.total_uncertainty_pct.toFixed(2)}%`} highlight />
              <Tile label="Measurement" value={`${uncertaintyResult.components.measurement.toFixed(2)}%`} />
              <Tile label="Vertical extrapolation" value={`${uncertaintyResult.components.vertical_extrapolation.toFixed(2)}%`} />
              <Tile label="MCP" value={`${uncertaintyResult.components.mcp.toFixed(2)}%`} />
              <Tile label="Future variability" value={`${uncertaintyResult.components.future_variability.toFixed(2)}%`} />
              <Tile label="P50" value={uncertaintyResult.p_factors.p50.toFixed(3)} />
              <Tile label="P75" value={uncertaintyResult.p_factors.p75.toFixed(3)} />
              <Tile label="P90" value={uncertaintyResult.p_factors.p90.toFixed(3)} />
              <Tile label="P99" value={uncertaintyResult.p_factors.p99.toFixed(3)} />
            </dl>
            {/* These are WIND-SPEED exceedances, the MCP sampling cap withheld credit, and
                the components were combined assuming independence. All of that arrives in
                the response; none of it was ever on the screen. */}
            <Disclosure source={uncertaintyResult} title="What this uncertainty assumes" />
          </div>
        ) : null}
      </section>

      {uncertaintyResult ? (
        <section className="plot-grid">
          <div className="plot-cell">
            <h4>Uncertainty breakdown</h4>
            <PlotFrame
              plotName="uncertainty_breakdown"
              params={{
                total_pct: uncertaintyResult.total_uncertainty_pct,
                measurement_pct: uncertaintyResult.components.measurement,
                vertical_pct: uncertaintyResult.components.vertical_extrapolation,
                mcp_pct: uncertaintyResult.components.mcp,
                future_pct: uncertaintyResult.components.future_variability,
              }}
              height={320}
            />
          </div>
          <div className="plot-cell">
            <h4>Uncertainty tornado</h4>
            <PlotFrame
              plotName="uncertainty_tornado"
              params={{
                total_pct: uncertaintyResult.total_uncertainty_pct,
                measurement_pct: uncertaintyResult.components.measurement,
                vertical_pct: uncertaintyResult.components.vertical_extrapolation,
                mcp_pct: uncertaintyResult.components.mcp,
                future_pct: uncertaintyResult.components.future_variability,
              }}
              height={320}
            />
          </div>
        </section>
      ) : null}

      <section className="path-panel">
        <h3>Scenarios</h3>
        <p className="muted">
          Save the current config + outputs as a named scenario. Requires uncertainty to be calculated.
        </p>
        <div className="form-grid">
          <label className="form-field">
            <span>Scenario name</span>
            <input
              type="text"
              value={scenarioName}
              onChange={(e) => setScenarioName(e.target.value)}
              placeholder="Baseline"
            />
          </label>
        </div>
        <div className="path-actions">
          <RunButton
            label="Save scenario"
            onClick={save}
            disabled={!scenarioName.trim() || !uncertaintyResult}
          />
        </div>

        {scenarios.length === 0 ? (
          <p className="muted">No scenarios saved.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s, i) => (
                <tr key={`${s.name}-${i}`}>
                  <td>{s.name}</td>
                  <td>{s.created_at}</td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => deleteScenarioSnapshot(i)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: string;
  min?: number;
  max?: number;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function Tile({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={`metric-tile ${highlight ? "metric-highlight" : ""}`}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
