import { useDroppable } from "@dnd-kit/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview-react";
import createScatterplot from "regl-scatterplot";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import type { ChartDrop } from "../dnd";
import { useCharts } from "../charts/store";
import { speedChannels, useSensors } from "../sensors";
import { useSelection, useSharedSelection, type Polygon } from "../selection/store";
import { useCampaign } from "../shell/context";
import { lassoPolygon, ticks, toScreenX, toScreenY, type Box, type Vertex } from "./geometry";
import { decodePairs, plotPoints, polygonsOf, rangesFor, type Pairs } from "./pairs";
import "./scatter.css";

async function fetchPairs(sessionId: string, x: string, y: string, highlight: string): Promise<Pairs> {
  const response = await fetch(`/api/sessions/${sessionId}/pairs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-GoKaatru-Session": sessionId },
    body: JSON.stringify({ x_channel: x, y_channel: y, start: "", end: "", highlight }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `The pairs request failed (${response.status})`);
  }
  return decodePairs(await response.arrayBuffer());
}

/** The tokens the points are drawn in; WebGL cannot read CSS variables, so they are read
 * from the document and read again when the theme changes. */
function readPalette() {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return { muted: token("--gk-series-4"), accent: token("--gk-accent"), surface: token("--gk-surface") };
}

function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setVersion((value) => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return version;
}

function AxisPicker({
  axis,
  label,
  value,
  channels,
  shown,
  onChange,
}: {
  axis: "x" | "y";
  label: string;
  value: string;
  channels: string[];
  shown: { x: string; y: string };
  onChange: (channel: string) => void;
}) {
  const drop: ChartDrop = { kind: "scatter", axis, shown };
  const { setNodeRef, isOver } = useDroppable({ id: `scatter-${axis}-drop`, data: drop });
  return (
    <div ref={setNodeRef} className={`gk-scatter-axis${isOver ? " gk-scatter-drop" : ""}`}>
      <label>
        <span>{label}</span>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          {channels.map((channel) => (
            <option key={channel} value={channel}>
              {channel}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

const path = (points: Vertex[]) => points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ") + " Z";

export function ScatterPanel(_props: IDockviewPanelProps) {
  const { sessionId } = useCampaign();
  const sensors = useSensors(sessionId);
  const rows = sensors.data ?? [];
  const channels = rows.map((row) => row.name);
  const speeds = speedChannels(rows);
  const chosen = useCharts((state) => state.scatter);
  const setAxis = useCharts((state) => state.setScatterAxis);
  const x = chosen?.x ?? speeds[1] ?? speeds[0] ?? "";
  const y = chosen?.y ?? speeds[0] ?? "";
  const shown = { x, y };
  const bothSpeeds = speeds.includes(x) && speeds.includes(y);

  const selection = useSharedSelection();
  const term = useSelection((state) => state.terms.scatter);
  const draw = useSelection((state) => state.draw);
  const clear = useSelection((state) => state.clear);

  const pairs = useQuery({
    queryKey: ["pairs", sessionId, x, y, selection],
    enabled: x !== "" && y !== "",
    queryFn: () => fetchPairs(sessionId, x, y, selection),
    placeholderData: keepPreviousData,
  });
  const data = pairs.data && pairs.data.meta.x_channel === x && pairs.data.meta.y_channel === y ? pairs.data : undefined;
  const ranges = useMemo(() => (data ? rangesFor(data, bothSpeeds) : null), [data, bothSpeeds]);

  const ready = channels.length >= 2;
  const plotRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scatterRef = useRef<ReturnType<typeof createScatterplot> | null>(null);
  const [box, setBox] = useState<Box>({ width: 0, height: 0 });
  const theme = useThemeVersion();
  const [trail, setTrail] = useState<Vertex[] | null>(null);
  const trailRef = useRef<Vertex[] | null>(null);
  const extendRef = useRef(false);

  useEffect(() => {
    const element = plotRef.current;
    if (!element) return;
    const measure = () => setBox({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ready]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const palette = readPalette();
    // The camera is fixed and the library's own lasso, pan and zoom are unreachable: the
    // canvas takes no pointer events, so a drag over the plot is always this panel's lasso.
    const scatter = createScatterplot({
      canvas,
      width: Math.max(box.width, 1),
      height: Math.max(box.height, 1),
      aspectRatio: Math.max(box.width, 1) / Math.max(box.height, 1),
      cameraIsFixed: true,
      deselectOnEscape: false,
      deselectOnDblClick: false,
      backgroundColor: palette.surface,
      pointColor: [palette.muted, palette.accent],
      pointColorActive: palette.accent,
      colorBy: "category",
      pointSize: 3,
      opacity: 0.55,
    });
    scatterRef.current = scatter;
    return () => {
      scatter.destroy();
      scatterRef.current = null;
    };
    // The plot's size is applied by the effect below; the instance is made once per canvas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  useEffect(() => {
    const scatter = scatterRef.current;
    if (!scatter || box.width < 2 || box.height < 2) return;
    const palette = readPalette();
    void scatter.set({
      width: box.width,
      height: box.height,
      aspectRatio: box.width / box.height,
      backgroundColor: palette.surface,
      pointColor: [palette.muted, palette.accent],
      pointColorActive: palette.accent,
    });
  }, [box, theme]);

  // regl-scatterplot refuses, with a rejected promise, a draw issued while the previous one
  // is still running; draws are queued so each starts after the last, and a queued draw for
  // a scatterplot since destroyed is dropped.
  const drawing = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    const scatter = scatterRef.current;
    if (!scatter || !data || !ranges || box.width < 2) return;
    const points = plotPoints(data, ranges.x, ranges.y);
    drawing.current = drawing.current.then(async () => {
      if (scatterRef.current !== scatter) return;
      await scatter.draw({ x: points.x, y: points.y, category: points.category });
    });
  }, [data, ranges, box, theme]);

  const polygons: Polygon[] = polygonsOf(term, x, y);

  const finish = () => {
    const drawn = trailRef.current;
    trailRef.current = null;
    setTrail(null);
    if (!drawn || !ranges) return;
    const polygon = lassoPolygon(drawn, ranges.x, ranges.y, box);
    if (!polygon) {
      clear("scatter");
      return;
    }
    draw("scatter", { kind: "polygon", x_channel: x, y_channel: y, vertices: polygon }, extendRef.current);
  };

  const local = (event: PointerEvent<SVGSVGElement>): Vertex => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0 || !ranges) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    extendRef.current = event.shiftKey;
    trailRef.current = [local(event)];
    setTrail([local(event)]);
    plotRef.current?.parentElement?.focus();
  };
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const current = trailRef.current;
    if (!current) return;
    current.push(local(event));
    setTrail(current.slice());
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") clear("scatter");
  };

  const total = data?.meta.window_records;
  const records = data?.meta.records;
  const highlighted = data?.meta.highlight?.records;
  const caption =
    data === undefined
      ? pairs.isError
        ? pairs.error.message
        : "Loading pairs"
      : `${records} of ${total} records with both channels${highlighted === undefined ? "" : `, ${highlighted} highlighted`}`;

  if (!ready) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Two channels against each other. Lasso the points that disagree.</p>
      </div>
    );
  }

  const xTicks = ranges ? ticks(ranges.x) : [];
  const yTicks = ranges ? ticks(ranges.y) : [];
  return (
    <div className="gk-panel gk-scatter">
      <div className="gk-scatter-controls">
        <AxisPicker axis="x" label="X axis" value={x} channels={channels} shown={shown} onChange={(c) => setAxis("x", c, shown)} />
        <AxisPicker axis="y" label="Y axis" value={y} channels={channels} shown={shown} onChange={(c) => setAxis("y", c, shown)} />
      </div>
      <div
        className="gk-scatter-frame"
        tabIndex={0}
        role="img"
        aria-label={`Scatter of ${y} against ${x}. ${caption}. Drag to lasso points, Shift to add, Escape to clear.`}
        onKeyDown={onKeyDown}
      >
        <div className="gk-scatter-plot" ref={plotRef}>
          <canvas ref={canvasRef} className="gk-scatter-canvas" />
          {ranges && box.width > 0 ? (
            <>
              <div className="gk-scatter-ticks" aria-hidden="true">
                {xTicks.map((tick) => (
                  <span key={`x${tick}`} className="gk-scatter-tick-x" style={{ left: toScreenX(tick, ranges.x, box) }}>
                    {tick}
                  </span>
                ))}
                {yTicks.map((tick) => (
                  <span key={`y${tick}`} className="gk-scatter-tick-y" style={{ top: toScreenY(tick, ranges.y, box) }}>
                    {tick}
                  </span>
                ))}
                <span className="gk-scatter-title-x">{x}</span>
                <span className="gk-scatter-title-y">{y}</span>
              </div>
              <svg
                className="gk-scatter-overlay"
                width={box.width}
                height={box.height}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={finish}
                onPointerCancel={() => {
                  trailRef.current = null;
                  setTrail(null);
                }}
                data-x-hi={ranges.x.hi}
                data-y-hi={ranges.y.hi}
                data-testid="scatter-overlay"
              >
                {xTicks.map((tick) => (
                  <line key={`gx${tick}`} className="gk-scatter-grid" x1={toScreenX(tick, ranges.x, box)} x2={toScreenX(tick, ranges.x, box)} y1={0} y2={box.height} />
                ))}
                {yTicks.map((tick) => (
                  <line key={`gy${tick}`} className="gk-scatter-grid" y1={toScreenY(tick, ranges.y, box)} y2={toScreenY(tick, ranges.y, box)} x1={0} x2={box.width} />
                ))}
                {bothSpeeds ? (
                  <line
                    className="gk-scatter-diagonal"
                    x1={toScreenX(ranges.x.lo, ranges.x, box)}
                    y1={toScreenY(ranges.y.lo, ranges.y, box)}
                    x2={toScreenX(ranges.x.hi, ranges.x, box)}
                    y2={toScreenY(ranges.y.hi, ranges.y, box)}
                  />
                ) : null}
                {polygons.map((polygon, i) => (
                  <path
                    key={i}
                    className="gk-scatter-lasso"
                    d={path(polygon.vertices.map(([vx, vy]) => [toScreenX(vx, ranges.x, box), toScreenY(vy, ranges.y, box)] as Vertex))}
                  />
                ))}
                {trail ? <path className="gk-scatter-lasso gk-scatter-lasso-live" d={path(trail)} /> : null}
              </svg>
            </>
          ) : null}
        </div>
      </div>
      <p className="gk-scatter-caption gk-muted" aria-live="polite">
        {caption}
      </p>
    </div>
  );
}
