// Gate report — what was checked, what each check found, and what it excluded.
//
// The Spread Explorer shows gate chips on a row, which answers "was this scenario
// excluded". It does not answer the question a reader actually has when a spread comes
// back thinner than expected: *which* check did the excluding, on what number, and
// against what threshold. Without that, an analyst cannot tell whether the campaign or
// the threshold is at fault — and on the first live-reanalysis run that distinction was
// the whole finding (design doc §13.6).
//
// Every gate is listed, including the ones nothing tripped. A reader needs to know what
// *was* checked, not only what failed.
import { useMemo, useState } from "react";
import clsx from "clsx";

import { useSweepStore } from "../../store/useSweepStore";
import { gateValue, summariseGates, type GateSummary } from "../../lib/sweepAnalysis";
import {
  AXIS_COLUMNS,
  AXIS_LABELS,
  GATE_META,
  GATE_STATUS_MEANING,
  type AxisColumn,
  type GateStatus,
  type ScenarioRow,
} from "../../types/sweep";

const STATUS_ORDER: GateStatus[] = ["fail", "warn", "marked", "pass", "not_applicable"];

const STATUS_TONE: Record<GateStatus, string> = {
  pass: "gate-pass",
  warn: "gate-warn",
  fail: "gate-fail",
  not_applicable: "gate-na",
  marked: "gate-marked",
};

function formatValue(value: number | null): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 1) return value.toFixed(3);
  return value.toFixed(4);
}

