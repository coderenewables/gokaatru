import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { EnergyMetricsSummary, ExtremeWindSummary, MastEffectsSummary, McpReadinessSummary, PersistenceSummary, QcDiagnosticsSummary, RampSummary, SensorComparisonSummary, SensorRow, SensorStatistics } from "../types/analysis";
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
  | "advanced"
  | "comparison"
  | "mcp";

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
  { id: "comparison", label: "Comparison & QC" },
  { id: "mcp", label: "MCP readiness" },
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
      // Only fetch statistics for wind-speed and wind-direction sensors — these
      // are the analytically relevant ones. Fetching stats for every column
      // (GPS, status flags, oceanographic channels) is wasteful and crashes on
      // non-numeric data.
      const relevantSensors = sensors.filter(
        (s) => s.sensor_type === "wind_speed" || s.sensor_type === "wind_direction",
      );
      for (const sensor of relevantSensors) {
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
          {activeSection === "summary" ? <SummarySection sensors={sensors} rows={rows} stats={stats} speedSensor={speedSensor} directionSensor={selectedDirection} /> : null}
          {activeSection === "coverage" ? <CoverageSection sensorName={speedSensor} loadCoverage={loadCoverage} /> : null}
          {activeSection === "wind" ? <WindClimateSection speedSensor={speedSensor} directionSensor={selectedDirection} /> : null}
          {activeSection === "vertical" ? <VerticalStructureSection speedSensors={sensorsByType.wind_speed} directionSensors={sensorsByType.wind_direction} /> : null}
          {activeSection === "turbulence" ? <TurbulenceSection speedSensor={speedSensor} directionSensor={selectedDirection} /> : null}
          {activeSection === "atmosphere" ? <AtmosphereSection sensorsByType={sensorsByType} /> : null}
          {activeSection === "climatology" ? <ClimatologySection sensors={sensors} speedSensor={speedSensor} /> : null}
          {activeSection === "energy" ? <EnergySection speedSensor={speedSensor} directionSensor={selectedDirection} /> : null}
          {activeSection === "advanced" ? <AdvancedChecksSection speedSensor={speedSensor} /> : null}
          {activeSection === "comparison" ? <ComparisonQcSection directionSensor={selectedDirection} /> : null}
          {activeSection === "mcp" ? <McpReadinessSection speedSensor={speedSensor} /> : null}
        </div>
      </div>
    </div>
  );
}

