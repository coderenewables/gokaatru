import type { SessionStep, SessionSummaryResponse } from "./types";

export type WorkflowStep = {
  path: string;
  label: string;
  description: string;
  requiredSteps: SessionStep[];
};

export const workflowSteps: WorkflowStep[] = [
  {
    path: "/overview",
    label: "Overview",
    description: "Health, project summary, and next-step navigation",
    requiredSteps: [],
  },
  {
    path: "/brighthub",
    label: "BrightHub",
    description: "Login, datasets, ERA5 & MERRA-2 access",
    requiredSteps: [],
  },
  {
    path: "/data",
    label: "Data",
    description: "Uploads, coverage, cleaning, and project metadata",
    requiredSteps: ["timeseries", "datamodel"],
  },
  {
    path: "/reanalysis",
    label: "Reanalysis",
    description: "ERA5 node discovery, extraction, and interpolation",
    requiredSteps: ["era5_nodes", "era5_extract", "era5_interpolate"],
  },
  {
    path: "/site",
    label: "Vertical Extrapolation",
    description: "Shear and hub-height extrapolation",
    requiredSteps: ["shear_table"],
  },
  {
    path: "/ltc",
    label: "LTC",
    description: "Correction algorithms, ensemble, clipping, and uncertainty",
    requiredSteps: ["ltc", "ensemble"],
  },
  {
    path: "/results",
    label: "Results",
    description: "Plots, maps, exports, and output inspection",
    requiredSteps: [],
  },
  {
    path: "/chat",
    label: "Chat",
    description: "Ask questions about your data using an AI assistant",
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