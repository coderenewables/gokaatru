import { BrushComponent, DataZoomComponent, DatasetComponent, GridComponent } from "echarts/components";
import { LineChart, ScatterChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import * as echarts from "echarts/core";
import type { Adapter, Data, Rect } from "../types";
import { HI_COLOR } from "../types";

echarts.use([BrushComponent, DataZoomComponent, DatasetComponent, GridComponent, LineChart, ScatterChart, CanvasRenderer]);

const GRID = { left: 50, right: 10, top: 10, bottom: 30 };

export function create(): Adapter {
  let chart: echarts.ECharts;
  let el: HTMLElement;
  let data: Data;

  const nextFinished = () =>
    new Promise<void>((resolve) => {
      const h = () => { chart.off("finished", h); resolve(); };
      chart.on("finished", h);
    });

  const pairs = (xs: ArrayLike<number>, ys: ArrayLike<number>, idx: ArrayLike<number>) => {
    const out = new Array<[number, number]>(idx.length);
    for (let i = 0; i < idx.length; i++) out[i] = [xs[idx[i]], ys[idx[i]]];
    return out;
  };

  return {
    async mount(host, d, onSelect) {
      el = host;
      data = d;
      chart = echarts.init(el, undefined, { renderer: "canvas", width: el.clientWidth, height: el.clientHeight });
      const timeline = d.kind === "timeline";
      const source: Record<string, ArrayLike<number>> = {};
      let series: unknown[];
      if (d.kind === "timeline") {
        source.x = d.x;
        d.ys.forEach((y, c) => { source["c" + c] = y; });
        series = [
          ...d.ys.map((_, c) => ({
            id: "m" + c, type: "line", datasetIndex: 0, encode: { x: "x", y: "c" + c }, showSymbol: false, sampling: "lttb",
            lineStyle: { width: 1 }, silent: true, animation: false, progressive: 5000, progressiveThreshold: 3000,
          })),
          ...d.ys.map((_, c) => ({ id: "o" + c, type: "scatter", symbolSize: 3, large: true, silent: true, z: 10, itemStyle: { color: HI_COLOR }, data: [] })),
        ];
      } else {
        source.x = d.x;
        source.y = d.y;
        series = [
          { id: "m0", type: "scatter", datasetIndex: 0, encode: { x: "x", y: "y" }, symbolSize: 2, large: true, largeThreshold: 2000, silent: true, animation: false, itemStyle: { color: "#2b6cb0" } },
          { id: "o0", type: "scatter", symbolSize: 3, large: true, silent: true, z: 10, itemStyle: { color: HI_COLOR }, data: [] },
        ];
      }
      const option = {
        animation: false,
        grid: GRID,
        dataset: [{ source }],
        xAxis: { type: "value", min: timeline ? (d as { xmin: number }).xmin : 0, max: timeline ? (d as { xmax: number }).xmax : 25 },
        yAxis: { type: "value", min: 0, max: timeline ? 26 : 25 },
        dataZoom: timeline
          ? [{ type: "inside", xAxisIndex: 0, moveOnMouseMove: false, zoomOnMouseWheel: false }]
          : [{ type: "inside", xAxisIndex: 0, moveOnMouseMove: false }, { type: "inside", yAxisIndex: 0, moveOnMouseMove: false }],
        brush: { toolbox: [], xAxisIndex: 0, yAxisIndex: timeline ? undefined : 0, brushType: timeline ? "lineX" : "rect", brushMode: "single", throttleType: "debounce", throttleDelay: 0 },
        series,
      };
      (window as unknown as { __lib: unknown }).__lib = chart;
      // brushselected and brushEnd arrive in either order at the end of a drag; emit once both are in and agree on the range
      let ended = false;
      let emitted = false;
      let endRange: any = null;
      let lastSel: { range: any; dataIndex: number[] } | null = null;
      const sameRange = (a: any, b: any) => JSON.stringify(a) === JSON.stringify(b);
      const tryEmit = () => {
        if (emitted || !ended || !lastSel || !sameRange(lastSel.range, endRange)) return;
        emitted = true;
        const rng = endRange;
        const range = timeline ? { x: rng as [number, number] } : { x: rng[0] as [number, number], y: rng[1] as [number, number] };
        // brushselected delivers no indices for sampled/large series; the reported range is used instead
        onSelect(lastSel.dataIndex.length ? { indices: lastSel.dataIndex, range } : { range, nativeCount: 0 });
      };
      chart.on("brush", () => { ended = false; emitted = false; });
      chart.on("brushEnd", (e: any) => { ended = true; endRange = e.areas?.[0]?.coordRange ?? null; tryEmit(); });
      chart.on("brushselected", (e: any) => {
        const bt = e.batch?.[0];
        lastSel = { range: bt?.areas?.[0]?.coordRange, dataIndex: bt?.selected?.[0]?.dataIndex ?? [] };
        tryEmit();
      });
      const done = nextFinished();
      chart.setOption(option as never, true);
      await done;
      chart.dispatchAction({ type: "takeGlobalCursor", key: "brush", brushOption: { brushType: timeline ? "lineX" : "rect", brushMode: "single" } });
    },
    plot(): Rect {
      const b = el.getBoundingClientRect();
      return { left: b.left + GRID.left, top: b.top + GRID.top, width: b.width - GRID.left - GRID.right, height: b.height - GRID.top - GRID.bottom };
    },
    toPage(x, y) {
      const b = el.getBoundingClientRect();
      const p = chart.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [x, y]);
      return [b.left + p[0], b.top + p[1]];
    },
    async setSelection(indices) {
      const done = nextFinished();
      if (data.kind === "timeline") {
        const t = data;
        chart.setOption({ series: t.ys.map((y, c) => ({ id: "o" + c, data: pairs(t.x, y, indices) })) } as never);
      } else {
        chart.setOption({ series: [{ id: "o0", data: pairs(data.x, data.y, indices) }] } as never);
      }
      await done;
    },
    async zoom(frac) {
      const done = nextFinished();
      if (data.kind === "timeline") {
        const r = data.xmax - data.xmin;
        chart.dispatchAction({ type: "dataZoom", dataZoomIndex: 0, startValue: data.xmin + r * (0.5 - frac / 2), endValue: data.xmin + r * (0.5 + frac / 2) });
      } else {
        const lo = 25 * (0.5 - frac / 2), hi = 25 * (0.5 + frac / 2);
        chart.dispatchAction({ type: "dataZoom", dataZoomIndex: 0, startValue: lo, endValue: hi });
        chart.dispatchAction({ type: "dataZoom", dataZoomIndex: 1, startValue: lo, endValue: hi });
      }
      await Promise.race([done, new Promise((r) => setTimeout(r, 5000))]);
    },
    destroy() { chart.dispose(); },
  };
}
