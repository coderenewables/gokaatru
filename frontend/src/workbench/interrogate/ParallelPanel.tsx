import { type PointerEvent, useMemo, useRef, useState } from "react";

import { AXIS_COLUMNS, AXIS_LABELS } from "../../types/sweep";
import { formatMetric, metricLabel } from "./ScenariosPanel";
import { type Range, levelOf, levelsOf, metricValue, metricsPresent, useFilteredRows, useInterrogate, useTerms } from "./store";
import { useOpenSweep, useWidth } from "./useSweeps";
import "./interrogate.css";

const HEIGHT = 380;
const MARGIN = { left: 28, right: 28, top: 118, bottom: 26 };
const GRAB = 12;
const MIN_DRAG = 3;

interface AxisScale {
  id: string;
  label: string;
  categorical: boolean;
  /** Numeric axes: the value range; categorical axes: the levels, top to bottom. */
  lo: number;
  hi: number;
  levels: string[];
}

/** The y of a value on an axis, top of the plot being the axis's high end. */
function yOf(scale: AxisScale, value: number | string, plot: number): number {
  if (scale.categorical) {
    const k = scale.levels.indexOf(String(value));
    const n = scale.levels.length;
    return MARGIN.top + (n <= 1 ? plot / 2 : (k / (n - 1)) * plot);
  }
  const span = scale.hi - scale.lo;
  return MARGIN.top + (span > 0 ? (1 - (Number(value) - scale.lo) / span) * plot : plot / 2);
}

function valueAtY(scale: AxisScale, y: number, plot: number): number {
  const span = scale.hi - scale.lo;
  const fraction = Math.min(1, Math.max(0, (y - MARGIN.top) / plot));
  return scale.hi - fraction * span;
}

/** Parallel coordinates: each scenario as a line across the five axes and every metric. Drag
 * on an axis to brush it (Shift adds); lines outside every brush and filter are faded. */
