// Spread Explorer — design doc §9.3. The centrepiece.
//
// Distribution, filters and the scenario table over one result set. Inadmissible
// scenarios render as a ghost layer: visible, and never counted into a percentile.
// That distinction is the reason the gates exist, so it has to be visible rather than
// implied by a row silently missing from a chart.
import { useMemo } from "react";
import clsx from "clsx";

import { useSweepStore } from "../../store/useSweepStore";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import {
  admissibleRows,
  axisLevels,
  failedRows,
  filterRows,
  formatMetric,
  gateValue,
  inadmissibleRows,
  metricValues,
  spreadStats,
  toCsv,
  valueHistogram,
} from "../../lib/sweepAnalysis";
import {
  AXIS_COLUMNS,
  AXIS_LABELS,
  HEADLINE_METRICS,
  METRIC_COLUMNS,
  METRIC_META,
  type AxisColumn,
  type GateStatus,
  type ScenarioRow,
} from "../../types/sweep";

const GATE_TONE: Record<GateStatus, string> = {
  pass: "gate-pass",
  warn: "gate-warn",
  fail: "gate-fail",
  not_applicable: "gate-na",
  marked: "gate-marked",
};

function gateColumns(row: ScenarioRow): Array<[string, GateStatus]> {
  // `gate_<name>` carries the verdict, `gate_<name>_value` the number it was reached on.
  // Only the verdicts are chips; without the second filter every value column renders as
  // a phantom gate, and a number passes the "not a pass" test the chip list applies.
  return Object.entries(row)
    .filter(([key]) => key.startsWith("gate_") && !key.endsWith("_value"))
    .map(([key, value]) => [key.slice("gate_".length), value as GateStatus]);
}

