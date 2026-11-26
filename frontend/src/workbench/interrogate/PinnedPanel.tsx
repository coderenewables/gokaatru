import { useQueries } from "@tanstack/react-query";
import { useState } from "react";

import { AXIS_COLUMNS, AXIS_LABELS, METRIC_COLUMNS } from "../../types/sweep";
import { api, unwrap } from "../api";
import { loadScenario } from "../model/scenario";
import { useCampaign } from "../shell/context";
import { saveFile } from "./export";
import { formatMetric, metricLabel } from "./ScenariosPanel";
import { type SweepRow, metricValue, useInterrogate } from "./store";
import "./interrogate.css";

/** Every leaf of a configuration as a dotted path, so two runconfigs can be set against each other. */
export function flatten(value: unknown, prefix = ""): Record<string, string> {
  if (value === null || typeof value !== "object") return { [prefix]: JSON.stringify(value) };
  const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item] as const) : Object.entries(value);
  if (entries.length === 0) return { [prefix]: Array.isArray(value) ? "[]" : "{}" };
  return Object.assign({}, ...entries.map(([key, item]) => flatten(item, prefix ? `${prefix}.${key}` : key)));
}

/** The paths where two configurations differ, with each one's value; absent where one lacks it. */
export function differences(left: Record<string, string>, right: Record<string, string>): [string, string, string][] {
  const paths = [...new Set([...Object.keys(left), ...Object.keys(right)])].sort();
  return paths.filter((path) => left[path] !== right[path]).map((path) => [path, left[path] ?? "(absent)", right[path] ?? "(absent)"]);
}

const DIFFERENCE_LIMIT = 60;

/** Two pinned scenarios side by side (plan §3.3 "Interrogate"): their axes, metrics and gates,
 * and where their materialised configurations differ; either can be loaded into Model. */
export function PinnedPanel() {
  const { sessionId } = useCampaign();
  const sweepId = useInterrogate((state) => state.sweepId);
  const rows = useInterrogate((state) => state.rows);
  const pinned = useInterrogate((state) => state.pinned);
  const unpin = useInterrogate((state) => state.unpin);
  const [said, setSaid] = useState("");
  const chosen = pinned
    .map((hash) => rows.find((row) => row.config_hash === hash))
    .filter((row): row is SweepRow => row !== undefined);
  const configs = useQueries({
    queries: chosen.map((row) => ({
      queryKey: ["scenario-runconfig", sessionId, sweepId, row.config_hash],
      enabled: sweepId !== null,
      queryFn: async () =>
        unwrap(
          await api.GET("/api/sessions/{session_id}/sweep/{sweep_id}/scenarios/{config_hash}/runconfig", {
            params: { path: { session_id: sessionId, sweep_id: sweepId ?? "", config_hash: row.config_hash } },
          }),
        ),
    })),
  });

  if (chosen.length === 0) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Pin two scenarios in Scenarios to set them side by side.</p>
      </div>
    );
  }
  const label = (row: SweepRow) => row.config_hash.slice(0, 8);
  const differs = (values: unknown[]) => values.length === 2 && JSON.stringify(values[0]) !== JSON.stringify(values[1]);
  const lines: [string, (row: SweepRow) => unknown, (row: SweepRow) => string][] = [
    ...AXIS_COLUMNS.map((axis) => [AXIS_LABELS[axis], (row: SweepRow) => row[axis], (row: SweepRow) => String(row[axis] ?? "—")] as [string, (row: SweepRow) => unknown, (row: SweepRow) => string]),
    ...METRIC_COLUMNS.map((column) => [
      metricLabel(column),
      (row: SweepRow) => metricValue(row, column),
      (row: SweepRow) => formatMetric(column, metricValue(row, column)),
    ] as [string, (row: SweepRow) => unknown, (row: SweepRow) => string]),
    ["Admissible", (row) => row.admissible, (row) => (row.admissible ? "yes" : "no")],
    ["Failed gates", (row) => row.failed_gates, (row) => String(row.failed_gates || "none")],
  ];
  const both = configs.length === 2 && configs.every((query) => query.data);
  const diff = both ? differences(flatten(configs[0].data), flatten(configs[1].data)) : [];
  return (
    <div className="gk-panel gk-int-pinned" tabIndex={0}>
      <table className="gk-compare">
        <caption className="gk-muted">Pinned scenarios; a line where they differ is marked</caption>
        <thead>
          <tr>
            <th scope="col">Scenario</th>
            {chosen.map((row) => (
              <th key={row.config_hash} scope="col">
                {label(row)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map(([name, value, shown]) => {
            const different = differs(chosen.map(value));
            return (
              <tr key={name} data-differs={different || undefined}>
                <th scope="row">
                  {name}
                  {different && <span className="gk-sr"> (differs)</span>}
                </th>
                {chosen.map((row) => (
                  <td key={row.config_hash}>{shown(row)}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="gk-actions">
        {chosen.map((row, index) => (
          <span key={row.config_hash} className="gk-pinned-actions">
            <button
              type="button"
              className="gk-button"
              disabled={row.status !== "ok" || sweepId === null}
              onClick={() => {
                setSaid("");
                if (sweepId) loadScenario(sessionId, sweepId, row.config_hash).catch((error: Error) => setSaid(error.message));
              }}
            >
              Load {label(row)} into Model
            </button>
            <button
              type="button"
              className="gk-button"
              disabled={!configs[index]?.data}
              onClick={() =>
                saveFile(`${sweepId}-${row.config_hash}.runconfig.json`, `${JSON.stringify(configs[index].data, null, 2)}\n`, "application/json")
              }
            >
              Download {label(row)} configuration
            </button>
            <button type="button" className="gk-button" onClick={() => unpin(row.config_hash)}>
              Unpin {label(row)}
            </button>
          </span>
        ))}
      </div>
      {said && (
        <p role="alert" className="gk-warning">
          {said}
        </p>
      )}
      {chosen.length === 2 && (
        <>
          <h3>Where their configurations differ</h3>
          {configs.some((query) => query.isError) && <p className="gk-warning">A scenario's configuration could not be read.</p>}
          {both && diff.length === 0 && <p className="gk-muted">Their configurations are the same.</p>}
          {diff.length > 0 && (
            <table className="gk-compare gk-int-diff">
              <caption className="gk-muted">
                {diff.length > DIFFERENCE_LIMIT ? `The first ${DIFFERENCE_LIMIT} of ${diff.length} differing settings` : `${diff.length} differing settings`}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Setting</th>
                  <th scope="col">{label(chosen[0])}</th>
                  <th scope="col">{label(chosen[1])}</th>
                </tr>
              </thead>
              <tbody>
                {diff.slice(0, DIFFERENCE_LIMIT).map(([path, left, right]) => (
                  <tr key={path}>
                    <th scope="row">{path}</th>
                    <td>{left}</td>
                    <td>{right}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
