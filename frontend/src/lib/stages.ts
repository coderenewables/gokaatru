// Stage-status logic (spec §3.3).
//
// Maps the backend's `completed_steps` array (spec §1.2) onto the 8-stage
// workflow so the Stepper can show done/locked/available per stage.
import type { StageId, StageStatus } from "../types/analysis";

export const STAGE_ORDER: StageId[] = [
  "data",
  "reanalysis",
  "explore",
  "shear",
  "reanalysis_extrapolation",
  "ltc",
  "clipping",
  "ensemble",
];

export interface StageMeta {
  title: string;
  description: string;
  /** completed_steps tokens required to consider this stage "done". */
  requiredSteps: string[];
  /** Stages that must be done before this one is unlocked. */
  prerequisiteStages: StageId[];
}

export const STAGE_META: Record<StageId, StageMeta> = {
  data: {
    title: "Data loading",
    description: "Load measured data from files or import from BrightHub; set site & hub height.",
    requiredSteps: ["timeseries", "datamodel", "config"],
    prerequisiteStages: [],
  },
  explore: {
    title: "Measured-data exploration",
    description: "Recovery/availability, wind rose, Weibull, diurnal/annual profiles, shear profile.",
    requiredSteps: ["timeseries", "datamodel"],
    prerequisiteStages: ["data"],
  },
  reanalysis: {
    title: "Reanalysis acquisition",
    description: "Download ERA5 + MERRA-2 at 4 nodes and interpolate to the site.",
    requiredSteps: ["era5_nodes", "era5_extract", "era5_interpolate"],
    prerequisiteStages: ["data"],
  },
  shear: {
    title: "Shear → hub (measured)",
    description: "Shear or roughness calculation then extrapolate measured sensors to hub height.",
    requiredSteps: ["shear_table"],
    prerequisiteStages: ["data", "explore"],
  },
  reanalysis_extrapolation: {
    title: "Reanalysis → hub",
    description: "Confirm long-term reference series exist at hub height using the chosen shear method.",
    requiredSteps: ["era5_interpolate"],
    prerequisiteStages: ["reanalysis", "shear"],
  },
  ltc: {
    title: "Long-Term Correction",
    description: "MCP between measured (short) and reanalysis (long); visualize fits.",
    requiredSteps: ["ltc"],
    prerequisiteStages: ["shear", "reanalysis_extrapolation"],
  },
  clipping: {
    title: "Clipping analysis",
    description: "Decide the representative historical window for the EYA (advisory).",
    requiredSteps: ["ltc"],
    prerequisiteStages: ["ltc"],
  },
  ensemble: {
    title: "Ensemble & uncertainty",
    description: "Blend LTC outputs, compute uncertainty, save scenarios.",
    requiredSteps: ["ensemble"],
    prerequisiteStages: ["ltc"],
  },
};

/**
 * Compute the status of every stage from the backend's completed_steps.
 *
 * Rule:
 *  - "done"      if all requiredSteps are present.
 *  - "locked"    if any prerequisite stage is not done.
 *  - "available" otherwise (ready to run but not yet complete).
 */
export function computeStageStatuses(completedSteps: string[]): Record<StageId, StageStatus> {
  const present = new Set(completedSteps);

  const isStageDone = (stage: StageId): boolean => {
    const meta = STAGE_META[stage];
    return meta.requiredSteps.every((step) => present.has(step));
  };

  const result = {} as Record<StageId, StageStatus>;
  for (const stage of STAGE_ORDER) {
    const meta = STAGE_META[stage];
    if (isStageDone(stage)) {
      result[stage] = "done";
    } else if (meta.prerequisiteStages.some((prereq) => !isStageDone(prereq))) {
      result[stage] = "locked";
    } else {
      result[stage] = "available";
    }
  }
  return result;
}
