import { z } from "zod";

export const measurementTypeSchema = z.enum(["mast", "lidar", "sodar", "floating-lidar", "hybrid"]);
export const sensorKindSchema = z.enum(["speed", "direction", "temperature", "pressure", "humidity", "quality", "other"]);
export const cleaningRuleTypeSchema = z.enum([
  "range_filter",
  "outlier_filter",
  "icing_filter",
  "time_window",
  "availability_window",
  "custom",
]);
export const shearMethodSchema = z.enum(["power_law", "log_law", "roughness", "windkit"]);
export const reanalysisProviderSchema = z.enum(["era5", "merra2", "brighthub", "windkit"]);
export const ltcAlgorithmSchema = z.enum([
  "speedsort",
  "linear_least_squares",
  "total_least_squares",
  "variance_ratio",
  "xgboost",
  "ensemble",
  "windkit_linreg_mcp",
  "windkit_varrat_mcp",
]);

const locationSchema = z.object({
  latitude: z.number(),
  longitude: z.number(),
  elevationM: z.number(),
  region: z.string(),
  timeZone: z.string(),
});

const projectSchema = z.object({
  name: z.string().min(1),
  client: z.string(),
  measurementType: measurementTypeSchema,
  notes: z.string(),
});

const sensorSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  column: z.string(),
  kind: sensorKindSchema,
  heightM: z.number().nonnegative(),
  unit: z.string(),
});

const mastSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  latitude: z.number(),
  longitude: z.number(),
  elevationM: z.number(),
  boomOrientationDeg: z.number(),
  sensors: z.array(sensorSchema),
});

const standardizationSchema = z.object({
  timestampColumn: z.string(),
  timestampFormat: z.string(),
  timezone: z.string(),
  missingValues: z.array(z.string()),
  canonicalWindSpeedUnit: z.literal("m/s"),
  canonicalDirectionUnit: z.literal("deg"),
  tabularFormat: z.literal("records"),
  windkitDatasetFormat: z.enum(["xarray-dataset", "xarray-dataarray"]),
  geometryFormat: z.literal("geojson"),
});

const datasetBindingSchema = z.object({
  sharedDatasetId: z.string(),
  timeseriesFileName: z.string(),
  datamodelFileName: z.string(),
  activeSensorNames: z.array(z.string()),
});

const cleaningRuleSchema = z.object({
  id: z.string().min(1),
  ruleType: cleaningRuleTypeSchema,
  sensor: z.string(),
  params: z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])),
  startDate: z.string(),
  endDate: z.string(),
});

const shearConfigSchema = z.object({
  method: shearMethodSchema,
  speedSensorPair: z.array(z.string()),
  directionSensor: z.string(),
  aggregation: z.enum(["mean", "median", "p90"]),
  targetHubHeightM: z.number().positive(),
  useWindKit: z.boolean(),
});

const reanalysisNodeSchema = z.object({
  provider: reanalysisProviderSchema,
  latitude: z.number(),
  longitude: z.number(),
  label: z.string(),
});

const reanalysisConfigSchema = z.object({
  preferredProvider: reanalysisProviderSchema,
  searchLatitude: z.number(),
  searchLongitude: z.number(),
  startDate: z.string(),
  endDate: z.string(),
  nodes: z.array(reanalysisNodeSchema),
});

const ltcConfigSchema = z.object({
  algorithms: z.array(ltcAlgorithmSchema),
  shortColumn: z.string(),
  longColumn: z.string(),
  shortDirectionColumn: z.string(),
  longDirectionColumn: z.string(),
  measuredColumn: z.string(),
  uncertainty: z.object({
    measurementUncertaintyPct: z.number().nonnegative(),
    measurementHeightM: z.number().positive(),
    hubHeightM: z.number().positive(),
    shearMethod: z.string(),
    mcpRSquared: z.number().min(0).max(1),
    concurrentHours: z.number().positive(),
    iavPct: z.number().nonnegative(),
    shearStd: z.number().nonnegative(),
    isInterpolation: z.boolean(),
  }),
});

const workflowConfigSchema = z.object({
  mode: z.enum(["auto", "manual"]),
  preferredTemplates: z.array(z.string()),
  snapshotName: z.string(),
});

const windkitConfigSchema = z.object({
  enabledCategories: z.array(z.string()),
  preferredDatasetAssetId: z.string(),
  preferNormalizedAssets: z.boolean(),
});

const compareConfigSchema = z.object({
  branchSessionIds: z.array(z.string()),
  baselineLabel: z.string(),
});

export const windAnalysisConfigSchema = z.object({
  version: z.literal("2026-05"),
  project: projectSchema,
  site: locationSchema.extend({
    hubHeightM: z.number().positive(),
    rotorDiameterM: z.number().positive(),
  }),
  mast: z.object({
    primaryMastId: z.string().min(1),
    masts: z.array(mastSchema),
  }),
  standardization: standardizationSchema,
  inputs: datasetBindingSchema,
  cleaning: z.object({
    rules: z.array(cleaningRuleSchema),
    lastAppliedRuleId: z.string(),
  }),
  shear: shearConfigSchema,
  reanalysis: reanalysisConfigSchema,
  ltc: ltcConfigSchema,
  workflow: workflowConfigSchema,
  windkit: windkitConfigSchema,
  compare: compareConfigSchema,
});

export type WindAnalysisConfig = z.infer<typeof windAnalysisConfigSchema>;
export type MeasurementType = z.infer<typeof measurementTypeSchema>;
export type WorkflowMode = z.infer<typeof workflowConfigSchema>[
  "mode"
];