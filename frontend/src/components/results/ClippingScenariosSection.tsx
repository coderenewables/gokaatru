// Results — Clipping & scenarios section (optional).
//
// Shown only when clipping analysis or saved scenarios exist. Read-only: the
// clipping recommendation table and the saved-scenario list (no save/delete
// actions — those live in the Ensemble stage view).
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { MetricTile, UnavailableSection } from "./resultsShared";

export function ClippingScenariosSection() {
  const clippingReport = useWorkspaceStore((state) => state.clippingReport);
  const scenarios = useWorkspaceStore((state) => state.scenarios);

  const hasClipping = clippingReport != null;
  const hasScenarios = scenarios.length > 0;

  if (!hasClipping && !hasScenarios) {
    return (
      <UnavailableSection
        title="Clipping & scenarios"
        requirement="Run clipping analysis or save a scenario to populate this section."
      />
    );
  }

  return (
    <div className="sensor-overview-content">
      {hasClipping && clippingReport ? (
        <section className="path-panel">
          <h3>Clipping recommendation</h3>
          <dl className="metrics-grid">
            <MetricTile
              label="Optimal start year"
              value={String(clippingReport.optimal_start_year)}
              highlight
            />
            <MetricTile
              label="Min uncertainty"
              value={`${clippingReport.min_uncertainty.toFixed(2)}%`}
              highlight
            />
            <MetricTile label="IAV" value={`${clippingReport.iav.toFixed(2)}%`} />
          </dl>

          {clippingReport.analysis_data.length > 0 ? (
            <div className="stats-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Start year</th>
                    <th>Years</th>
                    <th>Mean speed</th>
                    <th>IAV</th>
                    <th>LTA ratio</th>
                    <th>Historic unc.</th>
                    <th>Climate unc.</th>
                    <th>Combined unc.</th>
                  </tr>
                </thead>
                <tbody>
                  {clippingReport.analysis_data.map((row) => (
                    <tr key={row.start_year}>
                      <td>{row.start_year}</td>
                      <td>{row.n_years}</td>
                      <td>{row.mean_speed.toFixed(2)}</td>
                      <td>{row.iav.toFixed(2)}</td>
                      <td>{row.lta_ratio.toFixed(3)}</td>
                      <td>{row.historic_uncertainty.toFixed(2)}%</td>
                      <td>{row.climate_uncertainty.toFixed(2)}%</td>
                      <td>{row.combined_uncertainty.toFixed(2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      {hasScenarios ? (
        <section className="path-panel">
          <h3>Saved scenarios</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s, i) => (
                <tr key={`${s.name}-${i}`}>
                  <td>{s.name}</td>
                  <td>{s.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {scenarios.length > 1 ? (
        <section className="path-panel">
          <h3>Scenario comparison</h3>
          <PlotFrame plotName="scenario_comparison" params={{}} height={360} />
        </section>
      ) : null}
    </div>
  );
}
