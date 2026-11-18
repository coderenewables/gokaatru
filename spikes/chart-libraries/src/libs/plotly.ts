import type { Adapter, Data, Payload, Rect } from "../types";
import { HI_COLOR } from "../types";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Plotly = any;

function gather<T extends Float32Array | Float64Array>(src: T, idx: ArrayLike<number>): T {
  const out = new (src.constructor as new (n: number) => T)(idx.length);
  for (let i = 0; i < idx.length; i++) out[i] = src[idx[i]];
  return out;
}

export function createPlotly(Plotly: Plotly): Adapter {
  let gd: any;
  let data: Data;
  let nTraces = 0;

  return {
    async mount(el, d, onSelect) {
      gd = el;
      data = d;
      let traces: unknown[];
      const layout: Record<string, unknown> = {
        width: el.clientWidth, height: el.clientHeight, showlegend: false, dragmode: "select",
        margin: { l: 50, r: 10, t: 10, b: 30 },
      };
      if (d.kind === "timeline") {
        const main = d.ys.map((y, c) => ({ type: "scattergl", mode: "lines", x: d.x, y, line: { width: 1 }, hoverinfo: "skip", name: "c" + c }));
        const over = d.ys.map(() => ({ type: "scattergl", mode: "markers", x: [], y: [], marker: { size: 3, color: HI_COLOR }, hoverinfo: "skip" }));
        traces = [...main, ...over];
        nTraces = d.ys.length;
        layout.selectdirection = "h";
        layout.xaxis = { range: [d.xmin, d.xmax] };
        layout.yaxis = { range: [0, 26] };
      } else {
        traces = [{
          type: "scattergl", mode: "markers", x: d.x, y: d.y, hoverinfo: "skip",
          marker: { size: 2, color: "#2b6cb0" },
          selected: { marker: { color: HI_COLOR, size: 3, opacity: 1 } },
          unselected: { marker: { opacity: 0.15 } },
        }];
        nTraces = 1;
        layout.xaxis = { range: [0, 25] };
        layout.yaxis = { range: [0, 25] };
      }
      await Plotly.newPlot(gd, traces, layout, { displayModeBar: false, staticPlot: false });
      gd.on("plotly_selected", (e: any) => {
        if (!e) return;
        const pts: any[] = e.points ?? [];
        const idx: number[] = [];
        for (const p of pts) if (p.curveNumber === 0) idx.push(p.pointIndex ?? p.pointNumber);
        // lines-only scattergl traces are not selectable (no points delivered); fall back to the reported range
        const payload: Payload = idx.length || !e.range ? { indices: idx } : { nativeCount: 0 };
        if (e.range) payload.range = { x: e.range.x, y: e.range.y };
        onSelect(payload);
      });
    },
    plot(): Rect {
      const b = gd.getBoundingClientRect();
      const s = gd._fullLayout._size;
      return { left: b.left + s.l, top: b.top + s.t, width: s.w, height: s.h };
    },
    toPage(x, y) {
      const b = gd.getBoundingClientRect();
      const fl = gd._fullLayout;
      return [b.left + fl.xaxis._offset + fl.xaxis.l2p(x), b.top + fl.yaxis._offset + fl.yaxis.l2p(y)];
    },
    async setSelection(indices, fromBrush) {
      if (data.kind === "scatter") {
        if (fromBrush) return;
        await Plotly.restyle(gd, { selectedpoints: [Array.from(indices)] }, [0]);
        return;
      }
      const t = data;
      const targets = t.ys.map((_, i) => nTraces + i);
      await Plotly.restyle(gd, { x: t.ys.map(() => gather(t.x, indices)), y: t.ys.map((y) => gather(y, indices)) }, targets);
    },
    async zoom(frac) {
      if (data.kind === "timeline") {
        const r = data.xmax - data.xmin;
        await Plotly.relayout(gd, { "xaxis.range": [data.xmin + r * (0.5 - frac / 2), data.xmin + r * (0.5 + frac / 2)] });
      } else {
        const lo = 25 * (0.5 - frac / 2), hi = 25 * (0.5 + frac / 2);
        await Plotly.relayout(gd, { "xaxis.range": [lo, hi], "yaxis.range": [lo, hi] });
      }
    },
    destroy() { Plotly.purge(gd); },
  };
}
