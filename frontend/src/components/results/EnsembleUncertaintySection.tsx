// Results — Ensemble & uncertainty section.
//
// "Ensemble results + final uncertainty budget and P50/P75/P90/P99."
// Read-only: ensemble status/plots and uncertainty tiles + plots, mirroring
// the result-rendering portions of EnsembleView.tsx exactly.
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { MetricTile, UnavailableSection } from "./resultsShared";

export function EnsembleUncertaintySection() {
  const ensembleSummary = useWorkspaceStore((state) => state.ensembleSummary);
  const uncertaintyResult = useWorkspaceStore((state) => state.uncertaintyResult);

  const hasEnsemble = Boolean(ensembleSummary?.available);
  const hasUncertainty = uncertaintyResult != null;

  if (!hasEnsemble && !hasUncertainty) {
    return (
      <UnavailableSection
        title="Ensemble & uncertainty"
        requirement="Run the Ensemble & uncertainty stage (Stage 8) to populate this section."
      />
    );
  }

  return (
    <div className="sensor-overview-content">
      {hasEnsemble && ensembleSummary ? (
        <>
          <section className="path-panel">
            <h3>Ensemble</h3>
            <p className="status-ok">
              ✓ Ensemble ready · {ensembleSummary.rows ?? 0} rows ·{" "}
              {(ensembleSummary.columns ?? []).length} columns
            </p>
            <dl className="metrics-grid">
              <MetricTile label="Rows" value={String(ensembleSummary.rows ?? 0)} />
              <MetricTile label="Columns" value={String((ensembleSummary.columns ?? []).length)} />
              <MetricTile
                label="Reference columns"
                value={String((ensembleSummary.reference_columns ?? []).length)}
              />
            </dl>
          </section>

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
        </>
      ) : (
        <UnavailableSection
          title="Ensemble"
          requirement="Run the ensemble blend (requires at least two LTC results) to populate this panel."
        />
      )}

      {hasUncertainty && uncertaintyResult ? (
        <>
          <section className="path-panel">
            <h3>Uncertainty budget</h3>
            <dl className="metrics-grid">
              <MetricTile
                label="Total uncertainty"
                value={`${uncertaintyResult.total_uncertainty_pct.toFixed(2)}%`}
                highlight
              />
              <MetricTile
                label="Measurement"
                value={`${uncertaintyResult.components.measurement.toFixed(2)}%`}
              />
              <MetricTile
                label="Vertical extrapolation"
                value={`${uncertaintyResult.components.vertical_extrapolation.toFixed(2)}%`}
              />
              <MetricTile label="MCP" value={`${uncertaintyResult.components.mcp.toFixed(2)}%`} />
              <MetricTile
                label="Future variability"
                value={`${uncertaintyResult.components.future_variability.toFixed(2)}%`}
              />
              <MetricTile label="P50" value={uncertaintyResult.p_factors.p50.toFixed(3)} />
              <MetricTile label="P75" value={uncertaintyResult.p_factors.p75.toFixed(3)} />
              <MetricTile label="P90" value={uncertaintyResult.p_factors.p90.toFixed(3)} />
              <MetricTile label="P99" value={uncertaintyResult.p_factors.p99.toFixed(3)} />
            </dl>
          </section>

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
        </>
      ) : (
        <UnavailableSection
          title="Uncertainty budget"
          requirement="Calculate uncertainty to see the component budget and P-factors."
        />
      )}
    </div>
  );
}
