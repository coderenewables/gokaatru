import type { WindAnalysisConfig } from "../types/analysis";
import { windAnalysisConfigSchema } from "../types/analysis";

export function createDefaultWindAnalysisConfig(): WindAnalysisConfig {
  return windAnalysisConfigSchema.parse({
    version: "2026-05",
    project: {
      name: "GoKaatru Project",
      client: "",
      measurementType: "mast",
      notes: "",
    },
    site: {
      latitude: 0,
      longitude: 0,
      elevationM: 0,
      region: "",
      timeZone: "UTC",
      hubHeightM: 120,
      rotorDiameterM: 150,
    },
    mast: {
      primaryMastId: "primary-mast",
      masts: [
        {
          id: "primary-mast",
          name: "Primary mast",
          latitude: 0,
          longitude: 0,
          elevationM: 0,
          boomOrientationDeg: 0,
          sensors: [
            {
              id: "ws-100m",
              label: "Wind speed 100m",
              column: "",
              kind: "speed",
              heightM: 100,
              unit: "m/s",
            },
            {
              id: "wd-100m",
              label: "Wind direction 100m",
              column: "",
              kind: "direction",
              heightM: 100,
              unit: "deg",
            },
          ],
        },
      ],
    },
    standardization: {
      timestampColumn: "Timestamp",
      timestampFormat: "iso8601",
      timezone: "UTC",
      missingValues: ["", "NA", "NaN", "null"],
      canonicalWindSpeedUnit: "m/s",
      canonicalDirectionUnit: "deg",
      tabularFormat: "records",
      windkitDatasetFormat: "xarray-dataset",
      geometryFormat: "geojson",
    },
    inputs: {
      sharedDatasetId: "",
      timeseriesFileName: "",
      datamodelFileName: "",
      activeSensorNames: [],
    },
    cleaning: {
      rules: [],
      lastAppliedRuleId: "",
    },
    shear: {
      method: "power_law",
      speedSensorPair: [],
      directionSensor: "",
      aggregation: "mean",
      targetHubHeightM: 120,
      useWindKit: true,
    },
    reanalysis: {
      preferredProvider: "era5",
      searchLatitude: 0,
      searchLongitude: 0,
      startDate: "2000-01-01",
      endDate: "2025-12-31",
      nodes: [],
    },
    ltc: {
      algorithms: ["speedsort", "ensemble"],
      shortColumn: "",
      longColumn: "",
      shortDirectionColumn: "",
      longDirectionColumn: "",
      measuredColumn: "",
      uncertainty: {
        measurementUncertaintyPct: 2.5,
        measurementHeightM: 100,
        hubHeightM: 120,
        shearMethod: "power_law",
        mcpRSquared: 0.92,
        concurrentHours: 8760,
        iavPct: 6,
        shearStd: 0,
        isInterpolation: false,
      },
    },
    workflow: {
      mode: "auto",
      preferredTemplates: [],
      snapshotName: "baseline",
    },
    windkit: {
      enabledCategories: ["wind", "climate", "climate-stats", "ltc", "topography", "windfarm", "spatial"],
      preferredDatasetAssetId: "",
      preferNormalizedAssets: true,
    },
    compare: {
      branchSessionIds: [],
      baselineLabel: "Baseline",
    },
  });
}