function Histogram({
  admissible,
  ghost,
  label,
  precision,
}: {
  admissible: number[];
  ghost: number[];
  label: string;
  precision: number;
}) {
  const admissibleBuckets = valueHistogram(admissible, precision);
  const ghostBuckets = valueHistogram(ghost, precision);
  if (admissibleBuckets.length === 0 && ghostBuckets.length === 0) {
    return <p className="muted">No values to plot.</p>;
  }

  const admissibleByValue = new Map(admissibleBuckets.map((bucket) => [bucket.value, bucket.count]));
  const ghostByValue = new Map(ghostBuckets.map((bucket) => [bucket.value, bucket.count]));
  const values = [...new Set([...admissibleByValue.keys(), ...ghostByValue.keys()])].sort((a, b) => a - b);
  const peak = Math.max(
    ...values.map((value) => (admissibleByValue.get(value) ?? 0) + (ghostByValue.get(value) ?? 0)),
    1,
  );

  return (
    <div className="sweep-histogram-wrap">
      <div className="sweep-histogram" role="img" aria-label={`Distribution of ${label}`}>
        {values.map((value) => {
          const count = admissibleByValue.get(value) ?? 0;
          const ghostCount = ghostByValue.get(value) ?? 0;
          const total = count + ghostCount;
          return (
            <div
              key={value}
              className="sweep-histogram-column"
              title={`${value}: ${total} scenario${total === 1 ? "" : "s"}`}
            >
              <div className="sweep-histogram-ghost" style={{ height: `${(ghostCount / peak) * 100}%` }} />
              <div className="sweep-histogram-bar" style={{ height: `${(count / peak) * 100}%` }} />
            </div>
          );
        })}
      </div>
      {/* Counts labelled directly, not just on hover: sweep axes are discrete, so distinct
          values often recur with near-identical counts (e.g. 8 values at 36 scenarios each)
          and bar height alone then carries almost no signal - it reads as a rendering bug
          rather than a genuinely flat distribution without a number to confirm it. */}
      <div className="sweep-histogram-axis">
        {values.map((value) => {
          const total = (admissibleByValue.get(value) ?? 0) + (ghostByValue.get(value) ?? 0);
          return (
            <span key={value} className="sweep-histogram-tick">
              <strong>{total}</strong>
              {value.toFixed(precision)}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function SpreadExplorer() {
  const apiBaseUrl = useWorkspaceStore((state) => state.apiBaseUrl);
  const session = useWorkspaceStore((state) => state.session);

  const rows = useSweepStore((state) => state.rows);
  const metric = useSweepStore((state) => state.metric);
  const filters = useSweepStore((state) => state.filters);
  const showInadmissible = useSweepStore((state) => state.showInadmissible);
  const selectedScenario = useSweepStore((state) => state.selectedScenario);
  const setMetric = useSweepStore((state) => state.setMetric);
  const setFilter = useSweepStore((state) => state.setFilter);
  const clearFilters = useSweepStore((state) => state.clearFilters);
  const setShowInadmissible = useSweepStore((state) => state.setShowInadmissible);
  const selectScenario = useSweepStore((state) => state.selectScenario);
  const downloadRunconfig = useSweepStore((state) => state.downloadRunconfig);

  const filtered = useMemo(() => filterRows(rows, filters), [rows, filters]);
  const good = useMemo(() => admissibleRows(filtered), [filtered]);
  const excluded = useMemo(() => inadmissibleRows(filtered), [filtered]);
  const failed = useMemo(() => failedRows(filtered), [filtered]);
  const stats = useMemo(() => spreadStats(good, metric), [good, metric]);

  const visible = useMemo(
    () => (showInadmissible ? filtered : [...good, ...failed]),
    [failed, filtered, good, showInadmissible],
  );

  if (rows.length === 0) {
    return <p className="muted">Run a sweep, or open a saved one, to explore its spread.</p>;
  }

  const meta = METRIC_META[metric];

  return (
    <div className="sweep-explorer">
      <section className="sweep-metric-bar">
        <label>
          Metric
          <select value={metric} onChange={(event) => setMetric(event.target.value as typeof metric)}>
            <optgroup label="Headline">
              {HEADLINE_METRICS.map((name) => (
                <option key={name} value={name}>
                  {METRIC_META[name].label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Secondary">
              {METRIC_COLUMNS.filter((name) => !METRIC_META[name].headline).map((name) => (
                <option key={name} value={name}>
                  {METRIC_META[name].label}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <label className="sweep-ghost-toggle">
          <input
            type="checkbox"
            checked={showInadmissible}
            onChange={(event) => setShowInadmissible(event.target.checked)}
          />
          Show scenarios excluded by a gate ({excluded.length})
        </label>
        <button type="button" onClick={() => clearFilters()}>
          Clear filters
        </button>
      </section>

      <section className="sweep-distribution">
        <h4>
          {meta.label} across {good.length} admissible scenario{good.length === 1 ? "" : "s"}
        </h4>
        <Histogram
          admissible={metricValues(good, metric)}
          ghost={showInadmissible ? metricValues(excluded, metric) : []}
          label={meta.label}
          precision={meta.precision}
        />
        {stats ? (
          <dl className="sweep-stat-row">
            {(
              [
                ["mean", stats.mean],
                ["median", stats.p50],
                ["σ", stats.std],
              ] as Array<[string, number]>
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{formatMetric(value, metric)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="muted">No admissible scenario carries this metric.</p>
        )}
        <p className="muted">
          Statistics are over admissible scenarios only. Excluded scenarios stay in the
          table below and, when shown, render as the pale layer behind the distribution.
        </p>
      </section>

      <section className="sweep-filter-rail">
        <h5>Filter by axis</h5>
        {AXIS_COLUMNS.map((axis) => {
          const levels = axisLevels(rows, axis);
          if (levels.length < 2) return null;
          const active = filters[axis] ?? [];
          return (
            <div key={axis} className="sweep-filter-group">
              <span>{AXIS_LABELS[axis as AxisColumn]}</span>
              {levels.map((level) => (
                <label key={level} className={clsx("sweep-filter-chip", { on: active.includes(level) })}>
                  <input
                    type="checkbox"
                    checked={active.includes(level)}
                    onChange={() =>
                      setFilter(
                        axis as AxisColumn,
                        active.includes(level)
                          ? active.filter((entry) => entry !== level)
                          : [...active, level],
                      )
                    }
                  />
                  {level.replace(/_/g, " ")}
                </label>
              ))}
            </div>
          );
        })}
      </section>

      <section className="sweep-table-panel">
        <h5>
          {visible.length} scenario{visible.length === 1 ? "" : "s"}
          {failed.length > 0 ? ` · ${failed.length} failed` : ""}
        </h5>
        <div className="sweep-table-scroll">
          <table className="data-table sweep-table">
            <thead>
              <tr>
                <th>Scenario</th>
                {AXIS_COLUMNS.map((axis) => (
                  <th key={axis}>{AXIS_LABELS[axis as AxisColumn]}</th>
                ))}
                <th>{meta.label}</th>
                <th>Gates</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.config_hash}
                  className={clsx({
                    "row-inadmissible": row.status === "ok" && !row.admissible,
                    "row-failed": row.status === "failed",
                    "row-selected": selectedScenario === row.config_hash,
                  })}
                  onClick={() => selectScenario(row.config_hash)}
                >
                  <td>
                    <code>{row.config_hash.slice(0, 8)}</code>
                  </td>
                  {AXIS_COLUMNS.map((axis) => (
                    <td key={axis}>{String(row[axis] ?? "—").replace(/_/g, " ")}</td>
                  ))}
                  <td>{row.status === "failed" ? "—" : formatMetric(row[metric], metric)}</td>
                  <td className="sweep-gate-cell">
                    {row.status === "failed" ? (
                      <span className="gate-fail" title={row.error ?? ""}>
                        did not run
                      </span>
                    ) : (
                      gateColumns(row)
                        .filter(([, status]) => status !== "pass" && status !== "not_applicable")
                        .map(([name, status]) => (
                          <span
                            key={name}
                            className={GATE_TONE[status]}
                            title={`${status.replace(/_/g, " ")}${
                              gateValue(row, name) == null ? "" : ` — measured ${gateValue(row, name)}`
                            }`}
                          >
                            {name.replace(/_/g, " ")}
                          </span>
                        ))
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selectedScenario ? (
        <section className="sweep-detail-panel">
          <h5>Scenario {selectedScenario.slice(0, 8)}</h5>
          {(() => {
            const row = rows.find((entry) => entry.config_hash === selectedScenario);
            if (!row) return null;
            return (
              <>
                <dl className="sweep-detail-metrics">
                  {METRIC_COLUMNS.map((name) => (
                    <div key={name}>
                      <dt>{METRIC_META[name].label}</dt>
                      <dd>{formatMetric(row[name], name)}</dd>
                    </div>
                  ))}
                </dl>
                {row.error ? <p className="sweep-error">{row.error}</p> : null}
                <div className="sweep-detail-actions">
                  <button
                    type="button"
                    disabled={row.status !== "ok"}
                    onClick={() =>
                      void downloadRunconfig(apiBaseUrl, session?.session_id ?? "", row.config_hash)
                    }
                  >
                    Download this scenario&apos;s runconfig
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const blob = new Blob([toCsv(rows)], { type: "text/csv" });
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement("a");
                      link.href = url;
                      link.download = "sweep-results.csv";
                      link.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Export all scenarios as CSV
                  </button>
                </div>
              </>
            );
          })()}
        </section>
      ) : null}
    </div>
  );
}
