// The sweep design (decisions/0015.6): which levels of the five axes a sweep crosses. Pure
// logic, kept apart from the store and the panels so it is tested without either.

export const AXES = [
  { key: "shear_fit_policies", label: "Shear-fit sensors (A1)" },
  { key: "reference_policies", label: "Extrapolation reference (A2)" },
  { key: "shear_models", label: "Vertical profile (B)" },
  { key: "reference_sources", label: "Long-term reference (C)" },
  { key: "ltc_algorithms", label: "LTC method (D)" },
] as const;

export type AxisKey = (typeof AXES)[number]["key"];

/** The MCP estimators the engine can run; mirrors `LTC_ALGORITHMS` on the server. */
export const LTC_ALGORITHMS = [
  "variance_ratio",
  "linear_least_squares",
  "total_least_squares",
  "speedsort",
  "xgboost",
] as const;

export interface SweepDesign {
  shear_fit_policies: string[];
  reference_policies: string[];
  shear_models: string[];
  reference_sources: string[];
  ltc_algorithms: string[];
  hub_height_m: number | null;
  /** Required when a shear-fit policy resolves to fewer than two heights. */
  analyst_shear_alpha: number | null;
}

/** The body of POST .../sweep/estimate and .../sweep/run/stream. */
export interface SweepRequest {
  shear_fit_policies: string[];
  reference_policies: string[];
  shear_models: string[];
  reference_sources: string[];
  ltc_algorithms: string[];
  hub_height_m?: number | null;
  analyst_shear_alpha?: number | null;
  thresholds?: Record<string, number> | null;
}

export interface AxisLevel {
  name: string;
  available: boolean;
  reason?: string | null;
  resolved_columns?: string[];
  can_fit_shear?: boolean;
}

export interface SweepAxes {
  sensor_policies: AxisLevel[];
  shear_models: AxisLevel[];
  reference_sources: AxisLevel[];
}

export const DEFAULT_DESIGN: SweepDesign = {
  shear_fit_policies: ["nearest_2"],
  reference_policies: ["nearest_2"],
  shear_models: ["power_law_mean"],
  reference_sources: ["era5", "merra2"],
  ltc_algorithms: ["variance_ratio", "linear_least_squares"],
  hub_height_m: null,
  analyst_shear_alpha: null,
};

/** Standard EYA ties the two sensor axes together; Exhaustive crosses them fully. Crossing is
 * always available and is not the default because the leaf count is what constrains a run. */
export const PRESETS: Record<string, Partial<SweepDesign>> = {
  "Quick look": {
    shear_fit_policies: ["nearest_2"],
    reference_policies: ["nearest_2"],
    shear_models: ["power_law_mean"],
    reference_sources: ["era5"],
    ltc_algorithms: ["variance_ratio"],
  },
  "Standard EYA": {
    shear_fit_policies: ["nearest_2", "widest_lever"],
    reference_policies: ["nearest_2", "widest_lever"],
    shear_models: ["power_law_mean", "power_law_momm"],
    reference_sources: ["era5", "merra2"],
    ltc_algorithms: ["variance_ratio", "linear_least_squares", "total_least_squares"],
  },
  Exhaustive: {
    shear_fit_policies: ["nearest_2", "availability_90", "redundant_boom", "widest_lever"],
    reference_policies: ["nearest_2", "availability_90", "redundant_boom", "widest_lever"],
    shear_models: ["power_law_mean", "power_law_median", "power_law_momm", "power_law_constant", "log_law_mean"],
    reference_sources: ["era5", "merra2"],
    ltc_algorithms: [...LTC_ALGORITHMS],
  },
};

/** The levels each axis offers: the session's for sensors, models and sources, the engine's
 * list for the LTC method. */
export function axisLevels(key: AxisKey, axes: SweepAxes | null): AxisLevel[] {
  switch (key) {
    case "shear_fit_policies":
    case "reference_policies":
      return axes?.sensor_policies ?? [];
    case "shear_models":
      return axes?.shear_models ?? [];
    case "reference_sources":
      return axes?.reference_sources ?? [];
    case "ltc_algorithms":
      return LTC_ALGORITHMS.map((name) => ({ name, available: true }));
  }
}

const names = (levels: AxisLevel[]) => new Set(levels.filter((level) => level.available).map((level) => level.name));

/** Intersect a design with what this session can run, and say what was dropped: a preset names
 * levels unconditionally, and a level selected but disabled is a box the analyst cannot untick.
 * A silently narrowed Exhaustive is not exhaustive, so the dropped names are returned. */
export function retainAvailable(design: SweepDesign, axes: SweepAxes | null): { design: SweepDesign; dropped: string[] } {
  if (!axes) return { design, dropped: [] };
  const sensors = names(axes.sensor_policies);
  const models = names(axes.shear_models);
  const sources = names(axes.reference_sources);
  const dropped = new Set<string>();
  const keep = (levels: string[], allowed: Set<string>) =>
    levels.filter((name) => {
      if (allowed.has(name)) return true;
      dropped.add(name);
      return false;
    });
  return {
    design: {
      ...design,
      shear_fit_policies: keep(design.shear_fit_policies, sensors),
      reference_policies: keep(design.reference_policies, sensors),
      shear_models: keep(design.shear_models, models),
      reference_sources: keep(design.reference_sources, sources),
    },
    dropped: [...dropped],
  };
}

/** The request the server takes. `hub_height_m` is sent only when set: the server's default
 * is the session's hub, and the old interface never sent one. */
export function requestBody(design: SweepDesign): SweepRequest {
  return {
    shear_fit_policies: design.shear_fit_policies,
    reference_policies: design.reference_policies,
    shear_models: design.shear_models,
    reference_sources: design.reference_sources,
    ltc_algorithms: design.ltc_algorithms,
    ...(design.hub_height_m === null ? {} : { hub_height_m: design.hub_height_m }),
    analyst_shear_alpha: design.analyst_shear_alpha,
    thresholds: null,
  };
}

/** A design from a request-shaped spec (the estimate's body, or a manifest's spec): what
 * "Sweep around this" hands over. Axes the spec leaves out keep the default. */
export function designFromSpec(spec: Partial<SweepRequest>): SweepDesign {
  return {
    shear_fit_policies: spec.shear_fit_policies ?? DEFAULT_DESIGN.shear_fit_policies,
    reference_policies: spec.reference_policies ?? DEFAULT_DESIGN.reference_policies,
    shear_models: spec.shear_models ?? DEFAULT_DESIGN.shear_models,
    reference_sources: spec.reference_sources ?? DEFAULT_DESIGN.reference_sources,
    ltc_algorithms: spec.ltc_algorithms ?? DEFAULT_DESIGN.ltc_algorithms,
    hub_height_m: spec.hub_height_m ?? null,
    analyst_shear_alpha: spec.analyst_shear_alpha ?? null,
  };
}

/** Whether a chosen shear-fit policy resolves to one height, so an exponent must be supplied. */
export function requiresAnalystShear(design: SweepDesign, axes: SweepAxes | null): boolean {
  if (!axes) return false;
  return design.shear_fit_policies.some((name) => {
    const level = axes.sensor_policies.find((entry) => entry.name === name);
    return Boolean(level?.available) && level?.can_fit_shear === false;
  });
}

/** The axes with no level ticked; a sweep needs at least one on each. */
export function emptyAxes(design: SweepDesign): AxisKey[] {
  return AXES.filter((axis) => design[axis.key].length === 0).map((axis) => axis.key);
}
