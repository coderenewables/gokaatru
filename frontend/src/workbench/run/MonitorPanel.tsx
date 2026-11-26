import { useInterrogate } from "../interrogate/store";
import { useCampaign } from "../shell/context";
import { usePhase } from "../shell/phase";
import { useLatestSweepId, useRun } from "./store";
import "./run.css";

/** The run, scenario by scenario, and its outcome (decisions/0015.6, 0015.8). The server has no
 * route to stop a sweep, so there is no Stop here. */
export function MonitorPanel() {
  const { sessionId } = useCampaign();
  const run = useRun((state) => state.run);
  const sweepId = useLatestSweepId(sessionId);

  if (run.phase === "idle") {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>{sweepId ? `The last sweep of this campaign is ${sweepId}. ` : ""}Design a sweep and press Run sweep; each scenario appears here as it finishes.</p>
      </div>
    );
  }

  const manifest = run.manifest;
  const counts = manifest?.counts;
  const gates = Object.entries(manifest?.gate_failures ?? {});
  return (
    <div className="gk-panel gk-monitor">
      <progress
        className="gk-progress"
        max={Math.max(run.total, 1)}
        value={run.completed}
        aria-label="Scenarios accounted for"
      />
      <p className="gk-progress-text" role="status">
        {run.phase === "running" ? "Running: " : run.phase === "finished" ? "Finished: " : "Stopped: "}
        {run.completed.toLocaleString()} of {run.total.toLocaleString()} scenarios accounted for. {run.scenarios.ok} completed,{" "}
        {run.scenarios.inadmissible} inadmissible, {run.scenarios.failed} failed, {run.scenarios.duplicates} skipped as duplicates;{" "}
        {run.prefixes.completed} of {run.prefixes.started} shear tables built.
      </p>

      {run.phase === "error" ? (
        <p className="gk-form-error" role="alert">
          The sweep ended with an error: {run.error}
        </p>
      ) : null}

      {manifest ? (
        <section className="gk-outcome" aria-label="Outcome">
          <h3>Outcome</h3>
          <p>
            Sweep <code>{manifest.sweep_id}</code>
            {manifest.stopped_early ? ", stopped early" : ""}.{" "}
            <button
              type="button"
              className="gk-button"
              onClick={() => {
                useInterrogate.getState().openSweep(manifest.sweep_id);
                usePhase.getState().goTo("interrogate");
              }}
            >
              Open it in Interrogate
            </button>
          </p>
          {counts ? (
            <dl className="gk-estimate-counts">
              <div>
                <dt>Planned</dt>
                <dd>{counts.planned.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Completed</dt>
                <dd>{counts.completed.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Failed</dt>
                <dd>{counts.failed.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Admissible</dt>
                <dd>{counts.admissible.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Inadmissible</dt>
                <dd>{counts.inadmissible.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Duplicates skipped</dt>
                <dd>{(counts.duplicates_skipped ?? 0).toLocaleString()}</dd>
              </div>
            </dl>
          ) : null}
          {manifest.diagnosis ? <p className="gk-notice">{manifest.diagnosis}</p> : null}
          {gates.length > 0 ? (
            <table className="gk-compare">
              <caption>Completed scenarios failing each gate</caption>
              <thead>
                <tr>
                  <th scope="col">Gate</th>
                  <th scope="col">Scenarios</th>
                </tr>
              </thead>
              <tbody>
                {gates.map(([gate, count]) => (
                  <tr key={gate}>
                    <th scope="row">{gate}</th>
                    <td>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {manifest.duplicates_skipped && manifest.duplicates_skipped.length > 0 ? (
            <details>
              <summary>{manifest.duplicates_skipped.length} skipped as duplicates</summary>
              <ul className="gk-leaves" tabIndex={0} aria-label="Leaves skipped as duplicates">
                {manifest.duplicates_skipped.map((entry, index) => (
                  <li key={index}>
                    {entry.shear_fit_policy} / {entry.reference_policy} <span className="gk-leaf-note">repeats {entry.same_as.slice(0, 8)}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {manifest.not_swept_statement ? <p className="gk-not-swept">{manifest.not_swept_statement}</p> : null}
        </section>
      ) : null}

      {/* Scrolls once the run is long: focusable, so a keyboard can scroll it. */}
      <ol className="gk-events" aria-label="Events" tabIndex={0}>
        {[...run.log].reverse().map((line) => (
          <li key={line.id} className={`gk-event gk-event-${line.kind}`}>
            {line.text}
          </li>
        ))}
      </ol>
    </div>
  );
}
