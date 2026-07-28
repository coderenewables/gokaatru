import { describe, expect, it } from "vitest";

import { computeStageStatuses, STAGE_META, STAGE_ORDER } from "../lib/stages";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import {
  buildRunconfigUpdates,
  hydrateConfigFromRunconfig,
  serializeConfigToRunconfig,
  setConfigValue,
} from "../lib/configSync";
import { LTC_ALGORITHMS, PLOT_NAMES } from "../types/analysis";

describe("STAGE_ORDER + STAGE_META", () => {
  it("exposes all 9 stages in dependency order", () => {
    expect(STAGE_ORDER).toEqual([
      "data",
      "cleaning",
      "reanalysis",
      "explore",
      "shear",
      "reanalysis_extrapolation",
      "ltc",
      "clipping",
      "ensemble",
    ]);
  });

  it("every stage has metadata and a gating rule", () => {
    for (const stage of STAGE_ORDER) {
      const meta = STAGE_META[stage];
      expect(meta.title.length).toBeGreaterThan(0);
      // Advisory stages (cleaning) gate on prerequisites alone; all others
      // require at least one completed-step token.
      const isAdvisory = stage === "cleaning";
      if (isAdvisory) {
        expect(meta.requiredSteps.length).toBe(0);
        expect(meta.prerequisiteStages.length).toBeGreaterThan(0);
      } else {
        expect(meta.requiredSteps.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("computeStageStatuses", () => {
  it("marks the data stage available and locks every downstream stage when nothing is completed", () => {
    const statuses = computeStageStatuses([]);
    // data has no prerequisites → always available (or done) until completed.
    expect(statuses.data).toBe("available");
    // cleaning is advisory (no required steps) → done immediately; every other
    // stage has at least one prerequisite that isn't done → locked.
    expect(statuses.cleaning).toBe("done");
    for (const stage of STAGE_ORDER) {
      if (stage === "data" || stage === "cleaning") continue;
      expect(statuses[stage]).toBe("locked");
    }
  });

  it("treats cleaning as advisory (done once its data prerequisite is done)", () => {
    const statuses = computeStageStatuses(["timeseries", "datamodel", "config"]);
    expect(statuses.cleaning).toBe("done");
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

  it("serializeConfigToRunconfig persists the full editing surface (not just 4 keys)", () => {
    const base = createDefaultWindAnalysisConfig();
    // Mutate fields across every editable section (each returns a fresh config).
    let config = base;
    config = setConfigValue(config, "project.client", "Acme Energy");
    config = setConfigValue(config, "project.notes", "Bankable EYA");
    config = setConfigValue(config, "site.rotorDiameterM", 162);
    config = setConfigValue(config, "shear.speedSensorPair", ["Spd_80m", "Spd_120m"]);
    config = setConfigValue(config, "shear.aggregation", "momm");
    config = setConfigValue(config, "cleaning.rules", [
      { id: "r1", ruleType: "range_check", sensor: "Spd_80m", params: { min: 0, max: 50 }, startDate: "", endDate: "" },
    ]);
    config = setConfigValue(config, "ltc.algorithms", ["speedsort", "xgboost"]);
    config = setConfigValue(config, "ltc.shortColumn", "Spd_120m_hub");
    config = setConfigValue(config, "ltc.uncertainty.iavPct", 5.4);
    config = setConfigValue(config, "reanalysis.startDate", "2003-01-01");
    config = setConfigValue(config, "compare.baselineLabel", "P90 case");

    const runconfig = serializeConfigToRunconfig(config);
    // Backend-canonical keys still present.
    expect(runconfig.project_name).toBe(config.project.name);
    expect(runconfig.hub_height_m).toBe(config.site.hubHeightM);
    // Full-surface blocks persisted.
    expect((runconfig.project as Record<string, unknown>).client).toBe("Acme Energy");
    expect((runconfig.site as Record<string, unknown>).rotorDiameterM).toBe(162);
    expect((runconfig.shear as Record<string, unknown>).aggregation).toBe("momm");
    expect((runconfig.cleaning as { rules: unknown[] }).rules).toHaveLength(1);
    expect((runconfig.ltc as { algorithms: string[] }).algorithms).toEqual(["speedsort", "xgboost"]);
    expect((runconfig.reanalysis as Record<string, unknown>).startDate).toBe("2003-01-01");
    expect((runconfig.compare as Record<string, unknown>).baselineLabel).toBe("P90 case");
  });

  it("serialize → hydrate round-trips the full config losslessly", () => {
    let config = createDefaultWindAnalysisConfig();
    config = setConfigValue(config, "project.client", "Round-Trip Co");
    config = setConfigValue(config, "shear.speedSensorPair", ["Spd_80m", "Spd_120m"]);
    config = setConfigValue(config, "ltc.uncertainty.iavPct", 7.1);

    const serialized = serializeConfigToRunconfig(config);
    const rehydrated = hydrateConfigFromRunconfig(serialized);

    expect(rehydrated.project.client).toBe("Round-Trip Co");
    expect(rehydrated.shear.speedSensorPair).toEqual(["Spd_80m", "Spd_120m"]);
    expect(rehydrated.ltc.uncertainty.iavPct).toBe(7.1);
    // Canonical fields still drive the derived setters.
    expect(rehydrated.site.hubHeightM).toBe(config.site.hubHeightM);
    expect(rehydrated.shear.targetHubHeightM).toBe(config.site.hubHeightM);
  });

  it("hydrate tolerates a minimal server runconfig and falls back to defaults", () => {
    const minimal = { project_name: "X", hub_height_m: 100 };
    const hydrated = hydrateConfigFromRunconfig(minimal);
    expect(hydrated.project.name).toBe("X");
    expect(hydrated.site.hubHeightM).toBe(100);
    // Untouched sections keep their defaults.
    expect(hydrated.ltc.algorithms).toEqual(createDefaultWindAnalysisConfig().ltc.algorithms);
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
