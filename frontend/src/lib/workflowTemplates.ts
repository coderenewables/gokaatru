import type { NodeConfigValue } from "./nodeRegistry";

export type WorkflowTemplateStep = {
  laneId: string;
  templateId: string;
  config?: Record<string, NodeConfigValue>;
};

export type WorkflowTemplate = {
  id: string;
  label: string;
  description: string;
  steps: WorkflowTemplateStep[];
};

export const workflowTemplates: WorkflowTemplate[] = [
  {
    id: "standard-mcp",
    label: "Standard MCP",
    description: "Dataset to uncertainty using one LTC algorithm.",
    steps: [
      { laneId: "group-dataset", templateId: "parse_timeseries" },
      {
        laneId: "group-cleaning",
        templateId: "apply_cleaning_rule",
        config: {
          params_json: '{"rule_type":"range_check","sensor":"Spd_100m","params":{"min":0.3,"max":40.0}}',
        },
      },
      { laneId: "group-site", templateId: "calculate_shear_timeseries" },
      { laneId: "group-site", templateId: "extrapolate_to_hub_height" },
      { laneId: "group-reanalysis", templateId: "find_era5_nodes" },
      { laneId: "group-reanalysis", templateId: "extract_era5_data" },
      { laneId: "group-reanalysis", templateId: "interpolate_era5_to_site" },
      { laneId: "group-ltc", templateId: "run_ltc_speedsort" },
      { laneId: "group-results", templateId: "calculate_uncertainty" },
    ],
  },
  {
    id: "multi-algorithm",
    label: "Multi-Algorithm",
    description: "Run multiple LTC methods then blend and score uncertainty.",
    steps: [
      { laneId: "group-dataset", templateId: "parse_timeseries" },
      {
        laneId: "group-cleaning",
        templateId: "apply_cleaning_rule",
        config: {
          params_json: '{"rule_type":"spike_filter","sensor":"Spd_100m","params":{"window_size":6,"sigma_threshold":3.0}}',
        },
      },
      { laneId: "group-site", templateId: "calculate_shear_timeseries" },
      { laneId: "group-site", templateId: "extrapolate_to_hub_height" },
      { laneId: "group-reanalysis", templateId: "find_era5_nodes" },
      { laneId: "group-reanalysis", templateId: "extract_era5_data" },
      { laneId: "group-reanalysis", templateId: "interpolate_era5_to_site" },
      { laneId: "group-ltc", templateId: "run_ltc_speedsort" },
      { laneId: "group-ltc", templateId: "run_ltc_variance_ratio" },
      { laneId: "group-ltc", templateId: "run_ltc_total_least_squares" },
      { laneId: "group-ltc", templateId: "run_ensemble" },
      { laneId: "group-results", templateId: "calculate_uncertainty" },
    ],
  },
  {
    id: "quick-explore",
    label: "Quick Explore",
    description: "Fast exploratory charts without full LTC execution.",
    steps: [
      { laneId: "group-dataset", templateId: "parse_timeseries" },
      { laneId: "group-cleaning", templateId: "get_data_coverage" },
      { laneId: "group-results", templateId: "plot_windrose" },
      { laneId: "group-results", templateId: "plot_weibull" },
      { laneId: "group-results", templateId: "plot_diurnal" },
    ],
  },
];

export const workflowTemplateIndex = Object.fromEntries(
  workflowTemplates.map((template) => [template.id, template]),
) as Record<string, WorkflowTemplate>;
