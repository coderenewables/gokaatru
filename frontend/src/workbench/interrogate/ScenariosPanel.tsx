import { useMemo, useState } from "react";

import { AXIS_COLUMNS, AXIS_LABELS, METRIC_META, type MetricColumn } from "../../types/sweep";
import {
  MAX_PINNED,
  describeTerms,
  levelsOf,
  metricValue,
  metricsPresent,
  useFilteredRows,
  useInterrogate,
  useTerms,
} from "./store";
import { loadScenario } from "../model/scenario";
import { useCampaign } from "../shell/context";
import { useOpenSweep, useSweepList } from "./useSweeps";
import "./interrogate.css";

/** The table shows this many rows at most; the count above it is of every filtered scenario. */
export const TABLE_LIMIT = 300;

export const metricLabel = (column: string) => METRIC_META[column as MetricColumn]?.label ?? column;
export function formatMetric(column: string, value: number | null): string {
  if (value === null) return "—";
  const meta = METRIC_META[column as MetricColumn];
  return meta ? value.toFixed(meta.precision) : String(value);
}

function when(stamp: string | null): string {
  return stamp ? stamp.slice(0, 16).replace("T", " ") : "unfinished";
}

/** The scenarios of one sweep: choose the sweep and the metric, filter by level, read the
 * terms every brush has drawn, and pin up to two rows to compare. */
