import { useQuery } from "@tanstack/react-query";

import { AXIS_LABELS } from "../../types/sweep";
import { api, unwrap } from "../api";
import { useCampaign } from "../shell/context";
import { type SweepRow, useFilteredRows, useInterrogate } from "./store";
import "./interrogate.css";

const STATUSES = ["pass", "warn", "marked", "fail", "not_applicable"] as const;

/** Each gate's verdicts over the scenarios in view, counted from the rows' own gate columns. */
export function gateTally(rows: SweepRow[]): { gate: string; counts: Record<string, number> }[] {
  const gates = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (key.startsWith("gate_") && !key.endsWith("_value")) gates.add(key.slice("gate_".length));
    }
  }
  return [...gates].sort().map((gate) => {
    const counts: Record<string, number> = {};
    for (const row of rows) {
      const status = row[`gate_${gate}`];
      if (typeof status === "string") counts[status] = (counts[status] ?? 0) + 1;
    }
    return { gate, counts };
  });
}

/** Which scenarios the admissibility gates let through, and which axes they left with one
 * level: "0% of the spread" can mean a choice that was never varied among the admissible
 * scenarios, not one that does not matter (get_sweep_summary). */
export function GatesPanel() {
  const { sessionId } = useCampaign();
  const sweepId = useInterrogate((state) => state.sweepId);
  const rows = useFilteredRows();
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
  const tally = gateTally(rows);
  return (
    <div className="gk-panel gk-int-gates" tabIndex={0}>
      <table className="gk-compare">
        <caption className="gk-muted">Gate verdicts over the {rows.length} scenarios in view</caption>
        <thead>
          <tr>
            <th scope="col">Gate</th>
            {STATUSES.map((status) => (
              <th key={status} scope="col">
                {status.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tally.map(({ gate, counts }) => (
            <tr key={gate}>
              <th scope="row">{gate.replace(/_/g, " ")}</th>
              {STATUSES.map((status) => (
                <td key={status} className="gk-num">
                  {counts[status] ?? 0}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
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
