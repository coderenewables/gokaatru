export type NodeStatus = "idle" | "pending" | "running" | "done" | "error" | "skipped";

export type NodeConfigValue = string | number | boolean;

export type NodeConfigField = {
  key: string;
  label: string;
  type: "text" | "number" | "boolean" | "select";
  defaultValue: NodeConfigValue;
  options?: Array<{ label: string; value: string }>;
  placeholder?: string;
};

export type WorkflowNodeData = {
  kind: "group" | "operation" | "dataset" | "fork";
  label: string;
  description: string;
  status: NodeStatus;
  branchColor?: string;
  stale?: boolean;
  category?: string;
  templateId?: string;
  summary?: string;
  config?: Record<string, NodeConfigValue>;
  fields?: NodeConfigField[];
  badge?: string;
};

export type NodeTemplate = {
  id: string;
  label: string;
  description: string;
  category: string;
  fields: NodeConfigField[];
};

export type NodePaletteGroup = {
  id: string;
  label: string;
  description: string;
  accent: string;
  items: NodeTemplate[];
};

type ToolPaletteGroupDefinition = {
  id: string;
  label: string;
  description: string;
  accent: string;
  toolFunctions: string[];
  extras?: NodeTemplate[];
};

const DEFAULT_TOOL_FIELDS: NodeConfigField[] = [
  {
    key: "params_json",
    label: "Parameters JSON",
    type: "text",
    defaultValue: "{}",
    placeholder: '{"key":"value"}',
  },
];

const TOKEN_MAP: Record<string, string> = {
  api: "API",
  brighthub: "BrightHub",
  bwc: "BWC",
  cdf: "CDF",
  cp: "CP",
  crs: "CRS",
  ct: "CT",
  era5: "ERA5",
  geowc: "GeoWC",
  gwc: "GWC",
  iav: "IAV",
  ltc: "LTC",
  mast: "Mast",
  mcp: "MCP",
  momm: "MoMM",
  rews: "REWS",
  tswc: "TSWC",
  wtg: "WTG",
  windkit: "WindKit",
  wwc: "WWC",
  ws: "WS",
  xgboost: "XGBoost",
};

function toTitleToken(token: string): string {
  const mapped = TOKEN_MAP[token.toLowerCase()];
  if (mapped) {
    return mapped;
  }

  return token.charAt(0).toUpperCase() + token.slice(1);
}

function humanizeToolFunctionName(functionName: string): string {
  return functionName
    .split("_")
    .map((token) => toTitleToken(token))
    .join(" ");
}

function createToolTemplate(functionName: string, category: string): NodeTemplate {
  return {
    id: functionName,
    label: humanizeToolFunctionName(functionName),
    description: `Registered MCP tool: ${functionName}`,
    category,
    fields: DEFAULT_TOOL_FIELDS,
  };
}

