// Pure arithmetic for the Prepare phase's prefix-stat tiles (design doc: Prepare).
// A plain mean over already-disclosed per-sensor coverage numbers — no new default,
// clamp or threshold, so this does not need a disclosure entry of its own.
import type { SensorRow } from "../types/analysis";

export function meanCoverage(sensors: SensorRow[], dropped?: Set<string>): number | null {
  const kept = dropped ? sensors.filter((sensor) => !dropped.has(sensor.name)) : sensors;
  if (kept.length === 0) return null;
  const total = kept.reduce((sum, sensor) => sum + sensor.data_coverage_pct, 0);
  return total / kept.length;
}
