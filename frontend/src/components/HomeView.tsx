// Pre-session landing (spec §3.1). Shown until a session is created/restored.
import { useWorkspaceStore } from "../store/useWorkspaceStore";

export function HomeView() {
  const busyLabel = useWorkspaceStore((state) => state.busyLabel);
  const sessionStatus = useWorkspaceStore((state) => state.sessionStatus);
  const sessionError = useWorkspaceStore((state) => state.sessionError);
  const bootstrapSession = useWorkspaceStore((state) => state.bootstrapSession);

  const loading = sessionStatus === "loading";

  return (
    <main className="home-shell">
      <section className="home-card">
        <h1>GoKaatru</h1>
        <p className="home-tagline">Wind Resource Assessment — workflow-driven frontend.</p>
        <p className="muted">
          Create a workspace session to begin the 8-stage pipeline: data loading, reanalysis acquisition,
          exploration, shear, LTC, clipping, and ensemble.
        </p>
        <button
          type="button"
          className="primary-button"
          onClick={() => void bootstrapSession()}
          disabled={loading}
        >
          {loading ? (busyLabel ?? "Starting…") : "Start workspace"}
        </button>
        {sessionError ? <p className="error-text">{sessionError}</p> : null}
      </section>
    </main>
  );
}
