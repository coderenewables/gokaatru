import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AXIS_COLUMNS, AXIS_LABELS, GATE_META, GATE_STATUS_MEANING, type AxisColumn, type GateStatus } from "../../types/sweep";
import { api, unwrap } from "../api";
import { useCampaign } from "../shell/context";
import { type SweepRow, useFilteredRows, useInterrogate } from "./store";
import { useOpenSweep } from "./useSweeps";
import "./interrogate.css";

// What was checked, what each check found and what it excluded. The scenario table says
// whether a scenario was excluded; a reader whose spread came back thinner than expected needs
// which check did it, on what number, against what threshold, so the campaign and the threshold
// can be told apart. Every gate is listed, including those nothing tripped.

export const STATUS_ORDER: GateStatus[] = ["fail", "warn", "marked", "pass", "not_applicable"];

export interface GateSummary {
  gate: string;
  counts: Record<GateStatus, number>;
  failed: SweepRow[];
  warned: SweepRow[];
  marked: SweepRow[];
  /** The measured value's range over the scenarios where the gate had something to measure. */
  valueRange: { min: number; max: number } | null;
  /** The gate excluded every completed scenario: a measurement of the threshold, not the site. */
  excludedEverything: boolean;
}

export function gateValue(row: SweepRow, gate: string): number | null {
  const value = row[`gate_${gate}_value`];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Every gate over the completed rows, found from the rows' own ``gate_*`` columns so a gate
 * added on the server appears without a change here; the gates that excluded something first.
 * A scenario that never ran reached no gate and is not counted. */
export function summariseGates(rows: readonly SweepRow[]): GateSummary[] {
  const completed = rows.filter((row) => row.status === "ok");
  const names = new Set<string>();
  for (const row of completed) {
    for (const key of Object.keys(row)) {
      if (key.startsWith("gate_") && !key.endsWith("_value")) names.add(key.slice("gate_".length));
    }
  }
  return [...names]
    .map((gate) => {
      const counts: Record<GateStatus, number> = { pass: 0, warn: 0, fail: 0, not_applicable: 0, marked: 0 };
      const failed: SweepRow[] = [];
      const warned: SweepRow[] = [];
      const marked: SweepRow[] = [];
      const values: number[] = [];
      for (const row of completed) {
        const status = row[`gate_${gate}`];
        if (typeof status !== "string" || !(status in counts)) continue;
        counts[status as GateStatus] += 1;
        if (status === "fail") failed.push(row);
        if (status === "warn") warned.push(row);
        if (status === "marked") marked.push(row);
        const value = gateValue(row, gate);
        if (value !== null) values.push(value);
      }
      return {
        gate,
        counts,
        failed,
        warned,
        marked,
        valueRange: values.length ? { min: Math.min(...values), max: Math.max(...values) } : null,
        excludedEverything: completed.length > 0 && counts.fail === completed.length,
      };
    })
    .sort((a, b) => b.counts.fail - a.counts.fail || b.counts.warn - a.counts.warn || a.gate.localeCompare(b.gate));
}

function formatValue(value: number | null): string {
  if (value === null) return "—";
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 1) return value.toFixed(3);
  return value.toFixed(4);
}

const labelOf = (gate: string) => GATE_META[gate]?.label ?? gate.replace(/_/g, " ");
const plural = (count: number) => `${count} scenario${count === 1 ? "" : "s"}`;

/** The scenarios behind one verdict, drawn only once opened: a large sweep can exclude
 * thousands. */
