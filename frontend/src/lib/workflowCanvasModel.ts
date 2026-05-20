import { workflowTemplateIndex } from "./workflowTemplates";

export type WorkflowLaneGroup = {
  id: string;
  label: string;
  description: string;
  position: { x: number; y: number };
};

export const foundationLaneGroups: WorkflowLaneGroup[] = [
  {
    id: "group-dataset",
    label: "Dataset Source",
    description: "Choose a dataset and prepare timeseries inputs.",
    position: { x: 40, y: 120 },
  },
  {
    id: "group-cleaning",
    label: "Data Cleaning",
    description: "Apply cleaning rules before downstream analysis.",
    position: { x: 340, y: 120 },
  },
  {
    id: "group-site",
    label: "Vertical Extrapolation",
    description: "Build shear products and hub-height series.",
    position: { x: 640, y: 120 },
  },
  {
    id: "group-reanalysis",
    label: "Reanalysis",
    description: "Discover, extract, and interpolate long-term reference data.",
    position: { x: 940, y: 120 },
  },
  {
    id: "group-ltc",
    label: "LTC",
    description: "Run long-term correction algorithms and ensemble blending.",
    position: { x: 1240, y: 120 },
  },
  {
    id: "group-results",
    label: "Results",
    description: "Uncertainty, plots, exports, and comparison outputs.",
    position: { x: 1540, y: 120 },
  },
];

const laneByNormalizedCategory: Record<string, string> = {
  "dataset source": "group-dataset",
  "data cleaning": "group-cleaning",
  "vertical extrapolation": "group-site",
  reanalysis: "group-reanalysis",
  ltc: "group-ltc",
  results: "group-results",
};

export function getWorkflowLane(laneId: string | null | undefined): WorkflowLaneGroup | null {
  if (!laneId) {
    return null;
  }
  return foundationLaneGroups.find((lane) => lane.id === laneId) ?? null;
}

export function inferLaneIdForTemplate(templateId: string | null | undefined, category?: string | null): string | null {
  if (!templateId && !category) {
    return null;
  }

  if (templateId) {
    for (const template of Object.values(workflowTemplateIndex)) {
      const matchingStep = template.steps.find((step) => step.templateId === templateId);
      if (matchingStep) {
        return matchingStep.laneId;
      }
    }
  }

  if (!category) {
    return null;
  }

  return laneByNormalizedCategory[category.trim().toLowerCase()] ?? null;
}