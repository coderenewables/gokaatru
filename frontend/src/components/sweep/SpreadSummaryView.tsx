// Spread Summary & Scenario Export — design doc §9.5.
//
// **The engine does not nominate a central estimate.** It reports the spread and the
// analyst decides. No recommended scenario, no selection rule, no implied endorsement —
// the tool's job is to make the choice informed, not to make it.
//
// So the statistics here are presented as a description of the scenario set, never
// captioned as a result, and the export is per-scenario: the analyst picks the one they
// will stand behind and takes its runconfig away.
import { useEffect, useMemo } from "react";

import { useSweepStore, spreadKey } from "../../store/useSweepStore";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import {
  admissibleRows,
  failedRows,
  filterRows,
  formatMetric,
  inadmissibleRows,
  spreadStats,
  toCsv,
} from "../../lib/sweepAnalysis";
import {
  HEADLINE_METRICS,
  METRIC_META,
  describeDuplicateLevels,
  type MetricColumn,
} from "../../types/sweep";
import { SubstitutionBadge, SubstitutionExplainer } from "./SubstitutionExplainer";

function download(name: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function SpreadSummaryView() {
  const apiBaseUrl = useWorkspaceStore((state) => state.apiBaseUrl);
  const session = useWorkspaceStore((state) => state.session);

  const rows = useSweepStore((state) => state.rows);
  const manifest = useSweepStore((state) => state.manifest);
  const filters = useSweepStore((state) => state.filters);
  const metric = useSweepStore((state) => state.metric);
  const downloadRunconfig = useSweepStore((state) => state.downloadRunconfig);

  const filtered = useMemo(() => filterRows(rows, filters), [rows, filters]);
  const good = useMemo(() => admissibleRows(filtered), [filtered]);
  const excluded = useMemo(() => inadmissibleRows(filtered), [filtered]);
  const failed = useMemo(() => failedRows(filtered), [filtered]);
  const sweepId = useSweepStore((state) => state.manifest?.sweep_id ?? "");
  const spread = useSweepStore((state) => state.spread);
  const substitutionByKey = useSweepStore((state) => state.substitution);
  const loadSpread = useSweepStore((state) => state.loadSpread);

  const hashes = useMemo(() => good.map((row) => row.config_hash), [good]);

  // One request carries both the decomposition and the uncertainty substitution; the
  // substitution is read off the long-term speed whatever metric is selected.
  useEffect(() => {
    if (!session || hashes.length < 2) return;
    void loadSpread(apiBaseUrl, session.session_id, metric, hashes);
  }, [apiBaseUrl, session, metric, hashes, loadSpread]);

  const key = spreadKey(sweepId, metric, hashes);
  const contributions = spread[key] ?? [];
  const substitution = substitutionByKey[key];
  const minLevels = substitution?.min_levels ?? 3;

  if (rows.length === 0) {
    return <p className="muted">Run a sweep, or open a saved one, to summarise its spread.</p>;
  }

  return (
    <div className="sweep-summary">
      {manifest?.diagnosis ? (
        <section className="sweep-diagnosis">
          <h4>No scenario was admissible</h4>
          <p>{manifest.diagnosis}</p>
          {manifest.gate_failures && Object.keys(manifest.gate_failures).length > 0 ? (
            <ul>
              {Object.entries(manifest.gate_failures).map(([gate, count]) => (
                <li key={gate}>
                  {gate.replace(/_/g, " ")}: {count} scenario{count === 1 ? "" : "s"}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      <section className="sweep-no-recommendation">
        <h4>This is a spread, not a recommendation</h4>
        <p>
          The engine does not nominate a central estimate. Every figure below describes the
          set of scenarios that were run and passed their gates — it is not an answer, and
          choosing which scenario to stand behind is yours to make.
        </p>
      </section>

      <section>
        <h4>Headline spread</h4>
        <div className="sweep-headline-grid">
          {HEADLINE_METRICS.map((name) => {
            const stats = spreadStats(good, name as MetricColumn);
            const meta = METRIC_META[name as MetricColumn];
            return (
              <div key={name} className="sweep-headline-card">
                <h5>{meta.label}</h5>
                {stats ? (
                  <>
                    <dl>
                      <div>
                        <dt>P50</dt>
                        <dd>{formatMetric(stats.p50, name as MetricColumn)}</dd>
                      </div>
                      <div>
                        <dt>P10 – P90</dt>
                        <dd>
                          {formatMetric(stats.p10, name as MetricColumn)} –{" "}
                          {formatMetric(stats.p90, name as MetricColumn)}
                        </dd>
                      </div>
                      <div>
                        <dt>full range</dt>
                        <dd>
                          {formatMetric(stats.min, name as MetricColumn)} –{" "}
                          {formatMetric(stats.max, name as MetricColumn)}
                        </dd>
                      </div>
                      <div>
                        <dt>spread</dt>
                        <dd>{stats.rangePctOfMean.toFixed(2)}% of mean</dd>
                      </div>
                    </dl>
                    <small>over {stats.count} admissible scenarios</small>
                  </>
                ) : (
                  <p className="muted">No admissible scenario carries this metric.</p>
                )}
              </div>
            );
          })}
        </div>
        <p className="muted">
          Speed and energy do not move proportionally: the energy sensitivity factor S
          varies across scenarios with where each one&apos;s distribution sits against the
          power curve, so a 2% speed spread is not a 6% energy spread at every site.
        </p>
      </section>

      <section className="sweep-budget">
        <h4>Uncertainty budget</h4>
        <p className="muted">
          Where the sweep&apos;s empirical spread displaced a parametric term, and where it
          added one the model does not otherwise carry.
        </p>
        {substitution?.available && substitution.components ? (
          substitution.components.map((entry) => (
            <SubstitutionBadge key={entry.component} entry={entry} minLevels={minLevels} />
          ))
        ) : (
          <p className="muted">{substitution?.reason ?? "The budget is computed on the server once the spread loads."}</p>
        )}
        {substitution?.available && substitution.totals?.parametric && substitution.totals.substituted ? (
          <p>
            Total uncertainty, median over {substitution.totals.scenarios} scenarios:{" "}
            <strong>{substitution.totals.substituted.median.toFixed(2)}%</strong> with the sweep
            spread folded in, against {substitution.totals.parametric.median.toFixed(2)}% from the
            parametric model alone. The spread raised the total for{" "}
            {substitution.totals.raised} of them
            {substitution.totals.scenarios_missing_components > 0
              ? `; ${substitution.totals.scenarios_missing_components} lacked a parametric component and are not counted`
              : ""}
            .
          </p>
        ) : null}
        <SubstitutionExplainer minLevels={minLevels} />
        <p className="muted">
          Axis coverage this number was earned on:{" "}
          {contributions
            .map((entry) => {
              const base = `${entry.levels} level${entry.levels === 1 ? "" : "s"}`;
              const dups = describeDuplicateLevels(entry);
              return dups.length > 0 ? `${base} (same sensors: ${dups.join("; ")})` : base;
            })
            .join(", ") || "—"}
          .
        </p>
      </section>

      <section className="sweep-composition">
        <h4>What the set contains</h4>
        <dl className="sweep-stat-row">
          <div>
            <dt>admissible</dt>
            <dd>{good.length}</dd>
          </div>
          <div>
            <dt>excluded by a gate</dt>
            <dd>{excluded.length}</dd>
          </div>
          <div>
            <dt>failed to run</dt>
            <dd>{failed.length}</dd>
          </div>
          <div>
            <dt>fixed-prefix hash</dt>
            <dd>
              <code>{manifest?.fixed_prefix_hash.slice(0, 12) ?? "—"}</code>
            </dd>
          </div>
        </dl>
        <p className="muted">
          Scenarios built on a different fixed prefix — different cleaning, different
          reanalysis — are not comparable with these, and the hash is what makes that
          checkable.
        </p>
      </section>

      <section className="sweep-export">
        <h4>Take a scenario away</h4>
        <p className="muted">
          Every scenario is retained with its own complete runconfig. Pick the one you will
          stand behind and download it as the project&apos;s configuration of record.
        </p>
        <div className="sweep-detail-actions">
          <button type="button" onClick={() => download("sweep-results.csv", toCsv(rows), "text/csv")}>
            All scenarios (CSV)
          </button>
          <button
            type="button"
            disabled={!manifest}
            onClick={() =>
              manifest &&
              download("sweep-manifest.json", JSON.stringify(manifest, null, 2), "application/json")
            }
          >
            Manifest (JSON)
          </button>
        </div>
        <div className="sweep-table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>{METRIC_META[metric].label}</th>
                <th>Admissible</th>
                <th>Runconfig</th>
              </tr>
            </thead>
            <tbody>
              {good.map((row) => (
                <tr key={row.config_hash}>
                  <td>
                    <code>{row.config_hash.slice(0, 8)}</code>
                  </td>
                  <td>{formatMetric(row[metric], metric)}</td>
                  <td>yes</td>
                  <td>
                    <button
                      type="button"
                      onClick={() =>
                        void downloadRunconfig(
                          apiBaseUrl,
                          session?.session_id ?? "",
                          row.config_hash,
                        )
                      }
                    >
                      Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
