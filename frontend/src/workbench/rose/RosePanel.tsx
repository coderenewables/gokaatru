import { useDroppable } from "@dnd-kit/core";
import { useQuery } from "@tanstack/react-query";
import { type PointerEvent, useMemo, useRef } from "react";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { useCharts } from "../charts/store";
import { instrumentsKey } from "../datatree/DataPanel";
import type { ChartDrop } from "../dnd";
import { useSelection, useSharedSelection } from "../selection/store";
import { useCampaign } from "../shell/context";
import { useRuleDraft } from "../flags/draft";
import { LABELS, SECTORS, bearingOf, contiguousBounds, sectorOf, sectorsOf, termOf, toggled, wedge } from "./geometry";
import "./rose.css";

type Instrument = Schemas["Instrument"];
const RADIUS = 100;

/** The vane the rose reads by default: the highest in the data. The speed beside it, for the
 * sector means: the cup at the same height, else the highest cup. */
export function defaultChannels(instruments: Instrument[]): { direction: string | null; speed: string | null } {
  const present = instruments.filter((instrument) => instrument.in_data);
  const vanes = present.filter((instrument) => instrument.sensor_type === "wind_direction");
  const cups = present.filter((instrument) => instrument.sensor_type === "wind_speed");
  const direction = vanes[0] ?? null;
  const beside = direction ? cups.find((cup) => cup.height_m === direction.height_m) : undefined;
  return { direction: direction?.name ?? null, speed: (beside ?? cups[0])?.name ?? null };
}

function windrose(sessionId: string, speed: string, direction: string, selection: string) {
  return async () =>
    unwrap(
      await api.POST("/api/sessions/{session_id}/operations/compute_windrose_data", {
        params: { path: { session_id: sessionId } },
        body: { speed_sensor: speed, direction_sensor: direction, num_sectors: SECTORS, selection },
      }),
    );
}

/** The wind rose: direction frequency of every record, the shared selection's over it, and
 * sector clicks as the rose's term of the crossfilter (plan §3.3 "Wind rose"). */
