import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { SensorRow, SensorStatistics } from "../types/analysis";
import { PlotFrame } from "./common/PlotFrame";
import { SensorPicker } from "./common/SensorPicker";

type OverviewSectionId =
  | "summary"
  | "coverage"
  | "wind"
  | "vertical"
  | "turbulence"
  | "atmosphere"
  | "climatology"
  | "energy"
  | "advanced";

const OVERVIEW_SECTIONS: Array<{ id: OverviewSectionId; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "coverage", label: "Coverage & gaps" },
  { id: "wind", label: "Wind climate" },
  { id: "vertical", label: "Vertical structure" },
  { id: "turbulence", label: "Turbulence" },
  { id: "atmosphere", label: "Atmosphere" },
  { id: "climatology", label: "Climatology" },
  { id: "energy", label: "Energy metrics" },
  { id: "advanced", label: "Advanced checks" },
];

export function SensorReviewView() {
  const sensors = useWorkspaceStore((state) => state.sensors);
  const loadSensorStatistics = useWorkspaceStore((state) => state.loadSensorStatistics);
  const loadCoverage = useWorkspaceStore((state) => state.loadCoverage);
  const [stats, setStats] = useState<Record<string, SensorStatistics>>({});
  const [activeSection, setActiveSection] = useState<OverviewSectionId>("summary");

  const sensorsByType = useMemo(() => groupSensorsByType(sensors), [sensors]);
  const defaultSpeedSensor = sensorsByType.wind_speed
    .slice()
    .sort((left, right) => right.data_coverage_pct - left.data_coverage_pct)[0]?.name ?? "";
  const [speedSensor, setSpeedSensor] = useState(defaultSpeedSensor);
  const [directionSensor, setDirectionSensor] = useState("");

  useEffect(() => {
    if (!speedSensor && defaultSpeedSensor) setSpeedSensor(defaultSpeedSensor);
  }, [defaultSpeedSensor, speedSensor]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const next: Record<string, SensorStatistics> = {};
      for (const sensor of sensors) {
        try {
          next[sensor.name] = await loadSensorStatistics(sensor.name);
        } catch {
          // Sensors without valid numerical data are omitted from the summary table.
        }
        if (cancelled) return;
      }
      if (!cancelled) setStats(next);
    };
    void run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sensors]);

  const selectedDirection = directionSensor || (findNearestDirectionSensor(
    sensorsByType.wind_speed.find((sensor) => sensor.name === speedSensor)?.height_m ?? 0,
    sensorsByType.wind_direction,
  )?.name ?? "");
  const rows = sensors.filter((sensor) => stats[sensor.name]);

  return (
    <div className="sensor-overview-view">
      <header className="sensor-overview-header">
        <div>
          <p className="sensor-overview-eyebrow">Measurement validation</p>
          <h2>Sensor overview</h2>
          <p className="muted">Validate data quality, characterize the measured wind climate, and identify WRA data gaps.</p>
        </div>
      </header>

      <section className="path-panel sensor-overview-selection" aria-label="Analysis sensor selection">
        <div className="form-grid">
          <label className="form-field">
            <span>Primary wind-speed sensor</span>
            <SensorPicker
              sensors={sensors}
              kind="speed"
              value={speedSensor}
              onChange={(value) => setSpeedSensor(value as string)}
            />
          </label>
          <label className="form-field">
            <span>Direction sensor</span>
            <SensorPicker
              sensors={sensors}
              kind="direction"
              value={selectedDirection}
              onChange={(value) => setDirectionSensor(value as string)}
            />
          </label>
        </div>
      </section>

      <div className="sensor-overview-layout">
        <nav className="sensor-overview-nav" aria-label="Sensor overview sections">
          {OVERVIEW_SECTIONS.map((section) => (
            <button
              key={section.id}
              type="button"
              className={activeSection === section.id ? "active" : undefined}
              aria-current={activeSection === section.id ? "page" : undefined}
              onClick={() => setActiveSection(section.id)}
            >
              {section.label}
            </button>
          ))}
        </nav>

        <div className="sensor-overview-content">
          {activeSection === "summary" ? <SummarySection sensors={sensors} rows={rows} stats={stats} /> : null}
          {activeSection === "coverage" ? <CoverageSection sensorName={speedSensor} loadCoverage={loadCoverage} /> : null}
          {activeSection === "wind" ? <WindClimateSection speedSensor={speedSensor} directionSensor={selectedDirection} /> : null}
          {activeSection === "vertical" ? <VerticalStructureSection speedSensors={sensorsByType.wind_speed} directionSensors={sensorsByType.wind_direction} /> : null}
          {activeSection === "turbulence" ? <TurbulenceSection speedSensor={speedSensor} /> : null}
          {activeSection === "atmosphere" ? <AtmosphereSection sensorsByType={sensorsByType} /> : null}
          {activeSection === "climatology" ? <ClimatologySection sensors={sensors} /> : null}
          {activeSection === "energy" ? <UnavailableSection title="Energy metrics" requirement="Power density, directional energy contribution, and exceedance statistics require the planned energy-analysis endpoint." /> : null}
          {activeSection === "advanced" ? <UnavailableSection title="Advanced checks" requirement="Extreme winds, ramp events, persistence, sensor comparison, mast shadow, QC diagnostics, and MCP readiness are queued for the next API increment." /> : null}
        </div>
      </div>
    </div>
  );
}

