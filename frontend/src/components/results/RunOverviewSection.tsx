// Results — Run overview header (always visible, not a switchable nav item).
//
// Answers "what has been done in this session, and what's still missing?"
// Pulls only from summary / session / config in the store. Read-only.
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { STAGE_ORDER, STAGE_META } from "../../lib/stages";
import type { StageId } from "../../types/analysis";
import { MetricTile } from "./resultsShared";

function isStageDone(stage: StageId, completedSteps: string[]): boolean {
  const required = STAGE_META[stage].requiredSteps;
  if (required.length === 0) {
    // Advisory stages (e.g. cleaning) have no required token; treat as done
    // when their prerequisite data is present. We fall back to the step list.
    return false;
  }
  return required.every((step) => completedSteps.includes(step));
}

export function RunOverviewSection() {
  const summary = useWorkspaceStore((state) => state.summary);
  const session = useWorkspaceStore((state) => state.session);
  const config = useWorkspaceStore((state) => state.config);

  const coordinate = summary?.coordinate ?? null;
  const latitude = coordinate?.latitude ?? config.site.latitude;
  const longitude = coordinate?.longitude ?? config.site.longitude;
  const elevation = coordinate?.elevation_m ?? config.site.elevationM;

  const completedSteps = summary?.completed_steps ?? session?.completed_steps ?? [];

  return (
    <div className="sensor-overview-content">
      <section className="path-panel sensor-overview-report-head">
        <div>
          <h3>Run overview</h3>
          <p className="muted">
            {config.project.name || session?.project_name || "Untitled project"}
            {config.project.client ? ` · ${config.project.client}` : ""}
          </p>
        </div>
        <button
          type="button"
          className="run-button run-button-secondary print-overview-button"
          onClick={() => window.print()}
        >
          Print / export
        </button>
      </section>

      <section className="path-panel">
        <h3>Site &amp; session</h3>
        <dl className="metrics-grid">
          <MetricTile label="Measurement type" value={config.project.measurementType || session?.measurement_type || "—"} />
          <MetricTile label="Latitude" value={Number.isFinite(latitude) ? latitude.toFixed(4) : "—"} />
          <MetricTile label="Longitude" value={Number.isFinite(longitude) ? longitude.toFixed(4) : "—"} />
          <MetricTile label="Elevation" value={Number.isFinite(elevation) ? `${elevation.toFixed(1)} m` : "—"} />
          <MetricTile label="Hub height" value={`${(config.site.hubHeightM || summary?.hub_height_m || 0).toFixed(1)} m`} />
          <MetricTile label="Rotor diameter" value={`${config.site.rotorDiameterM.toFixed(1)} m`} />
          <MetricTile label="Sensors mapped" value={summary?.sensor_count != null ? String(summary.sensor_count) : "—"} />
          <MetricTile
            label="Avg coverage"
            value={summary?.avg_coverage_pct != null ? `${summary.avg_coverage_pct.toFixed(1)}%` : "—"}
          />
          <MetricTile label="Session created" value={formatTimestamp(session?.created_at)} />
          <MetricTile label="Last updated" value={formatTimestamp(session?.updated_at)} />
        </dl>
      </section>

      <section className="path-panel">
        <h3>Workflow progress</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Stage</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {STAGE_ORDER.map((stage) => {
              const done = isStageDone(stage, completedSteps);
              return (
                <tr key={stage}>
                  <td>{STAGE_META[stage].title}</td>
                  <td className={done ? "status-ok" : "status-warn"}>
                    {done ? "✓ Done" : "Pending"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
