// Workspace header (spec §3.1): project name, hub height, coordinate,
// refresh action, busy indicator, session id.
import { useWorkspaceStore } from "../store/useWorkspaceStore";

export function AppHeader() {
  const session = useWorkspaceStore((state) => state.session);
  const summary = useWorkspaceStore((state) => state.summary);
  const busyLabel = useWorkspaceStore((state) => state.busyLabel);
  const refreshWorkspace = useWorkspaceStore((state) => state.refreshWorkspace);

  const projectName = summary?.project_name ?? "Untitled project";
  const hubHeight = summary?.hub_height_m;
  const coordinate = summary?.coordinate;
  const coordinateLabel = coordinate
    ? `${coordinate.latitude.toFixed(3)}, ${coordinate.longitude.toFixed(3)}`
    : null;

  return (
    <header className="app-header">
      <div className="app-header-titles">
        <h1>GoKaatru</h1>
        <p className="app-header-subtitle">
          {projectName}
          {hubHeight ? ` · hub ${hubHeight}m` : ""}
          {coordinateLabel ? ` · ${coordinateLabel}` : ""}
        </p>
      </div>
      <div className="app-header-status">
        {busyLabel ? (
          <span className="busy-pill" role="status">
            <span className="busy-dot" aria-hidden="true" /> {busyLabel}
          </span>
        ) : (
          session && <span className="session-id">session {session.session_id.slice(0, 8)}</span>
        )}
        <button
          type="button"
          className="icon-button"
          onClick={() => void refreshWorkspace()}
          disabled={Boolean(busyLabel)}
          title="Refresh workspace"
          aria-label="Refresh workspace"
        >
          ↻
        </button>
      </div>
    </header>
  );
}