function ScenarioList({
  gate,
  rows,
  tone,
  onSelect,
}: {
  gate: string;
  rows: ScenarioRow[];
  tone: string;
  onSelect: (hash: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <div className="gate-scenario-list">
      <table className="data-table">
        <thead>
          <tr>
            <th>Scenario</th>
            {AXIS_COLUMNS.map((axis) => (
              <th key={axis}>{AXIS_LABELS[axis as AxisColumn]}</th>
            ))}
            <th>Measured</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.config_hash} onClick={() => onSelect(row.config_hash)}>
              <td>
                <code>{row.config_hash.slice(0, 8)}</code>
              </td>
              {AXIS_COLUMNS.map((axis) => (
                <td key={axis}>{String(row[axis] ?? "—").replace(/_/g, " ")}</td>
              ))}
              <td className={tone}>{formatValue(gateValue(row, gate))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GateCard({
  summary,
  thresholds,
  onSelect,
}: {
  summary: GateSummary;
  thresholds: Record<string, number>;
  onSelect: (hash: string) => void;
}) {
  const [expanded, setExpanded] = useState(summary.counts.fail > 0);
  const meta = GATE_META[summary.gate];
  const label = meta?.label ?? summary.gate.replace(/_/g, " ");
  const affected = summary.counts.fail + summary.counts.warn + summary.counts.marked;

  return (
    <section className={clsx("gate-card", { "gate-card-excluding": summary.counts.fail > 0 })}>
      <header>
        <button
          type="button"
          className="gate-card-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          <h4>{label}</h4>
        </button>
        <div className="gate-tally">
          {STATUS_ORDER.filter((status) => summary.counts[status] > 0).map((status) => (
            <span key={status} className={STATUS_TONE[status]} title={GATE_STATUS_MEANING[status]}>
              {summary.counts[status]} {status.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      </header>

      {summary.excludedEverything ? (
        <p className="gate-card-alarm">
          This gate excluded <strong>every</strong> completed scenario. That is a
          measurement of the threshold rather than of the site — check the value below
          before widening the sweep.
        </p>
      ) : null}

      {expanded ? (
        <div className="gate-card-body">
          {meta ? (
            <>
              <p>{meta.measures}</p>
              <p className="muted">
                <strong>Applies to:</strong> {meta.appliesTo}
              </p>
            </>
          ) : (
            <p className="muted">No description is registered for this gate.</p>
          )}

          <dl className="gate-thresholds">
            {(meta?.thresholdKeys ?? []).map((key) => (
              <div key={key}>
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd>{thresholds[key] ?? "—"}</dd>
              </div>
            ))}
            {summary.valueRange ? (
              <div>
                <dt>observed range</dt>
                <dd>
                  {formatValue(summary.valueRange.min)} – {formatValue(summary.valueRange.max)}
                </dd>
              </div>
            ) : null}
          </dl>

          {summary.counts.fail > 0 ? (
            <>
              <h5>
                Excluded {summary.counts.fail} scenario{summary.counts.fail === 1 ? "" : "s"}
              </h5>
              <ScenarioList
                gate={summary.gate}
                rows={summary.failedRows}
                tone="gate-fail"
                onSelect={onSelect}
              />
            </>
          ) : null}

          {summary.counts.warn > 0 ? (
            <>
              <h5>
                Flagged {summary.counts.warn} scenario{summary.counts.warn === 1 ? "" : "s"}{" "}
                <small>— still counted in every statistic</small>
              </h5>
              <ScenarioList
                gate={summary.gate}
                rows={summary.warnedRows}
                tone="gate-warn"
                onSelect={onSelect}
              />
            </>
          ) : null}

          {summary.counts.marked > 0 ? (
            <>
              <h5>
                Marked {summary.counts.marked} scenario{summary.counts.marked === 1 ? "" : "s"}{" "}
                <small>— not a defect, kept visible</small>
              </h5>
              <ScenarioList
                gate={summary.gate}
                rows={summary.markedRows}
                tone="gate-marked"
                onSelect={onSelect}
              />
            </>
          ) : null}

          {affected === 0 ? (
            <p className="muted">Nothing tripped this gate.</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function GateReportView() {
  const rows = useSweepStore((state) => state.rows);
  const manifest = useSweepStore((state) => state.manifest);
  const selectScenario = useSweepStore((state) => state.selectScenario);

  const summaries = useMemo(() => summariseGates(rows), [rows]);
  const completed = rows.filter((row) => row.status === "ok");
  const excluded = completed.filter((row) => !row.admissible);
  const couldNotRun = rows.filter((row) => row.status === "failed");

  if (rows.length === 0) {
    return <p className="muted">Run a sweep, or open a saved one, to see its gate report.</p>;
  }

  const thresholds = manifest?.thresholds ?? {};

  return (
    <div className="gate-report">
      <section className="gate-overview">
        <h4>Admissibility</h4>
        <p className="muted">
          A scenario is admissible when no gate fails it. Warned, marked and
          not-applicable all still count — only a failure excludes.
        </p>
        <dl className="sweep-stat-row">
          <div>
            <dt>completed</dt>
            <dd>{completed.length}</dd>
          </div>
          <div>
            <dt>admissible</dt>
            <dd>{completed.length - excluded.length}</dd>
          </div>
          <div>
            <dt>excluded by a gate</dt>
            <dd>{excluded.length}</dd>
          </div>
          <div>
            <dt>could not run</dt>
            <dd>{couldNotRun.length}</dd>
          </div>
        </dl>
        {manifest?.diagnosis ? (
          <p className="gate-card-alarm">{manifest.diagnosis}</p>
        ) : null}
      </section>

      {summaries.map((summary) => (
        <GateCard
          key={summary.gate}
          summary={summary}
          thresholds={thresholds}
          onSelect={selectScenario}
        />
      ))}

      {couldNotRun.length > 0 ? (
        <section className="gate-card">
          <header>
            <h4>Scenarios that could not run</h4>
            <div className="gate-tally">
              <span className="gate-fail">{couldNotRun.length} failed</span>
            </div>
          </header>
          <div className="gate-card-body">
            <p className="muted">
              These never reached the gates — the pipeline refused them, with the stage
              that refused. They are recorded rather than dropped so the table still
              enumerates the whole scenario space.
            </p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Scenario</th>
                  {AXIS_COLUMNS.map((axis) => (
                    <th key={axis}>{AXIS_LABELS[axis as AxisColumn]}</th>
                  ))}
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {couldNotRun.map((row) => (
                  <tr key={row.config_hash}>
                    <td>
                      <code>{row.config_hash.slice(0, 8)}</code>
                    </td>
                    {AXIS_COLUMNS.map((axis) => (
                      <td key={axis}>{String(row[axis] ?? "—").replace(/_/g, " ")}</td>
                    ))}
                    <td className="gate-fail">{row.error ?? "no reason recorded"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
