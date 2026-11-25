import { type PointerEvent, useMemo, useRef, useState } from "react";

import { formatMetric, metricLabel } from "./ScenariosPanel";
import { type Range, metricValue, useFilteredRows, useInterrogate } from "./store";
import { useOpenSweep, useWidth } from "./useSweeps";
import "./interrogate.css";

const HEIGHT = 200;
const MARGIN = { left: 40, right: 12, top: 8, bottom: 28 };
const BINS = 24;
const TICKS = 5;

/** Counts of the values per equal-width bin over [lo, hi]; drawing only. */
export function binCounts(values: number[], lo: number, hi: number, bins = BINS): number[] {
  const counts = new Array<number>(bins).fill(0);
  const span = hi - lo;
  for (const value of values) {
    const k = span > 0 ? Math.min(bins - 1, Math.max(0, Math.floor(((value - lo) / span) * bins))) : 0;
    counts[k] += 1;
  }
  return counts;
}

/** The metric's histogram over the scenarios: grey is every scenario the other views let
 * through, accent the ones this view's own brush keeps too; drag to brush, Shift to add a range. */
export function DistributionPanel() {
  const metric = useInterrogate((state) => state.metric);
  const rows = useInterrogate((state) => state.rows);
  const showInadmissible = useInterrogate((state) => state.showInadmissible);
  const ranges = useInterrogate((state) => state.distribution);
  const brush = useInterrogate((state) => state.brushDistribution);
  const clear = useInterrogate((state) => state.clearDistribution);
  const sweepId = useInterrogate((state) => state.sweepId);
  const open = useOpenSweep();
  const context = useFilteredRows("distribution");
  const kept = useFilteredRows();
  const [host, width] = useWidth<HTMLDivElement>();
  const [live, setLive] = useState<Range | null>(null);
  const drag = useRef<{ at: number; extend: boolean } | null>(null);
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");

  const domain = useMemo(() => {
    const values = rows
      .filter((row) => showInadmissible || row.admissible)
      .map((row) => metricValue(row, metric))
      .filter((value): value is number => value !== null);
    if (values.length === 0) return null;
    return { lo: Math.min(...values), hi: Math.max(...values) };
  }, [rows, metric, showInadmissible]);

  const grey = useMemo(
    () => binCounts(context.map((row) => metricValue(row, metric)).filter((v): v is number => v !== null), domain?.lo ?? 0, domain?.hi ?? 0),
    [context, metric, domain],
  );
  const accent = useMemo(
    () => binCounts(kept.map((row) => metricValue(row, metric)).filter((v): v is number => v !== null), domain?.lo ?? 0, domain?.hi ?? 0),
    [kept, metric, domain],
  );

  if (sweepId === null) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>Choose a sweep in the Scenarios panel to see a metric's distribution.</p>
      </div>
    );
  }
  if (open.isError) return <div className="gk-panel"><p role="alert">{open.error.message}</p></div>;
  if (!domain) {
    return (
      <div className="gk-panel gk-panel-empty">
        <p>{open.isLoading ? "Loading the sweep…" : `No scenario has a value for ${metricLabel(metric)}.`}</p>
      </div>
    );
  }

  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const span = domain.hi - domain.lo;
  const peak = Math.max(1, ...grey);
  const xOf = (value: number) => MARGIN.left + (span > 0 ? ((value - domain.lo) / span) * plotWidth : plotWidth / 2);
  const valueAt = (clientX: number, svg: SVGSVGElement) => {
    const box = svg.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (clientX - box.left - MARGIN.left) / plotWidth));
    return domain.lo + fraction * span;
  };
  const barWidth = plotWidth / BINS;

  const onDown = (event: PointerEvent<SVGSVGElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const at = valueAt(event.clientX, event.currentTarget);
    drag.current = { at, extend: event.shiftKey };
    setLive({ min: at, max: at });
  };
  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    const current = drag.current;
    if (!current) return;
    const to = valueAt(event.clientX, event.currentTarget);
    setLive({ min: Math.min(current.at, to), max: Math.max(current.at, to) });
  };
  const onUp = () => {
    const current = drag.current;
    drag.current = null;
    const range = live;
    setLive(null);
    // A click is not a brush: a range narrower than a pixel would select nothing by accident.
    if (!current || !range || (range.max - range.min) * (plotWidth / (span || 1)) < 3) return;
    brush(range, current.extend);
  };

  const parsed = { min: Number(low), max: Number(high) };
  const valid = low.trim() !== "" && high.trim() !== "" && Number.isFinite(parsed.min) && Number.isFinite(parsed.max);
  const apply = (extend: boolean) => {
    if (!valid) return;
    brush({ min: Math.min(parsed.min, parsed.max), max: Math.max(parsed.min, parsed.max) }, extend);
  };

  const ticks = Array.from({ length: TICKS }, (_, k) => domain.lo + (span * k) / (TICKS - 1));
  const shown = live ? [...ranges, live] : ranges;

  return (
    <div
      className="gk-panel gk-interrogate"
      onKeyDown={(event) => {
        if (event.key === "Escape") clear();
      }}
    >
      <p className="gk-selection-count" aria-live="polite">
        <strong>{kept.length}</strong>
        <span className="gk-muted"> of {rows.length} scenarios in the filter, by {metricLabel(metric)}</span>
      </p>
      <div ref={host} className="gk-int-chart">
        <svg
          width={width}
          height={HEIGHT}
          className="gk-int-svg"
          role="img"
          tabIndex={0}
          aria-label={`Histogram of ${metricLabel(metric)} over ${context.length} scenarios, ${kept.length} kept by every brush${
            ranges.length ? `; ${ranges.length} range${ranges.length > 1 ? "s" : ""} brushed` : ""
          }`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={() => {
            drag.current = null;
            setLive(null);
          }}
        >
          <line x1={MARGIN.left} x2={width - MARGIN.right} y1={MARGIN.top + plotHeight} y2={MARGIN.top + plotHeight} className="gk-int-axis" />
          {grey.map((count, k) => {
            const h = (count / peak) * plotHeight;
            return (
              <g key={k}>
                <rect className="gk-hist-context" x={MARGIN.left + k * barWidth + 1} width={Math.max(0, barWidth - 2)} y={MARGIN.top + plotHeight - h} height={h} />
                <rect
                  className="gk-hist-kept"
                  x={MARGIN.left + k * barWidth + 1}
                  width={Math.max(0, barWidth - 2)}
                  y={MARGIN.top + plotHeight - (accent[k] / peak) * plotHeight}
                  height={(accent[k] / peak) * plotHeight}
                />
              </g>
            );
          })}
          {shown.map((range, k) => (
            <rect
              key={k}
              className="gk-brush"
              x={xOf(range.min)}
              width={Math.max(1, xOf(range.max) - xOf(range.min))}
              y={MARGIN.top}
              height={plotHeight}
            />
          ))}
          {ticks.map((tick) => (
            <text key={tick} className="gk-int-tick" x={xOf(tick)} y={HEIGHT - 8} textAnchor="middle">
              {formatMetric(metric, tick)}
            </text>
          ))}
          <text className="gk-int-tick" x={MARGIN.left - 6} y={MARGIN.top + 10} textAnchor="end">
            {peak}
          </text>
          <text className="gk-int-tick" x={MARGIN.left - 6} y={MARGIN.top + plotHeight} textAnchor="end">
            0
          </text>
        </svg>
      </div>
      <form
        className="gk-int-range"
        aria-label={`Brush ${metricLabel(metric)} by value`}
        onSubmit={(event) => {
          event.preventDefault();
          apply(false);
        }}
      >
        <label className="gk-field">
          Minimum
          <input type="number" step="any" value={low} onChange={(event) => setLow(event.target.value)} />
        </label>
        <label className="gk-field">
          Maximum
          <input type="number" step="any" value={high} onChange={(event) => setHigh(event.target.value)} />
        </label>
        <button type="submit" className="gk-button" disabled={!valid}>
          Brush
        </button>
        <button type="button" className="gk-button" disabled={!valid} onClick={() => apply(true)}>
          Add range
        </button>
        <button type="button" className="gk-button" disabled={ranges.length === 0} onClick={clear}>
          Clear
        </button>
      </form>
    </div>
  );
}
