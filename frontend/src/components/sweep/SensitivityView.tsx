// Sensitivity & Decomposition — design doc §9.4.
//
// The headline finding of the whole engine: which methodological choice actually moves
// the answer. Only computable because the core is a factorial, and now on the critical
// path rather than a presentation layer — §8.1 uses these per-axis spreads to size the
// uncertainty substitution.
//
// The tornado needs a baseline to vary against. That baseline is an **arithmetic anchor,
// not a recommendation**: the engine nominates no central estimate (§9.5), and changing
// the anchor moves the bars without moving the reported spread, which is computed over
// the whole admissible set and is anchor-independent.
import { useMemo } from "react";

import { useSweepStore } from "../../store/useSweepStore";
import {
  admissibleRows,
  decomposeVariance,
  filterRows,
  formatMetric,
  spreadStats,
} from "../../lib/sweepAnalysis";
import { AXIS_LABELS, METRIC_META, type AxisColumn } from "../../types/sweep";

export function SensitivityView() {
  const rows = useSweepStore((state) => state.rows);
  const metric = useSweepStore((state) => state.metric);
  const filters = useSweepStore((state) => state.filters);

  const good = useMemo(() => admissibleRows(filterRows(rows, filters)), [rows, filters]);
  const contributions = useMemo(() => decomposeVariance(good, metric), [good, metric]);
  const stats = useMemo(() => spreadStats(good, metric), [good, metric]);

  if (rows.length === 0) {
    return <p className="muted">Run a sweep to decompose its spread.</p>;
  }
  if (contributions.length === 0 || good.length < 2) {
    return (
      <p className="muted">
        A decomposition needs at least two admissible scenarios carrying{" "}
        {METRIC_META[metric].label}. This sweep has {good.length}.
      </p>
    );
  }

  const meta = METRIC_META[metric];
  const maxSwing = Math.max(...contributions.map((entry) => Math.abs(entry.swing)), 1e-12);

  return (
    <div className="sweep-sensitivity">
      <section>
        <h4>Where the spread comes from</h4>
        <p className="muted">
          Share of the variance in {meta.label} attributable to each axis, over{" "}
          {good.length} admissible scenarios.
        </p>
        <ul className="sweep-decomposition">
          {contributions.map((entry) => (
            <li key={entry.axis}>
              <span className="sweep-decomposition-label">
                {AXIS_LABELS[entry.axis as AxisColumn]}
                <small>
                  {entry.levels} level{entry.levels === 1 ? "" : "s"}
                </small>
              </span>
              <span className="sweep-decomposition-track">
                <span
                  className="sweep-decomposition-fill"
                  style={{ width: `${Math.max(0, entry.share) * 100}%` }}
                />
              </span>
              <span className="sweep-decomposition-value">{(entry.share * 100).toFixed(1)}%</span>
            </li>
          ))}
        </ul>
        <p className="muted">
          A first-order decomposition: it attributes nothing to interactions between axes,
          so these shares describe main effects and will not account for the whole spread
          where axes interact.
        </p>
      </section>

      <section>
        <h4>Swing per axis</h4>
        <p className="muted">
          The gap between the best and worst level mean on each axis, in {meta.unit || "metric units"}.
        </p>
        <ul className="sweep-tornado">
          {contributions.map((entry) => (
            <li key={entry.axis}>
              <span className="sweep-tornado-label">{AXIS_LABELS[entry.axis as AxisColumn]}</span>
              <span className="sweep-tornado-track">
                <span
                  className="sweep-tornado-fill"
                  style={{ width: `${(Math.abs(entry.swing) / maxSwing) * 100}%` }}
                />
              </span>
              <span className="sweep-tornado-value">{formatMetric(entry.swing, metric)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>Level means</h4>
        <p className="muted">
          What each individual choice is worth. A level with few scenarios behind it is a
          weaker estimate — the count says how much weight it carries.
        </p>
        <div className="sweep-level-means">
          {contributions.map((entry) => (
            <div key={entry.axis}>
              <h5>{AXIS_LABELS[entry.axis as AxisColumn]}</h5>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Level</th>
                    <th>Mean</th>
                    <th>Scenarios</th>
                  </tr>
                </thead>
                <tbody>
                  {entry.levelMeans.map((level) => (
                    <tr key={level.level}>
                      <td>{level.level.replace(/_/g, " ")}</td>
                      <td>{formatMetric(level.mean, metric)}</td>
                      <td>{level.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>

      {stats ? (
        <section className="sweep-spread-note">
          <h4>Total spread</h4>
          <p>
            {formatMetric(stats.min, metric)} to {formatMetric(stats.max, metric)} —{" "}
            {stats.rangePctOfMean.toFixed(2)}% of the mean, across {stats.count} admissible
            scenarios. This figure is computed over the whole admissible set and does not
            depend on which scenario is used as the anchor above.
          </p>
        </section>
      ) : null}
    </div>
  );
}
