import type { AnalysisSummary, SessionSummary } from "../lib/api";

interface AppHeaderProps {
  session: SessionSummary;
  summary: AnalysisSummary | null;
  busyLabel: string | null;
  onRefresh: () => void;
}

function metricLabel(value: unknown, fallback = "Not ready") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

export function AppHeader({ session, summary, busyLabel, onRefresh }: AppHeaderProps) {
  return (
    <header className="workspace-header">
      <div>
        <p className="eyebrow">Config-driven wind analysis workspace</p>
        <h1>{metricLabel(summary?.project_name ?? session.project_name, "Untitled project")}</h1>
        <p className="workspace-subtitle">
          Session {session.session_id} · Hub {metricLabel(summary?.hub_height_m ?? session.hub_height_m)} m ·
          Completed {(summary?.completed_steps ?? session.completed_steps ?? []).length} step(s)
        </p>
      </div>

      <div className="header-actions">
        {busyLabel ? <span className="status-pill status-pill-busy">{busyLabel}</span> : null}
        <button className="secondary-button" onClick={onRefresh} type="button">
          Refresh workspace
        </button>
      </div>
    </header>
  );
}