function SummarySection({ sensors, rows, stats }: { sensors: SensorRow[]; rows: SensorRow[]; stats: Record<string, SensorStatistics> }) {
  const windSpeedCount = sensors.filter((sensor) => sensor.sensor_type === "wind_speed").length;
  const directionalCount = sensors.filter((sensor) => sensor.sensor_type === "wind_direction").length;
  const meanCoverage = sensors.length > 0
    ? sensors.reduce((total, sensor) => total + sensor.data_coverage_pct, 0) / sensors.length
    : null;

  return (
    <>
      <section className="path-panel">
        <h3>Measurement inventory</h3>
        <dl className="metrics-grid">
          <MetricTile label="Sensors" value={String(sensors.length)} />
          <MetricTile label="Wind speed" value={String(windSpeedCount)} />
          <MetricTile label="Direction" value={String(directionalCount)} />
          <MetricTile label="Mean coverage" value={meanCoverage === null ? "N/A" : `${meanCoverage.toFixed(1)}%`} />
        </dl>
      </section>
      <section className="path-panel">
        <h3>Sensor statistics</h3>
        {rows.length > 0 ? (
          <div className="stats-table-wrap">
            <table className="stats-table">
              <thead>
                <tr><th>Sensor</th><th>Type</th><th>Height</th><th>Min</th><th>Mean</th><th>Max</th><th>Weibull k</th><th>Weibull A</th><th>Coverage</th></tr>
              </thead>
              <tbody>
                {rows.map((sensor) => {
                  const sensorStats = stats[sensor.name];
                  return (
                    <tr key={sensor.name}>
                      <td>{sensor.name}</td><td>{sensor.sensor_type}</td><td>{fmt(sensor.height_m)} m</td>
                      <td>{fmt(sensorStats.min_value)}</td><td>{fmt(sensorStats.mean)}</td><td>{fmt(sensorStats.max_value)}</td>
                      <td>{sensor.sensor_type === "wind_speed" ? fmt(sensorStats.weibull_k) : "N/A"}</td>
                      <td>{sensor.sensor_type === "wind_speed" ? fmt(sensorStats.weibull_A) : "N/A"}</td><td>{fmt(sensorStats.coverage_pct)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <p className="muted">Load a dataset to calculate sensor statistics.</p>}
      </section>
    </>
  );
}

function CoverageSection({ sensorName, loadCoverage }: { sensorName: string; loadCoverage: (sensorName: string) => Promise<import("../types/analysis").CoverageDetail> }) {
  const [coverage, setCoverage] = useState<import("../types/analysis").CoverageDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!sensorName) {
      setCoverage(null);
      return undefined;
    }
    void loadCoverage(sensorName).then((result) => {
      if (!cancelled) setCoverage(result);
    }).catch(() => {
      if (!cancelled) setCoverage(null);
    });
    return () => {
      cancelled = true;
    };
  }, [loadCoverage, sensorName]);

  if (!sensorName) return <UnavailableSection title="Data coverage & gaps" requirement="A wind-speed sensor is required to inspect coverage and gaps." />;

  return (
    <>
      <section className="path-panel">
        <h3>Availability · {sensorName}</h3>
        {coverage ? (
          <dl className="metrics-grid">
            <MetricTile label="Total records" value={String(coverage.total_records)} />
            <MetricTile label="Valid records" value={String(coverage.valid_records)} />
            <MetricTile label="Coverage" value={`${coverage.coverage_pct.toFixed(1)}%`} />
            <MetricTile label="Largest gap" value={`${coverage.largest_gap_minutes} min`} />
            <MetricTile label="Gaps over 1 h" value={String(coverage.gaps_over_1_hour)} />
          </dl>
        ) : <p className="muted">Loading availability statistics…</p>}
      </section>
      <section className="path-panel"><h3>Coverage timeline</h3><PlotFrame plotName="coverage_timeline" params={{}} height={360} /></section>
      <section className="path-panel"><h3>Coverage by sensor</h3><PlotFrame plotName="data_coverage" params={{}} height={360} /></section>
    </>
  );
}

function WindClimateSection({ speedSensor, directionSensor }: { speedSensor: string; directionSensor: string }) {
  const loadWindClimate = useWorkspaceStore((state) => state.loadWindClimate);
  const [summary, setSummary] = useState<import("../types/analysis").WindClimateSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setSummary(null);
      return undefined;
    }
    void loadWindClimate(speedSensor, directionSensor).then((result) => {
      if (!cancelled) setSummary(result);
    }).catch(() => {
      if (!cancelled) setSummary(null);
    });
    return () => {
      cancelled = true;
    };
  }, [directionSensor, loadWindClimate, speedSensor]);

  if (!speedSensor) return <UnavailableSection title="Wind climate" requirement="At least one wind-speed sensor is required." />;
  return (
    <>
      {summary ? (
        <section className="path-panel">
          <h3>Wind-climate statistics</h3>
          <dl className="metrics-grid">
            <MetricTile label="Mean speed" value={`${summary.mean_speed.toFixed(2)} m/s`} />
            <MetricTile label="Cube mean" value={`${summary.cube_mean_speed.toFixed(2)} m/s`} />
            <MetricTile label="Weibull k" value={summary.weibull_k.toFixed(2)} />
            <MetricTile label="Weibull A" value={`${summary.weibull_A.toFixed(2)} m/s`} />
            <MetricTile label="Fit RMSE" value={summary.weibull_rmse.toFixed(4)} />
            <MetricTile label="P90 exceedance" value={`${summary.exceedance.p90.toFixed(2)} m/s`} />
            {summary.direction ? <MetricTile label="Prevailing sector" value={summary.direction.prevailing_sector} /> : null}
            {summary.direction ? <MetricTile label="Circular variance" value={summary.direction.circular_variance.toFixed(3)} /> : null}
          </dl>
        </section>
      ) : null}
      <section className="path-panel"><h3>Wind speed time series</h3><PlotFrame plotName="timeseries" params={{ sensor_names: speedSensor }} height={360} /></section>
      <section className="path-panel"><h3>Speed distribution & exceedance</h3><PlotFrame plotName="speed_distribution" params={{ sensor_name: speedSensor }} height={360} /></section>
      <section className="path-panel"><h3>Weibull distribution</h3><PlotFrame plotName="weibull" params={{ sensor_name: speedSensor }} height={360} /></section>
      <section className="path-panel"><h3>Exceedance probability</h3><PlotFrame plotName="exceedance_curve" params={{ sensor_name: speedSensor }} height={360} /></section>
      <section className="path-panel">
        <h3>Wind rose</h3>
        {directionSensor ? <><PlotFrame plotName="windrose" params={{ speed_sensor: speedSensor, direction_sensor: directionSensor }} height={360} /><PlotFrame plotName="direction_distribution" params={{ direction_sensor: directionSensor }} height={360} /><PlotFrame plotName="sector_speed" params={{ speed_sensor: speedSensor, direction_sensor: directionSensor }} height={360} /><PlotFrame plotName="energy_rose" params={{ speed_sensor: speedSensor, direction_sensor: directionSensor }} height={360} /></> : <p className="muted">Select a direction sensor to generate wind-direction and sector analyses.</p>}
      </section>
    </>
  );
}