export function ParallelPanel() {
  const sweepId = useInterrogate((state) => state.sweepId);
  const rows = useInterrogate((state) => state.rows);
  const showInadmissible = useInterrogate((state) => state.showInadmissible);
  const terms = useTerms();
  const brushRange = useInterrogate((state) => state.brushRange);
  const brushLevels = useInterrogate((state) => state.brushLevels);
  const removeTerm = useInterrogate((state) => state.removeTerm);
  const clearParallel = useInterrogate((state) => state.clearParallel);
  const open = useOpenSweep();
  const kept = useFilteredRows();
  const [host, width] = useWidth<HTMLDivElement>(720);
  const [live, setLive] = useState<{ axis: number; y0: number; y1: number } | null>(null);
  const drag = useRef<{ axis: number; y0: number; extend: boolean } | null>(null);
  const [chosen, setChosen] = useState<string>(AXIS_COLUMNS[0]);
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");

  const plot = HEIGHT - MARGIN.top - MARGIN.bottom;
  const visible = useMemo(() => rows.filter((row) => showInadmissible || row.admissible), [rows, showInadmissible]);
  const scales = useMemo<AxisScale[]>(() => {
    const categorical = AXIS_COLUMNS.map((axis) => ({
      id: axis,
      label: AXIS_LABELS[axis],
      categorical: true,
      lo: 0,
      hi: 0,
      levels: levelsOf(rows, axis),
    }));
    const numeric = metricsPresent(visible.length ? visible : rows).map((column) => {
      const values = (visible.length ? visible : rows).map((row) => metricValue(row, column)).filter((v): v is number => v !== null);
      return { id: column, label: metricLabel(column), categorical: false, lo: Math.min(...values), hi: Math.max(...values), levels: [] };
    });
    return [...categorical, ...numeric];
  }, [rows, visible]);

  const step = scales.length > 1 ? (width - MARGIN.left - MARGIN.right) / (scales.length - 1) : 0;
  const xOf = (index: number) => MARGIN.left + index * step;

  const lines = useMemo(
    () =>
      visible.map((row) => {
        const points: string[] = [];
        scales.forEach((scale, index) => {
          const value = scale.categorical ? levelOf(row, scale.id) : metricValue(row, scale.id);
          if (value === null) return;
          points.push(`${points.length === 0 ? "M" : "L"}${(MARGIN.left + index * step).toFixed(1)} ${yOf(scale, value, plot).toFixed(1)}`);
        });
        return { hash: row.config_hash, admissible: row.admissible, d: points.join(" ") };
      }),
    [visible, scales, step, plot],
  );
  const keptHashes = useMemo(() => new Set(kept.map((row) => row.config_hash)), [kept]);

  if (sweepId === null) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Choose a sweep in the Scenarios panel to see its scenarios across every axis and metric.</p>
      </div>
    );
  }
  if (open.isError) return <div className="gk-panel"><p role="alert">{open.error.message}</p></div>;
  if (rows.length === 0) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>{open.isLoading ? "Loading the sweep…" : "This sweep has no scenarios."}</p>
      </div>
    );
  }

  const axisAt = (event: PointerEvent<SVGSVGElement>): { axis: number; y: number } | null => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left;
    const index = Math.round((x - MARGIN.left) / (step || 1));
    if (index < 0 || index >= scales.length || Math.abs(x - xOf(index)) > GRAB) return null;
    return { axis: index, y: Math.min(MARGIN.top + plot, Math.max(MARGIN.top, event.clientY - box.top)) };
  };

  const onDown = (event: PointerEvent<SVGSVGElement>) => {
    const hit = axisAt(event);
    if (!hit) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { axis: hit.axis, y0: hit.y, extend: event.shiftKey };
    setLive({ axis: hit.axis, y0: hit.y, y1: hit.y });
  };
  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    const current = drag.current;
    if (!current) return;
    const box = event.currentTarget.getBoundingClientRect();
    const y = Math.min(MARGIN.top + plot, Math.max(MARGIN.top, event.clientY - box.top));
    setLive({ axis: current.axis, y0: current.y0, y1: y });
  };
  const onUp = () => {
    const current = drag.current;
    drag.current = null;
    const brush = live;
    setLive(null);
    if (!current || !brush) return;
    const scale = scales[current.axis];
    const top = Math.min(brush.y0, brush.y1);
    const bottom = Math.max(brush.y0, brush.y1);
    if (scale.categorical) {
      const inside = scale.levels.filter((level) => {
        const y = yOf(scale, level, plot);
        return y >= top && y <= bottom;
      });
      const nearest = [...scale.levels].sort(
        (a, b) => Math.abs(yOf(scale, a, plot) - (top + bottom) / 2) - Math.abs(yOf(scale, b, plot) - (top + bottom) / 2),
      )[0];
      brushLevels(scale.id, inside.length > 0 ? inside : [nearest], current.extend);
      return;
    }
    if (bottom - top < MIN_DRAG) return;
    brushRange(scale.id, { min: valueAtY(scale, bottom, plot), max: valueAtY(scale, top, plot) }, current.extend);
  };

  const target = scales.find((scale) => scale.id === chosen) ?? scales[0];
  const parsed = { min: Number(low), max: Number(high) };
  const valid = low.trim() !== "" && high.trim() !== "" && Number.isFinite(parsed.min) && Number.isFinite(parsed.max);
  const applyRange = (extend: boolean) => {
    if (!valid) return;
    brushRange(target.id, { min: Math.min(parsed.min, parsed.max), max: Math.max(parsed.min, parsed.max) }, extend);
  };
  const togglePicked = (level: string) => {
    const current = terms.picked[target.id] ?? [];
    const next = current.includes(level) ? current.filter((item) => item !== level) : [...current, level];
    if (next.length === 0) removeTerm(`picked:${target.id}`);
    else brushLevels(target.id, next);
  };

  const drawnBands = (): Array<{ x: number; y: number; height: number; key: string }> => {
    const bands: Array<{ x: number; y: number; height: number; key: string }> = [];
    scales.forEach((scale, index) => {
      if (scale.categorical) {
        const half = scale.levels.length > 1 ? plot / (scale.levels.length - 1) / 2 : plot / 2;
        for (const level of terms.picked[scale.id] ?? []) {
          const y = yOf(scale, level, plot);
          bands.push({ x: xOf(index), y: Math.max(MARGIN.top, y - half), height: Math.min(2 * half, MARGIN.top + plot - Math.max(MARGIN.top, y - half)), key: `${scale.id}-${level}` });
        }
      } else {
        (terms.ranges[scale.id] ?? []).forEach((range: Range, k: number) => {
          const top = yOf(scale, range.max, plot);
          bands.push({ x: xOf(index), y: top, height: Math.max(2, yOf(scale, range.min, plot) - top), key: `${scale.id}-${k}` });
        });
      }
    });
    return bands;
  };
  const anyTerm = Object.keys(terms.ranges).length + Object.keys(terms.picked).length > 0;
  const keptLines = lines.filter((line) => keptHashes.has(line.hash));

  return (
    <div
      className="gk-panel gk-interrogate"
      onKeyDown={(event) => {
        if (event.key === "Escape") clearParallel();
      }}
    >
      <p className="gk-selection-count" aria-live="polite">
        <strong>{kept.length}</strong>
        <span className="gk-muted"> of {rows.length} scenarios in the filter</span>
      </p>
      <div ref={host} className="gk-int-chart">
        <svg
          width={width}
          height={HEIGHT}
          className="gk-int-svg gk-parallel"
          role="img"
          tabIndex={0}
          aria-label={`Parallel coordinates of ${rows.length} scenarios across ${scales.length} axes; ${keptLines.length} kept${
            anyTerm ? ", with brushes drawn" : ""
          }`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={() => {
            drag.current = null;
            setLive(null);
          }}
        >
          <g className="gk-lines-faded">
            {lines
              .filter((line) => !keptHashes.has(line.hash))
              .map((line) => (
                <path key={line.hash} d={line.d} className="gk-line gk-line-faded" />
              ))}
          </g>
          <g className="gk-lines-kept">
            {keptLines.map((line) => (
              <path key={line.hash} d={line.d} className={line.admissible ? "gk-line gk-line-kept" : "gk-line gk-line-ghost"} />
            ))}
          </g>
          {scales.map((scale, index) => (
            <g key={scale.id}>
              <line className="gk-int-axis" x1={xOf(index)} x2={xOf(index)} y1={MARGIN.top} y2={MARGIN.top + plot} />
              <text className="gk-axis-title" transform={`translate(${xOf(index) + 4} ${MARGIN.top - 20}) rotate(-50)`}>
                {scale.label}
              </text>
              {scale.categorical ? (
                scale.levels.map((level) => (
                  <text key={level} className="gk-int-tick" x={xOf(index) + 4} y={yOf(scale, level, plot) + 3}>
                    {level.length > 9 ? `${level.slice(0, 8)}…` : level}
                  </text>
                ))
              ) : (
                <>
                  <text className="gk-int-tick" x={xOf(index)} y={MARGIN.top - 5} textAnchor="middle">
                    {formatMetric(scale.id, scale.hi)}
                  </text>
                  <text className="gk-int-tick" x={xOf(index)} y={MARGIN.top + plot + 14} textAnchor="middle">
                    {formatMetric(scale.id, scale.lo)}
                  </text>
                </>
              )}
            </g>
          ))}
          {drawnBands().map((band) => (
            <rect key={band.key} className="gk-brush" x={band.x - 5} width={10} y={band.y} height={band.height} />
          ))}
          {live && Math.abs(live.y1 - live.y0) > 0 && (
            <rect
              className="gk-brush"
              x={xOf(live.axis) - 5}
              width={10}
              y={Math.min(live.y0, live.y1)}
              height={Math.abs(live.y1 - live.y0)}
            />
          )}
        </svg>
      </div>
      <div className="gk-int-range" role="group" aria-label="Brush an axis by keyboard">
        <label className="gk-field">
          Axis
          <select value={target.id} onChange={(event) => setChosen(event.target.value)}>
            {scales.map((scale) => (
              <option key={scale.id} value={scale.id}>
                {scale.label}
              </option>
            ))}
          </select>
        </label>
        {target.categorical ? (
          <div className="gk-int-levels-pick" role="group" aria-label={`Levels of ${target.label}`}>
            {target.levels.map((level) => (
              <button
                key={level}
                type="button"
                className="gk-button"
                aria-pressed={(terms.picked[target.id] ?? []).includes(level)}
                onClick={() => togglePicked(level)}
              >
                {level}
              </button>
            ))}
          </div>
        ) : (
          <>
            <label className="gk-field">
              Minimum
              <input type="number" step="any" value={low} onChange={(event) => setLow(event.target.value)} />
            </label>
            <label className="gk-field">
              Maximum
              <input type="number" step="any" value={high} onChange={(event) => setHigh(event.target.value)} />
            </label>
            <button type="button" className="gk-button" disabled={!valid} onClick={() => applyRange(false)}>
              Brush axis
            </button>
            <button type="button" className="gk-button" disabled={!valid} onClick={() => applyRange(true)}>
              Add range
            </button>
          </>
        )}
        <button type="button" className="gk-button" disabled={!anyTerm} onClick={clearParallel}>
          Clear brushes
        </button>
      </div>
    </div>
  );
}
