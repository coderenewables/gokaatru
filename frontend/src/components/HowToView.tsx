// How To page: in-app documentation on how to use GoKaatru.
//
// Surfaced through the primary "How To" nav tab. Mirrors the layout of the
// other top-level views (a centered scrollable card) and documents the
// session lifecycle, automatic canvas planning, the post-import Stepper, and
// the navigation tabs.
import { useWorkspaceStore } from "../store/useWorkspaceStore";

interface PipelineStep {
  n: number;
  title: string;
  body: string;
}

export const PIPELINE: PipelineStep[] = [
  {
    n: 1,
    title: "Data import",
    body: "Upload measured time-series files (or import from BrightHub), set the site coordinate and hub height, and choose the long-term reference provider (BrightHub for ERA5 + MERRA-2, or EarthDataHub for ERA5 only).",
  },
  {
    n: 2,
    title: "Save config and setup",
    body: "Saving the config downloads the reanalysis at the four surrounding nodes, interpolates it to the site, and builds the default Canvas plan. The plan is prepared but not executed — the Canvas runs only when you start it.",
  },
  {
    n: 3,
    title: "Data cleaning (optional)",
    body: "Review the measurement inventory and apply only the cleaning filters appropriate for the campaign. Nothing here is required; skip straight to the Analysis Engine if the campaign needs no filtering.",
  },
  {
    n: 4,
    title: "Analysis Engine",
    body: "Sweep the scenario space — sensor policies, shear methods, LTC algorithms — and read the resulting spread, sensitivity, and gate report before committing to a single pipeline.",
  },
  {
    n: 5,
    title: "Measured-data exploration",
    body: "Inspect recovery and availability, the wind rose, the Weibull fit, diurnal and annual profiles, and the measured shear profile.",
  },
  {
    n: 6,
    title: "Shear → hub (measured)",
    body: "Apply a shear or roughness calculation to extrapolate the measured sensors up to hub height.",
  },
  {
    n: 7,
    title: "Reanalysis → hub",
    body: "Confirm the long-term reference series exist at hub height using the chosen shear method.",
  },
  {
    n: 8,
    title: "Long-Term Correction (LTC)",
    body: "Run the MCP correlation between the short measured record and the long reanalysis record, and visualize the fits.",
  },
  {
    n: 9,
    title: "Clipping analysis",
    body: "Decide the representative historical window for the energy yield assessment (advisory).",
  },
  {
    n: 10,
    title: "Ensemble & uncertainty",
    body: "Blend the LTC outputs, compute the uncertainty, and save your scenarios.",
  },
];

interface TabDoc {
  label: string;
  body: string;
}

const TAB_DOCS: TabDoc[] = [
  { label: "Data import", body: "Upload or import measurements, choose the reanalysis provider, and save the site and hub-height configuration." },
  { label: "Data cleaning", body: "Optional filtering applied once, before any scenario runs. Skippable in full." },
  { label: "Analysis Engine", body: "Sweep the scenario space and read the spread, sensitivity, and gate report." },
  { label: "Canvas", body: "Review and edit the prepared analysis plan, then run it when you choose." },
  { label: "Stepper", body: "The eight post-import guided analysis stages. Each stage unlocks from its prerequisites." },
  { label: "Results", body: "Read-only aggregate report of everything the session has produced." },
  { label: "Sensor Overview", body: "Validate measured data quality and characterize the measured wind climate." },
  { label: "Copilot", body: "Chat with the agent to drive the workflow conversationally." },
  { label: "Compare", body: "Compare saved scenarios side by side." },
  { label: "How To", body: "This page." },
];

export function HowToView() {
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab);

  return (
    <main className="howto-shell">
      <section className="howto-card">
        <header className="howto-card-head">
          <h1>How to use GoKaatru</h1>
          <p className="muted">
            GoKaatru is a workflow-driven wind resource assessment tool. The pages below walk through the session
            lifecycle, automatic Canvas planning, and the eight-stage analysis pipeline.
          </p>
        </header>

        <article className="howto-section">
          <h2>1 · Start a workspace session</h2>
          <p>
            From the landing screen, choose <strong>Start workspace</strong> to create (or restore) a session. A
            session holds your data, configuration, and results across all stages. You can refresh the workspace at
            any time with the <span aria-hidden="true">↻</span> button in the top-right header.
          </p>
        </article>

        <article className="howto-section">
          <h2>2 · Import data, review Canvas, then use Stepper</h2>
          <p>
            The <strong>Data import</strong> tab prepares the default Canvas once measurements and hub height are
            saved. The <strong>Stepper</strong> tab then shows the eight post-import stages. Each chip is color-coded by status:
          </p>
          <ul className="howto-legend">
            <li><span className="howto-dot status-done" aria-hidden="true" /> <strong>Done</strong> — completed.</li>
            <li><span className="howto-dot status-ready" aria-hidden="true" /> <strong>Ready</strong> — available to run.</li>
            <li><span className="howto-dot status-locked" aria-hidden="true" /> <strong>Locked</strong> — finish its prerequisite first.</li>
          </ul>
          <p>
            Review or edit the Canvas before running it. Click a ready Stepper stage to open it, then use its action
            button to run that stage. Locked stages show a tooltip naming the blocking upstream stage. The full flow is:
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
        </article>

        <article className="howto-section">
          <h2>3 · Use the other tabs</h2>
          <p>The primary navigation switches between these views:</p>
          <dl className="howto-tabs">
            {TAB_DOCS.map((tab) => (
              <div className="howto-tab-row" key={tab.label}>
                <dt>{tab.label}</dt>
                <dd>{tab.body}</dd>
              </div>
            ))}
          </dl>
        </article>

        <article className="howto-section">
          <h2>4 · Tips</h2>
          <ul className="howto-tips">
            <li>The header shows your project name, hub height, and site coordinate while a session is active.</li>
            <li>The <strong>Activity</strong> panel (right side of the Stepper) logs every action with a timestamp.</li>
            <li>The <strong>Assets</strong> drawer lists the files and artifacts generated by each stage.</li>
            <li>Stages stay locked until their prerequisites are complete — if a stage is locked, complete the named upstream stage first.</li>
          </ul>
        </article>

        <footer className="howto-card-foot">
          <button
            type="button"
            className="primary-button"
            onClick={() => setActiveTab("import")}
          >
            Go to Data import
          </button>
        </footer>
      </section>
    </main>
  );
}
