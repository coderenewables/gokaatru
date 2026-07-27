// Pre-session landing (spec §3.1). Shown until a session is created/restored —
// i.e. on first app start and after deleting a session. Doubles as an intro to
// the app with a how-to overview of the pipeline and the navigation tabs.
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { PIPELINE } from "./HowToView";

export function HomeView() {
  const busyLabel = useWorkspaceStore((state) => state.busyLabel);
  const sessionStatus = useWorkspaceStore((state) => state.sessionStatus);
  const sessionError = useWorkspaceStore((state) => state.sessionError);
  const bootstrapSession = useWorkspaceStore((state) => state.bootstrapSession);

  const loading = sessionStatus === "loading";

  return (
    <main className="home-shell">
      <section className="home-card">
        <img src="/gokaatru-logo.png" alt="GoKaatru logo" className="home-logo" />
        <h1>GoKaatru</h1>
        <p className="home-tagline">Wind Resource Assessment — workflow-driven frontend.</p>
        <p className="muted">
          GoKaatru turns a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended
          dataset ready for an Energy Yield Assessment. Create a workspace session to begin the guided
          8-stage pipeline.
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

      <section className="home-card home-howto">
        <h2>How it works</h2>
        <p className="muted">
          A session holds your uploads, configuration, and results across every stage. Work through the
          Stepper in order — each stage unlocks the next — or explore the Canvas, Copilot, Compare, and
          WindKit tabs at any time. The full guide lives on the <strong>How To</strong> tab once you're in.
        </p>
        <ol className="howto-pipeline">
          {PIPELINE.map((step) => (
            <li key={step.n}>
              <span className="howto-pipeline-n">{step.n}</span>
              <span className="howto-pipeline-text">
                <strong>{step.title}.</strong> {step.body}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
