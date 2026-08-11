// Results — Measured data section.
//
// "What does the measured data say?" Read-only: sensor inventory, primary
// sensor statistics/coverage (via the same lightweight load* calls used by
// SensorReviewView / ExploreView), and already-computed Plotly figures.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { SensorPicker } from "../common/SensorPicker";
import type { CoverageDetail, PlotName, PlotRequest, SensorRow, SensorStatistics } from "../../types/analysis";
import { MetricTile, UnavailableSection } from "./resultsShared";

export function MeasuredDataSection() {
  const sensors = useWorkspaceStore((state) => state.sensors);
  const loadSensorStatistics = useWorkspaceStore((state) => state.loadSensorStatistics);
  const loadCoverage = useWorkspaceStore((state) => state.loadCoverage);

  const speedSensors = useMemo(
    () => sensors.filter((s) => s.sensor_type === "wind_speed"),
    [sensors],
  );
  const defaultSpeedSensor = useMemo(
    () => speedSensors.slice().sort((a, b) => b.data_coverage_pct - a.data_coverage_pct)[0]?.name ?? "",
    [speedSensors],
  );
  const defaultDirectionSensor = useMemo(() => {
    const speedHeight = speedSensors.find((s) => s.name === defaultSpeedSensor)?.height_m ?? 0;
    const directions = sensors.filter((s) => s.sensor_type === "wind_direction");
    const nearest = directions.reduce<SensorRow | undefined>((closest, sensor) => {
      if (!closest) return sensor;
      return Math.abs(sensor.height_m - speedHeight) < Math.abs(closest.height_m - speedHeight)
        ? sensor
        : closest;
    }, undefined);
    return nearest?.name ?? "";
  }, [defaultSpeedSensor, sensors, speedSensors]);

  const [speedSensor, setSpeedSensor] = useState(defaultSpeedSensor);
  const [directionSensor, setDirectionSensor] = useState(defaultDirectionSensor);
  const [stats, setStats] = useState<SensorStatistics | null>(null);
  const [coverage, setCoverage] = useState<CoverageDetail | null>(null);

  useEffect(() => {
    if (!speedSensor && defaultSpeedSensor) setSpeedSensor(defaultSpeedSensor);
    if (!directionSensor && defaultDirectionSensor) setDirectionSensor(defaultDirectionSensor);
  }, [defaultDirectionSensor, defaultSpeedSensor, directionSensor, speedSensor]);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setStats(null);
      setCoverage(null);
      return undefined;
    }
    void Promise.all([
      loadSensorStatistics(speedSensor).catch(() => null),
      loadCoverage(speedSensor).catch(() => null),
    ]).then(([sensorStats, coverageDetail]) => {
      if (!cancelled) {
        setStats(sensorStats);
        setCoverage(coverageDetail);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadCoverage, loadSensorStatistics, speedSensor]);

  if (sensors.length === 0) {
    return (
      <UnavailableSection
        title="Measured data"
        requirement="Load a dataset (Data import) to populate the measured-data summary."
      />
    );
  }

  const sdSensor = sensors.some((s) => s.name === `${speedSensor}_sd`) ? `${speedSensor}_sd` : "";

  const params = (extra: Partial<PlotRequest> = {}): PlotRequest => ({
    speed_sensor: speedSensor,
    sensor_name: speedSensor,
    sensor_names: speedSensor,
    direction_sensor: directionSensor,
    ...extra,
  });

  return (
    <div className="sensor-overview-content">
      <section className="path-panel">
        <h3>Sensor inventory</h3>
        <div className="stats-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Height (m)</th>
                <th>Type</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {sensors.map((sensor) => (
                <tr key={sensor.name}>
                  <td>{sensor.name}</td>
                  <td>{sensor.height_m.toFixed(1)}</td>
                  <td>{sensor.sensor_type}</td>
                  <td>{sensor.data_coverage_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="path-panel">
        <h3>Primary sensor selection</h3>
        <div className="form-grid">
          <label className="form-field">
            <span>Speed sensor</span>
            <SensorPicker
              sensors={sensors}
              kind="speed"
              value={speedSensor}
              onChange={(v) => setSpeedSensor(v as string)}
            />
          </label>
          <label className="form-field">
            <span>Direction sensor</span>
            <SensorPicker
              sensors={sensors}
              kind="direction"
              value={directionSensor}
              onChange={(v) => setDirectionSensor(v as string)}
            />
          </label>
        </div>
      </section>

      {stats ? (
        <section className="path-panel">
          <h3>Statistics · {stats.sensor_name}</h3>
          <dl className="metrics-grid">
            <MetricTile label="Mean" value={`${stats.mean.toFixed(2)} m/s`} />
            <MetricTile label="Median" value={`${stats.median.toFixed(2)} m/s`} />
            <MetricTile label="Std" value={stats.std.toFixed(2)} />
            <MetricTile label="Weibull k" value={stats.weibull_k?.toFixed(2) ?? "N/A"} />
            <MetricTile label="Weibull A" value={stats.weibull_A?.toFixed(2) ?? "N/A"} />
            <MetricTile label="Coverage" value={`${stats.coverage_pct.toFixed(1)}%`} />
          </dl>
        </section>
      ) : null}

      {coverage ? (
        <section className="path-panel">
          <h3>Recovery / availability · {coverage.sensor}</h3>
          <dl className="metrics-grid">
            <MetricTile label="Total records" value={String(coverage.total_records)} />
            <MetricTile label="Valid records" value={String(coverage.valid_records)} />
            <MetricTile label="Coverage" value={`${coverage.coverage_pct.toFixed(1)}%`} />
            <MetricTile label="Largest gap" value={`${coverage.largest_gap_minutes} min`} />
            <MetricTile label="Gaps > 1h" value={String(coverage.gaps_over_1_hour)} />
          </dl>
        </section>
      ) : null}

      <section className="plot-grid">
        <PlotCell title="Coverage timeline" plotName="coverage_timeline" params={params()} />
        <PlotCell title="Data coverage" plotName="data_coverage" params={params()} />
      </section>

      <section className="plot-grid">
        <PlotCell title="Weibull fit" plotName="weibull" params={params({ sensor_name: speedSensor })} />
        <PlotCell
          title="Wind rose"
          plotName="windrose"
          params={params({ speed_sensor: speedSensor, direction_sensor: directionSensor })}
          hide={!directionSensor}
        />
      </section>

      <section className="plot-grid">
        <PlotCell title="Diurnal profile" plotName="diurnal" params={params({ sensor_names: speedSensor })} />
        <PlotCell title="Monthly means" plotName="monthly_means" params={params({ sensor_names: speedSensor })} />
      </section>

      <section className="plot-grid">
        <PlotCell title="Shear profile" plotName="shear_profile" params={params()} />
        <PlotCell
          title="Turbulence intensity"
          plotName="turbulence_intensity"
          params={params({ sensor_a: speedSensor, sensor_b: sdSensor })}
          hide={!sdSensor}
        />
      </section>
    </div>
  );
}

function PlotCell({
  title,
  plotName,
  params,
  hide = false,
}: {
  title: string;
  plotName: PlotName;
  params: PlotRequest;
  hide?: boolean;
}) {
  if (hide) {
    return (
      <div className="plot-cell plot-empty">
        <p className="muted">{title}: select the required sensor to render.</p>
      </div>
    );
  }
  return (
    <div className="plot-cell">
      <h4>{title}</h4>
      <PlotFrame plotName={plotName} params={params} height={320} />
    </div>
  );
}
