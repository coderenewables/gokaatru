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
});