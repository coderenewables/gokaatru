import createScatterplot from "regl-scatterplot";
import type { Adapter, Data } from "../types";
import { SC_S } from "../types";

const DOMAIN = 25;

export function create(): Adapter {
  let sp: ReturnType<typeof createScatterplot>;
  let canvas: HTMLCanvasElement;

  return {
    modifier: "Shift",
    async mount(el, d: Data, onSelect) {
      if (d.kind !== "scatter") throw new Error("scatter only");
      canvas = document.createElement("canvas");
      el.appendChild(canvas);
      sp = createScatterplot({
        canvas,
        width: SC_S,
        height: SC_S,
        pointSize: 2,
        pointColor: [0.17, 0.42, 0.69, 1],
        pointColorActive: [0.89, 0.34, 0.18, 1],
        backgroundColor: [1, 1, 1, 1],
        lassoType: "rectangle",
        opacity: 1,
      } as never);
      (window as unknown as { __lib: unknown }).__lib = sp;
      let poly: [number, number][] | undefined;
      // "select" fires before "lassoEnd"; the polygon is exposed lazily and read after the paint barrier
      sp.subscribe("lassoEnd", (e: any) => {
        poly = (e.coordinates as number[][]).map((p) => [((p[0] + 1) / 2) * SC_S, ((1 - p[1]) / 2) * SC_S] as [number, number]);
      });
      sp.subscribe("select", (e: any) => onSelect({ indices: e.points, get poly() { return poly; } }));
      // regl-scatterplot wants normalised device coordinates in [-1, 1]; the fixed 0..25 m/s domain is mapped here.
      const nx = new Float32Array(d.x.length);
      const ny = new Float32Array(d.y.length);
      for (let i = 0; i < d.x.length; i++) {
        nx[i] = (d.x[i] / DOMAIN) * 2 - 1;
        ny[i] = (d.y[i] / DOMAIN) * 2 - 1;
      }
      await sp.draw({ x: nx, y: ny } as never);
    },
    plot() {
      const b = canvas.getBoundingClientRect();
      return { left: b.left, top: b.top, width: b.width, height: b.height };
    },
    toPage(x, y) {
      const b = canvas.getBoundingClientRect();
      const nx = (x / DOMAIN) * 2 - 1;
      const ny = (y / DOMAIN) * 2 - 1;
      return [b.left + ((nx + 1) / 2) * b.width, b.top + ((1 - ny) / 2) * b.height];
    },
    canvasOrigin() {
      const b = canvas.getBoundingClientRect();
      return [b.left, b.top];
    },
    async setSelection(indices, fromBrush) {
      if (fromBrush) return;
      await sp.select(Array.from(indices), { preventEvent: true } as never);
    },
    async zoom(frac) {
      await sp.zoomToLocation([0, 0], frac, { transition: false } as never);
    },
    destroy() { sp.destroy(); },
  };
}