function SummarySection({ sensors, rows, stats, speedSensor, directionSensor }: { sensors: SensorRow[]; rows: SensorRow[]; stats: Record<string, SensorStatistics>; speedSensor: string; directionSensor: string }) {
  const loadOverviewSummary = useWorkspaceStore((state) => state.loadOverviewSummary);
  const [summary, setSummary] = useState<import("../types/analysis").OverviewSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setSummary(null);
      return undefined;
    }
    void loadOverviewSummary(speedSensor, directionSensor).then((result) => {
      if (!cancelled) setSummary(result);
    }).catch(() => {
      if (!cancelled) setSummary(null);
    });
    return () => {
      cancelled = true;
    };
  }, [directionSensor, loadOverviewSummary, speedSensor]);

  const windSpeedCount = sensors.filter((sensor) => sensor.sensor_type === "wind_speed").length;
  const directionalCount = sensors.filter((sensor) => sensor.sensor_type === "wind_direction").length;
  const meanCoverage = sensors.length > 0
    ? sensors.reduce((total, sensor) => total + sensor.data_coverage_pct, 0) / sensors.length
    : null;

  return (
    <>
      <section className="path-panel sensor-overview-report-head">
        <div>
          <h3>Bankable assessment summary</h3>
          <p className="muted">Primary sensor: {speedSensor || "Not selected"}{directionSensor ? ` · Direction: ${directionSensor}` : ""}</p>
        </div>
        <button type="button" className="run-button run-button-secondary print-overview-button" onClick={() => window.print()}>Print summary</button>
      </section>
      {summary ? <section className="path-panel bankable-summary-table"><h3>Key assessment statistics</h3><div className="stats-table-wrap"><table className="stats-table"><thead><tr><th>Category</th><th>Metric</th><th>Value</th><th>Unit</th><th>Status</th></tr></thead><tbody>{summary.items.map((item, index) => <tr key={`${item.category}-${item.metric}-${index}`} className={item.status === "unavailable" ? "summary-unavailable" : undefined}><td>{item.category}</td><td>{item.metric}</td><td>{String(item.value)}</td><td>{item.unit || "-"}</td><td>{item.status === "available" ? "Available" : "Unavailable"}</td></tr>)}</tbody></table></div></section> : <section className="path-panel"><h3>Key assessment statistics</h3><p className="muted">Loading consolidated assessment statistics…</p></section>}
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

function TurbulenceSection({ speedSensor, directionSensor }: { speedSensor: string; directionSensor: string }) {
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
  return <><section className="path-panel"><h3>Turbulence intensity statistics</h3><dl className="metrics-grid"><MetricTile label="Mean TI" value={summary.mean_ti.toFixed(3)} /><MetricTile label="P90 TI" value={summary.p90_ti.toFixed(3)} /><MetricTile label="Representative TI" value={summary.representative_ti.toFixed(3)} /><MetricTile label="IEC TI near 15 m/s" value={summary.iec_ti_at_15ms.toFixed(3)} /></dl></section><section className="path-panel"><h3>TI versus wind speed</h3><PlotFrame plotName="turbulence_intensity" params={{ speed_sensor: speedSensor, sensor_b: summary.sd_sensor }} height={500} /></section>{directionSensor ? <section className="path-panel"><h3>Turbulence wind rose</h3><PlotFrame plotName="turbulence_windrose" params={{ speed_sensor: speedSensor, sensor_b: summary.sd_sensor, direction_sensor: directionSensor }} height={500} /></section> : <UnavailableSection title="Turbulence wind rose" requirement="A wind-direction sensor is required to summarize turbulence intensity by sector." />}</>;
}

function AtmosphereSection({ sensorsByType }: { sensorsByType: ReturnType<typeof groupSensorsByType> }) {
  const loadAtmosphericConditions = useWorkspaceStore((state) => state.loadAtmosphericConditions);
  const temperatureSensor = sensorsByType.temperature[0]?.name ?? "";
  const pressureSensor = sensorsByType.pressure[0]?.name ?? "";
  const humiditySensor = sensorsByType.humidity[0]?.name ?? "";
  const [summary, setSummary] = useState<import("../types/analysis").AtmosphericConditionsSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!temperatureSensor || !pressureSensor) {
      setSummary(null);
      return undefined;
    }
    void loadAtmosphericConditions(temperatureSensor, pressureSensor, humiditySensor).then((result) => {
      if (!cancelled) setSummary(result);
    }).catch(() => {
      if (!cancelled) setSummary(null);
    });
    return () => {
      cancelled = true;
    };
  }, [humiditySensor, loadAtmosphericConditions, pressureSensor, temperatureSensor]);

  return <>
    {summary ? <section className="path-panel"><h3>Atmospheric &amp; density statistics</h3><dl className="metrics-grid"><MetricTile label="Mean temperature" value={summary.temperature.mean.toFixed(2)} /><MetricTile label="Mean pressure" value={summary.pressure.mean.toFixed(1)} /><MetricTile label="Mean density" value={`${summary.air_density.mean.toFixed(3)} kg/m³`} /><MetricTile label="Density factor" value={summary.air_density.density_correction_factor.toFixed(3)} />{summary.humidity ? <MetricTile label="Mean humidity" value={`${summary.humidity.mean.toFixed(1)}%`} /> : null}</dl></section> : null}
    {temperatureSensor ? <VariableAnalysisSection title="Temperature" sensorName={temperatureSensor} /> : <UnavailableSection title="Temperature" requirement="No compatible sensor is present in this data model." />}
    {pressureSensor ? <VariableAnalysisSection title="Pressure" sensorName={pressureSensor} /> : <UnavailableSection title="Pressure" requirement="No compatible sensor is present in this data model." />}
    {humiditySensor ? <VariableAnalysisSection title="Humidity" sensorName={humiditySensor} /> : <UnavailableSection title="Humidity" requirement="No compatible sensor is present in this data model." />}
    {summary ? <section className="path-panel"><h3>Air density</h3><PlotFrame plotName="air_density" params={{ sensor_a: temperatureSensor, sensor_b: pressureSensor, sensor_name: humiditySensor }} height={620} /></section> : <UnavailableSection title="Air density" requirement="Measured temperature and pressure are required; humidity is used when available." />}
    <UnavailableSection title="Rainfall & icing" requirement="No compatible precipitation or icing-detection input is present in this data model." />
  </>;
}

