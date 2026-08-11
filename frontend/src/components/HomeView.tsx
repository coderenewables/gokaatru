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
      <section className="home-hero">
        <div className="home-hero-copy">
          <div className="home-brand">
            <img src="/gokaatru-logo.png" alt="GoKaatru logo" className="home-logo" />
            <span className="home-wordmark">GoKaatru</span>
          </div>
          <p className="home-eyebrow">Wind Resource Assessment</p>
          <h1>Turn a measured campaign into a bankable wind resource.</h1>
          <p className="home-tagline">
            GoKaatru takes you from raw met-mast or lidar files to a long-term-corrected, hub-height,
            ensemble-blended dataset with a full uncertainty budget — ready for an Energy Yield Assessment.
          </p>
          <div className="home-hero-actions">
            <button
              type="button"
              className="primary-button home-cta"
              onClick={() => void bootstrapSession()}
              disabled={loading}
            >
              {loading ? (busyLabel ?? "Starting…") : "Start workspace"}
            </button>
            <span className="home-cta-hint muted">Free to explore · your data stays in the session</span>
          </div>
          {sessionError ? <p className="error-text">{sessionError}</p> : null}
        </div>

        <ol className="home-steps" aria-label="Pipeline overview">
          {PIPELINE.slice(0, 4).map((step) => (
            <li key={step.n}>
              <span className="howto-pipeline-n">{step.n}</span>
              <span className="home-step-text">
                <strong>{step.title}.</strong> {step.body}
              </span>
            </li>
          ))}
          <li className="home-steps-more muted">…then exploration, shear, LTC, clipping, ensemble &amp; uncertainty.</li>
        </ol>
      </section>

      <section className="home-features" aria-label="What GoKaatru does">
        {FEATURES.map((feature) => (
          <article className="home-feature" key={feature.title}>
            <span className="home-feature-icon" aria-hidden="true">{feature.icon}</span>
            <h3>{feature.title}</h3>
            <p className="muted">{feature.body}</p>
          </article>
        ))}
      </section>
    </main>
  );
}

const FEATURES: Array<{ icon: string; title: string; body: string }> = [
  {
    icon: "⬆",
    title: "Flexible data import",
    body: "Upload time-series + an IEA Task 43 data model, pull a BrightHub location, or load a shared dataset — then pick exactly which sensors stay in the analysis.",
  },
  {
    icon: "▶",
    title: "One-click automatic run",
    body: "Save config and run model builds the default Canvas plan and executes the full pipeline — shear, ERA5, LTC, ensemble, uncertainty — with live node progress.",
  },
  {
    icon: "◫",
    title: "Editable Canvas",
    body: "Every run is an editable React-Flow graph: rerun auto or step-by-step, fork branches, and snapshot configurations to compare later.",
  },
  {
    icon: "✚",
    title: "Measured-data validation",
    body: "Sensor Overview and exploration surfaces cover recovery, Weibull, wind rose, diurnal/annual profiles, shear, and turbulence before you commit.",
  },
  {
    icon: "∑",
    title: "Ensemble + uncertainty",
    body: "Five LTC algorithms blended by inverse-RMSE, with an RSS uncertainty budget and P50/P75/P90/P99 factors for a defensible EYA.",
  },
  {
    icon: "❏",
    title: "Read-only Results report",
    body: "A single aggregate report of everything the session produced — measured data, shear, reanalysis, LTC, ensemble, and uncertainty — ready to print.",
  },
];
