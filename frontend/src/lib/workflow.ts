import type { SessionSummaryResponse, SessionStep } from "./types";

export type WorkflowStep = {
  path: string;
  label: string;
  shortLabel: string;
  description: string;
  requiredSteps: SessionStep[];
};

export const workflowSteps: WorkflowStep[] = [
  {
    path: "/overview",
    label: "Overview",
    shortLabel: "Overview",
    description: "Session status and next-step navigation.",
    requiredSteps: [],
  },
  {
    path: "/brighthub",
    label: "BrightHub",
    shortLabel: "BrightHub",
    description: "Login, dataset discovery, and BrightHub-backed reference data setup.",
    requiredSteps: [],
  },
  {
    path: "/data",
    label: "Data",
    shortLabel: "Data",
    description: "Uploads, coverage, cleaning, and project metadata.",
    requiredSteps: ["timeseries", "datamodel", "config"],
  },
  {
    path: "/reanalysis",
    label: "Reanalysis",
    shortLabel: "Reanalysis",
    description: "ERA5 node discovery, extraction, and interpolation.",
    requiredSteps: ["era5_nodes", "era5_extract", "era5_interpolate"],
  },
  {
    path: "/site",
    label: "Vertical Extrapolation",
    shortLabel: "V. Extrapolation",
    description: "Shear and hub-height extrapolation.",
    requiredSteps: ["shear_table"],
  },
  {
    path: "/ltc",
    label: "LTC",
    shortLabel: "LTC",
    description: "Correction algorithms, ensemble, clipping, and uncertainty inputs.",
    requiredSteps: ["ltc", "ensemble"],
  },
  {
    path: "/results",
    label: "Results",
    shortLabel: "Results",
    description: "Plots, maps, exports, and output inspection.",
    requiredSteps: [],
  },
  {
    path: "/chat",
    label: "Chat",
    shortLabel: "Chat",
    description: "Ask questions about your data using an AI assistant.",
    requiredSteps: [],
  },
];

export function isWorkflowStepComplete(summary: SessionSummaryResponse | undefined, step: WorkflowStep): boolean {
  if (step.requiredSteps.length === 0) {
    return true;
  }
  if (!summary) {
    return false;
  }
  return step.requiredSteps.every((requiredStep) => summary.completed_steps.includes(requiredStep));
}

export function findNextIncompletePath(summary: SessionSummaryResponse | undefined): string {
  const nextStep = workflowSteps.find((step) => !isWorkflowStepComplete(summary, step) && step.path !== "/results");
  return nextStep?.path ?? "/results";
}
