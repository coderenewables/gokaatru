// Stage 5 — Vertical extrapolation: reanalysis → hub (spec §4 / Stage 5).
//
// Mostly confirmation + visualization: Stage 4's /extrapolation/hub call already
// extrapolated all reanalysis nodes. Offer a re-run and an overlay plot.
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { RunButton } from "../common/RunButton";

export function ReanalysisExtrapolationView() {
  const config = useWorkspaceStore((state) => state.config);
  const summary = useWorkspaceStore((state) => state.summary);
  const invokeSessionOperation = useWorkspaceStore((state) => state.invokeSessionOperation);
  const era5Nodes = useWorkspaceStore((state) => state.era5Nodes);
  const merraNodes = useWorkspaceStore((state) => state.merraNodes);

  const hubHeight = config.site.hubHeightM;
  const shearModel = config.shear.method === "log_law" ? "log_law" : "power_law";

  const reExtrapolate = async (): Promise<void> => {
    await invokeSessionOperation("Re-extrapolate reanalysis to hub", "POST", "/extrapolation/hub", {
      hub_height_m: hubHeight,
      shear_model: shearModel,
    });
  };

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Reanalysis → hub confirmation</h3>
        <p className="muted">
          Stage 4's extrapolate-to-hub call already extrapolated all reanalysis nodes to {hubHeight}m using{" "}
          <strong>{shearModel}</strong>. Use the action below to re-run if nodes changed.
        </p>
        <div className="path-actions">
          <RunButton
            label={`Re-extrapolate to ${hubHeight}m`}
            onClick={reExtrapolate}
          />
        </div>
        {summary?.era5_interpolated_ready ? (
          <p className="status-ok">✓ ERA5 interpolated series ready</p>
        ) : (
          <p className="muted">ERA5 interpolated series not ready — complete Stage 2 first.</p>
        )}
      </section>

      <section className="path-panel">
        <h3>Reference series</h3>
        <dl className="metrics-grid">
          <Tile label="ERA5 nodes" value={String(era5Nodes.length)} />
          <Tile label="MERRA-2 nodes" value={String(merraNodes.length)} />
          <Tile label="Reference column" value={`Spd_${hubHeight}m_hub`} />
        </dl>
      </section>

      <section className="plot-grid">
        <div className="plot-cell">
          <h4>ERA5 vs measured overlay</h4>
          <PlotFrame plotName="era5_measured_overlay" params={{}} height={340} />
        </div>
        <div className="plot-cell">
          <h4>ERA5 comparison</h4>
          <PlotFrame plotName="era5_comparison" params={{}} height={340} />
        </div>
      </section>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
