import { useQuery } from "@tanstack/react-query";

import type { Schemas } from "../../api/client";
import { AXIS_LABELS } from "../../types/sweep";
import { api, unwrap } from "../api";
import { useCampaign } from "../shell/context";
import { formatMetric, metricLabel } from "./ScenariosPanel";
import { useFilteredHashes, useInterrogate } from "./store";
import "./interrogate.css";

type Spread = Schemas["AnalyzeSweepSpreadResult"];

const axisLabel = (axis: string) => AXIS_LABELS[axis as keyof typeof AXIS_LABELS] ?? axis.replace(/_/g, " ");
const percent = (value: number | null | undefined) => (value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`);

/** How much each axis moves the metric over the scenarios the brushes keep (plan §3.3
 * "Interrogate"). The decomposition is the server's (POST /sweep/{id}/spread over the filtered
 * config hashes): the browser selects, it never computes the figure. */
export function SensitivityPanel() {
  const { sessionId } = useCampaign();
  const sweepId = useInterrogate((state) => state.sweepId);
  const metric = useInterrogate((state) => state.metric);
  const hashes = useFilteredHashes();
  const spread = useQuery({
    queryKey: ["spread", sessionId, sweepId, metric, hashes.join(",")],
    enabled: sweepId !== null && hashes.length > 0,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/sweep/{sweep_id}/spread", {
          params: { path: { session_id: sessionId, sweep_id: sweepId ?? "" } },
          body: { metric, config_hashes: hashes },
        }),
      ) as unknown as Spread,
  });

  if (sweepId === null) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Choose a sweep in Scenarios to see how much each axis moves the metric.</p>
      </div>
    );
  }
  if (hashes.length === 0) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>No scenario is left by the filters, so there is nothing to decompose.</p>
      </div>
    );
  }
  if (spread.isError) {
    return (
      <div className="gk-panel">
        <p role="alert" className="gk-warning">
          {spread.error.message}
        </p>
      </div>
    );
  }
  const result = spread.data;
  if (!result) return <div className="gk-panel gk-panel-empty"><p>Decomposing…</p></div>;
  const substitution = result.uncertainty_substitution;
  return (
    <div className="gk-panel gk-int-sensitivity" tabIndex={0}>
      <p className="gk-int-not-swept" role="note">
        {result.not_swept_statement}
      </p>
      <h2>
        {metricLabel(metric)} over {result.scenarios_analysed} scenarios
      </h2>
      <table className="gk-compare">
        <caption className="gk-muted">Share of the variance each axis explains alone, and the swing between its level means</caption>
        <thead>
          <tr>
            <th scope="col">Axis</th>
            <th scope="col">Levels</th>
            <th scope="col">Share</th>
            <th scope="col">Swing</th>
          </tr>
        </thead>
        <tbody>
          {result.contributions.map((entry) => (
            <tr key={entry.axis}>
              <th scope="row">{axisLabel(entry.axis)}</th>
              <td className="gk-num">{entry.levels}</td>
              <td>
                <span className="gk-share" aria-hidden="true">
                  <span style={{ width: `${Math.max(0, Math.min(1, entry.share ?? 0)) * 100}%` }} />
                </span>{" "}
                {percent(entry.share)}
              </td>
              <td className="gk-num">{formatMetric(metric, entry.swing ?? null)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.single_level_axes.length > 0 && (
        <p className="gk-muted">
          Not varied among these scenarios: {result.single_level_axes.map(axisLabel).join(", ")}. {result.single_level_note}
        </p>
      )}
      {result.contributions.some((entry) => Object.keys(entry.duplicate_levels).length > 0) && (
        <ul className="gk-muted" aria-label="Levels that picked the same sensors">
          {result.contributions.flatMap((entry) =>
            Object.entries(entry.duplicate_levels).map(([level, duplicate]) => (
              <li key={`${entry.axis}-${level}`}>
                same sensors: {level} = {duplicate.same_as.join(", ")} ({duplicate.scenarios} scenarios)
              </li>
            )),
          )}
        </ul>
      )}
      <p className="gk-muted">{result.basis_note}</p>
      <h3>Spread</h3>
      <dl className="gk-facts">
        {(["count", "min", "max", "mean", "std", "range"] as const).map((key) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{key === "count" ? result.spread.count : formatMetric(metric, result.spread[key] ?? null)}</dd>
          </div>
        ))}
      </dl>
      <h3>Uncertainty substitution</h3>
      {substitution.available && substitution.components ? (
        <table className="gk-compare">
          <caption className="gk-muted">{substitution.note}</caption>
          <thead>
            <tr>
              <th scope="col">Component</th>
              <th scope="col">Parametric</th>
              <th scope="col">From the sweep</th>
              <th scope="col">Applied</th>
              <th scope="col">Basis</th>
            </tr>
          </thead>
          <tbody>
            {substitution.components.map((component) => (
              <tr key={component.component}>
                <th scope="row">{component.component.replace(/_/g, " ")}</th>
                <td className="gk-num">{component.parametric_mean_pct?.toFixed(2) ?? "—"}%</td>
                <td className="gk-num">{component.empirical_pct?.toFixed(2) ?? "—"}%</td>
                <td className="gk-num">{component.applied_pct?.toFixed(2) ?? "—"}%</td>
                <td>{component.basis.replace(/_/g, " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="gk-muted">{substitution.reason ?? "Not available for these scenarios."}</p>
      )}
    </div>
  );
}
