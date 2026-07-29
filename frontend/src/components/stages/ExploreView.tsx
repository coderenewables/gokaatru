// Stage 3 — Measured-data exploration (spec §4 / Stage 3).
//
// Read-heavy analytics dashboard. A global speed-sensor selector drives a grid
// of PlotFrame panels: coverage timeline, Weibull, wind rose, diurnal, monthly,
// shear profile, turbulence intensity. A direction sensor feeds the wind rose.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { SensorPicker } from "../common/SensorPicker";
import { RunButton } from "../common/RunButton";
import type { PlotName, PlotRequest, SensorRow } from "../../types/analysis";

export function ExploreView() {
  const sensors = useWorkspaceStore((state) => state.sensors);
  const sensorStatistics = useWorkspaceStore((state) => state.sensorStatistics);
  const coverageDetail = useWorkspaceStore((state) => state.coverageDetail);
  const loadSensorStatistics = useWorkspaceStore((state) => state.loadSensorStatistics);
  const loadCoverage = useWorkspaceStore((state) => state.loadCoverage);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const saveConfig = useWorkspaceStore((state) => state.saveConfig);

  const speedSensors = useMemo(() => sensors.filter((s) => s.sensor_type === "wind_speed"), [sensors]);
  const defaultSensor = speedSensors.sort((a, b) => b.data_coverage_pct - a.data_coverage_pct)[0]?.name ?? "";

  const [speedSensor, setSpeedSensor] = useState(defaultSensor);
  const [directionSensor, setDirectionSensor] = useState("");

  useEffect(() => {
    if (!speedSensor && defaultSensor) setSpeedSensor(defaultSensor);
  }, [defaultSensor, speedSensor]);

  const refreshStats = async () => {
    if (!speedSensor) return;
    await Promise.all([loadSensorStatistics(speedSensor), loadCoverage(speedSensor)]);
  };

  useEffect(() => {
    if (speedSensor) void refreshStats().catch(() => {
      /* stats load is best-effort; errors are logged via the store activity feed */
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speedSensor]);

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Sensor selection</h3>
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
        <div className="path-actions">
          <RunButton label="Refresh statistics" onClick={refreshStats} disabled={!speedSensor} />
          <RunButton
            label="Lock choices"
            variant="secondary"
            onClick={async () => {
              updateConfigValue("shear.directionSensor", directionSensor);
              updateConfigValue("ltc.shortColumn", speedSensor);
              await saveConfig();
            }}
          />
        </div>
      </section>

      {sensorStatistics ? (
        <section className="path-panel">
          <h3>Statistics · {sensorStatistics.sensor_name}</h3>
          <dl className="metrics-grid">
            <Tile label="Mean" value={sensorStatistics.mean.toFixed(2)} />
            <Tile label="Median" value={sensorStatistics.median.toFixed(2)} />
            <Tile label="Std" value={sensorStatistics.std.toFixed(2)} />
            <Tile label="Min" value={sensorStatistics.min_value.toFixed(2)} />
            <Tile label="Max" value={sensorStatistics.max_value.toFixed(2)} />
            <Tile label="Count" value={String(sensorStatistics.count)} />
            <Tile label="Coverage" value={`${sensorStatistics.coverage_pct.toFixed(1)}%`} />
            <Tile label="Weibull k" value={sensorStatistics.weibull_k?.toFixed(2) ?? "N/A"} />
            <Tile label="Weibull A" value={sensorStatistics.weibull_A?.toFixed(2) ?? "N/A"} />
          </dl>
        </section>
      ) : null}

      {coverageDetail ? (
        <section className="path-panel">
          <h3>Recovery / availability · {coverageDetail.sensor}</h3>
          <dl className="metrics-grid">
            <Tile label="Total records" value={String(coverageDetail.total_records)} />
            <Tile label="Valid records" value={String(coverageDetail.valid_records)} />
            <Tile label="Coverage" value={`${coverageDetail.coverage_pct.toFixed(1)}%`} />
            <Tile label="Largest gap (min)" value={String(coverageDetail.largest_gap_minutes)} />
            <Tile label="Gaps > 1h" value={String(coverageDetail.gaps_over_1_hour)} />
          </dl>
        </section>
      ) : null}

      <PlotGrid speedSensor={speedSensor} directionSensor={directionSensor} sensors={sensors} />
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function PlotGrid({
  speedSensor,
  directionSensor,
  sensors,
}: {
  speedSensor: string;
  directionSensor: string;
  sensors: SensorRow[];
}) {
  const params = (extra: Partial<PlotRequest> = {}): PlotRequest => ({
    speed_sensor: speedSensor,
    sensor_name: speedSensor,
    sensor_names: speedSensor,
    direction_sensor: directionSensor,
    ...extra,
  });

  const sdSensor = sensors.find((s) => s.name === speedSensor)?.name
    ? `${speedSensor}_sd`
    : "";

  return (
    <>
      <section className="plot-grid">
        <PlotCell title="Coverage timeline" plotName="coverage_timeline" params={params()} />
        <PlotCell title="Data coverage" plotName="data_coverage" params={params()} />
      </section>

      {speedSensor ? (
        <section className="plot-grid">
          <PlotCell title="Weibull fit" plotName="weibull" params={params({ sensor_name: speedSensor })} />
          <PlotCell
            title="Wind rose"
            plotName="windrose"
            params={params({ speed_sensor: speedSensor, direction_sensor: directionSensor })}
            hide={!directionSensor}
          />
        </section>
      ) : null}

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
    </>
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