function VariableAnalysisSection({ title, sensorName }: { title: string; sensorName: string }) {
  return <><section className="path-panel"><h3>{title} time series</h3><PlotFrame plotName="timeseries" params={{ sensor_names: sensorName }} height={340} /></section><section className="path-panel"><h3>{title} distribution</h3><PlotFrame plotName="sensor_distribution" params={{ sensor_name: sensorName }} height={340} /></section><section className="path-panel"><h3>{title} diurnal &amp; monthly distributions</h3><PlotFrame plotName="diurnal_boxplot" params={{ sensor_name: sensorName }} height={340} /><PlotFrame plotName="monthly_boxplot" params={{ sensor_name: sensorName }} height={340} /></section></>;
}

function ClimatologySection({ sensors, speedSensor }: { sensors: SensorRow[]; speedSensor: string }) {
  const speedSensors = sensors.filter((sensor) => sensor.sensor_type === "wind_speed");
  if (speedSensors.length === 0) return <UnavailableSection title="Climatology" requirement="At least one wind-speed sensor is required for diurnal and monthly profiles." />;
  return <>
    <ProfileSection title="Wind-speed diurnal profile" sensors={speedSensors} />
    <section className="path-panel"><h3>Monthly means</h3><PlotFrame plotName="monthly_means" params={{ sensor_names: speedSensors.map((sensor) => sensor.name).join(",") }} height={360} /></section>
    <section className="path-panel"><h3>Diurnal &amp; monthly wind-speed distributions</h3><PlotFrame plotName="diurnal_boxplot" params={{ sensor_name: speedSensor }} height={360} /><PlotFrame plotName="monthly_boxplot" params={{ sensor_name: speedSensor }} height={360} /></section>
    <section className="path-panel"><h3>Seasonal wind-speed profile</h3><PlotFrame plotName="seasonal_profile" params={{ sensor_names: speedSensor }} height={360} /></section>
    <UnavailableSection title="Interannual variability" requirement="Annual variability is shown only when at least three complete measurement years are available." />
  </>;
}

function EnergySection({ speedSensor, directionSensor }: { speedSensor: string; directionSensor: string }) {
  const loadEnergyMetrics = useWorkspaceStore((state) => state.loadEnergyMetrics);
  const [summary, setSummary] = useState<EnergyMetricsSummary | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setSummary(null);
      setUnavailable(true);
      return undefined;
    }
    setUnavailable(false);
    void loadEnergyMetrics(speedSensor, directionSensor).then((result) => {
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
  }, [directionSensor, loadEnergyMetrics, speedSensor]);

  if (unavailable) return <UnavailableSection title="Energy metrics" requirement="A wind-speed sensor with valid measured values is required." />;
  if (!summary) return <section className="path-panel"><h3>Energy metrics</h3><p className="muted">Loading wind-power density…</p></section>;
  return <>
    <section className="path-panel"><h3>Wind-power density</h3><dl className="metrics-grid"><MetricTile label="Power density" value={`${summary.wind_power_density_w_m2.toFixed(0)} W/m²`} /><MetricTile label="Cube mean speed" value={`${summary.mean_cube_speed_m_s.toFixed(2)} m/s`} /><MetricTile label="Air density" value={`${summary.air_density_kg_m3.toFixed(3)} kg/m³`} /><MetricTile label="Density source" value={summary.density_source} /><MetricTile label="Directional sectors" value={String(summary.sectors.length)} /></dl></section>
    <section className="path-panel"><h3>Power-density distribution &amp; energy rose</h3><PlotFrame plotName="power_density" params={{ speed_sensor: speedSensor, direction_sensor: directionSensor }} height={620} /></section>
  </>;
}

