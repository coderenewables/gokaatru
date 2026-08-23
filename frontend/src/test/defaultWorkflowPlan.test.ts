import { describe, expect, it } from "vitest";

import { buildDefaultWorkflowConfig } from "../lib/defaultWorkflowPlan";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import type { SensorRow } from "../types/analysis";

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
  { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 94, record_count: 1000 },
  { name: "Dir_120m", height_m: 120, sensor_type: "wind_direction", data_coverage_pct: 94, record_count: 1000 },
];

describe("buildDefaultWorkflowConfig", () => {
  it("chooses a conservative measured-to-ensemble workflow from the sensor inventory", () => {
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 150;
    config.site.latitude = 52.4;
    config.site.longitude = 4.9;

    const planned = buildDefaultWorkflowConfig(config, SENSORS);

    expect(planned.inputs.activeSensorNames).toEqual(["Spd_80m", "Spd_120m", "Dir_120m"]);
    expect(planned.shear).toMatchObject({
      method: "power_law",
      speedSensorPair: ["Spd_80m", "Spd_120m"],
      directionSensor: "Dir_120m",
      targetHubHeightM: 150,
    });
    expect(planned.reanalysis).toMatchObject({
      preferredProvider: "brighthub",
      searchLatitude: 52.4,
      searchLongitude: 4.9,
    });
    expect(planned.ltc).toMatchObject({
      algorithms: ["linear_least_squares", "variance_ratio"],
      shortColumn: "Spd_150m_hub",
      longColumn: "Spd_150m_hub",
      measuredColumn: "Spd_150m_hub",
    });
    expect(planned.workflow.defaultPlanKey).toContain("default-workflow-v1");
    expect(planned.cleaning.rules).toEqual([]);
  });

  it("uses the two speed measurements nearest to the requested hub height for shear", () => {
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 110;
    const planned = buildDefaultWorkflowConfig(config, [
      ...SENSORS,
      { name: "Spd_40m", height_m: 40, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
    ]);

    expect(planned.shear.speedSensorPair).toEqual(["Spd_80m", "Spd_120m"]);
  });

  it("F-15: widens past a pair too close together for a usable shear fit", () => {
    // 118 m and 120 m are both nearest to a 119 m hub, but ln(120/118) = 0.017 - well under
    // the 0.2 floor - so a 1% speed error would swing alpha by roughly 0.6. A 60 m sensor is
    // farther from the hub but gives ln(120/60) = 0.69, comfortably clear of the floor, and
    // must be preferred over the near-duplicate pair.
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 119;
    const planned = buildDefaultWorkflowConfig(config, [
      { name: "Spd_118m", height_m: 118, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
      { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
      { name: "Spd_60m", height_m: 60, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
    ]);

    expect(planned.shear.speedSensorPair).toEqual(["Spd_60m", "Spd_120m"]);
  });

  it("F-15: falls back to the nearest pair when no wider option clears the floor", () => {
    // Only two sensors exist and they are close together - there is no wider pair available,
    // so the pre-fix nearest-2 behaviour is still the right (only) answer, not a refusal.
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 119;
    const planned = buildDefaultWorkflowConfig(config, [
      { name: "Spd_118m", height_m: 118, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
      { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
    ]);

    expect(planned.shear.speedSensorPair).toEqual(["Spd_118m", "Spd_120m"]);
  });
});