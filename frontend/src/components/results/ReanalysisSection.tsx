// Results — Reanalysis section.
//
// "What does the reanalysis data say, and how was it prepared?" Read-only:
// ERA5/MERRA-2 node listings, homogeneity report, interpolation status, and
// already-computed reanalysis comparison plots + optional site map.
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { NodeTable } from "../common/NodeTable";
import { MiniMap } from "../common/MiniMap";
import { PlotFrame } from "../common/PlotFrame";
import { UnavailableSection } from "./resultsShared";

export function ReanalysisSection() {
  const era5Nodes = useWorkspaceStore((state) => state.era5Nodes);
  const merraNodes = useWorkspaceStore((state) => state.merraNodes);
  const homogeneityReport = useWorkspaceStore((state) => state.homogeneityReport);
  const summary = useWorkspaceStore((state) => state.summary);
  const siteMap = useWorkspaceStore((state) => state.siteMap);

  const hasNodes = era5Nodes.length > 0 || merraNodes.length > 0;
  const hasHomogeneity = homogeneityReport != null && homogeneityReport.length > 0;
  const hasAnything = hasNodes || hasHomogeneity || Boolean(summary?.era5_interpolated_ready);

  if (!hasAnything) {
    return (
      <UnavailableSection
        title="Reanalysis"
        requirement="Run the Reanalysis acquisition stage to download ERA5/MERRA-2 nodes and interpolate to site."
      />
    );
  }

  return (
    <div className="sensor-overview-content">
      <section className="path-panel">
        <h3>Interpolation status</h3>
        {summary?.era5_interpolated_ready ? (
          <p className="status-ok">✓ ERA5 interpolated to site</p>
        ) : (
          <p className="muted">Interpolated series not yet ready.</p>
        )}
        {summary?.era5_data_sets_loaded != null ? (
          <p className="muted">{summary.era5_data_sets_loaded} reanalysis dataset(s) loaded.</p>
        ) : null}
      </section>

      {hasNodes ? (
        <section className="path-panel">
          <h3>Reanalysis nodes</h3>
          {era5Nodes.length > 0 ? (
            <>
              <h4>ERA5 nodes</h4>
              <NodeTable nodes={era5Nodes} provider="ERA5" />
            </>
          ) : null}
          {merraNodes.length > 0 ? (
            <>
              <h4>MERRA-2 nodes</h4>
              <NodeTable nodes={merraNodes} provider="MERRA-2" />
            </>
          ) : null}
        </section>
      ) : null}

      {hasHomogeneity ? (
        <section className="path-panel">
          <h3>Homogeneity (Pettitt change-point)</h3>
          <table className="data-table homogeneity-table">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Recommended start year</th>
                <th>Pettitt p-value</th>
                <th>Trend / year</th>
              </tr>
            </thead>
            <tbody>
              {(homogeneityReport ?? []).map((d) => {
                const significant = d.pettitt_p_value < 0.05;
                return (
                  <tr key={d.name}>
                    <td>{d.name}</td>
                    <td>
                      <strong>{d.recommended_start_year}</strong>
                    </td>
                    <td className={significant ? "status-warn" : "status-ok"}>
                      {d.pettitt_p_value.toFixed(4)}
                      {significant ? " ⚠ change-point" : ""}
                    </td>
                    <td>{d.trend_per_year.toFixed(4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : null}

      {summary?.era5_interpolated_ready ? (
        <section className="plot-grid">
          <div className="plot-cell">
            <h4>Measured vs ERA5 — scatter (concurrent period)</h4>
            <PlotFrame plotName="era5_scatter" params={{}} height={360} />
          </div>
          <div className="plot-cell">
            <h4>Measured vs ERA5 — monthly overlay</h4>
            <PlotFrame plotName="era5_measured_overlay" params={{}} height={360} />
          </div>
        </section>
      ) : null}

      <section className="plot-grid">
        <div className="plot-cell">
          <h4>ERA5 comparison</h4>
          <PlotFrame plotName="era5_comparison" params={{}} height={320} />
        </div>
      </section>

      {siteMap ? (
        <section className="path-panel">
          <h3>Site overview map</h3>
          <MiniMap geojson={siteMap} />
        </section>
      ) : null}
    </div>
  );
}