function AdvancedChecksSection({ speedSensor }: { speedSensor: string }) {
  const loadExtremeWinds = useWorkspaceStore((state) => state.loadExtremeWinds);
  const loadWindRamps = useWorkspaceStore((state) => state.loadWindRamps);
  const loadWindPersistence = useWorkspaceStore((state) => state.loadWindPersistence);
  const [results, setResults] = useState<{ extremes: ExtremeWindSummary | null; ramps: RampSummary | null; persistence: PersistenceSummary | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setResults({ extremes: null, ramps: null, persistence: null });
      return undefined;
    }
    void Promise.all([
      loadExtremeWinds(speedSensor).catch(() => null),
      loadWindRamps(speedSensor).catch(() => null),
      loadWindPersistence(speedSensor).catch(() => null),
    ]).then(([extremes, ramps, persistence]) => {
      if (!cancelled) setResults({ extremes, ramps, persistence });
    });
    return () => {
      cancelled = true;
    };
  }, [loadExtremeWinds, loadWindPersistence, loadWindRamps, speedSensor]);

  if (!speedSensor) return <UnavailableSection title="Advanced checks" requirement="A wind-speed sensor is required." />;
  if (!results) return <section className="path-panel"><h3>Advanced checks</h3><p className="muted">Loading extreme, ramp, and persistence diagnostics…</p></section>;
  return <>
    {results.extremes ? <><section className="path-panel"><h3>Extreme winds</h3><dl className="metrics-grid"><MetricTile label="Annual maxima" value={String(results.extremes.sample_years)} /><MetricTile label="GEV 50-year" value={`${results.extremes.gev.wind_50_year.toFixed(2)} m/s`} /><MetricTile label="GEV 100-year" value={`${results.extremes.gev.wind_100_year.toFixed(2)} m/s`} /><MetricTile label="Gumbel 50-year" value={`${results.extremes.gumbel.wind_50_year.toFixed(2)} m/s`} /></dl>{results.extremes.screening_only ? <p className="muted">Screening estimate only: fewer than {results.extremes.minimum_recommended_years} annual maxima are available.</p> : null}</section><section className="path-panel"><h3>Annual maxima &amp; return levels</h3><PlotFrame plotName="extremes_fit" params={{ speed_sensor: speedSensor }} height={420} /></section></> : <UnavailableSection title="Extreme winds" requirement="At least two calendar years with valid observations are required for a screening fit." />}
    {results.ramps ? <><section className="path-panel"><h3>Wind ramps</h3><dl className="metrics-grid"><MetricTile label="Mean absolute ramp" value={`${results.ramps.mean_absolute_ramp_m_s.toFixed(2)} m/s`} /><MetricTile label="P95 ramp" value={`${results.ramps.p95_absolute_ramp_m_s.toFixed(2)} m/s`} /><MetricTile label="Events" value={String(results.ramps.event_count)} /><MetricTile label="Threshold" value={`${results.ramps.event_threshold_m_s.toFixed(1)} m/s`} /></dl></section><section className="path-panel"><h3>Ramp diagnostics</h3><PlotFrame plotName="ramp_histogram" params={{ speed_sensor: speedSensor }} height={420} /></section></> : <UnavailableSection title="Wind ramps" requirement="Consecutive valid records are required." />}
    {results.persistence ? <><section className="path-panel"><h3>Calm &amp; high-wind persistence</h3><dl className="metrics-grid"><MetricTile label="Calm frequency" value={`${results.persistence.calm_pct.toFixed(1)}%`} /><MetricTile label="High-wind frequency" value={`${results.persistence.high_wind_pct.toFixed(1)}%`} /><MetricTile label="Longest calm" value={formatHours(results.persistence.max_calm_duration_minutes)} /><MetricTile label="Longest high wind" value={formatHours(results.persistence.max_high_wind_duration_minutes)} /></dl></section><section className="path-panel"><h3>Persistence duration curves</h3><PlotFrame plotName="duration_curve" params={{ speed_sensor: speedSensor }} height={420} /></section></> : <UnavailableSection title="Persistence" requirement="Valid consecutive records are required." />}
  </>;
}