function VerticalStructureSection({ speedSensors, directionSensors }: { speedSensors: SensorRow[]; directionSensors: SensorRow[] }) {
  const loadVerticalStructure = useWorkspaceStore((state) => state.loadVerticalStructure);
  const [summary, setSummary] = useState<import("../types/analysis").VerticalStructureSummary | null>(null);
  const speedNames = speedSensors.map((sensor) => sensor.name).join(",");
  const directionNames = directionSensors.map((sensor) => sensor.name).join(",");

  useEffect(() => {
    let cancelled = false;
    if (speedSensors.length < 2) {
      setSummary(null);
      return undefined;
    }
    void loadVerticalStructure(speedNames, directionNames).then((result) => {
      if (!cancelled) setSummary(result);
    }).catch(() => {
      if (!cancelled) setSummary(null);
    });
    return () => {
      cancelled = true;
    };
  }, [directionNames, loadVerticalStructure, speedNames, speedSensors.length]);

  if (speedSensors.length < 2) return <UnavailableSection title="Vertical structure" requirement="Two or more wind-speed heights are required for a measured wind profile and shear analysis." />;
  return <>
    {summary ? <section className="path-panel"><h3>Profile, shear &amp; veer statistics</h3><dl className="metrics-grid"><MetricTile label="Mean alpha" value={summary.alpha.mean.toFixed(3)} /><MetricTile label="Median alpha" value={summary.alpha.median.toFixed(3)} /><MetricTile label="Alpha P10 / P90" value={`${summary.alpha.p10.toFixed(3)} / ${summary.alpha.p90.toFixed(3)}`} /><MetricTile label="Power-law R²" value={summary.power_law_r_squared.toFixed(3)} /><MetricTile label="Roughness length" value={`${summary.roughness_length_m.toFixed(4)} m`} />{summary.veer ? <MetricTile label="Mean veer" value={`${summary.veer.mean_deg_per_100m.toFixed(2)} deg / 100 m`} /> : null}</dl></section> : null}
    <section className="path-panel"><h3>Measured shear profile</h3><PlotFrame plotName="shear_profile" params={{}} height={400} /></section>
    <section className="path-panel"><h3>Wind shear alpha</h3><PlotFrame plotName="shear_alpha" params={{ sensor_names: speedNames }} height={620} /></section>
    {directionSensors.length >= 2 ? <section className="path-panel"><h3>Wind veer</h3><PlotFrame plotName="wind_veer" params={{ sensor_names: directionNames }} height={390} /></section> : <UnavailableSection title="Wind veer" requirement="Two or more wind-direction heights are required." />}
  </>;
}

