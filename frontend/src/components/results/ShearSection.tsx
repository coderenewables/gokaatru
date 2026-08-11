// Results — Shear & vertical extrapolation section.
//
// "What did the shear analysis produce?" Read-only: the 12×24 shear/roughness
// lookup matrix, the shear coefficient timeseries, the measured shear profile,
// and confirmation that the hub-height column was written into the measured
// timeseries. Mirrors the data sources of ShearExtrapolationView (stage 4).
import { useMemo } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { MetricTile, UnavailableSection } from "./resultsShared";

export function ShearSection() {
  const summary = useWorkspaceStore((state) => state.summary);
  const config = useWorkspaceStore((state) => state.config);
  const sensors = useWorkspaceStore((state) => state.sensors);

  const method = config.shear.method === "log_law" ? "log_law" : "power_law";
  const tableType = method === "power_law" ? "shear" : "roughness";
  const tableReady =
    method === "power_law" ? Boolean(summary?.shear_table_ready) : Boolean(summary?.roughness_table_ready);

  const hubHeight = config.site.hubHeightM || summary?.hub_height_m || 0;
  const hubColumn = useMemo(() => {
    if (!hubHeight) return "";
    return Number.isInteger(hubHeight) ? `Spd_${hubHeight}m_hub` : `Spd_${hubHeight}m_hub`;
  }, [hubHeight]);
  const hubColumnPresent = useMemo(
    () => (hubColumn ? sensors.some((s) => s.name === hubColumn) : false),
    [hubColumn, sensors],
  );

  if (!tableReady) {
    return (
      <UnavailableSection
        title="Shear & vertical extrapolation"
        requirement="Run the Shear → hub stage (Stage 4) to compute the shear timeseries and 12×24 lookup table."
      />
    );
  }

  return (
    <div className="sensor-overview-content">
      <section className="path-panel">
        <h3>Shear method &amp; hub output</h3>
        <dl className="metrics-grid">
          <MetricTile label="Method" value={method === "power_law" ? "Power law (α)" : "Log law (z₀)"} />
          <MetricTile label="Hub height" value={hubHeight ? `${hubHeight.toFixed(1)} m` : "—"} />
          <MetricTile
            label="Hub column in measured series"
            value={hubColumnPresent ? `✓ ${hubColumn}` : "Not written"}
            highlight={hubColumnPresent}
          />
        </dl>
        {!hubColumnPresent ? (
          <p className="muted">
            The hub-height column ({hubColumn || "Spd_…m_hub"}) is not present in the measured
            timeseries yet — run extrapolate-to-hub (Stage 4) to append it.
          </p>
        ) : null}
      </section>

      <section className="plot-grid">
        <div className="plot-cell">
          <h4>{method === "power_law" ? "Shear table (12×24)" : "Roughness table (12×24)"}</h4>
          <PlotFrame plotName="shear_table" params={{ table_type: tableType }} height={340} />
        </div>
        <div className="plot-cell">
          <h4>Shear profile</h4>
          <PlotFrame plotName="shear_profile" params={{}} height={340} />
        </div>
      </section>

      <section className="plot-grid">
        <div className="plot-cell">
          <h4>{method === "power_law" ? "Shear coefficient timeseries" : "Roughness timeseries"}</h4>
          <PlotFrame plotName="shear_timeseries" params={{}} height={340} />
        </div>
        {hubColumnPresent ? (
          <div className="plot-cell">
            <h4>Hub-height series</h4>
            <PlotFrame plotName="timeseries" params={{ sensor_names: hubColumn }} height={340} />
          </div>
        ) : null}
      </section>
    </div>
  );
}
