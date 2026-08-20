// Sweep Designer — design doc §9.1.
//
// Axis cards plus the element that matters most on this screen: a live combinatorics
// counter showing leaves *and* prefix computations. A user who sees "960 leaves, 43 shear
// computations" understands the shape of the run in a way the leaf count alone does not
// convey, and it is what stops an accidental multi-hour launch.
//
// Levels this session cannot run are disabled **with their reason**. Applicability is a
// property of the data, not of the analyst's knowledge: a lidar has no boom redundancy,
// and letting someone select a level that will fail every leaf is worse than saying so.
import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";

import { RunButton } from "../common/RunButton";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import {
  SWEEP_PRESETS,
  requiresAnalystShear,
  unavailableSelections,
  useSweepStore,
  type SweepSelection,
} from "../../store/useSweepStore";
import { AXIS_LABELS, LTC_ALGORITHMS, type AxisLevel } from "../../types/sweep";

/** Suggested exponents for the single-height case, each labelled with where it comes from. */
const SHEAR_SUGGESTIONS: Array<{ value: number; label: string }> = [
  { value: 0.143, label: "0.143 — 1/7, neutral open land" },
  { value: 0.2, label: "0.20 — IEC 61400-1 onshore normal profile" },
];

const AXIS_HELP: Record<string, string> = {
  shearFitPolicies:
    "Which sensors the vertical profile is fitted on. A narrow, well-conditioned pair and a wide set answer different questions, and the disagreement between them is the point.",
  referencePolicies:
    "Which sensors the hub-height series is carried up from. Crossed against the fit set, so mismatched pairings — a narrow fit with a wide reference — are reachable.",
  shearModels:
    "How the profile is modelled and aggregated. Power law with a month-hour table is the common choice; the log law and a single site-wide exponent are the useful foils.",
  referenceSources:
    "Which long-term reanalysis the correction is made against. ERA5 and MERRA-2 are run as separate scenarios and their disagreement is read off the spread rather than blended away.",
  ltcAlgorithms:
    "The MCP estimator. Note that variance ratio is invariant to an affine rescaling of the reference, so it cannot see that kind of disagreement between sources — a small axis-C spread measured with it alone is not evidence the sources agree.",
};

interface AxisCardProps {
  title: string;
  help: string;
  levels: AxisLevel[];
  selected: string[];
  onToggle: (level: string) => void;
}

