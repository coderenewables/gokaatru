import { BUCKETS, N, N_CHANNELS, decimateMinMax, genChannel, timeAxis } from "./data";
import type { Adapter, Data, Payload } from "./types";
import { SC_S, TL_H, TL_W } from "./types";

const q = new URLSearchParams(location.search);
const lib = q.get("lib") ?? "none";
const cs = q.get("case") ?? "blank";
const isScatter = cs.startsWith("scatter");

const stage = document.getElementById("stage") as HTMLElement;
const perf = performance as Performance & { memory?: { usedJSHeapSize: number } };
const gcFn = (window as unknown as { gc?: () => void }).gc;

function heap(): number {
  gcFn?.();
  return perf.memory ? perf.memory.usedJSHeapSize : -1;
}

function syncGL(): void {
  const buf = new Uint8Array(4);
  for (const c of Array.from(document.querySelectorAll("canvas"))) {
    const gl = (c.getContext("webgl2") ?? c.getContext("webgl")) as WebGLRenderingContext | null;
    if (gl) gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, buf);
  }
}

/** Painted-frame barrier: next animation frame, forced GPU completion on every WebGL canvas, then one macrotask. */
export async function barrier(): Promise<void> {
  await new Promise<void>((r) => requestAnimationFrame(() => r()));
  syncGL();
  await new Promise<void>((r) => setTimeout(r, 0));
}

function median(a: number[]): number {
  const s = [...a].sort((x, y) => x - y);
  return s[Math.floor(s.length / 2)];
}

interface Prepared { data: Data; genMs: number; decimateMs: number; pointsPerChannel: number; channels: number }

function prepare(): Prepared {
  const x = timeAxis();
  const t0 = performance.now();
  let decimateMs = 0;
  if (isScatter) {
    const a = genChannel(0);
    const b = genChannel(1);
    let n = 0;
    for (let i = 0; i < N; i++) if (a[i] === a[i] && b[i] === b[i]) n++;
    const sx = new Float32Array(n);
    const sy = new Float32Array(n);
    let k = 0;
    for (let i = 0; i < N; i++) if (a[i] === a[i] && b[i] === b[i]) { sx[k] = a[i]; sy[k] = b[i]; k++; }
    return { data: { kind: "scatter", x: sx, y: sy }, genMs: performance.now() - t0, decimateMs, pointsPerChannel: n, channels: 1 };
  }
  const nCh = cs === "timeline-1" ? 1 : cs === "timeline-6" ? 6 : N_CHANNELS;
  const ys: Float32Array[] = [];
  let xs = x;
  for (let c = 0; c < nCh; c++) {
    const g = genChannel(c);
    if (cs === "timeline-60-decimated") {
      const t = performance.now();
      const d = decimateMinMax(g, x, BUCKETS);
      decimateMs += performance.now() - t;
      xs = d.x;
      ys.push(d.y);
    } else {
      ys.push(g);
    }
  }
  const genMs = performance.now() - t0 - decimateMs;
  return { data: { kind: "timeline", x: xs, ys, xmin: 0, xmax: N / 144 }, genMs, decimateMs, pointsPerChannel: ys[0].length, channels: nCh };
}

async function loadAdapter(): Promise<Adapter> {
  if (lib === "plotly4") return (await import("./libs/plotly4")).create();
  if (lib === "plotly2") return (await import("./libs/plotly2")).create();
  if (lib === "echarts") return (await import("./libs/echarts")).create();
  if (lib === "uplot") return isScatter ? (await import("./libs/regl")).create() : (await import("./libs/uplot")).create();
  throw new Error("unknown lib " + lib);
}

// ---- selection bookkeeping -------------------------------------------------

function lowerBound(x: ArrayLike<number>, v: number): number {
  let lo = 0, hi = x.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (x[m] < v) lo = m + 1; else hi = m; }
  return lo;
}

