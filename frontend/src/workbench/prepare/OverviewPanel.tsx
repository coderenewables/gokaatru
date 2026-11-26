import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { speedChannels, useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import { shown } from "./rules";
import "./prepare.css";

type Qc = Schemas["ComputeQcDiagnosticsResult"];
type Comparison = Schemas["ComputeSensorComparisonResult"];
type Readiness = Schemas["ComputeMcpReadinessResult"];
type MastEffects = Schemas["ComputeMastEffectsResult"];
type Atmosphere = Schemas["ComputeAtmosphericConditionsResult"];

const run = (sessionId: string) => ({ params: { path: { session_id: sessionId } } });

/** One section of the overview: its operation's answer, or the server's reason for not
 * giving one. Keys hold the session id, so a change to the campaign refetches it. */
function Section<T>({ id, title, query, children }: {
  id: string;
  title: string;
  query: { data: T | undefined; error: Error | null; isPending: boolean };
  children: (data: T) => ReactNode;
}) {
  return (
    <section aria-labelledby={`gk-overview-${id}`} className="gk-overview-section">
      <h2 id={`gk-overview-${id}`}>{title}</h2>
      {query.error ? (
        <p role="alert" className="gk-refusal">{query.error.message}</p>
      ) : query.data === undefined ? (
        <p className="gk-muted">{query.isPending ? "Reading…" : "Nothing to show."}</p>
      ) : (
        children(query.data)
      )}
    </section>
  );
}

function Pairs({ rows, label }: { rows: [string, ReactNode][]; label: string }) {
  return (
    <dl className="gk-pairs" aria-label={label}>
      {rows.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function QcTable({ qc }: { qc: Qc }) {
  return (
    <>
      <p className="gk-muted">{qc.cleaning_rules_applied} cleaning rules applied.</p>
      <table className="gk-table" aria-label="Quality control by sensor">
        <thead>
          <tr>
            <th scope="col">Sensor</th>
            <th scope="col">Range</th>
            <th scope="col">Range failures</th>
            <th scope="col">Flat-line records</th>
            <th scope="col">Removed by cleaning</th>
          </tr>
        </thead>
        <tbody>
          {qc.sensors.map((row) => (
            <tr key={row.sensor}>
              <th scope="row">{row.sensor}</th>
              <td title={row.range_bounds_source}>
                {shown(row.range_min)} to {shown(row.range_max)}
              </td>
              <td>{row.range_failures}</td>
              <td>{row.flatline_records}</td>
              <td>{row.removed_after_cleaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function ComparisonPairs({ data }: { data: Comparison }) {
  return (
    <Pairs
      label={`${data.sensor_a} against ${data.sensor_b}`}
      rows={[
        ["Sensors", `${data.sensor_a} against ${data.sensor_b}`],
        ["Records", data.record_count],
        ["Slope", shown(data.slope)],
        ["Offset", shown(data.offset)],
        ["R²", shown(data.r_squared)],
        ["Correlation", shown(data.correlation)],
        ["Bias", shown(data.bias)],
        ["RMSE", shown(data.rmse)],
      ]}
    />
  );
}

function ReadinessPairs({ data }: { data: Readiness }) {
  return (
    <>
      <p>
        <strong>{data.ready ? "Ready" : "Not ready"}</strong> for a correlation against {data.reference_sensor}.
      </p>
      {data.not_ready_reasons.length > 0 && (
        <ul aria-label="Why it is not ready">
          {data.not_ready_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <Pairs
        label="MCP readiness figures"
        rows={[
          ["Concurrent hours", `${shown(data.concurrent_hours)} (at least ${shown(data.min_concurrent_hours)})`],
          ["R²", `${shown(data.r_squared)} (at least ${shown(data.min_r_squared)})`],
          ["Slope", shown(data.slope)],
          ["Offset", shown(data.offset)],
          ["Correlation", shown(data.correlation)],
          ["Bias", shown(data.bias)],
          ["RMSE", shown(data.rmse)],
        ]}
      />
    </>
  );
}

function MastEffectsTable({ data }: { data: MastEffects }) {
  return (
    <>
      <p className="gk-muted">
        {data.sensor_a} against {data.sensor_b} by {data.direction_sensor}; baseline speed ratio {shown(data.baseline_speed_ratio)}. Affected sectors:{" "}
        {data.affected_sectors.length > 0 ? data.affected_sectors.join(", ") : "none"}.
      </p>
      <table className="gk-table" aria-label="Speed ratio by sector">
        <thead>
          <tr>
            <th scope="col">Sector</th>
            <th scope="col">Records</th>
            <th scope="col">Speed ratio</th>
          </tr>
        </thead>
        <tbody>
          {data.sectors.map((sector) => (
            <tr key={sector.label}>
              <th scope="row">{sector.label}</th>
              <td>{sector.record_count}</td>
              <td>{sector.sufficient_records ? shown(sector.speed_ratio) : "too few records"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function AtmosphereTable({ data }: { data: Atmosphere }) {
  const series: [string, { mean: number | null; min: number | null; max: number | null; std: number | null; record_count: number } | null][] = [
    [`Temperature (${data.temperature_sensor})`, data.temperature],
    [`Pressure (${data.pressure_sensor})`, data.pressure],
    [data.humidity_sensor ? `Humidity (${data.humidity_sensor})` : "Humidity", data.humidity],
    ["Air density", data.air_density],
  ];
  return (
    <>
      <table className="gk-table" aria-label="Atmospheric conditions">
        <thead>
          <tr>
            <th scope="col">Series</th>
            <th scope="col">Mean</th>
            <th scope="col">Min</th>
            <th scope="col">Max</th>
            <th scope="col">Std</th>
            <th scope="col">Records</th>
          </tr>
        </thead>
        <tbody>
          {series.map(([name, item]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>{shown(item?.mean)}</td>
              <td>{shown(item?.min)}</td>
              <td>{shown(item?.max)}</td>
              <td>{shown(item?.std)}</td>
              <td>{item?.record_count ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.air_density.warning && <p className="gk-warning">{data.air_density.warning}</p>}
    </>
  );
}

/** The tables of the old Sensor Overview, each from its own operation (decisions/0015.13).
 * The channels each is asked about are the campaign's speed channels, highest first; an
 * operation that cannot answer (no temperature sensor, no reference) says why. */
export function OverviewPanel() {
  const { sessionId } = useCampaign();
  const sensors = useSensors(sessionId);
  const speeds = speedChannels(sensors.data ?? []);
  const [top, second] = speeds;
  // An empty campaign has nothing to diagnose; each operation would only refuse.
  const ready = (sensors.data?.length ?? 0) > 0;

  const qc = useQuery({
    queryKey: ["overview", "qc", sessionId],
    enabled: ready,
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/compute_qc_diagnostics", { ...run(sessionId), body: {} })),
    retry: false,
  });
  const comparison = useQuery({
    queryKey: ["overview", "comparison", sessionId, top, second],
    enabled: ready,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/compute_sensor_comparison", {
          ...run(sessionId),
          body: top && second ? { sensor_a: top, sensor_b: second } : {},
        }),
      ),
    retry: false,
  });
  const readiness = useQuery({
    queryKey: ["overview", "readiness", sessionId, top],
    enabled: ready,
    queryFn: async () =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/compute_mcp_readiness", { ...run(sessionId), body: { speed_sensor: top ?? "" } })),
    retry: false,
  });
  const mast = useQuery({
    queryKey: ["overview", "mast", sessionId, top, second],
    enabled: ready,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/compute_mast_effects", {
          ...run(sessionId),
          body: top && second ? { sensor_a: top, sensor_b: second } : {},
        }),
      ),
    retry: false,
  });
  const atmosphere = useQuery({
    queryKey: ["overview", "atmosphere", sessionId],
    enabled: ready,
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/compute_atmospheric_conditions", { ...run(sessionId), body: {} })),
    retry: false,
  });

  if (sensors.data?.length === 0) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>No records yet. Load the campaign&apos;s files in the Data panel to see its sensors diagnosed here.</p>
      </div>
    );
  }

  return (
    <div className="gk-panel gk-overview" tabIndex={0}>
      <Section id="qc" title="Quality control" query={qc}>
        {(data) => <QcTable qc={data} />}
      </Section>
      <Section id="comparison" title="Sensor comparison" query={comparison}>
        {(data) => <ComparisonPairs data={data} />}
      </Section>
      <Section id="readiness" title="MCP readiness" query={readiness}>
        {(data) => <ReadinessPairs data={data} />}
      </Section>
      <Section id="mast" title="Mast effects" query={mast}>
        {(data) => <MastEffectsTable data={data} />}
      </Section>
      <Section id="atmosphere" title="Atmospheric conditions" query={atmosphere}>
        {(data) => <AtmosphereTable data={data} />}
      </Section>
    </div>
  );
}
