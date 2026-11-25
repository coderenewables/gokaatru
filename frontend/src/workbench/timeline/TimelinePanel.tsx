import { useDroppable } from "@dnd-kit/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { useCharts } from "../charts/store";
import type { ChartDrop } from "../dnd";
import { useFlagFocus } from "../flags/store";
import { useSelection } from "../selection/store";
import { speedChannels, useSensors } from "../sensors";
import { useCampaign } from "../shell/context";
import {
  adjacentBand,
  bandAt,
  brushTerm,
  CLICK_PIXELS,
  DEFAULT_STEP_MS,
  type FlagBand,
  flagLine,
  plotData,
  termExtent,
  termRanges,
  withAlpha,
  zoomWindow,
} from "./helpers";
import { fetchFlagBands, fetchSeries, flagsKey, seriesKey } from "./queries";
import "./timeline.css";

const DEBOUNCE_MS = 150;
const WHEEL_STEP = 0.8;
const MAX_BUCKETS = 20000;
const MIN_BUCKETS = 50;
/** Widths round to this many pixels so a resize that changes nothing visible refetches nothing. */
const BUCKET_ROUNDING = 50;
const ENVELOPE_ALPHA = 0.28;

interface Palette {
  series: string[];
  text: string;
  muted: string;
  border: string;
  select: string;
  flagSoft: string;
}

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    series: [1, 2, 3, 4, 5, 6].map((n) => read(`--gk-series-${n}`)),
    text: read("--gk-text"),
    muted: read("--gk-muted"),
    border: read("--gk-border"),
    select: read("--gk-select-soft"),
    flagSoft: read("--gk-flag-soft"),
  };
}

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

/** Bumps when the theme attribute on <html> changes, so colours are read again. */
function useThemeTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setTick((value) => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return tick;
}

const iso = (ms: number) => new Date(ms).toISOString();
const stamp = (ms: number) => iso(ms).slice(0, 16).replace("T", " ");

/** Every channel over time as its min/max envelope (decisions/0005): the window on screen is
 * fetched at one bucket per pixel and fetched again when the analyst zooms. */