export function ScenariosPanel() {
  const sweeps = useSweepList();
  const sweepId = useInterrogate((state) => state.sweepId);
  const openSweep = useInterrogate((state) => state.openSweep);
  const all = useInterrogate((state) => state.rows);
  const open = useOpenSweep();
  const terms = useTerms();
  const filtered = useFilteredRows();
  const metric = useInterrogate((state) => state.metric);
  const setMetric = useInterrogate((state) => state.setMetric);
  const showInadmissible = useInterrogate((state) => state.showInadmissible);
  const setShow = useInterrogate((state) => state.setShowInadmissible);
  const toggleLevel = useInterrogate((state) => state.toggleLevel);
  const removeTerm = useInterrogate((state) => state.removeTerm);
  const clearAll = useInterrogate((state) => state.clearAll);
  const pinned = useInterrogate((state) => state.pinned);
  const pin = useInterrogate((state) => state.pin);
  const unpin = useInterrogate((state) => state.unpin);
  const [descending, setDescending] = useState<boolean | null>(null);
  const { sessionId } = useCampaign();
  const [loadError, setLoadError] = useState("");

  const metrics = useMemo(() => metricsPresent(all), [all]);
  const chips = describeTerms(terms);
  const sorted = useMemo(() => {
    if (descending === null) return filtered;
    const sign = descending ? -1 : 1;
    return [...filtered].sort((a, b) => {
      const left = metricValue(a, metric);
      const right = metricValue(b, metric);
      if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
      return sign * (left - right);
    });
  }, [filtered, descending, metric]);
  const shown = sorted.slice(0, TABLE_LIMIT);
  const full = pinned.length >= MAX_PINNED;

  if (sweeps.isError) return <div className="gk-panel"><p role="alert">{sweeps.error.message}</p></div>;
  if (sweeps.data && sweeps.data.length === 0) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>No sweep has been run for this campaign yet. Run one in the Run phase.</p>
      </div>
    );
  }

  return (
    <div
      className="gk-panel gk-interrogate"
      onKeyDown={(event) => {
        if (event.key === "Escape" && event.target instanceof HTMLElement && event.target.tagName !== "SELECT") clearAll();
      }}
    >
      <div className="gk-int-controls">
        <label className="gk-field">
          Sweep
          <select aria-label="Sweep" value={sweepId ?? ""} onChange={(event) => openSweep(event.target.value || null)}>
            <option value="">Choose a sweep</option>
            {(sweeps.data ?? []).map((sweep) => (
              <option key={sweep.sweep_id} value={sweep.sweep_id}>
                {sweep.sweep_id} · {when(sweep.started_at)} · {sweep.counts.completed ?? 0} done
                {sweep.in_progress ? " · in progress" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="gk-field">
          Metric
          <select aria-label="Metric" value={metric} onChange={(event) => setMetric(event.target.value)} disabled={!sweepId}>
            {(metrics.length ? metrics : [metric]).map((column) => (
              <option key={column} value={column}>
                {metricLabel(column)}
              </option>
            ))}
          </select>
        </label>
        <label className="gk-check">
          <input type="checkbox" checked={showInadmissible} onChange={(event) => setShow(event.target.checked)} />
          Show inadmissible scenarios
        </label>
      </div>

      {sweepId === null && <p className="gk-muted">Choose a sweep to see its scenarios.</p>}
      {open.isError && <p role="alert">{open.error.message}</p>}
      {open.isLoading && <p className="gk-muted">Loading the sweep…</p>}

      {sweepId !== null && all.length > 0 && (
        <>
          <div className="gk-int-levels" role="group" aria-label="Level filters">
            {AXIS_COLUMNS.map((axis) => {
              const levels = levelsOf(all, axis);
              const kept = terms.levels[axis];
              return (
                <fieldset key={axis} className="gk-columns">
                  <legend>{AXIS_LABELS[axis]}</legend>
                  {levels.map((level) => (
                    <label key={level} className="gk-check">
                      <input
                        type="checkbox"
                        checked={kept === undefined || kept.includes(level)}
                        onChange={() => toggleLevel(axis, level, levels)}
                      />
                      {level}
                    </label>
                  ))}
                </fieldset>
              );
            })}
          </div>

          <p className="gk-selection-count" aria-live="polite">
            <strong>{filtered.length}</strong>
            <span className="gk-muted"> of {all.length} scenarios</span>
          </p>
          {chips.length > 0 ? (
            <ul className="gk-terms" aria-label="Scenario terms">
              {chips.map((chip) => (
                <li key={chip.id} className="gk-term">
                  <span className="gk-term-label">{chip.label}</span>
                  <span className="gk-term-text">{chip.text}</span>
                  <button
                    type="button"
                    className="gk-icon-button"
                    aria-label={`Clear the term: ${chip.label} ${chip.text}`}
                    onClick={() => removeTerm(chip.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="gk-muted">Brush a chart or untick a level to filter. Escape clears every term.</p>
          )}
          <p className="gk-muted" aria-live="polite">
            Pinned {pinned.length} of {MAX_PINNED}
            {full ? ": unpin one to pin another." : "."}
          </p>

          {loadError && (
            <p role="alert" className="gk-warning">
              {loadError}
            </p>
          )}
          <div className="gk-int-table-wrap">
            <table className="gk-compare gk-int-table">
              <caption className="gk-sr">Scenarios of the open sweep</caption>
              <thead>
                <tr>
                  <th scope="col">Pin</th>
                  {AXIS_COLUMNS.map((axis) => (
                    <th key={axis} scope="col">{AXIS_LABELS[axis]}</th>
                  ))}
                  <th scope="col" aria-sort={descending === null ? "none" : descending ? "descending" : "ascending"}>
                    <button
                      type="button"
                      className="gk-sort"
                      onClick={() => setDescending((current) => (current === null ? true : current ? false : null))}
                    >
                      {metricLabel(metric)}
                      {descending === null ? "" : descending ? " ▼" : " ▲"}
                    </button>
                  </th>
                  <th scope="col">Admissible</th>
                  <th scope="col">Status</th>
                  <th scope="col">Model</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => {
                  const isPinned = pinned.includes(row.config_hash);
                  return (
                    <tr key={row.config_hash} className={isPinned ? "gk-row-pinned" : undefined}>
                      <td>
                        <button
                          type="button"
                          className="gk-button gk-pin"
                          aria-pressed={isPinned}
                          disabled={!isPinned && full}
                          title={!isPinned && full ? "Two are pinned; unpin one first" : undefined}
                          aria-label={`${isPinned ? "Unpin" : "Pin"} scenario ${row.config_hash.slice(0, 8)}`}
                          onClick={() => (isPinned ? unpin(row.config_hash) : pin(row.config_hash))}
                        >
                          {isPinned ? "Unpin" : "Pin"}
                        </button>
                      </td>
                      {AXIS_COLUMNS.map((axis) => (
                        <td key={axis}>{row[axis] ?? "—"}</td>
                      ))}
                      <td className="gk-num">{formatMetric(metric, metricValue(row, metric))}</td>
                      <td>{row.admissible ? "yes" : "no"}</td>
                      <td>{row.status}</td>
                      <td>
                        <button
                          type="button"
                          className="gk-button"
                          disabled={row.status !== "ok" || !sweepId}
                          aria-label={`Load scenario ${row.config_hash.slice(0, 8)} into Model`}
                          onClick={() => {
                            setLoadError("");
                            if (sweepId) loadScenario(sessionId, sweepId, row.config_hash).catch((error: Error) => setLoadError(error.message));
                          }}
                        >
                          Load
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {sorted.length > shown.length && (
            <p className="gk-muted">
              Showing the first {shown.length} of {sorted.length} filtered scenarios; the charts draw all of them.
            </p>
          )}
        </>
      )}
    </div>
  );
}
