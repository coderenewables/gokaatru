import { describe, expect, it } from "vitest";

import { computeStageStatuses, STAGE_META, STAGE_ORDER } from "../lib/stages";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import { buildRunconfigUpdates, hydrateConfigFromRunconfig, setConfigValue } from "../lib/configSync";
import { LTC_ALGORITHMS, PLOT_NAMES } from "../types/analysis";

describe("STAGE_ORDER + STAGE_META", () => {
  it("exposes all 8 stages in dependency order", () => {
    expect(STAGE_ORDER).toEqual([
      "data",
      "reanalysis",
      "explore",
      "shear",
      "reanalysis_extrapolation",
      "ltc",
      "clipping",
      "ensemble",
    ]);
  });

  it("every stage has metadata and required steps", () => {
    for (const stage of STAGE_ORDER) {
      const meta = STAGE_META[stage];
      expect(meta.title.length).toBeGreaterThan(0);
      expect(meta.requiredSteps.length).toBeGreaterThan(0);
    }
  });
});

describe("computeStageStatuses", () => {
  it("marks the data stage available and locks every downstream stage when nothing is completed", () => {
    const statuses = computeStageStatuses([]);
    // data has no prerequisites → always available (or done) until completed.
    expect(statuses.data).toBe("available");
    // every other stage has at least one prerequisite that isn't done → locked.
    for (const stage of STAGE_ORDER) {
      if (stage === "data") continue;
      expect(statuses[stage]).toBe("locked");
    }
  });

  it("marks data done once timeseries+datamodel+config are present", () => {
    const statuses = computeStageStatuses(["timeseries", "datamodel", "config"]);
    expect(statuses.data).toBe("done");
    // explore now unlocked (prereq data done) but not done itself — it shares data's required steps,
    // so it is also "done" by its own rule.
    expect(statuses.explore).toBe("done");
    // shear prereq is data+explore (both done) → available until shear_table present.
    expect(statuses.shear).toBe("available");
    expect(statuses.ltc).toBe("locked");
  });

  it("marks shear done when shear_table present and unlocks downstream reanalysis_extrapolation only if reanalysis done", () => {
    const statuses = computeStageStatuses([
      "timeseries",
      "datamodel",
      "config",
      "shear_timeseries",
      "shear_table",
    ]);
    expect(statuses.shear).toBe("done");
    // reanalysis not done → reanalysis_extrapolation locked.
    expect(statuses.reanalysis_extrapolation).toBe("locked");
    expect(statuses.ltc).toBe("locked");
  });

  it("marks the full pipeline done when all tokens are present", () => {
    const statuses = computeStageStatuses([
      "timeseries",
      "datamodel",
      "config",
      "era5_nodes",
      "era5_extract",
      "era5_interpolate",
      "shear_table",
      "ltc",
      "ensemble",
    ]);
    expect(statuses.data).toBe("done");
    expect(statuses.reanalysis).toBe("done");
    expect(statuses.shear).toBe("done");
    expect(statuses.reanalysis_extrapolation).toBe("done");
    expect(statuses.ltc).toBe("done");
    expect(statuses.clipping).toBe("done");
    expect(statuses.ensemble).toBe("done");
  });

  it("treats clipping as advisory (done when ltc is done, even without its own token)", () => {
    const statuses = computeStageStatuses(["timeseries", "datamodel", "config", "shear_table", "ltc"]);
    expect(statuses.clipping).toBe("done");
  });
});

describe("default config", () => {
  it("parses against the zod schema", () => {
    const config = createDefaultWindAnalysisConfig();
    expect(config.version).toBe("2026-05");
    expect(config.site.hubHeightM).toBe(120);
    expect(config.shear.method).toBe("power_law");
    expect(config.ltc.uncertainty.algorithm).toBe("speedsort");
  });
});

describe("configSync", () => {
  it("hydrates project/location/hub from runconfig", () => {
    const config = hydrateConfigFromRunconfig({
      project_name: "Site Alpha",
      measurement_type: "lidar",
      location: { latitude: 52.4, longitude: 4.9, elevation_m: 12 },
      hub_height_m: 140,
    });
    expect(config.project.name).toBe("Site Alpha");
    expect(config.project.measurementType).toBe("lidar");
    expect(config.site.latitude).toBe(52.4);
    expect(config.site.hubHeightM).toBe(140);
    expect(config.shear.targetHubHeightM).toBe(140);
  });

  it("falls back to defaults for unknown runconfig shapes", () => {
    const config = hydrateConfigFromRunconfig({});
    expect(config.project.name).toBe("GoKaatru Project");
    expect(config.site.hubHeightM).toBe(120);
  });

  it("setConfigValue updates a dotted path immutably", () => {
    const base = createDefaultWindAnalysisConfig();
    const next = setConfigValue(base, "project.name", "Site Beta");
    expect(next.project.name).toBe("Site Beta");
    expect(base.project.name).toBe("GoKaatru Project"); // unchanged
  });

  it("buildRunconfigUpdates emits only changed dotted keys", () => {
    const server = { project_name: "A", hub_height_m: 120 };
    const nextConfig = createDefaultWindAnalysisConfig();
    const modified = setConfigValue(nextConfig, "project.name", "B");
    const nextRunconfig = {
      project_name: modified.project.name,
      location: { latitude: 0, longitude: 0, elevation_m: 0 },
      hub_height_m: 120,
      measurement_type: "mast",
    };
    const updates = buildRunconfigUpdates(server, nextRunconfig);
    const keys = updates.map((u) => u.key);
    expect(keys).toContain("project_name");
    expect(keys).not.toContain("hub_height_m");
  });
});

describe("type constants", () => {
  it("LTC_ALGORITHMS matches the backend path values", () => {
    expect(LTC_ALGORITHMS).toEqual([
      "linear_least_squares",
      "total_least_squares",
      "speedsort",
      "variance_ratio",
      "xgboost",
    ]);
  });

  it("PLOT_NAMES has 24 entries", () => {
    expect(PLOT_NAMES.length).toBe(24);
  });
});