function ComparisonQcSection({ directionSensor }: { directionSensor: string }) {
  const loadSensorComparison = useWorkspaceStore((state) => state.loadSensorComparison);
  const loadMastEffects = useWorkspaceStore((state) => state.loadMastEffects);
  const loadQcDiagnostics = useWorkspaceStore((state) => state.loadQcDiagnostics);
  const [results, setResults] = useState<{ comparison: SensorComparisonSummary | null; mast: MastEffectsSummary | null; qc: QcDiagnosticsSummary | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      loadSensorComparison().catch(() => null),
      loadMastEffects("", "", directionSensor).catch(() => null),
      loadQcDiagnostics().catch(() => null),
    ]).then(([comparison, mast, qc]) => {
      if (!cancelled) setResults({ comparison, mast, qc });
    });
    return () => {
      cancelled = true;
    };
  }, [directionSensor, loadMastEffects, loadQcDiagnostics, loadSensorComparison]);

  if (!results) return <section className="path-panel"><h3>Comparison &amp; QC</h3><p className="muted">Loading sensor and quality-control diagnostics…</p></section>;
  return <>
    {results.comparison ? <><section className="path-panel"><h3>Sensor comparison</h3><dl className="metrics-grid"><MetricTile label="Pair" value={`${results.comparison.sensor_a} / ${results.comparison.sensor_b}`} /><MetricTile label="Correlation" value={results.comparison.correlation.toFixed(3)} /><MetricTile label="R²" value={results.comparison.r_squared.toFixed(3)} /><MetricTile label="RMSE" value={`${results.comparison.rmse.toFixed(3)} m/s`} /><MetricTile label="Bias" value={`${results.comparison.bias.toFixed(3)} m/s`} /></dl></section><section className="path-panel"><h3>Residual diagnostics</h3><PlotFrame plotName="sensor_residuals" params={{ sensor_a: results.comparison.sensor_a, sensor_b: results.comparison.sensor_b }} height={420} /></section></> : <UnavailableSection title="Sensor comparison" requirement="At least two concurrent wind-speed sensors are required." />}
    {results.mast ? <><section className="path-panel"><h3>Mast effects</h3><dl className="metrics-grid"><MetricTile label="Baseline ratio" value={results.mast.baseline_speed_ratio.toFixed(3)} /><MetricTile label={`Shadowed: ${results.mast.sensor_a}`} value={results.mast.affected_sectors_a.join(", ") || "None"} /><MetricTile label={`Shadowed: ${results.mast.sensor_b}`} value={results.mast.affected_sectors_b.join(", ") || "None"} /><MetricTile label="Direction sensor" value={results.mast.direction_sensor} /></dl></section><section className="path-panel"><h3>Directional speed ratio</h3><PlotFrame plotName="mast_shadow" params={{ sensor_a: results.mast.sensor_a, sensor_b: results.mast.sensor_b, direction_sensor: results.mast.direction_sensor }} height={420} /></section></> : <UnavailableSection title="Mast effects" requirement="Two speed sensors and a concurrent direction sensor are required." />}
    {results.qc ? <><section className="path-panel"><h3>Quality-control diagnostics</h3><dl className="metrics-grid"><MetricTile label="Cleaning rules" value={String(results.qc.cleaning_rules_applied)} /><MetricTile label="Sensors checked" value={String(results.qc.sensors.length)} /><MetricTile label="Range failures" value={String(results.qc.sensors.reduce((sum, sensor) => sum + sensor.range_failures, 0))} /></dl></section><section className="path-panel"><h3>QC failure counts</h3><PlotFrame plotName="qc_flags" params={{}} height={420} /></section></> : <UnavailableSection title="Quality-control diagnostics" requirement="Measured wind-speed sensors are required." />}
  </>;
}

function McpReadinessSection({ speedSensor }: { speedSensor: string }) {
  const loadMcpReadiness = useWorkspaceStore((state) => state.loadMcpReadiness);
  const [summary, setSummary] = useState<McpReadinessSummary | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!speedSensor) {
      setSummary(null);
      setUnavailable(true);
      return undefined;
    }
    setUnavailable(false);
    void loadMcpReadiness(speedSensor).then((result) => {
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
  }, [loadMcpReadiness, speedSensor]);

  if (unavailable) return <UnavailableSection title="MCP readiness" requirement="Interpolated ERA5 data and at least 10 concurrent hourly records are required." />;
  if (!summary) return <section className="path-panel"><h3>MCP readiness</h3><p className="muted">Loading ERA5 concurrent-period diagnostics…</p></section>;
  return <><section className="path-panel"><h3>MCP readiness</h3><dl className="metrics-grid"><MetricTile label="Reference" value={summary.reference_sensor} /><MetricTile label="Concurrent hours" value={String(summary.concurrent_hours)} /><MetricTile label="Correlation" value={summary.correlation.toFixed(3)} /><MetricTile label="R²" value={summary.r_squared.toFixed(3)} /><MetricTile label="RMSE" value={`${summary.rmse.toFixed(3)} m/s`} /><MetricTile label="Adjustment factor" value={summary.long_term_adjustment_factor.toFixed(3)} /><MetricTile label="Ready" value={summary.ready ? "Yes" : "Needs review"} /></dl></section><section className="path-panel"><h3>Measured vs ERA5 concurrent period</h3><PlotFrame plotName="mcp_readiness" params={{ speed_sensor: speedSensor }} height={420} /></section></>;
}

function UnavailableSection({ title, requirement }: { title: string; requirement: string }) {
  return <section className="path-panel sensor-overview-unavailable"><h3>{title}</h3><p className="muted">Not available for this dataset yet. {requirement}</p></section>;
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return <div className="metric-tile"><dt>{label}</dt><dd>{value}</dd></div>;
}

function formatHours(minutes: number): string {
  return `${(minutes / 60).toFixed(1)} h`;
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