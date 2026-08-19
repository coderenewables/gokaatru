// Stage 6 — Long-Term Correction (spec §4 / Stage 6).
//
// MCP between the measured hub-height series (short) and the long-term
// reanalysis hub series (long), for one or more algorithms. Results show as
// metrics cards + ltc_* diagnostic plots.
import { useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { Disclosure } from "../common/Disclosure";
import { MetricsCard } from "../common/MetricsCard";
import { PlotFrame } from "../common/PlotFrame";
import { RunButton } from "../common/RunButton";
import { SensorPicker } from "../common/SensorPicker";
import { LTC_ALGORITHMS, type LtcAlgorithm } from "../../types/analysis";

const ALGORITHM_HELP: Record<LtcAlgorithm, string> = {
  linear_least_squares: "Robust Huber regression; needs ≥10 concurrent points.",
  total_least_squares: "Orthogonal regression; needs ≥10 concurrent points.",
  speedsort: "TLS above threshold + dog-leg below; the standard WRA method.",
  variance_ratio: "Mean + std-scaling; needs non-zero reference std.",
  xgboost: "Gradient-boosted trees with directional+temporal features; needs ≥100 points.",
};

export function LtcView() {
  const config = useWorkspaceStore((state) => state.config);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const ltcResults = useWorkspaceStore((state) => state.ltcResults);
  const runLtcAlgorithms = useWorkspaceStore((state) => state.runLtcAlgorithms);
  const sensors = useWorkspaceStore((state) => state.sensors);

  const [algorithms, setAlgorithms] = useState<LtcAlgorithm[]>(
    (config.ltc.algorithms.filter((a) => a !== "ensemble") as LtcAlgorithm[]).length > 0
      ? (config.ltc.algorithms.filter((a) => a !== "ensemble") as LtcAlgorithm[])
      : ["speedsort"],
  );
  const [shortCol, setShortCol] = useState(config.ltc.shortColumn);
  const [longCol, setLongCol] = useState(config.ltc.longColumn);
  const [shortDirCol, setShortDirCol] = useState(config.ltc.shortDirectionColumn);
  const [longDirCol, setLongDirCol] = useState(config.ltc.longDirectionColumn);
  const [viewAlgorithm, setViewAlgorithm] = useState<string>("");

  const toggleAlgorithm = (alg: LtcAlgorithm) => {
    setAlgorithms((prev) => (prev.includes(alg) ? prev.filter((a) => a !== alg) : [...prev, alg]));
  };

  const run = async () => {
    updateConfigValue("ltc.algorithms", algorithms);
    updateConfigValue("ltc.shortColumn", shortCol);
    updateConfigValue("ltc.longColumn", longCol);
    updateConfigValue("ltc.shortDirectionColumn", shortDirCol);
    updateConfigValue("ltc.longDirectionColumn", longDirCol);
    await runLtcAlgorithms({
      algorithms,
      shortCol,
      longCol,
      shortDirCol: shortDirCol || undefined,
      longDirCol: longDirCol || undefined,
    });
    if (!viewAlgorithm && algorithms.length > 0) setViewAlgorithm(algorithms[0]);
  };

  const activeView = viewAlgorithm || ltcResults[0]?.algorithm || "";

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Columns</h3>
        <p className="muted">
          Short = measured hub-height speed; long = reanalysis hub-height speed. Direction columns are
          used only by the xgboost algorithm.
        </p>
        <div className="form-grid">
          <label className="form-field">
            <span>Short column (measured hub)</span>
            <SensorPicker
              sensors={sensors}
              kind="speed"
              value={shortCol}
              onChange={(v) => setShortCol(v as string)}
              placeholder="Select measured speed…"
            />
          </label>
          <label className="form-field">
            <span>Long column (reanalysis hub)</span>
            <SensorPicker
              sensors={sensors}
              kind="speed"
              value={longCol}
              onChange={(v) => setLongCol(v as string)}
              placeholder="Select reanalysis speed…"
            />
          </label>
          <label className="form-field">
            <span>Short direction col (xgboost)</span>
            <SensorPicker
              sensors={sensors}
              kind="direction"
              value={shortDirCol}
              onChange={(v) => setShortDirCol(v as string)}
              placeholder="Select measured direction…"
            />
          </label>
          <label className="form-field">
            <span>Long direction col (xgboost)</span>
            <SensorPicker
              sensors={sensors}
              kind="direction"
              value={longDirCol}
              onChange={(v) => setLongDirCol(v as string)}
              placeholder="Select reanalysis direction…"
            />
          </label>
        </div>
      </section>

      <section className="path-panel">
        <h3>Algorithms</h3>
        <div className="algorithm-chips">
          {LTC_ALGORITHMS.map((alg) => (
            <label
              key={alg}
              className={algorithms.includes(alg) ? "algorithm-chip selected" : "algorithm-chip"}
              title={ALGORITHM_HELP[alg]}
            >
              <input
                type="checkbox"
                checked={algorithms.includes(alg)}
                onChange={() => toggleAlgorithm(alg)}
              />
              <span>{alg}</span>
            </label>
          ))}
        </div>
        <div className="path-actions">
          <RunButton
            label={`Run ${algorithms.length} algorithm(s)`}
            onClick={run}
            disabled={algorithms.length === 0 || !shortCol || !longCol}
          />
        </div>
        {ltcResults.length === 0 ? (
          <p className="muted">No LTC results yet.</p>
        ) : null}
      </section>

      {ltcResults.length > 0 ? (
        <section className="path-panel">
          <h3>Metrics</h3>
          <div className="metrics-grid">
            {ltcResults.map((r) => (
              <MetricsCard
                key={r.algorithm}
                title={r.algorithm}
                metrics={r.metrics}
                highlight={["r_squared", "rmse"]}
              />
            ))}
          </div>
          {/* That linear_least_squares is Huber, that TLS assumes equal error variance,
              how much variance the fit attenuated, and which interval convention the
              measured series was matched on — one panel per algorithm. */}
          {ltcResults.map((r) => (
            <Disclosure
              key={`disclosure-${r.algorithm}`}
              source={r.metrics}
              title={`What ${r.algorithm} assumes`}
            />
          ))}
        </section>
      ) : null}

      {activeView ? (
        <section className="path-panel">
          <h3>Diagnostics</h3>
          <div className="form-field">
            <span>Algorithm</span>
            <select value={activeView} onChange={(e) => setViewAlgorithm(e.target.value)}>
              {ltcResults.map((r) => (
                <option key={r.algorithm} value={r.algorithm}>
                  {r.algorithm}
                </option>
              ))}
            </select>
          </div>
          <div className="plot-grid">
            <div className="plot-cell">
              <h4>Scatter + fit</h4>
              <PlotFrame plotName="ltc_scatter" params={{ algorithm: activeView }} height={320} />
            </div>
            <div className="plot-cell">
              <h4>Residuals</h4>
              <PlotFrame plotName="ltc_residuals" params={{ algorithm: activeView }} height={320} />
            </div>
            <div className="plot-cell">
              <h4>Monthly measured vs corrected</h4>
              <PlotFrame plotName="ltc_monthly" params={{ algorithm: activeView }} height={320} />
            </div>
            <div className="plot-cell">
              <h4>Rolling long-term convergence</h4>
              <PlotFrame plotName="ltc_convergence" params={{ algorithm: activeView }} height={320} />
            </div>
          </div>
          <div className="plot-cell">
            <h4>All algorithms compared</h4>
            <PlotFrame plotName="ltc_comparison" params={{}} height={340} />
          </div>
        </section>
      ) : null}
    </div>
  );
}
