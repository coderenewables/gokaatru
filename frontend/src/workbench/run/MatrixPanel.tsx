import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, unwrap } from "../api";
import { useCampaign } from "../shell/context";
import {
  AXES,
  PRESETS,
  axisLevels,
  emptyAxes,
  requestBody,
  requiresAnalystShear,
  type AxisLevel,
  type SweepAxes,
} from "./design";
import { useDesign, useRun } from "./store";
import "./run.css";

interface LeafAxes {
  shear_fit_policy: string;
  reference_policy: string;
  shear_model: string;
  reference_source: string;
  ltc_algorithm: string;
}

export interface Estimate {
  counts: { planned: number; prefixes: number; would_run: number; duplicates: number; unavailable: number };
  duplicates: Array<LeafAxes & { same_as: LeafAxes }>;
  unavailable: Array<LeafAxes & { stage: string; reason: string }>;
  duplicates_basis: string;
  refusals_basis: string;
}

/** How long the design stands still before it is priced: a tick per click would ask the
 * server to resolve every leaf each time. */
export const ESTIMATE_DEBOUNCE_MS = 250;

const SUGGESTED_ALPHA = [
  { value: 0.143, label: "0.143 (1/7, neutral open land)" },
  { value: 0.2, label: "0.20 (IEC 61400-1 onshore normal profile)" },
];

const leaf = (axes: LeafAxes) =>
  `${axes.shear_fit_policy} / ${axes.reference_policy} / ${axes.shear_model} / ${axes.reference_source} / ${axes.ltc_algorithm}`;

function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

function Level({ axis, level, checked }: { axis: (typeof AXES)[number]["key"]; level: AxisLevel; checked: boolean }) {
  const toggle = useDesign((state) => state.toggle);
  const note = !level.available
    ? level.reason
    : level.can_fit_shear === false
      ? "Resolves to one height: a shear exponent must be supplied below."
      : null;
  return (
    <li className="gk-level">
      <label className="gk-check">
        <input type="checkbox" checked={checked} disabled={!level.available} onChange={() => toggle(axis, level.name)} />
        <span>{level.name.replace(/_/g, " ")}</span>
      </label>
      {level.available && level.resolved_columns && level.resolved_columns.length > 0 ? (
        <small className="gk-level-resolved">{level.resolved_columns.join(", ")}</small>
      ) : null}
      {note ? <small className="gk-level-reason">{note}</small> : null}
    </li>
  );
}

