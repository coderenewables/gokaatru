// Run Monitor — design doc §9.2.
//
// A DAG progress view rather than a bar: prefix nodes fill in first and leaves stream
// after, so the memoisation is visible and the difference between "scenarios" and
// "computations" is legible while the run happens.
//
// Failed scenarios are listed with their exception, never silently dropped. A sweep that
// hides what it could not compute reports a spread over a set nobody can enumerate.
import { useMemo } from "react";
import clsx from "clsx";

import { RunButton } from "../common/RunButton";
import { useSweepStore } from "../../store/useSweepStore";
import type { SweepProgressEvent } from "../../types/sweep";

function prefixLabel(event: SweepProgressEvent): string {
  const key = event.detail?.shear_prefix;
  if (Array.isArray(key)) {
    return key.filter((part) => part != null).map(String).join(" · ");
  }
  return "prefix";
}

export function SweepMonitor() {
  const phase = useSweepStore((state) => state.phase);
  const progress = useSweepStore((state) => state.progress);
  const events = useSweepStore((state) => state.events);
  const error = useSweepStore((state) => state.error);
  const manifest = useSweepStore((state) => state.manifest);
  const stop = useSweepStore((state) => state.stop);

  const prefixes = useMemo(() => {
    const started = events.filter((event) => event.event === "prefix_started").map(prefixLabel);
    const completed = new Set(
      events.filter((event) => event.event === "prefix_completed").map(prefixLabel),
    );
    return started.map((label) => ({ label, done: completed.has(label) }));
  }, [events]);

  const failures = useMemo(
    () => events.filter((event) => event.event === "scenario_failed"),
    [events],
  );

  const percent =
    progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0;

  if (phase === "idle" && events.length === 0) {
    return (
      <p className="muted">
        No sweep is running. Design one on the previous tab and launch it to watch the
        spread form here.
      </p>
    );
  }

  return (
    <div className="sweep-monitor">
      <header className="sweep-monitor-header">
        <div>
          <h4>
            {phase === "running"
              ? "Running"
              : phase === "error"
                ? "Failed"
                : manifest?.stopped_early
                  ? "Stopped early"
                  : "Finished"}
          </h4>
          <p className="muted">
            {progress.completed.toLocaleString()} of {progress.total.toLocaleString()} scenarios
            {prefixes.length > 0
              ? ` · ${prefixes.filter((entry) => entry.done).length} of ${prefixes.length} shear computations`
              : null}
          </p>
        </div>
        {phase === "running" ? (
          <RunButton label="Stop" variant="secondary" silent onClick={() => stop()} />
        ) : null}
      </header>

      <div className="sweep-progress-track" role="progressbar" aria-valuenow={percent}>
        <div className="sweep-progress-fill" style={{ width: `${percent}%` }} />
      </div>

      {error ? <p className="sweep-error">{error}</p> : null}

      <section className="sweep-prefix-list">
        <h5>Shear computations</h5>
        <p className="muted">
          Every scenario downstream of one of these reuses its shear table — which is why
          the scenario count and the computation count differ.
        </p>
        <ul>
          {prefixes.map((entry) => (
            <li key={entry.label} className={clsx("sweep-prefix", { done: entry.done })}>
              <span className="sweep-prefix-dot" aria-hidden="true" />
              {entry.label}
            </li>
          ))}
        </ul>
      </section>

      {failures.length > 0 ? (
        <section className="sweep-failure-list">
          <h5>{failures.length} scenario{failures.length === 1 ? "" : "s"} could not run</h5>
          <p className="muted">
            Recorded as rows in the result table with their reason, not dropped.
          </p>
          <ul>
            {failures.slice(0, 25).map((event, index) => (
              <li key={`${event.config_hash ?? index}`}>
                <code>{(event.config_hash ?? "").slice(0, 8)}</code>{" "}
                {String(event.detail?.error ?? "no reason recorded")}
              </li>
            ))}
          </ul>
          {failures.length > 25 ? (
            <p className="muted">…and {failures.length - 25} more, all in the table.</p>
          ) : null}
        </section>
      ) : null}

      {manifest?.diagnosis ? (
        <section className="sweep-diagnosis">
          <h5>No scenario was admissible</h5>
          <p>{manifest.diagnosis}</p>
        </section>
      ) : null}

      {manifest ? (
        <section className="sweep-counts">
          <h5>Outcome</h5>
          <dl>
            <div>
              <dt>Planned</dt>
              <dd>{manifest.counts.planned}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd>{manifest.counts.completed}</dd>
            </div>
            <div>
              <dt>Admissible</dt>
              <dd>{manifest.counts.admissible}</dd>
            </div>
            <div>
              <dt>Excluded by a gate</dt>
              <dd>{manifest.counts.inadmissible}</dd>
            </div>
            <div>
              <dt>Failed</dt>
              <dd>{manifest.counts.failed}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </div>
  );
}