function Scenarios({ gate, rows, title }: { gate: string; rows: SweepRow[]; title: string }) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{title}</summary>
      {open && (
        <table className="gk-compare gk-int-table">
          <caption className="gk-muted">{title}, with the gate&apos;s measured value</caption>
          <thead>
            <tr>
              <th scope="col">Scenario</th>
              {AXIS_COLUMNS.map((axis) => (
                <th key={axis} scope="col">{AXIS_LABELS[axis as AxisColumn]}</th>
              ))}
              <th scope="col">Measured</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.config_hash}>
                <th scope="row"><code>{row.config_hash.slice(0, 8)}</code></th>
                {AXIS_COLUMNS.map((axis) => (
                  <td key={axis}>{String(row[axis] ?? "—")}</td>
                ))}
                <td className="gk-num">{formatValue(gateValue(row, gate))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

function GateSection({ summary, thresholds }: { summary: GateSummary; thresholds: Record<string, number> }) {
  const meta = GATE_META[summary.gate];
  const id = `gk-gate-${summary.gate}`;
  const tripped = summary.counts.fail + summary.counts.warn + summary.counts.marked;
  return (
    <section className="gk-gate" aria-labelledby={id} data-excluding={summary.counts.fail > 0 || undefined}>
      <h3 id={id}>{labelOf(summary.gate)}</h3>
      {summary.excludedEverything && (
        <p className="gk-warning" role="note">
          This gate excluded every completed scenario. That measures the threshold rather than the site: check the
          observed range against the threshold before widening the sweep.
        </p>
      )}
      {meta ? (
        <>
          <p>{meta.measures}</p>
          <p className="gk-muted">Applies to: {meta.appliesTo}</p>
        </>
      ) : (
        <p className="gk-muted">No description is registered for this gate.</p>
      )}
      <dl className="gk-pairs" aria-label={`${labelOf(summary.gate)} thresholds and observed range`}>
        {(meta?.thresholdKeys ?? []).map((key) => (
          <div key={key}>
            <dt>{key.replace(/_/g, " ")}</dt>
            <dd>{thresholds[key] ?? "not recorded"}</dd>
          </div>
        ))}
        <div>
          <dt>observed range</dt>
          <dd>{summary.valueRange ? `${formatValue(summary.valueRange.min)} to ${formatValue(summary.valueRange.max)}` : "nothing measured"}</dd>
        </div>
      </dl>
      <Scenarios gate={summary.gate} rows={summary.failed} title={`Excluded ${plural(summary.counts.fail)}`} />
      <Scenarios gate={summary.gate} rows={summary.warned} title={`Flagged ${plural(summary.counts.warn)}, still counted in every statistic`} />
      <Scenarios gate={summary.gate} rows={summary.marked} title={`Marked ${plural(summary.counts.marked)}, not a defect`} />
      {tripped === 0 && <p className="gk-muted">Nothing tripped this gate.</p>}
    </section>
  );
}

/** Which scenarios the admissibility gates let through and why, over the scenarios the other
 * filters keep, admissible or not; and which axes they left with one level: "0% of the spread"
 * can mean a choice never varied among the admissible scenarios, not one that does not matter
 * (get_sweep_summary). */
export function GatesPanel() {
  const { sessionId } = useCampaign();
  const sweepId = useInterrogate((state) => state.sweepId);
  const open = useOpenSweep();
  const rows = useFilteredRows("admissibility");
  const summary = useQuery({
    queryKey: ["sweep-summary", sessionId, sweepId],
    enabled: sweepId !== null,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/get_sweep_summary", {
          params: { path: { session_id: sessionId } },
          body: { sweep_id: sweepId ?? "" },
        }),
      ),
  });
  if (sweepId === null) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Choose a sweep in Scenarios to see which scenarios the gates let through.</p>
      </div>
    );
  }
  const manifest = open.data?.manifest;
  const thresholds = manifest?.thresholds ?? {};
  const completed = rows.filter((row) => row.status === "ok");
  const excluded = completed.filter((row) => !row.admissible);
  const couldNotRun = rows.filter((row) => row.status !== "ok");
  const gates = summariseGates(rows);
  return (
    <div className="gk-panel gk-int-gates" tabIndex={0}>
      <h2>Admissibility over the {plural(rows.length)} the filters keep, admissible or not</h2>
      <p className="gk-muted">A scenario is admissible when no gate fails it. Warned, marked and not applicable all still count.</p>
      <dl className="gk-pairs" aria-label="Admissibility counts">
        <div><dt>Completed</dt><dd>{completed.length}</dd></div>
        <div><dt>Admissible</dt><dd>{completed.length - excluded.length}</dd></div>
        <div><dt>Excluded by a gate</dt><dd>{excluded.length}</dd></div>
        <div><dt>Could not run</dt><dd>{couldNotRun.length}</dd></div>
      </dl>
      {manifest?.diagnosis && <p className="gk-warning" role="note">{manifest.diagnosis}</p>}

      <table className="gk-compare">
        <caption className="gk-muted">Gate verdicts over the {plural(completed.length)} completed</caption>
        <thead>
          <tr>
            <th scope="col">Gate</th>
            {STATUS_ORDER.map((status) => (
              <th key={status} scope="col">{status.replace(/_/g, " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {gates.map(({ gate, counts }) => (
            <tr key={gate}>
              <th scope="row">{labelOf(gate)}</th>
              {STATUS_ORDER.map((status) => (
                <td key={status} className="gk-num">{counts[status]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary>What each verdict means</summary>
        <dl className="gk-pairs" aria-label="What each verdict means">
          {STATUS_ORDER.map((status) => (
            <div key={status}>
              <dt>{status.replace(/_/g, " ")}</dt>
              <dd>{GATE_STATUS_MEANING[status]}</dd>
            </div>
          ))}
        </dl>
      </details>

      {gates.map((gate) => (
        <GateSection key={gate.gate} summary={gate} thresholds={thresholds} />
      ))}

      {couldNotRun.length > 0 && (
        <section className="gk-gate" aria-labelledby="gk-gate-could-not-run">
          <h3 id="gk-gate-could-not-run">Could not run: {plural(couldNotRun.length)}</h3>
          <p className="gk-muted">
            These reached no gate: the pipeline refused them, with the reason it gave. They are recorded rather than dropped,
            so the table still enumerates the whole design.
          </p>
          <table className="gk-compare gk-int-table">
            <caption className="gk-muted">Scenarios the pipeline refused</caption>
            <thead>
              <tr>
                <th scope="col">Scenario</th>
                {AXIS_COLUMNS.map((axis) => (
                  <th key={axis} scope="col">{AXIS_LABELS[axis as AxisColumn]}</th>
                ))}
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {couldNotRun.map((row) => (
                <tr key={row.config_hash}>
                  <th scope="row"><code>{row.config_hash.slice(0, 8)}</code></th>
                  {AXIS_COLUMNS.map((axis) => (
                    <td key={axis}>{String(row[axis] ?? "—")}</td>
                  ))}
                  <td>{typeof row.error === "string" ? row.error : "no reason recorded"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {summary.isError && (
        <p role="alert" className="gk-warning">
          {summary.error.message}
        </p>
      )}
      {summary.data && (
        <>
          <h3>Axes over the whole sweep</h3>
          <table className="gk-compare">
            <caption className="gk-muted">
              {summary.data.scenarios_admissible} of {summary.data.scenarios_total} scenarios admissible
              {summary.data.engine_version ? `, engine ${summary.data.engine_version}` : ", engine not recorded"}
            </caption>
            <thead>
              <tr>
                <th scope="col">Axis</th>
                <th scope="col">Designed</th>
                <th scope="col">Admissible</th>
                <th scope="col">Same sensors</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.data.axes).map(([axis, entry]) => (
                <tr key={axis} data-collapsed={entry.collapsed_to_one_level || undefined}>
                  <th scope="row">{AXIS_LABELS[axis as keyof typeof AXIS_LABELS] ?? axis}</th>
                  <td>{entry.levels_designed.join(", ")}</td>
                  <td>
                    {entry.levels_admissible.join(", ") || "none"}
                    {entry.collapsed_to_one_level ? " (one level: not varied)" : ""}
                  </td>
                  <td>
                    {Object.entries(entry.duplicate_levels)
                      .map(([level, duplicate]) => `${level} = ${duplicate.same_as.join(", ")}`)
                      .join("; ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="gk-muted">{summary.data.note}</p>
          <p className="gk-muted">{summary.data.duplicate_note}</p>
        </>
      )}
    </div>
  );
}
