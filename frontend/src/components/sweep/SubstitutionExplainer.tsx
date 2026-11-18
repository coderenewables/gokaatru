// Explaining the uncertainty substitution rule — design doc §9.6.
//
// `max(parametric, empirical)` is a **conservatism rule, not an estimator**, and a number
// whose derivation is invisible is a number a reviewer cannot check. Three depths, as the
// design requires: the badge at the number, the reasoning behind a disclosure, and a
// warning when an axis was too thinly covered for its empirical estimate to mean anything.
//
// The numbers are the server's (`uncertainty_substitution` on the spread response). This
// file computed them itself until 2026-11-18, from the swing of the uncertainty figure
// rather than of the wind speed, and the server's totals never carried them (F9).
import { useState } from "react";
import clsx from "clsx";

import { AXIS_LABELS, type SubstitutedComponent } from "../../types/sweep";

export const COMPONENT_LABELS: Record<SubstitutedComponent["component"], string> = {
  mcp: "MCP model",
  vertical_extrapolation: "Vertical extrapolation",
  long_term_reference: "Long-term reference",
};

function pct(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

export function SubstitutionBadge({
  entry,
  minLevels,
}: {
  entry: SubstitutedComponent;
  minLevels: number;
}) {
  const badge =
    entry.basis === "added"
      ? "added"
      : entry.basis === "empirical"
        ? "empirical"
        : entry.basis === "not_resolved"
          ? "not resolved"
          : "parametric";
  return (
    <div className="substitution-row">
      <span className="substitution-name">{COMPONENT_LABELS[entry.component]}</span>
      <strong className="substitution-value">{pct(entry.applied_pct)}</strong>
      <span
        className={clsx("substitution-badge", {
          empirical: entry.basis === "empirical",
          additive: entry.basis === "added",
        })}
      >
        {badge}
      </span>
      <small className="substitution-detail">
        parametric {pct(entry.parametric_mean_pct)} · sweep spread {pct(entry.empirical_pct)}
      </small>
      {entry.axes_under_resolved.length > 0 ? (
        <small className="substitution-warning">
          {entry.axes_under_resolved.map((axis) => AXIS_LABELS[axis]).join(" and ")} covered
          fewer than {minLevels} levels, so{" "}
          {entry.axes_under_resolved.length === 1 ? "its" : "their"} spread was not used.
        </small>
      ) : null}
    </div>
  );
}

export function SubstitutionExplainer({ minLevels }: { minLevels: number }) {
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
            An axis&apos;s sweep spread is the sample standard deviation of the long-term mean
            speed across that axis&apos;s level means, as a percentage of the sweep&apos;s mean
            speed. A component measured by several axes combines their spreads in quadrature.
            An axis needs at least {minLevels} levels: across one or two levels the figure is a
            range, not a dispersion estimate.
          </p>
          <p>
            The parametric term and the sweep spread measure <strong>the same quantity</strong>,
            so adding them would double-count. In root-sum-square terms,{" "}
            <code>max(p, e)</code> is identical to <em>adding only the shortfall the
            parametric term does not already cover</em>:{" "}
            <code>√(p² + max(0, e² − p²)) ≡ max(p, e)</code>. It is applied per scenario,
            against that scenario&apos;s own parametric term.
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
            independent long-term references has no parametric counterpart in the model.
            With two reanalyses it cannot be estimated under the {minLevels}-level rule, so it
            stays out of the total until a third reference is in the sweep. Note that variance
            ratio is invariant to an affine rescaling of the reference, so a small reference
            spread measured with that estimator alone is not evidence the sources agree.
          </p>
        </div>
      ) : null}
    </section>
  );
}
