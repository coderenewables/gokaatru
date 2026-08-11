// Results — Long-Term Correction section.
//
// "LTC statistics per model + correlation with measured data." Read-only:
// one MetricsCard per algorithm already run, a display-only algorithm selector
// driving diagnostic plots, and an always-shown all-algorithms comparison.
import { useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { MetricsCard } from "../common/MetricsCard";
import { PlotFrame } from "../common/PlotFrame";
import { UnavailableSection } from "./resultsShared";

export function LtcSection() {
  const ltcResults = useWorkspaceStore((state) => state.ltcResults);
  const [viewAlgorithm, setViewAlgorithm] = useState<string>("");

  if (ltcResults.length === 0) {
    return (
      <UnavailableSection
        title="Long-Term Correction"
        requirement="Run the Long-Term Correction stage (Stage 6) to populate this section."
      />
    );
  }

  const activeView = viewAlgorithm || ltcResults[0]?.algorithm || "";

  return (
    <div className="sensor-overview-content">
      <section className="path-panel">
        <h3>Model comparison</h3>
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
      </section>

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
    </div>
  );
}