function AxisCard({ title, help, levels, selected, onToggle }: AxisCardProps) {
  const [showHelp, setShowHelp] = useState(false);
  return (
    <section className="sweep-axis-card">
      <header>
        <h4>{title}</h4>
        <button
          type="button"
          className="sweep-axis-help-toggle"
          aria-expanded={showHelp}
          onClick={() => setShowHelp((value) => !value)}
        >
          Why this matters
        </button>
      </header>
      {showHelp ? <p className="sweep-axis-help">{help}</p> : null}
      <ul className="sweep-level-list">
        {levels.map((level) => (
          <li key={level.name}>
            <label className={clsx("sweep-level", { unavailable: !level.available })}>
              <input
                type="checkbox"
                checked={selected.includes(level.name)}
                disabled={!level.available}
                onChange={() => onToggle(level.name)}
              />
              <span className="sweep-level-name">{level.name.replace(/_/g, " ")}</span>
              {level.resolved_columns && level.resolved_columns.length > 0 ? (
                <small className="sweep-level-resolved">
                  → {level.resolved_columns.join(", ")}
                </small>
              ) : null}
              {!level.available && level.reason ? (
                <small className="sweep-level-reason">{level.reason}</small>
              ) : null}
              {level.available && level.can_fit_shear === false ? (
                <small className="sweep-level-reason">
                  Resolves to one height — a shear exponent must be supplied below.
                </small>
              ) : null}
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SweepDesigner() {
  const apiBaseUrl = useWorkspaceStore((state) => state.apiBaseUrl);
  const session = useWorkspaceStore((state) => state.session);

  const axes = useSweepStore((state) => state.axes);
  const axesError = useSweepStore((state) => state.axesError);
  const selection = useSweepStore((state) => state.selection);
  const phase = useSweepStore((state) => state.phase);
  const loadAxes = useSweepStore((state) => state.loadAxes);
  const toggleLevel = useSweepStore((state) => state.toggleLevel);
  const applyPreset = useSweepStore((state) => state.applyPreset);
  const setSelection = useSweepStore((state) => state.setSelection);
  const estimate = useSweepStore((state) => state.estimate);
  const start = useSweepStore((state) => state.start);

  const [cost, setCost] = useState<{ leaf_count: number; prefix_count: number } | null>(null);
  const sessionId = session?.session_id ?? "";

  useEffect(() => {
    if (sessionId) void loadAxes(apiBaseUrl, sessionId);
  }, [apiBaseUrl, loadAxes, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    void estimate(apiBaseUrl, sessionId).then((result) => {
      if (!cancelled) setCost(result);
    });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, estimate, selection, sessionId]);

  const sensorLevels = axes?.sensor_policies ?? [];
  const needsShear = requiresAnalystShear(selection, axes);
  const blocked = unavailableSelections(selection, axes);

  const ltcLevels = useMemo<AxisLevel[]>(
    () => LTC_ALGORITHMS.map((name) => ({ name, available: true })),
    [],
  );

  const emptyAxes = (
    [
      ["shearFitPolicies", selection.shearFitPolicies],
      ["referencePolicies", selection.referencePolicies],
      ["shearModels", selection.shearModels],
      ["referenceSources", selection.referenceSources],
      ["ltcAlgorithms", selection.ltcAlgorithms],
    ] as Array<[keyof SweepSelection, string[]]>
  ).filter(([, levels]) => levels.length === 0);

  const canLaunch =
    Boolean(sessionId) &&
    phase !== "running" &&
    emptyAxes.length === 0 &&
    blocked.length === 0 &&
    (!needsShear || selection.analystShearAlpha != null);

  return (
    <div className="sweep-designer">
      {axesError ? (
        <p className="sweep-error">
          The engine could not read this session&apos;s axes: {axesError}. Load a timeseries,
          a data model and both reanalyses first.
        </p>
      ) : null}

      <section className="sweep-presets">
        <span>Preset</span>
        {Object.keys(SWEEP_PRESETS).map((name) => (
          <button key={name} type="button" onClick={() => applyPreset(name)}>
            {name}
          </button>
        ))}
        <small>
          Standard EYA ties the two sensor axes together; Exhaustive crosses them fully.
          Crossing is always available — it is simply not the default, because the leaf
          count is what constrains the run.
        </small>
      </section>

      <div className="sweep-axis-grid">
        <AxisCard
          title={AXIS_LABELS.shear_fit_policy}
          help={AXIS_HELP.shearFitPolicies}
          levels={sensorLevels}
          selected={selection.shearFitPolicies}
          onToggle={(level) => toggleLevel("shearFitPolicies", level)}
        />
        <AxisCard
          title={AXIS_LABELS.reference_policy}
          help={AXIS_HELP.referencePolicies}
          levels={sensorLevels}
          selected={selection.referencePolicies}
          onToggle={(level) => toggleLevel("referencePolicies", level)}
        />
        <AxisCard
          title={AXIS_LABELS.shear_model}
          help={AXIS_HELP.shearModels}
          levels={axes?.shear_models ?? []}
          selected={selection.shearModels}
          onToggle={(level) => toggleLevel("shearModels", level)}
        />
        <AxisCard
          title={AXIS_LABELS.reference_source}
          help={AXIS_HELP.referenceSources}
          levels={axes?.reference_sources ?? []}
          selected={selection.referenceSources}
          onToggle={(level) => toggleLevel("referenceSources", level)}
        />
        <AxisCard
          title={AXIS_LABELS.ltc_algorithm}
          help={AXIS_HELP.ltcAlgorithms}
          levels={ltcLevels}
          selected={selection.ltcAlgorithms}
          onToggle={(level) => toggleLevel("ltcAlgorithms", level)}
        />
      </div>

      {needsShear ? (
        <section className="sweep-shear-input">
          <h4>Shear exponent required</h4>
          <p>
            A selected shear-fit policy resolves to a single measurement height, and an
            exponent cannot be fitted from one height. Supply one — from a nearby reference
            mast, a mesoscale model, terrain-class tables, or the IEC default. The scenario
            will be marked as resting on an assumption rather than a measurement, and takes
            the larger assumed-shear uncertainty.
          </p>
          <div className="sweep-shear-row">
            <input
              type="number"
              step="0.01"
              min="0"
              max="0.5"
              placeholder="e.g. 0.20"
              value={selection.analystShearAlpha ?? ""}
              onChange={(event) =>
                setSelection({
                  analystShearAlpha:
                    event.target.value === "" ? null : Number(event.target.value),
                })
              }
            />
            {SHEAR_SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.value}
                type="button"
                onClick={() => setSelection({ analystShearAlpha: suggestion.value })}
              >
                {suggestion.label}
              </button>
            ))}
          </div>
          <small>
            No default is prefilled on purpose: a value tabbed past is how an assumption
            becomes invisible.
          </small>
        </section>
      ) : null}

      <footer className="sweep-cost-bar">
        <div className="sweep-cost-figures">
          <strong>{cost ? cost.leaf_count.toLocaleString() : "—"}</strong>
          <span>scenarios</span>
          <strong>{cost ? cost.prefix_count.toLocaleString() : "—"}</strong>
          <span>shear computations</span>
          {cost && selection.ltcAlgorithms.includes("xgboost") ? (
            <em className="sweep-cost-warning">
              XGBoost is the cost centre — {Math.round(cost.leaf_count / Math.max(1, selection.ltcAlgorithms.length)).toLocaleString()} of
              these leaves train a model.
            </em>
          ) : null}
        </div>
        <div className="sweep-cost-actions">
          {emptyAxes.length > 0 ? (
            <span className="sweep-blocked">Select at least one level on every axis.</span>
          ) : null}
          {blocked.length > 0 ? (
            <span className="sweep-blocked">
              Not available on this session: {blocked.join(", ")}
            </span>
          ) : null}
          {needsShear && selection.analystShearAlpha == null ? (
            <span className="sweep-blocked">Supply a shear exponent to continue.</span>
          ) : null}
          <RunButton
            label={phase === "running" ? "Running…" : "Run sweep"}
            disabled={!canLaunch}
            silent
            onClick={() => void start(apiBaseUrl, sessionId)}
          />
        </div>
      </footer>
    </div>
  );
}