export function TimelinePanel() {
  const { sessionId } = useCampaign();
  const sensors = useSensors(sessionId);
  const chosen = useCharts((state) => state.timeline);
  const addToTimeline = useCharts((state) => state.addToTimeline);
  const removeFromTimeline = useCharts((state) => state.removeFromTimeline);
  const term = useSelection((state) => state.terms.timeline);
  const draw = useSelection((state) => state.draw);
  const clear = useSelection((state) => state.clear);
  const focusFlag = useFlagFocus((state) => state.focus);
  const themeTick = useThemeTick();

  const shown = useMemo(() => chosen ?? speedChannels(sensors.data ?? []), [chosen, sensors.data]);
  const shownKey = shown.join(",");

  const [view, setView] = useState<[number, number] | null>(null);
  const [extent, setExtent] = useState<[number, number] | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [chart, setChart] = useState<uPlot | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [pick, setPick] = useState("");

  const plotRef = useRef<HTMLDivElement | null>(null);
  const ranges = useMemo(() => termRanges(term), [term]);
  const live = useRef({ ranges, bands: [] as FlagBand[], palette: readPalette(), extent });
  const down = useRef({ x: 0, shift: false });
  const wheelTimer = useRef<number | undefined>(undefined);

  const { setNodeRef, isOver } = useDroppable({
    id: "timeline-drop",
    data: { kind: "timeline", shown } satisfies ChartDrop,
  });

  const buckets = useDebounced(
    Math.min(MAX_BUCKETS, Math.max(MIN_BUCKETS, Math.round(size.width / BUCKET_ROUNDING) * BUCKET_ROUNDING)),
    DEBOUNCE_MS,
  );
  const start = view ? iso(view[0]) : "";
  const end = view ? iso(view[1]) : "";

  const series = useQuery({
    queryKey: [...seriesKey(sessionId), shownKey, start, end, buckets],
    enabled: shown.length > 0 && size.width > 0,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => fetchSeries(sessionId, shown, start, end, buckets, signal),
  });
  const data = series.data && series.data.meta.channels.join(",") === shownKey ? series.data : undefined;

  const bounds = data ? ([data.meta.start_ms, data.meta.end_ms] as [number, number]) : null;
  const stepMs =
    data && !data.meta.decimated && data.times.length > 1 ? (data.times[1] - data.times[0]) * 1000 : DEFAULT_STEP_MS;
  const flags = useQuery({
    queryKey: [...flagsKey(sessionId), shownKey, bounds?.[0], bounds?.[1], stepMs],
    enabled: bounds !== null,
    placeholderData: keepPreviousData,
    queryFn: () => fetchFlagBands(sessionId, shown, iso(bounds![0]), iso(bounds![1]), stepMs),
  });

  useEffect(() => {
    if (data && view === null) setExtent([data.meta.start_ms, data.meta.end_ms]);
  }, [data, view]);

  // The chart's hooks read what changes between draws through this ref, so a new term or flag
  // set is a redraw rather than a new chart.
  useEffect(() => {
    live.current = { ...live.current, ranges, bands: flags.data ?? [], extent };
    if (chart?.data[0]?.length) chart.redraw(false);
  }, [ranges, flags.data, extent, chart]);

  // The chart: rebuilt when its channels or the theme change, resized in place.
  useEffect(() => {
    const host = plotRef.current;
    if (!host || shown.length === 0) return;
    const palette = readPalette();
    live.current.palette = palette;
    const colour = (index: number) => palette.series[index % palette.series.length];
    const axis = {
      stroke: palette.muted,
      grid: { stroke: palette.border, width: 1 },
      ticks: { stroke: palette.border, width: 1 },
    };
    const rect = host.getBoundingClientRect();
    const plot = new uPlot(
      {
        width: Math.max(100, Math.floor(rect.width)),
        height: Math.max(60, Math.floor(rect.height)),
        legend: { show: false },
        padding: [8, 8, 0, 0],
        cursor: { drag: { x: true, y: false, setScale: false }, points: { show: false } },
        scales: { x: { time: true } },
        axes: [
          { ...axis, font: "12px system-ui" },
          { ...axis, font: "12px system-ui", size: 48 },
        ],
        series: [
          { label: "Time" },
          ...shown.flatMap((channel, index) =>
            (["min", "max"] as const).map((edge) => ({
              label: `${channel} ${edge}`,
              stroke: colour(index),
              width: 1,
              spanGaps: false,
              points: { show: false },
            })),
          ),
        ],
        bands: shown.map((_, index) => ({
          series: [2 + 2 * index, 1 + 2 * index] as [number, number],
          fill: withAlpha(colour(index), ENVELOPE_ALPHA),
        })),
        tzDate: (seconds) => uPlot.tzDate(new Date(seconds * 1e3), "Etc/UTC"),
        hooks: {
          drawClear: [
            (u) => {
              const { bands, palette: colours } = live.current;
              const { left, top, width, height } = u.bbox;
              u.ctx.save();
              u.ctx.beginPath();
              u.ctx.rect(left, top, width, height);
              u.ctx.clip();
              u.ctx.fillStyle = colours.flagSoft;
              for (const band of bands) {
                const x0 = u.valToPos(band.start / 1000, "x", true);
                const x1 = u.valToPos(band.end / 1000, "x", true);
                // A band narrower than a pixel stays visible.
                u.ctx.fillRect(x0, top, Math.max(x1 - x0, 1), height);
              }
              u.ctx.restore();
            },
          ],
          draw: [
            (u) => {
              const { ranges: shaded, palette: colours } = live.current;
              const { left, top, width, height } = u.bbox;
              u.ctx.save();
              u.ctx.beginPath();
              u.ctx.rect(left, top, width, height);
              u.ctx.clip();
              u.ctx.fillStyle = colours.select;
              for (const [from, to] of shaded) {
                const x0 = Number.isFinite(from) ? u.valToPos(from / 1000, "x", true) : left;
                const x1 = Number.isFinite(to) ? u.valToPos(to / 1000, "x", true) : left + width;
                u.ctx.fillRect(x0, top, Math.max(x1 - x0, 1), height);
              }
              u.ctx.restore();
            },
          ],
          setSelect: [
            (u) => {
              const { left, width } = u.select;
              if (width < CLICK_PIXELS) return;
              const scale = u.scales.x;
              if (scale.min === undefined || scale.max === undefined) return;
              draw(
                "timeline",
                brushTerm(left, width, u.over.clientWidth, scale.min * 1000, scale.max * 1000),
                down.current.shift,
              );
              u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            },
          ],
        },
      },
      [[], ...shown.flatMap(() => [[], []])] as uPlot.AlignedData,
      host,
    );

    const over = plot.over;
    const onDown = (event: MouseEvent) => {
      down.current = { x: event.clientX, shift: event.shiftKey };
      host.focus({ preventScroll: true });
    };
    const onClick = (event: MouseEvent) => {
      if (Math.abs(event.clientX - down.current.x) >= CLICK_PIXELS) return;
      const scale = plot.scales.x;
      if (scale.min === undefined || scale.max === undefined) return;
      const pixel = event.clientX - over.getBoundingClientRect().left;
      const ms = (scale.min + (pixel / over.clientWidth) * (scale.max - scale.min)) * 1000;
      const band = bandAt(live.current.bands, ms);
      if (band) {
        focusFlag({ sensor: band.sensor, interval: band.interval });
        setAnnouncement(flagLine(band));
      } else {
        clear("timeline");
      }
    };
    const onWheel = (event: WheelEvent) => {
      const record = live.current.extent;
      const scale = plot.scales.x;
      if (!record || scale.min === undefined || scale.max === undefined) return;
      event.preventDefault();
      const anchor = (event.clientX - over.getBoundingClientRect().left) / over.clientWidth;
      const [from, to] = zoomWindow(
        scale.min * 1000,
        scale.max * 1000,
        Math.min(1, Math.max(0, anchor)),
        event.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP,
        record,
      );
      // The scale moves at once; the window is fetched once the wheel stops.
      plot.setScale("x", { min: from / 1000, max: to / 1000 });
      window.clearTimeout(wheelTimer.current);
      wheelTimer.current = window.setTimeout(() => setView([from, to]), DEBOUNCE_MS);
    };
    over.addEventListener("mousedown", onDown, true);
    over.addEventListener("click", onClick);
    over.addEventListener("wheel", onWheel, { passive: false });
    setChart(plot);
    return () => {
      window.clearTimeout(wheelTimer.current);
      over.removeEventListener("mousedown", onDown, true);
      over.removeEventListener("click", onClick);
      over.removeEventListener("wheel", onWheel);
      plot.destroy();
      setChart(null);
    };
    // The callbacks only call store actions, which are stable.
  }, [shownKey, themeTick, draw, clear, focusFlag, shown]);

  useEffect(() => {
    const host = plotRef.current;
    if (!host) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.floor(width), height: Math.floor(height) });
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, [shownKey]);

  // uPlot's time axis cannot be drawn before it has data: a resize of the empty chart (a
  // neighbouring panel settling its height does it) throws inside uPlot and leaves the chart
  // blank for good. So only a chart holding data is resized, and the data effect sizes it.
  useEffect(() => {
    if (chart && chart.data[0]?.length && size.width > 0 && size.height > 0) {
      chart.setSize({ width: size.width, height: size.height });
    }
  }, [chart, size]);

  useEffect(() => {
    // Cached data for another channel set can arrive while this effect still holds the chart
    // being replaced; uPlot throws on data whose columns do not match its series.
    if (!chart || !data || chart.series.length !== 1 + 2 * data.meta.channels.length) return;
    chart.setData(plotData(data) as uPlot.AlignedData, false);
    const [from, to] = view ?? [data.meta.start_ms, data.meta.end_ms];
    chart.setScale("x", { min: from / 1000, max: to / 1000 });
    const host = plotRef.current;
    if (host && host.clientWidth > 0 && host.clientHeight > 0) {
      chart.setSize({ width: host.clientWidth, height: host.clientHeight });
    }
  }, [chart, data, view]);

  const options = (sensors.data ?? []).map((row) => row.name).filter((name) => !shown.includes(name));
  const picked = options.includes(pick) ? pick : (options[0] ?? "");
  const selectionExtent = termExtent(ranges);
  const label =
    shown.length === 0
      ? "Timeline: no channel shown"
      : `Timeline of ${shown.join(", ")}` + (bounds ? `, ${stamp(bounds[0])} to ${stamp(bounds[1])} UTC` : "");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const palette = useMemo(readPalette, [themeTick]);

  return (
    <div className="gk-panel gk-timeline">
      <div className="gk-timeline-bar">
        <button
          type="button"
          className="gk-button"
          disabled={selectionExtent === null}
          onClick={() => selectionExtent && setView(selectionExtent)}
        >
          Zoom to selection
        </button>
        <button type="button" className="gk-button" disabled={view === null} onClick={() => setView(null)}>
          Whole record
        </button>
        <label htmlFor="gk-timeline-pick">Channel to add</label>
        <select
          id="gk-timeline-pick"
          value={picked}
          disabled={options.length === 0}
          onChange={(event) => setPick(event.target.value)}
        >
          {options.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="gk-button"
          disabled={picked === ""}
          onClick={() => addToTimeline(picked, shown)}
        >
          Add channel
        </button>
      </div>
      <ul className="gk-timeline-legend" aria-label="Timeline channels">
        {shown.map((channel, index) => (
          <li key={channel}>
            <span
              className="gk-swatch"
              aria-hidden="true"
              style={{ background: palette.series[index % palette.series.length] }}
            />
            <span>{channel}</span>
            <button
              type="button"
              className="gk-icon-button"
              aria-label={`Remove ${channel} from the timeline`}
              onClick={() => removeFromTimeline(channel, shown)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <div ref={setNodeRef} className={`gk-timeline-plot${isOver ? " gk-over" : ""}`}>
        {shown.length === 0 ? (
          <p className="gk-muted">No channel is shown. Drop one here or add one above.</p>
        ) : (
          <div
            ref={plotRef}
            role="img"
            tabIndex={0}
            aria-label={label}
            style={{ position: "absolute", inset: 0 }}
            onKeyDown={(event) => {
              if (event.key === "Escape") clear("timeline");
              if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                const band = adjacentBand(
                  flags.data ?? [],
                  useFlagFocus.getState().focused,
                  event.key === "ArrowRight" ? 1 : -1,
                );
                if (band) {
                  event.preventDefault();
                  focusFlag({ sensor: band.sensor, interval: band.interval });
                  setAnnouncement(flagLine(band));
                }
              }
            }}
          />
        )}
      </div>
      {series.isError && <p role="alert">{series.error.message}</p>}
      <p className="gk-timeline-status" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}