const toolPaletteGroupDefinitions: ToolPaletteGroupDefinition[] = [
  {
    id: "core-dataset-source",
    label: "Dataset Source",
    description: "Parse files, inspect sensors, and establish baseline coverage.",
    accent: "core",
    extras: [
      {
        id: "select-dataset",
        label: "Select Dataset",
        description: "Attach a shared dataset node onto the canvas branch.",
        category: "Dataset Source",
        fields: [],
      },
    ],
    toolFunctions: ["parse_timeseries", "parse_datamodel", "list_sensors", "get_data_coverage", "get_period_of_record"],
  },
  {
    id: "core-data-cleaning",
    label: "Data Cleaning",
    description: "Apply cleaning logic and inspect cleaning history.",
    accent: "core",
    toolFunctions: ["list_cleaning_rules", "apply_cleaning_rule", "undo_cleaning_rule", "get_cleaning_log"],
  },
  {
    id: "core-vertical-extrapolation",
    label: "Vertical Extrapolation",
    description: "Shear, roughness, and hub-height extrapolation toolchain.",
    accent: "core",
    toolFunctions: [
      "calculate_shear_timeseries",
      "calculate_roughness_timeseries",
      "build_shear_table",
      "build_aggr_momm_shear_table",
      "build_sector_shear_tables",
      "build_roughness_table",
      "extrapolate_to_hub_height",
      "extrapolate_reanalysis_to_hub",
    ],
  },
  {
    id: "core-reanalysis",
    label: "Reanalysis",
    description: "ERA5 discovery, extraction, interpolation, and homogeneity controls.",
    accent: "core",
    toolFunctions: [
      "find_era5_nodes",
      "extract_era5_data",
      "interpolate_era5_to_site",
      "compute_era5_wind_speed",
      "analyze_homogeneity",
      "apply_homogeneity_cutoff",
    ],
  },
  {
    id: "core-ltc",
    label: "LTC",
    description: "Long-term correction algorithms and ensemble blending.",
    accent: "core",
    toolFunctions: [
      "run_ltc_linear_least_squares",
      "run_ltc_total_least_squares",
      "run_ltc_speedsort",
      "run_ltc_variance_ratio",
      "run_ltc_xgboost",
      "run_ensemble",
    ],
  },
  {
    id: "core-post-processing",
    label: "Post-Processing & Results",
    description: "Uncertainty, clipping, and atmospheric correction operations.",
    accent: "core",
    toolFunctions: ["run_clipping_analysis", "calculate_uncertainty", "compute_air_density", "compute_air_density_timeseries"],
  },
  {
    id: "core-statistics",
    label: "Core Statistics",
    description: "Weibull, windrose, diurnal, monthly, and turbulence statistics.",
    accent: "core",
    toolFunctions: [
      "compute_weibull_params",
      "compute_windrose_data",
      "compute_diurnal_profile",
      "compute_monthly_stats",
      "compute_momm",
      "compute_turbulence_intensity",
      "compute_scatter_stats",
    ],
  },
  {
    id: "core-visualization",
    label: "Core Visualization",
    description: "Plotly chart generation tools for analysis outputs.",
    accent: "core",
    toolFunctions: [
      "plot_windrose",
      "plot_weibull",
      "plot_diurnal",
      "plot_monthly_means",
      "plot_annual_means",
      "plot_scatter",
      "plot_timeseries",
      "plot_data_coverage",
      "plot_shear_table",
      "plot_ltc_comparison",
      "plot_uncertainty_breakdown",
    ],
  },
  {
    id: "core-map-config",
    label: "Map & Configuration",
    description: "Map overlays, analysis summaries, and run configuration controls.",
    accent: "core",
    toolFunctions: [
      "get_mast_marker",
      "get_era5_node_markers",
      "get_site_overview_map",
      "get_analysis_summary",
      "get_run_config",
      "update_run_config",
      "save_run_config",
      "load_run_config",
    ],
  },
  {
    id: "core-brighthub",
    label: "BrightHub",
    description: "BrightHub authentication, location import, and reanalysis retrieval.",
    accent: "core",
    toolFunctions: [
      "brighthub_status",
      "brighthub_login",
      "brighthub_logout",
      "brighthub_list_locations",
      "brighthub_get_data_model",
      "brighthub_find_reanalysis_nodes",
      "brighthub_download_reanalysis",
      "brighthub_import_location",
    ],
  },
  {
    id: "windkit-wind",
    label: "WindKit - Wind",
    description: "Wind vector transformations, sectoring, shear, veer, and REWS.",
    accent: "windkit",
    toolFunctions: [
      "windkit_wind_speed",
      "windkit_wind_direction",
      "windkit_wind_speed_and_direction",
      "windkit_wind_vectors",
      "windkit_wind_direction_difference",
      "windkit_wd_to_sector",
      "windkit_vinterp_wind_direction",
      "windkit_vinterp_wind_speed",
      "windkit_rotor_equivalent_wind_speed",
      "windkit_shear_extrapolate",
      "windkit_shear_exponent",
      "windkit_veer_extrapolate",
      "windkit_wind_veer",
    ],
  },
  {
    id: "windkit-climate",
    label: "WindKit - Climate",
    description: "TSWC/BWC/WWC/GWC climate data creation, validation, and conversion.",
    accent: "windkit",
    toolFunctions: [
      "windkit_validate_tswc",
      "windkit_is_tswc",
      "windkit_create_tswc",
      "windkit_read_tswc",
      "windkit_tswc_from_dataframe",
      "windkit_tswc_resample",
      "windkit_validate_bwc",
      "windkit_is_bwc",
      "windkit_create_bwc",
      "windkit_read_bwc",
      "windkit_bwc_from_tswc",
      "windkit_bwc_to_file",
      "windkit_combine_bwcs",
      "windkit_weibull_fit",
      "windkit_validate_wwc",
      "windkit_is_wwc",
      "windkit_create_wwc",
      "windkit_read_wwc",
      "windkit_read_mfwwc",
      "windkit_wwc_to_file",
      "windkit_wwc_to_bwc",
      "windkit_weibull_combined",
      "windkit_validate_gwc",
      "windkit_is_gwc",
      "windkit_create_gwc",
      "windkit_read_gwc",
      "windkit_gwc_to_file",
      "windkit_validate_geowc",
      "windkit_is_geowc",
    ],
  },
  {
    id: "windkit-climate-stats",
    label: "WindKit - Climate Stats",
    description: "Climate-derived moments, distributions, and cross-prediction stats.",
    accent: "windkit",
    toolFunctions: [
      "windkit_create_met_fields",
      "windkit_mean_ws_moment",
      "windkit_ws_cdf",
      "windkit_ws_freq_gt_mean",
      "windkit_mean_wind_speed",
      "windkit_mean_power_density",
      "windkit_get_cross_predictions",
    ],
  },
  {
    id: "windkit-topography",
    label: "WindKit - Topography",
    description: "Landcover, roughness, elevation, raster/vector, and map geometry tools.",
    accent: "windkit",
    toolFunctions: [
      "windkit_get_landcover_table",
      "windkit_add_landcover_table",
      "windkit_roughness_to_landcover",
      "windkit_landcover_to_roughness",
      "windkit_read_roughness_map",
      "windkit_read_landcover_map",
      "windkit_landcover_map_to_file",
      "windkit_roughness_map_to_file",
      "windkit_read_elevation_map",
      "windkit_elevation_map_to_file",
      "windkit_create_raster_map",
      "windkit_get_raster_map",
      "windkit_create_vector_map",
      "windkit_get_vector_map",
      "windkit_lines_to_polygons",
      "windkit_polygons_to_lines",
      "windkit_snap_to_layer",
      "windkit_check_dead_ends",
      "windkit_check_lines_cross",
    ],
  },
  {
    id: "windkit-windfarm",
    label: "WindKit - Wind Farm",
    description: "Wind turbines, WTG curves, and uncertainty table operations.",
    accent: "windkit",
    toolFunctions: [
      "windkit_validate_windturbines",
      "windkit_is_windturbines",
      "windkit_check_wtg_keys",
      "windkit_create_wind_turbines_from_dataframe",
      "windkit_create_wind_turbines_from_arrays",
      "windkit_wind_turbines_to_geodataframe",
      "windkit_validate_wtg",
      "windkit_is_wtg",
      "windkit_estimate_regulation_type",
      "windkit_read_wtg",
      "windkit_wtg_power",
      "windkit_wtg_cp",
      "windkit_wtg_ct",
      "windkit_validate_uncertainty_table",
      "windkit_get_uncertainty_table",
      "windkit_total_uncertainty",
      "windkit_uncertainty_table_summary",
      "windkit_total_uncertainty_factor",
    ],
  },
  {
    id: "windkit-spatial",
    label: "WindKit - Spatial",
    description: "CRS, spatial object creation, interpolation, and clipping operations.",
    accent: "windkit",
    toolFunctions: [
      "windkit_get_crs",
      "windkit_set_crs",
      "windkit_crs_are_equal",
      "windkit_create_dataset",
      "windkit_create_raster",
      "windkit_create_point",
      "windkit_create_stacked_point",
      "windkit_create_cuboid",
      "windkit_is_point",
      "windkit_is_stacked_point",
      "windkit_is_cuboid",
      "windkit_is_raster",
      "windkit_to_point",
      "windkit_to_cuboid",
      "windkit_to_stacked_point",
      "windkit_to_raster",
      "windkit_gdf_to_ds",
      "windkit_ds_to_gdf",
      "windkit_interp_structured_like",
      "windkit_interp_unstructured",
      "windkit_interp_unstructured_like",
      "windkit_are_spatially_equal",
      "windkit_equal_spatial_shape",
      "windkit_covers",
      "windkit_clip",
      "windkit_clip_with_margin",
      "windkit_mask",
      "windkit_nearest_points",
      "windkit_reproject",
      "windkit_warp",
      "windkit_count_spatial_points",
    ],
  },
  {
    id: "windkit-mcp-ltc",
    label: "WindKit - MCP LTC",
    description: "WindKit MCP models for long-term correction.",
    accent: "windkit",
    toolFunctions: ["windkit_ltc_linreg_mcp", "windkit_ltc_varrat_mcp"],
  },
  {
    id: "windkit-weibull-utils",
    label: "WindKit - Weibull & Utilities",
    description: "Weibull utilities, coordinate bins, ERA5, and tutorial datasets.",
    accent: "windkit",
    toolFunctions: [
      "windkit_get_tutorial_data",
      "windkit_load_tutorial_data",
      "windkit_fit_weibull_wasp_m1_m3_fgtm",
      "windkit_fit_weibull_wasp_m1_m3",
      "windkit_fit_weibull_k_sumlogm",
      "windkit_weibull_moment",
      "windkit_weibull_pdf",
      "windkit_weibull_cdf",
      "windkit_weibull_freq_gt_mean",
      "windkit_get_weibull_probability",
      "windkit_read_cfdres",
      "windkit_create_sector_coords",
      "windkit_create_wsbin_coords",
      "windkit_get_era5",
    ],
  },
  {
    id: "windkit-plotting",
    label: "WindKit - Plotting",
    description: "WindKit visualization tools returning Plotly-compatible outputs.",
    accent: "windkit",
    toolFunctions: [
      "windkit_plot_histogram",
      "windkit_plot_histogram_lines",
      "windkit_plot_operational_curves",
      "windkit_plot_raster",
      "windkit_plot_roughness_rose",
      "windkit_plot_time_series",
      "windkit_plot_vertical_profile",
      "windkit_plot_wind_rose",
      "windkit_plot_landcover_map",
    ],
  },
];

export const foundationLaneGroups = [
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
] as const;

export const paletteGroups: NodePaletteGroup[] = toolPaletteGroupDefinitions.map((definition) => ({
  id: definition.id,
  label: definition.label,
  description: definition.description,
  accent: definition.accent,
  items: [
    ...(definition.extras ?? []),
    ...definition.toolFunctions.map((functionName) => createToolTemplate(functionName, definition.label)),
  ],
}));

export const nodeTemplateIndex = Object.fromEntries(
  paletteGroups.flatMap((group) => group.items.map((item) => [item.id, item])),
) as Record<string, NodeTemplate>;

export function buildTemplateConfig(template: NodeTemplate): Record<string, NodeConfigValue> {
  return Object.fromEntries(template.fields.map((field) => [field.key, field.defaultValue]));
}