export function RosePanel() {
  const { sessionId } = useCampaign();
  const chosen = useCharts((state) => state.rose);
  const setRose = useCharts((state) => state.setRose);
  const term = useSelection((state) => state.terms.rose);
  const draw = useSelection((state) => state.draw);
  const clear = useSelection((state) => state.clear);
  const selection = useSharedSelection();

  const instruments = useQuery({
    queryKey: instrumentsKey(sessionId),
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/list_instruments", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
  });
  const listed = instruments.data?.instruments ?? [];
  const defaults = defaultChannels(listed);
  const direction = chosen ?? defaults.direction;
  const speed = defaults.speed;
  const vanes = listed.filter((instrument) => instrument.in_data && instrument.sensor_type === "wind_direction");

  const all = useQuery({
    queryKey: ["windrose", sessionId, speed, direction, ""],
    enabled: Boolean(speed && direction),
    queryFn: windrose(sessionId, speed ?? "", direction ?? "", ""),
  });
  const selected = useQuery({
    queryKey: ["windrose", sessionId, speed, direction, selection],
    enabled: Boolean(speed && direction && selection),
    queryFn: windrose(sessionId, speed ?? "", direction ?? "", selection),
  });

  const { setNodeRef, isOver } = useDroppable({ id: "rose-drop", data: { kind: "rose" } satisfies ChartDrop });
  const picked = direction ? sectorsOf(term, direction) : [];
  const shadow = contiguousBounds(picked);
  const propose = useRuleDraft((state) => state.propose);
  const dragged = useRef<{ start: number; visited: Set<number>; extend: boolean } | null>(null);

  const scale = useMemo(() => {
    const frequencies = (all.data?.sectors ?? []).map((sector) => sector.frequency_pct ?? 0);
    return Math.max(1e-9, ...frequencies);
  }, [all.data]);

  const pick = (sectors: number[]) => {
    if (!direction) return;
    const next = termOf(sectors, direction);
    if (next === null) clear("rose");
    else draw("rose", next);
  };

  const sectorAt = (event: PointerEvent<SVGSVGElement>): number | null => {
    const box = event.currentTarget.getBoundingClientRect();
    const dx = event.clientX - (box.left + box.width / 2);
    const dy = event.clientY - (box.top + box.height / 2);
    if (Math.hypot(dx, dy) < 6) return null;
    return sectorOf(bearingOf(dx, dy));
  };

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    const k = sectorAt(event);
    if (k === null) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragged.current = { start: k, visited: new Set([k]), extend: event.shiftKey };
  };
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!dragged.current) return;
    const k = sectorAt(event);
    if (k !== null) dragged.current.visited.add(k);
  };
  const onPointerUp = () => {
    const drag = dragged.current;
    dragged.current = null;
    if (!drag) return;
    if (drag.visited.size === 1) {
      pick(toggled(picked, drag.start, drag.extend));
      return;
    }
    const visited = [...drag.visited];
    pick(drag.extend ? [...new Set([...picked, ...visited])].sort((a, b) => a - b) : visited.sort((a, b) => a - b));
  };

  if (instruments.data && !direction) {
    return <div className="gk-panel gk-panel-empty"><p>No wind vane in the data, so there is no rose to draw.</p></div>;
  }
  const failed = all.error ?? selected.error;
  const sectors = all.data?.sectors ?? [];
  const selectedSectors = selected.data?.sectors ?? [];
  const label = `Wind rose of ${direction ?? "direction"}: frequency by ${SECTORS} sectors of every record${
    selection ? ", the selection over it" : ""
  }${picked.length ? `; ${picked.map((k) => LABELS[k]).join(", ")} selected` : ""}`;

  return (
    <div ref={setNodeRef} className={isOver ? "gk-panel gk-rose gk-drop-over" : "gk-panel gk-rose"}>
      <div className="gk-rose-controls">
        <label>
          Vane{" "}
          <select value={direction ?? ""} onChange={(event) => setRose(event.target.value)}>
            {vanes.map((vane) => (
              <option key={vane.name} value={vane.name}>
                {vane.name}
              </option>
            ))}
          </select>
        </label>
        {speed && <span className="gk-muted">mean speed from {speed}</span>}
      </div>
      {failed && <p role="alert">{failed.message}</p>}
      <svg
        viewBox={`${-RADIUS - 20} ${-RADIUS - 20} ${2 * RADIUS + 40} ${2 * RADIUS + 40}`}
        className="gk-rose-chart"
        role="img"
        aria-label={label}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (dragged.current = null)}
        onKeyDown={(event) => {
          if (event.key === "Escape") clear("rose");
        }}
      >
        <circle r={RADIUS / 2} className="gk-rose-ring" />
        <circle r={RADIUS} className="gk-rose-ring" />
        {picked.map((k) => (
          <path key={`picked-${k}`} d={wedge(k, RADIUS)} className="gk-rose-picked" />
        ))}
        {sectors.map((sector, k) => (
          <path key={`all-${k}`} d={wedge(k, (RADIUS * (sector.frequency_pct ?? 0)) / scale)} className="gk-rose-all" />
        ))}
        {selection &&
          selectedSectors.map((sector, k) => (
            <path
              key={`sel-${k}`}
              d={wedge(k, (RADIUS * (sector.frequency_pct ?? 0) * selectedShare(selected.data)) / scale)}
              className="gk-rose-selected"
            />
          ))}
        <text y={-RADIUS - 6} className="gk-rose-label">N</text>
        <text x={RADIUS + 10} y={4} className="gk-rose-label">E</text>
        <text y={RADIUS + 14} className="gk-rose-label">S</text>
        <text x={-RADIUS - 10} y={4} className="gk-rose-label">W</text>
      </svg>
      <div className="gk-rose-sectors" role="group" aria-label="Sectors">
        {LABELS.map((name, k) => (
          <button
            key={name}
            type="button"
            aria-pressed={picked.includes(k)}
            onClick={(event) => pick(toggled(picked, k, event.shiftKey))}
          >
            {name}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="gk-button"
        disabled={!shadow || !speed}
        title={shadow ? undefined : "Select one run of adjacent sectors first"}
        onClick={() => {
          if (!shadow || !speed) return;
          propose({
            rule_type: "tower_shadow",
            sensor: speed,
            params: { exclude_sectors: shadow },
            label: `Tower shadow on ${speed}: directions ${shadow[0]}° to ${shadow[1]}°, read from the vane paired with ${speed} in the data model. Unlike a selected sector, tower_shadow includes ${shadow[1]}° itself.`,
          });
        }}
      >
        Make a tower-shadow rule
      </button>
    </div>
  );
}

/** The selection's sector frequencies are percentages of its own records; scaled by its share
 * of every record, its wedges sit inside the full rose's. */
function selectedShare(result: Schemas["ComputeWindroseDataResult"] | undefined): number {
  const used = result?.selection;
  return used && used.of_records > 0 ? used.records / used.of_records : 1;
}
