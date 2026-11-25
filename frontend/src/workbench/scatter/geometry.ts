// Pure geometry for the scatter: axis ranges, the data <-> normalised <-> screen mappings and
// the lasso's reduction to the polygon the server resolves (decision 0011). Nothing here
// touches WebGL, so it runs under jsdom.

export type Vertex = [number, number];

export interface Range {
  lo: number;
  hi: number;
}

/** The plot's inner box in CSS pixels; screen y grows downwards. */
export interface Box {
  width: number;
  height: number;
}

/** The server refuses a polygon of more than 1000 vertices; the lasso is cut well under it. */
export const MAX_LASSO_VERTICES = 200;

/** Below this the path is a click, not a lasso: the largest extent in pixels. */
export const MIN_LASSO_EXTENT_PX = 4;

/** A 1-2-5 step giving about ``count`` intervals over ``span``. */
export function niceStep(span: number, count = 6): number {
  if (!(span > 0)) return 1;
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  return (fraction < 1.5 ? 1 : fraction < 3.5 ? 2 : fraction < 7.5 ? 5 : 10) * power;
}

/** A fixed axis range holding [min, max]: from 0 (or below it for a channel that goes
 * negative) up to the next tick above the maximum. */
export function axisRange(min: number, max: number): Range {
  const step = niceStep(Math.max(max, 0) - Math.min(min, 0));
  const hi = Math.max(Math.ceil(max / step) * step, step);
  const lo = min < 0 ? Math.floor(min / step) * step : 0;
  return { lo, hi };
}

export function ticks(range: Range, count = 6): number[] {
  const step = niceStep(range.hi - range.lo, count);
  const first = Math.ceil(range.lo / step - 1e-9);
  const out: number[] = [];
  for (let i = first; i * step <= range.hi + step * 1e-9; i += 1) out.push(Number((i * step).toPrecision(12)));
  return out;
}

export function toNormalised(value: number, range: Range): number {
  return (2 * (value - range.lo)) / (range.hi - range.lo) - 1;
}

export function fromNormalised(value: number, range: Range): number {
  return range.lo + ((value + 1) / 2) * (range.hi - range.lo);
}

export function toScreenX(value: number, range: Range, box: Box): number {
  return ((value - range.lo) / (range.hi - range.lo)) * box.width;
}

export function toScreenY(value: number, range: Range, box: Box): number {
  return box.height - ((value - range.lo) / (range.hi - range.lo)) * box.height;
}

export function fromScreen(point: Vertex, x: Range, y: Range, box: Box): Vertex {
  return [
    x.lo + (point[0] / box.width) * (x.hi - x.lo),
    y.lo + ((box.height - point[1]) / box.height) * (y.hi - y.lo),
  ];
}

export function signedArea(ring: Vertex[]): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    sum += x1 * y2 - x2 * y1;
  }
  return sum / 2;
}

function triangle(a: Vertex, b: Vertex, c: Vertex): number {
  return Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2;
}

/** Cut a closed ring to at most ``limit`` vertices by repeatedly dropping the vertex whose
 * triangle with its neighbours is smallest (Visvalingam-Whyte), so corners survive and
 * straight runs go first. The ring is not repeated at its end; never fewer than 3. */
export function simplifyRing(ring: Vertex[], limit = MAX_LASSO_VERTICES): Vertex[] {
  const kept = ring.filter((point, i) => i === 0 || point[0] !== ring[i - 1][0] || point[1] !== ring[i - 1][1]);
  const last = kept[kept.length - 1];
  if (kept.length > 1 && kept[0][0] === last[0] && kept[0][1] === last[1]) kept.pop();
  const target = Math.max(3, limit);
  while (kept.length > target) {
    let at = 0;
    let least = Infinity;
    for (let i = 0; i < kept.length; i += 1) {
      const area = triangle(kept[(i + kept.length - 1) % kept.length], kept[i], kept[(i + 1) % kept.length]);
      if (area < least) {
        least = area;
        at = i;
      }
    }
    kept.splice(at, 1);
  }
  return kept;
}

/** The polygon a drawn screen path selects, in data units, or null when the path is a click
 * or encloses no area. */
export function lassoPolygon(path: Vertex[], x: Range, y: Range, box: Box): Vertex[] | null {
  if (path.length < 3) return null;
  const xs = path.map((point) => point[0]);
  const ys = path.map((point) => point[1]);
  const extent = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  if (extent < MIN_LASSO_EXTENT_PX) return null;
  const ring = simplifyRing(path, MAX_LASSO_VERTICES);
  if (ring.length < 3 || Math.abs(signedArea(ring)) < 1) return null;
  return ring.map((point) => {
    const [dx, dy] = fromScreen(point, x, y, box);
    return [Number(dx.toFixed(4)), Number(dy.toFixed(4))] as Vertex;
  });
}