/** Indices computed from a library-reported range (used when the library gives only a range). Binary search on x. */
function indicesFromRange(d: Data, p: Payload): Int32Array {
  const out: number[] = [];
  if (d.kind === "timeline") {
    const [a, b] = p.range!.x!;
    const y0 = d.ys[0];
    for (let i = lowerBound(d.x, a); i < d.x.length && d.x[i] <= b; i++) if (y0[i] === y0[i]) out.push(i);
  } else {
    const [a, b] = p.range!.x!;
    const [c, e] = p.range!.y!;
    for (let i = 0; i < d.x.length; i++) if (d.x[i] >= a && d.x[i] <= b && d.y[i] >= c && d.y[i] <= e) out.push(i);
  }
  return Int32Array.from(out);
}

/** Independent reference: naive linear scan over the data with the library's own reported bounds (or lasso polygon). */
function independentSet(d: Data, p: Payload, ad: Adapter): Uint8Array {
  const n = d.x.length;
  const mask = new Uint8Array(n);
  if (d.kind === "timeline") {
    const [a, b] = p.range!.x!;
    const y0 = d.ys[0];
    for (let i = 0; i < n; i++) {
      const v = y0[i];
      if (v === v && d.x[i] >= a && d.x[i] <= b) mask[i] = 1;
    }
    return mask;
  }
  if (p.poly) {
    const [ox, oy] = ad.canvasOrigin!();
    const poly = p.poly.map(([px, py]) => [px + ox, py + oy]);
    for (let i = 0; i < n; i++) {
      const [px, py] = ad.toPage(d.x[i], d.y[i]);
      let inside = false;
      for (let a = 0, b = poly.length - 1; a < poly.length; b = a++) {
        const [xa, ya] = poly[a], [xb, yb] = poly[b];
        if (ya > py !== yb > py && px < ((xb - xa) * (py - ya)) / (yb - ya) + xa) inside = !inside;
      }
      if (inside) mask[i] = 1;
    }
    return mask;
  }
  const [a, b] = p.range!.x!;
  const [c, e] = p.range!.y!;
  for (let i = 0; i < n; i++) if (d.x[i] >= a && d.x[i] <= b && d.y[i] >= c && d.y[i] <= e) mask[i] = 1;
  return mask;
}

function programmaticSelection(d: Data): Int32Array {
  const out: number[] = [];
  if (d.kind === "scatter") {
    for (let i = 0; i < d.x.length && out.length < 50000; i += 5) out.push(i);
  } else {
    const len = d.x.length;
    const want = len === N ? 50000 : Math.round((50000 / N) * len);
    const y0 = d.ys[0];
    for (let i = Math.floor(0.38 * len); i < len && out.length < want; i++) if (y0[i] === y0[i]) out.push(i);
  }
  return Int32Array.from(out);
}

// ---- harness ---------------------------------------------------------------

let adapter: Adapter | null = null;
let prepared: Prepared | null = null;
let hostEl: HTMLElement | null = null;
let armed = false;
let pointerUpT: number | null = null;
let brushDone: Promise<unknown> | null = null;
let resolveBrush: ((v: unknown) => void) | null = null;
let heapBefore = -1;
let selectionCallbackCount = 0;

window.addEventListener("pointerup", (e) => { if (armed && pointerUpT === null) pointerUpT = e.timeStamp; }, true);
window.addEventListener("mouseup", (e) => { if (armed && pointerUpT === null) pointerUpT = e.timeStamp; }, true);

