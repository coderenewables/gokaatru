import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { Adapter, Data, Rect } from "../types";
import { HI_COLOR } from "../types";

export function create(): Adapter {
  let u: uPlot;
  let data: Data;
  let sel: ArrayLike<number> | null = null;

  return {
    async mount(el, d, onSelect) {
      if (d.kind !== "timeline") throw new Error("timeline only");
      data = d;
      // uPlot treats null as a gap; NaN would be drawn as a value, so the NaN runs are converted to null.
      const cols: (ArrayLike<number | null>)[] = [d.x, ...d.ys.map((y) => Array.from(y, (v) => (v !== v ? null : v)))];
      const palette = ["#2b6cb0", "#2f855a", "#b7791f", "#805ad5", "#c53030", "#2c7a7b"];
      u = new uPlot(
        {
          width: el.clientWidth,
          height: el.clientHeight,
          legend: { show: false },
          cursor: { drag: { x: true, y: false, setScale: false }, points: { show: false } },
          scales: { x: { time: false, auto: false, min: d.xmin, max: d.xmax }, y: { auto: false, range: [0, 26] } },
          axes: [{}, {}],
          series: [{}, ...d.ys.map((_, c) => ({ stroke: palette[c % palette.length], width: 1, points: { show: false } }))],
          hooks: {
            setSelect: [
              (self) => {
                if (self.select.width <= 0) return;
                const a = self.posToVal(self.select.left, "x");
                const b = self.posToVal(self.select.left + self.select.width, "x");
                onSelect({ range: { x: [a, b] } });
              },
            ],
            draw: [
              (self) => {
                if (!sel) return;
                const ctx = self.ctx;
                const { left, top, width, height } = self.bbox;
                const x0 = self.scales.x.min!, x1 = self.scales.x.max!;
                ctx.save();
                ctx.beginPath();
                ctx.rect(left, top, width, height);
                ctx.clip();
                ctx.fillStyle = HI_COLOR;
                ctx.beginPath();
                const d2 = data as Extract<Data, { kind: "timeline" }>;
                for (const y of d2.ys) {
                  for (let k = 0; k < sel.length; k++) {
                    const i = sel[k];
                    const v = y[i];
                    if (v !== v) continue;
                    const px = left + ((d2.x[i] - x0) / (x1 - x0)) * width;
                    const py = top + (1 - v / 26) * height;
                    ctx.rect(px - 1.5, py - 1.5, 3, 3);
                  }
                }
                ctx.fill();
                ctx.restore();
              },
            ],
          },
        },
        cols as uPlot.AlignedData,
        el,
      );
    },
    plot(): Rect {
      const b = u.over.getBoundingClientRect();
      return { left: b.left, top: b.top, width: b.width, height: b.height };
    },
    toPage() { throw new Error("n/a"); },
    async setSelection(indices) {
      sel = indices;
      u.redraw(false, false);
      await Promise.resolve();
    },
    async zoom(frac) {
      const d = data as Extract<Data, { kind: "timeline" }>;
      const r = d.xmax - d.xmin;
      u.setScale("x", { min: d.xmin + r * (0.5 - frac / 2), max: d.xmin + r * (0.5 + frac / 2) });
      await Promise.resolve();
    },
    destroy() { u.destroy(); },
  };
}
