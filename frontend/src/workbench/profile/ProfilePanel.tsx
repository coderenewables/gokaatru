import { useQuery } from "@tanstack/react-query";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { useSharedSelection } from "../selection/store";
import { speedChannels, useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import "./profile.css";

type Structure = Schemas["ComputeVerticalStructureResult"];
type Point = { height: number; speed: number };

const WIDTH = 260;
const HEIGHT = 220;
const MARGIN = { left: 40, right: 12, top: 10, bottom: 30 };

export function profilePoints(result: Structure | undefined): Point[] {
  return (result?.mean_profile ?? [])
    .flatMap((point) =>
      point.height_m === null || point.mean_speed === null ? [] : [{ height: point.height_m, speed: point.mean_speed }],
    )
    .sort((a, b) => a.height - b.height);
}

/** Axis bounds holding both profiles: speed from 0, height from 0, each to a round top. */
export function profileBounds(...profiles: Point[][]): { speed: number; height: number } {
  const points = profiles.flat();
  const top = (value: number, step: number) => Math.max(step, Math.ceil((value * 1.05) / step) * step);
  return {
    speed: top(Math.max(0, ...points.map((point) => point.speed)), 2),
    height: top(Math.max(0, ...points.map((point) => point.height)), 20),
  };
}

function structure(sessionId: string, selection: string) {
  return async () =>
    unwrap(
      await api.POST("/api/sessions/{session_id}/operations/compute_vertical_structure", {
        params: { path: { session_id: sessionId } },
        body: { speed_sensors: "", selection },
      }),
    );
}

const alpha = (value: number | null | undefined) => (value === null || value === undefined ? "—" : value.toFixed(3));

/** The measured profile (P2-17): mean speed by height over the records where every height is
 * valid, for every record and for the shared selection, with each power-law exponent. */
export function ProfilePanel() {
  const { sessionId } = useCampaign();
  const selection = useSharedSelection();
  const sensors = useSensors(sessionId);
  const speeds = speedChannels(sensors.data ?? []).length;
  const all = useQuery({ queryKey: ["profile", sessionId, ""], enabled: speeds > 0, queryFn: structure(sessionId, "") });
  const selected = useQuery({
    queryKey: ["profile", sessionId, selection],
    enabled: speeds > 0 && selection !== "",
    queryFn: structure(sessionId, selection),
  });

  if (sensors.data !== undefined && speeds === 0) {
    return <div className="gk-panel gk-panel-empty"><p>No wind speed channel in the data, so there is no profile to draw.</p></div>;
  }
  if (all.isError) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>{all.error.message}</p>
      </div>
    );
  }
  const every = profilePoints(all.data);
  const chosen = selection ? profilePoints(selected.data) : [];
  const bounds = profileBounds(every, chosen);
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (speed: number) => MARGIN.left + (speed / bounds.speed) * plotWidth;
  const y = (height: number) => MARGIN.top + plotHeight - (height / bounds.height) * plotHeight;
  const line = (points: Point[]) => points.map((point) => `${x(point.speed)},${y(point.height)}`).join(" ");
  const speedTicks = Array.from({ length: 5 }, (_, i) => (bounds.speed * i) / 4);
  const heightTicks = Array.from({ length: 5 }, (_, i) => (bounds.height * i) / 4);
  const label = `Mean speed by height${every.length ? `: ${every.map((p) => `${p.height} m ${p.speed.toFixed(2)} m/s`).join(", ")}` : ""}${
    chosen.length ? `; selection ${chosen.map((p) => `${p.height} m ${p.speed.toFixed(2)} m/s`).join(", ")}` : ""
  }`;

  return (
    <div className="gk-panel gk-profile">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="gk-profile-chart" role="img" aria-label={label}>
        {speedTicks.map((tick) => (
          <g key={`s${tick}`}>
            <line x1={x(tick)} x2={x(tick)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} className="gk-profile-grid" />
            <text x={x(tick)} y={HEIGHT - 14} className="gk-profile-tick">{tick.toFixed(0)}</text>
          </g>
        ))}
        {heightTicks.map((tick) => (
          <g key={`h${tick}`}>
            <line x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(tick)} y2={y(tick)} className="gk-profile-grid" />
            <text x={MARGIN.left - 6} y={y(tick) + 4} className="gk-profile-tick gk-profile-tick-y">{tick.toFixed(0)}</text>
          </g>
        ))}
        <text x={MARGIN.left + plotWidth / 2} y={HEIGHT - 2} className="gk-profile-tick">mean speed, m/s</text>
        <polyline points={line(every)} className="gk-profile-all" />
        {every.map((point) => (
          <circle key={`a${point.height}`} cx={x(point.speed)} cy={y(point.height)} r={3} className="gk-profile-all-point" />
        ))}
        {chosen.length > 0 && <polyline points={line(chosen)} className="gk-profile-selected" />}
        {chosen.map((point) => (
          <circle key={`s${point.height}`} cx={x(point.speed)} cy={y(point.height)} r={3.5} className="gk-profile-selected-point" />
        ))}
      </svg>
      <table className="gk-compare">
        <caption className="gk-muted">Over records where every height is valid</caption>
        <thead>
          <tr>
            <th scope="col">Records</th>
            <th scope="col">Power-law α</th>
            <th scope="col">Used</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Every record</th>
            <td>{alpha(all.data?.power_law_alpha)}</td>
            <td>{all.data ? `${all.data.records_used} of ${all.data.records_available}` : "…"}</td>
          </tr>
          {selection && (
            <tr>
              <th scope="row">Selection</th>
              <td>{selected.isError ? "—" : alpha(selected.data?.power_law_alpha)}</td>
              <td>{selected.isError ? "none valid at every height" : selected.data ? `${selected.data.records_used}` : "…"}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
