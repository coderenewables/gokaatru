import type { SensorRow, WindAnalysisConfig } from "../types/analysis";

const DEFAULT_PLAN_VERSION = "default-workflow-v1";

function sortByHeight(sensors: SensorRow[]): SensorRow[] {
  return [...sensors].sort((left, right) => left.height_m - right.height_m || left.name.localeCompare(right.name));
}

function nearestSensor(sensors: SensorRow[], targetHeightM: number): SensorRow | undefined {
  return [...sensors].sort(
    (left, right) =>
      Math.abs(left.height_m - targetHeightM) - Math.abs(right.height_m - targetHeightM) ||
      right.height_m - left.height_m,
  )[0];
}

function nearestShearSensors(sensors: SensorRow[], targetHeightM: number): SensorRow[] {
  return [...sensors]
    .sort(
      (left, right) =>
        Math.abs(left.height_m - targetHeightM) - Math.abs(right.height_m - targetHeightM) ||
        right.height_m - left.height_m,
    )
    .slice(0, 2)
    .sort((left, right) => left.height_m - right.height_m);
}

function hubColumnName(hubHeightM: number): string {
  return `Spd_${Number.isInteger(hubHeightM) ? String(hubHeightM) : String(hubHeightM)}m_hub`;
}

export function defaultWorkflowPlanKey(config: WindAnalysisConfig, sensors: SensorRow[]): string {
  const inventory = sortByHeight(sensors)
    .map((sensor) => `${sensor.sensor_type}:${sensor.name}:${sensor.height_m}`)
    .join(",");
  return [DEFAULT_PLAN_VERSION, config.site.hubHeightM, config.inputs.sharedDatasetId || "uploaded", inventory].join("|");
}

export function buildDefaultWorkflowConfig(
  config: WindAnalysisConfig,
  sensors: SensorRow[],
): WindAnalysisConfig {
  const next = structuredClone(config);
  const speedSensors = sortByHeight(sensors.filter((sensor) => sensor.sensor_type === "wind_speed"));
  const directionSensors = sortByHeight(sensors.filter((sensor) => sensor.sensor_type === "wind_direction"));
  const hubHeightM = next.site.hubHeightM;
  const measuredSensor = nearestSensor(speedSensors, hubHeightM);
  const directionSensor = measuredSensor
    ? nearestSensor(directionSensors, measuredSensor.height_m)
    : directionSensors[directionSensors.length - 1];
  const lowSensor = speedSensors[0];
  const highSensor = speedSensors[speedSensors.length - 1];
  const isInterpolation = Boolean(
    lowSensor && highSensor && hubHeightM >= lowSensor.height_m && hubHeightM <= highSensor.height_m,
  );

  next.inputs.activeSensorNames = sensors.map((sensor) => sensor.name);
  next.shear.method = "power_law";
  next.shear.speedSensorPair = nearestShearSensors(speedSensors, hubHeightM).map((sensor) => sensor.name);
  next.shear.directionSensor = directionSensor?.name ?? "";
  next.shear.aggregation = "mean";
  next.shear.targetHubHeightM = hubHeightM;
  next.shear.useWindKit = false;

  next.reanalysis.preferredProvider = "brighthub";
  next.reanalysis.searchLatitude = next.site.latitude;
  next.reanalysis.searchLongitude = next.site.longitude;

  next.ltc.algorithms = ["linear_least_squares", "variance_ratio"];
  next.ltc.shortColumn = hubColumnName(hubHeightM);
  next.ltc.longColumn = hubColumnName(hubHeightM);
  next.ltc.shortDirectionColumn = directionSensor?.name ?? "";
  next.ltc.longDirectionColumn = directionSensor ? "ERA5_Direction" : "";
  next.ltc.measuredColumn = hubColumnName(hubHeightM);
  next.ltc.uncertainty.measurementHeightM = measuredSensor?.height_m ?? hubHeightM;
  next.ltc.uncertainty.hubHeightM = hubHeightM;
  next.ltc.uncertainty.shearMethod = "power_law";
  next.ltc.uncertainty.algorithm = "linear_least_squares";
  next.ltc.uncertainty.isInterpolation = isInterpolation;

  // Keep cleaning as a reviewed, explicit choice; auto-planning must not remove measurements.
  next.workflow.defaultPlanKey = defaultWorkflowPlanKey(next, sensors);
  return next;
}