function onSelect(p: Payload): void {
  if (!armed || pointerUpT === null || !prepared || !adapter) return;
  armed = false;
  const t0 = pointerUpT;
  const arrived = performance.now();
  selectionCallbackCount++;
  void (async () => {
   try {
    const d = prepared!.data;
    const fromIndices = p.indices !== undefined;
    const idx: ArrayLike<number> = fromIndices ? p.indices! : indicesFromRange(d, p);
    const computedAt = performance.now();
    await adapter!.setSelection(idx, true);
    await barrier();
    const t1 = performance.now();
    const ref = independentSet(d, p, adapter!);
    let nRef = 0;
    for (let i = 0; i < ref.length; i++) nRef += ref[i];
    const seen = new Uint8Array(ref.length);
    let nExtra = 0;
    for (let i = 0; i < idx.length; i++) { const k = idx[i]; if (!ref[k]) nExtra++; seen[k] = 1; }
    let nDistinct = 0, nMissing = 0;
    for (let i = 0; i < ref.length; i++) { nDistinct += seen[i]; if (ref[i] && !seen[i]) nMissing++; }
    resolveBrush?.({
      latencyMs: t1 - t0,
      callbackMs: arrived - t0,
      indicesMs: computedAt - arrived,
      paintMs: t1 - computedAt,
      source: fromIndices ? "library indices" : "range, indices computed here",
      nDelivered: idx.length,
      nSelected: nDistinct,
      nReference: nRef,
      nMissing,
      nExtra,
      agree: nMissing === 0 && nExtra === 0 && idx.length === nRef,
      nativeCount: p.nativeCount ?? null,
      bounds: p.range ?? null,
      callbacks: selectionCallbackCount,
    });
   } catch (err) {
    resolveBrush?.({ error: String(err) });
   }
  })();
}

const api = {
  async ready() {
    if (lib === "none") return { blank: true };
    prepared = prepare();
    hostEl = document.createElement("div");
    hostEl.style.width = (isScatter ? SC_S : TL_W) + "px";
    hostEl.style.height = (isScatter ? SC_S : TL_H) + "px";
    stage.appendChild(hostEl);
    adapter = await loadAdapter();
    return {
      genMs: prepared.genMs,
      decimateMs: prepared.decimateMs,
      pointsPerChannel: prepared.pointsPerChannel,
      channels: prepared.channels,
      totalPoints: prepared.pointsPerChannel * prepared.channels,
    };
  },
  async floor() {
    const s: number[] = [];
    for (let i = 0; i < 21; i++) { const t = performance.now(); await barrier(); s.push(performance.now() - t); }
    return median(s.slice(1));
  },
  gpu() {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") ?? c.getContext("webgl");
    if (!gl) return { renderer: "no webgl" };
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
      vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      version: gl.getParameter(gl.VERSION),
    };
  },
  async render() {
    heapBefore = heap();
    const t0 = performance.now();
    await adapter!.mount(hostEl!, prepared!.data, onSelect);
    const tLib = performance.now();
    await barrier();
    return { firstRenderMs: performance.now() - t0, libReturnMs: tLib - t0 };
  },
  brushPlan() {
    const d = prepared!.data;
    if (d.kind === "timeline") {
      const r = adapter!.plot();
      const y = r.top + r.height / 2;
      return { modifier: adapter!.modifier ?? null, points: [[r.left + 0.4 * r.width, y], [r.left + 0.6 * r.width, y]] };
    }
    const qs = (v: Float32Array, f: number) => { const s = Float32Array.from(v).sort(); return s[Math.floor(f * s.length)]; };
    const x0 = qs(d.x, 0.35), x1 = qs(d.x, 0.65), y0 = qs(d.y, 0.35), y1 = qs(d.y, 0.65);
    const a = adapter!.toPage(x0, y1);
    const b = adapter!.toPage(x1, y0);
    return { modifier: adapter!.modifier ?? null, points: [a, b] };
  },
  armBrush() {
    armed = true;
    pointerUpT = null;
    selectionCallbackCount = 0;
    brushDone = new Promise((r) => { resolveBrush = r; });
  },
  async brushResult() {
    const t = new Promise((r) => setTimeout(() => r({ timeout: true }), 15000));
    return Promise.race([brushDone, t]);
  },
  async highlight() {
    const idx = programmaticSelection(prepared!.data);
    const t0 = performance.now();
    await adapter!.setSelection(idx, false);
    await barrier();
    return { highlightMs: performance.now() - t0, n: idx.length };
  },
  async zoom() {
    const t0 = performance.now();
    await adapter!.zoom(0.1);
    await barrier();
    return { zoomMs: performance.now() - t0 };
  },
  heap() {
    const after = heap();
    return { heapBefore, heapAfter: after, heapDelta: after - heapBefore };
  },
};

(window as unknown as { __bench: typeof api }).__bench = api;