function EstimateSummary({ estimate }: { estimate: Estimate }) {
  const { counts } = estimate;
  return (
    <div className="gk-estimate">
      <dl className="gk-estimate-counts" aria-label="What the design would run">
        <div>
          <dt>Planned scenarios</dt>
          <dd>{counts.planned.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Shear tables</dt>
          <dd>{counts.prefixes.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Would run</dt>
          <dd>{counts.would_run.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Duplicates</dt>
          <dd>{counts.duplicates.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Unavailable</dt>
          <dd>{counts.unavailable.toLocaleString()}</dd>
        </div>
      </dl>
      {counts.duplicates > 0 ? (
        <details>
          <summary>{counts.duplicates.toLocaleString()} skipped as duplicates</summary>
          <p className="gk-basis">{estimate.duplicates_basis}</p>
          <ul className="gk-leaves">
            {estimate.duplicates.map((entry) => (
              <li key={leaf(entry)}>
                {leaf(entry)} <span className="gk-leaf-note">repeats {leaf(entry.same_as)}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {counts.unavailable > 0 ? (
        <details>
          <summary>{counts.unavailable.toLocaleString()} refused</summary>
          <p className="gk-basis">{estimate.refusals_basis}</p>
          <ul className="gk-leaves">
            {estimate.unavailable.map((entry) => (
              <li key={leaf(entry)}>
                {leaf(entry)}{" "}
                <span className="gk-leaf-note">
                  {entry.stage}: {entry.reason}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

/** The matrix sweep designer (decisions/0015.6): the five axes by their levels, priced live by
 * the server, which counts the duplicates and refusals with the code the run uses. */
export function MatrixPanel() {
  const { sessionId } = useCampaign();
  const design = useDesign((state) => state.design);
  const dropped = useDesign((state) => state.dropped);
  const unchecked = useDesign((state) => state.unchecked);
  const { applyPreset, retain, setHubHeight, setAnalystShearAlpha } = useDesign.getState();
  const running = useRun((state) => state.run.phase === "running");
  const start = useRun((state) => state.start);

  const axesQuery = useQuery({
    queryKey: ["sweep-axes", sessionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/sessions/{session_id}/sweep/axes", { params: { path: { session_id: sessionId } } })) as unknown as SweepAxes,
  });
  const axes = axesQuery.data ?? null;
  useEffect(() => {
    if (axes && unchecked) retain(axes);
  }, [axes, unchecked, retain]);

  const body = requestBody(design);
  const empty = emptyAxes(design);
  const needsShear = requiresAnalystShear(design, axes);
  const priced = useDebounced(JSON.stringify(body), ESTIMATE_DEBOUNCE_MS);
  const estimate = useQuery({
    queryKey: ["sweep-estimate", sessionId, priced],
    enabled: axes !== null && empty.length === 0,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/sweep/estimate", {
          params: { path: { session_id: sessionId } },
          body: JSON.parse(priced),
        }),
      ) as unknown as Estimate,
  });
  const current = estimate.data && priced === JSON.stringify(body) ? estimate.data : null;

  const blockers = [
    empty.length > 0 ? "Tick at least one level on every axis." : null,
    needsShear && design.analyst_shear_alpha === null ? "Supply a shear exponent to continue." : null,
    current && current.counts.would_run === 0 ? "Nothing in this design would run." : null,
  ].filter((text): text is string => text !== null);
  const canRun = axes !== null && !running && blockers.length === 0 && current !== null;

  if (axesQuery.isError) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>
          The engine could not read this campaign&apos;s axes: {axesQuery.error.message}. Load records, a data model and both
          reanalyses first.
        </p>
      </div>
    );
  }

  return (
    <div className="gk-panel gk-matrix">
      <div className="gk-presets" role="group" aria-label="Presets">
        {Object.keys(PRESETS).map((name) => (
          <button key={name} type="button" className="gk-button" onClick={() => applyPreset(name, axes)}>
            {name}
          </button>
        ))}
      </div>
      {dropped.length > 0 ? (
        <p className="gk-notice" role="status">
          Left out, not available on this campaign: {dropped.join(", ")}.
        </p>
      ) : null}

      {AXES.map((axis) => (
        <fieldset key={axis.key} className="gk-axis">
          <legend>{axis.label}</legend>
          <ul className="gk-levels">
            {axisLevels(axis.key, axes).map((level) => (
              <Level key={level.name} axis={axis.key} level={level} checked={design[axis.key].includes(level.name)} />
            ))}
          </ul>
        </fieldset>
      ))}

      <div className="gk-inline-form">
        <label className="gk-field">
          Hub height (m)
          <input
            type="number"
            step="1"
            min="0"
            placeholder="the campaign's"
            value={design.hub_height_m ?? ""}
            onChange={(event) => setHubHeight(event.target.value === "" ? null : Number(event.target.value))}
          />
        </label>
        <label className="gk-field">
          Analyst shear exponent{needsShear ? " (required)" : ""}
          <input
            type="number"
            step="0.01"
            min="0"
            max="0.5"
            placeholder="none"
            value={design.analyst_shear_alpha ?? ""}
            onChange={(event) => setAnalystShearAlpha(event.target.value === "" ? null : Number(event.target.value))}
          />
        </label>
        {SUGGESTED_ALPHA.map((suggestion) => (
          <button key={suggestion.value} type="button" className="gk-button" onClick={() => setAnalystShearAlpha(suggestion.value)}>
            {suggestion.label}
          </button>
        ))}
      </div>
      {needsShear ? (
        <p className="gk-basis">
          A chosen shear-fit policy resolves to a single height, and an exponent cannot be fitted from one. No default is filled
          in, so an assumption is never one that was tabbed past; the scenario is marked as resting on it.
        </p>
      ) : null}

      <section aria-label="Estimate">
        {estimate.isError ? <p className="gk-form-error">{estimate.error.message}</p> : null}
        {current ? <EstimateSummary estimate={current} /> : <p className="gk-basis">{empty.length > 0 ? "" : "Pricing the design..."}</p>}
      </section>

      <div className="gk-actions">
        <button
          type="button"
          className="gk-button gk-button-primary"
          disabled={!canRun}
          onClick={() => void start(sessionId, body)}
        >
          {running ? "Running..." : "Run sweep"}
        </button>
        {blockers.map((text) => (
          <span key={text} className="gk-warning">
            {text}
          </span>
        ))}
      </div>
    </div>
  );
}