function TurbulenceSection({ speedSensor }: { speedSensor: string }) {
  const loadTurbulenceAnalysis = useWorkspaceStore((state) => state.loadTurbulenceAnalysis);
  const [summary, setSummary] = useState<import("../types/analysis").TurbulenceSummary | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setSummary(null);
      setUnavailable(true);
      return undefined;
    }
    setUnavailable(false);
    void loadTurbulenceAnalysis(speedSensor).then((result) => {
      if (!cancelled) setSummary(result);
    }).catch(() => {
      if (!cancelled) {
        setSummary(null);
        setUnavailable(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadTurbulenceAnalysis, speedSensor]);

  if (unavailable) return <UnavailableSection title="Turbulence intensity" requirement="A matching 10-minute wind-speed standard-deviation channel is required to calculate TI." />;
  if (!summary) return <section className="path-panel"><h3>Turbulence intensity</h3><p className="muted">Loading turbulence statistics…</p></section>;
  return <><section className="path-panel"><h3>Turbulence intensity statistics</h3><dl className="metrics-grid"><MetricTile label="Mean TI" value={summary.mean_ti.toFixed(3)} /><MetricTile label="P90 TI" value={summary.p90_ti.toFixed(3)} /><MetricTile label="Representative TI" value={summary.representative_ti.toFixed(3)} /><MetricTile label="IEC TI near 15 m/s" value={summary.iec_ti_at_15ms.toFixed(3)} /></dl></section><section className="path-panel"><h3>TI versus wind speed</h3><PlotFrame plotName="turbulence_intensity" params={{ speed_sensor: speedSensor, sensor_b: summary.sd_sensor }} height={500} /></section></>;
}

function AtmosphereSection({ sensorsByType }: { sensorsByType: ReturnType<typeof groupSensorsByType> }) {
  const panels = [
    ["Temperature diurnal profile", sensorsByType.temperature],
    ["Pressure diurnal profile", sensorsByType.pressure],
    ["Humidity diurnal profile", sensorsByType.humidity],
  ] as const;
  return <>{panels.map(([title, sensors]) => sensors.length > 0 ? <ProfileSection key={title} title={title} sensors={sensors} /> : <UnavailableSection key={title} title={title.replace(" diurnal profile", "")} requirement="No compatible sensor is present in this data model." />)}</>;
}

function ClimatologySection({ sensors }: { sensors: SensorRow[] }) {
  const speedSensors = sensors.filter((sensor) => sensor.sensor_type === "wind_speed");
  if (speedSensors.length === 0) return <UnavailableSection title="Climatology" requirement="At least one wind-speed sensor is required for diurnal and monthly profiles." />;
  return <>
    <ProfileSection title="Wind-speed diurnal profile" sensors={speedSensors} />
    <section className="path-panel"><h3>Monthly means</h3><PlotFrame plotName="monthly_means" params={{ sensor_names: speedSensors.map((sensor) => sensor.name).join(",") }} height={360} /></section>
    <UnavailableSection title="Seasonal & interannual analysis" requirement="Seasonal Weibull and year-to-year variability will be enabled when record-span analysis is added." />
  </>;
}

function UnavailableSection({ title, requirement }: { title: string; requirement: string }) {
  return <section className="path-panel sensor-overview-unavailable"><h3>{title}</h3><p className="muted">Not available for this dataset yet. {requirement}</p></section>;
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return <div className="metric-tile"><dt>{label}</dt><dd>{value}</dd></div>;
}

function groupSensorsByType(sensors: SensorRow[]): Record<"wind_speed" | "wind_direction" | "temperature" | "pressure" | "humidity", SensorRow[]> {
  return {
    wind_speed: sensors.filter((sensor) => sensor.sensor_type === "wind_speed"),
    wind_direction: sensors.filter((sensor) => sensor.sensor_type === "wind_direction"),
    temperature: sensors.filter((sensor) => sensor.sensor_type === "temperature"),
    pressure: sensors.filter((sensor) => sensor.sensor_type === "pressure"),
    humidity: sensors.filter((sensor) => sensor.sensor_type === "humidity"),
  };
}

export function findNearestDirectionSensor(speedHeight: number, directionSensors: SensorRow[]): SensorRow | undefined {
  return directionSensors.reduce<SensorRow | undefined>((closest, sensor) => {
    if (!closest) return sensor;
    const candidateDistance = Math.abs(sensor.height_m - speedHeight);
    const closestDistance = Math.abs(closest.height_m - speedHeight);
    return candidateDistance < closestDistance ? sensor : closest;
  }, undefined);
}

export function ProfileSection({ title, sensors }: { title: string; sensors: SensorRow[] }) {
  const [selectedSensors, setSelectedSensors] = useState(() => sensors.map((sensor) => sensor.name));

  useEffect(() => {
    setSelectedSensors(sensors.map((sensor) => sensor.name));
  }, [sensors]);

  if (sensors.length === 0) return null;
  return (
    <section className="path-panel">
      <h3>{title}</h3>
      <SensorPicker
        sensors={sensors}
        kind="all"
        multiple
        value={selectedSensors}
        onChange={(value) => setSelectedSensors(value as string[])}
      />
      {selectedSensors.length > 0 ? (
        <PlotFrame plotName="diurnal" params={{ sensor_names: selectedSensors.join(", ") }} height={320} />
      ) : (
        <p className="muted">Select at least one sensor to show a diurnal profile.</p>
      )}
    </section>
  );
}

function fmt(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "N/A";
}