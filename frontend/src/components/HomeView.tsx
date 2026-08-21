// Pre-session landing (spec §3.1). Shown until a session is created/restored —
// i.e. on first app start and after deleting a session.
//
// The page leads with the scenario sweep rather than with the pipeline, because the
// sweep is what distinguishes the tool: every other stage exists to feed it. The
// numbers in the proof strip are the *implemented* counts, read off
// `server/core/sweep.py`, `scenario_pipeline.py` and `admissibility.py` — a landing
// page that overstates its own engine is the fastest way to lose an assessor, who is
// exactly the reader who will check.
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
          <p className="home-eyebrow">Wind resource assessment · scenario analysis engine</p>
          <h1>
            Every defensible scenario,
            <br />
            <em>and the spread they disagree by.</em>
          </h1>
          <p className="home-tagline">
            From raw met-mast or lidar files to a long-term-corrected, hub-height dataset with a
            full uncertainty budget. Then the part that is usually left to a footnote: rather
            than defending one methodological path, run them all and report the range.
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
          <li className="home-steps-more muted">
            …then exploration, shear, LTC, clipping, ensemble &amp; uncertainty — before the
            engine sweeps the whole scenario space over them.
          </li>
        </ol>
      </section>

      <section className="home-proof" aria-label="Engine at a glance">
        {PROOF.map((item) => (
          <div className="home-proof-item" key={item.label}>
            <span className="home-proof-value">{item.value}</span>
            <span className="home-proof-label">{item.label}</span>
            <span className="home-proof-detail muted">{item.detail}</span>
          </div>
        ))}
      </section>

      <section className="home-spotlight" aria-labelledby="home-spotlight-title">
        <div className="home-spotlight-copy">
          <p className="home-spotlight-eyebrow">The analysis engine</p>
          <h2 id="home-spotlight-title">A single estimate hides the choice that produced it.</h2>
          <p>
            Two competent analysts, the same campaign, different defensible choices — and two
            different answers. The engine crosses those choices factorially instead of picking
            one, runs each combination end to end, and reports the spread on long-term
            hub-height mean speed and on AEP from a generic 3&nbsp;MW curve.
          </p>
          <p>
            Scenarios are screened by seven admissibility gates before they count. A warning
            keeps a scenario and flags it; a failure excludes it, with the measured value and
            the threshold shown side by side, so a thin spread is never mistaken for agreement.
            The surviving spread is root-sum-squared into the uncertainty budget, substituting
            the observed disagreement wherever it exceeds the parametric term.
          </p>
        </div>
        <ul className="home-axes" aria-label="Scenario axes">
          {AXES.map((axis) => (
            <li key={axis.name}>
              <span className="home-axis-name">{axis.name}</span>
              <span className="home-axis-levels">{axis.levels}</span>
            </li>
          ))}
        </ul>
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

      <footer className="home-foot muted">
        Profile, shear and density follow IEC&nbsp;61400-12-1; measurements are described by the
        IEA Task&nbsp;43 data model. Nothing is reported that cannot be re-derived from its own
        runconfig.
      </footer>
    </main>
  );
}

/** Implemented counts, not aspirational ones — see the note at the top of the file. */
const PROOF: Array<{ value: string; label: string; detail: string }> = [
  {
    value: "1,120",
    label: "scenarios in a full sweep",
    detail: "4 × 4 × 7 × 2 × 5, crossed factorially",
  },
  {
    value: "5",
    label: "axes of methodological choice",
    detail: "the decisions two analysts would genuinely disagree on",
  },
  {
    value: "7",
    label: "admissibility gates",
    detail: "two-tier: a warning is counted and flagged, a failure excluded",
  },
  {
    value: "1 : 1",
    label: "scenario to runconfig",
    detail: "every result carries the parameters that produced it",
  },
];

const AXES: Array<{ name: string; levels: string }> = [
  {
    name: "Which sensors fit the exponent",
    levels: "nearest-2 to hub · availability ≥ 90% · redundant-boom pair · widest lever",
  },
  {
    name: "Which sensor is carried to hub",
    levels: "the same four policies, chosen independently of the fit",
  },
  {
    name: "Vertical profile model",
    levels: "power law and log law, each aggregated by mean, median or MoMM",
  },
  {
    name: "Long-term reference",
    levels: "ERA5 at 100 m · MERRA-2 at 50 m, each interpolated from its four surrounding nodes",
  },
  {
    name: "Long-term correction",
    levels: "linear LS · total LS · variance ratio · SpeedSort · XGBoost",
  },
];

const FEATURES: Array<{ icon: string; title: string; body: string }> = [
  {
    icon: "⬆",
    title: "Flexible data import",
    body: "Upload time-series plus an IEA Task 43 data model, pull a BrightHub location, or load a shared dataset — then pick exactly which sensors stay in the analysis.",
  },
  {
    icon: "◍",
    title: "Cleaned once, shared by all",
    body: "Cleaning is deliberately outside the scenario space: it runs once after import and every scenario inherits it, so the spread measures methodology rather than filter settings.",
  },
  {
    icon: "▶",
    title: "One-click automatic run",
    body: "Save config and run builds the default Canvas plan and executes the full pipeline — shear, ERA5, LTC, ensemble, uncertainty — with live node progress.",
  },
  {
    icon: "◫",
    title: "Editable Canvas",
    body: "Every run is an editable React-Flow graph: rerun auto or step-by-step, fork branches, and snapshot configurations to compare later.",
  },
  {
    icon: "✚",
    title: "Measured-data validation",
    body: "Sensor Overview and exploration surfaces cover recovery, Weibull, wind rose, diurnal and annual profiles, shear, and turbulence before you commit.",
  },
  {
    icon: "∑",
    title: "Ensemble + uncertainty",
    body: "Five LTC algorithms blended by inverse-RMSE, with an RSS uncertainty budget and P50/P75/P90/P99 factors for a defensible EYA.",
  },
  {
    icon: "◔",
    title: "Gate report, not a verdict",
    body: "Every check that ran, what it measured on each scenario, and the threshold it was judged against — including the gates nothing tripped.",
  },
  {
    icon: "❏",
    title: "Read-only Results report",
    body: "A single aggregate report of everything the session produced — measured data, shear, reanalysis, LTC, ensemble, and uncertainty — ready to print.",
  },
];
