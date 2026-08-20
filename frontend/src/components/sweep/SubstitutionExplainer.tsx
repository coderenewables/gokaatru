// Explaining the uncertainty substitution rule — design doc §9.6.
//
// `max(parametric, empirical)` is a **conservatism rule, not an estimator**, and a number
// whose derivation is invisible is a number a reviewer cannot check. Three depths, as the
// design requires: the badge at the number, the reasoning behind a disclosure, and a
// warning when an axis was too thinly covered for its empirical estimate to mean anything.
import { useState } from "react";
import clsx from "clsx";

import type { AxisContribution } from "../../lib/sweepAnalysis";
import { AXIS_LABELS, type AxisColumn } from "../../types/sweep";

/** Below this many levels an axis spread is under-resolved and cannot displace anything. */
export const MIN_LEVELS_FOR_EMPIRICAL = 3;

export interface SubstitutionRow {
  component: string;
  /** Which axes measure this component empirically. */
  axes: AxisColumn[];
  parametric: number | null;
  empirical: number | null;
  /** Whether the empirical estimate rests on enough axis coverage to be trusted. */
  underResolved: boolean;
  /** True when this term has no parametric counterpart and is a genuine addition. */
  additive?: boolean;
}

export function SubstitutionBadge({ row }: { row: SubstitutionRow }) {
  const empiricalWins =
    row.empirical != null && (row.parametric == null || row.empirical > row.parametric);
  const applied = row.additive
    ? row.empirical
    : Math.max(row.parametric ?? 0, row.empirical ?? 0);
  return (
    <div className="substitution-row">
      <span className="substitution-name">{row.component}</span>
      <strong className="substitution-value">
        {applied == null ? "—" : `${applied.toFixed(2)}%`}
      </strong>
      <span
        className={clsx("substitution-badge", {
          empirical: empiricalWins && !row.additive,
          additive: row.additive,
        })}
      >
        {row.additive ? "added" : empiricalWins ? "empirical" : "parametric"}
      </span>
      <small className="substitution-detail">
        parametric {row.parametric == null ? "—" : `${row.parametric.toFixed(2)}%`} · sweep
        spread {row.empirical == null ? "—" : `${row.empirical.toFixed(2)}%`}
      </small>
      {row.underResolved ? (
        <small className="substitution-warning">
          {row.axes.map((axis) => AXIS_LABELS[axis]).join(" and ")} covered fewer than{" "}
          {MIN_LEVELS_FOR_EMPIRICAL} levels — the empirical spread is under-resolved and the
          parametric term was kept.
        </small>
      ) : null}
    </div>
  );
}

export function SubstitutionExplainer() {
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="substitution-explainer">
      <button
        type="button"
        className="disclosure-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Hide" : "How this total is combined"}
      </button>
      {expanded ? (
        <div className="substitution-explanation">
          <p>
            The parametric term and the sweep spread measure <strong>the same quantity</strong>,
            so adding them would double-count. In root-sum-square terms,{" "}
            <code>max(p, e)</code> is identical to <em>adding only the shortfall the
            parametric term does not already cover</em>:{" "}
            <code>√(p² + max(0, e² − p²)) ≡ max(p, e)</code>.
          </p>
          <p>
            The rule is one-sided on purpose. An empirical spread can be too small because
            the sweep was narrow, which under-reports uncertainty; that is the dangerous
            direction, and taking the larger of the two guards it.
          </p>
          <p className="substitution-caveat">
            Two consequences, stated rather than buried: the engine can never report{" "}
            <strong>less</strong> uncertainty than the parametric model alone, and{" "}
            <code>max()</code> is biased upward. This is a deliberate conservative choice,
            not a neutral estimate. Because a wider sweep can only hold a component flat or
            raise it, a narrow sweep produces a tighter number — so the axis coverage is
            shown beside the total.
          </p>
          <p className="substitution-caveat">
            One term is genuinely additive rather than substituted: disagreement between
            two independent reanalyses has no parametric counterpart in the model. Note
            that variance ratio is invariant to an affine rescaling of the reference, so a
            small reference spread measured with that estimator alone is not evidence the
            sources agree.
          </p>
        </div>
      ) : null}
    </section>
  );
}

/** Map axis contributions onto the uncertainty components they measure empirically. */
export function buildSubstitutionRows(
  contributions: AxisContribution[],
  components: Record<string, number | null>,
): SubstitutionRow[] {
  const byAxis = new Map(contributions.map((entry) => [entry.axis, entry]));
  // Axis swing is expressed in metric units; on a percentage metric it is already a
  // percentage, which is why the substitution is only shown for the uncertainty metrics.
  const swingPct = (axes: AxisColumn[]): { value: number | null; levels: number } => {
    const entries = axes.map((axis) => byAxis.get(axis)).filter(Boolean) as AxisContribution[];
    if (entries.length === 0) return { value: null, levels: 0 };
    const combined = Math.sqrt(
      entries.reduce((total, entry) => total + entry.swing ** 2, 0),
    );
    return { value: combined, levels: Math.max(...entries.map((entry) => entry.levels)) };
  };

  const definitions: Array<{
    component: string;
    axes: AxisColumn[];
    parametricKey: string | null;
    additive?: boolean;
  }> = [
    { component: "MCP model", axes: ["ltc_algorithm"], parametricKey: "u_mcp_pct" },
    {
      component: "Vertical extrapolation",
      axes: ["shear_fit_policy", "reference_policy", "shear_model"],
      parametricKey: "u_vertical_pct",
    },
    {
      component: "Long-term reference",
      axes: ["reference_source"],
      parametricKey: null,
      additive: true,
    },
  ];

  return definitions.map((definition) => {
    const { value, levels } = swingPct(definition.axes);
    const underResolved = levels > 0 && levels < MIN_LEVELS_FOR_EMPIRICAL;
    return {
      component: definition.component,
      axes: definition.axes,
      parametric: definition.parametricKey ? (components[definition.parametricKey] ?? null) : null,
      empirical: underResolved ? null : value,
      underResolved,
      additive: definition.additive,
    };
  });
}
