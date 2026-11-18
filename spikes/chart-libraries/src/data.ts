// Deterministic synthetic wind-campaign data: 5 years x 10 minute records.
export const N = 5 * 365 * 144; // 262,800
export const STEP_DAYS = 1 / 144;
export const BUCKETS = 1600;
export const N_CHANNELS = 60;

export function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function ar1(rng: () => number, n: number, phi: number, sd: number): Float32Array {
  const out = new Float32Array(n);
  const innov = sd * Math.sqrt(1 - phi * phi);
  let v = 0;
  for (let i = 0; i < n; i += 2) {
    const r = Math.sqrt(-2 * Math.log(rng() + 1e-12));
    const th = 2 * Math.PI * rng();
    v = phi * v + innov * r * Math.cos(th);
    out[i] = v;
    if (i + 1 < n) {
      v = phi * v + innov * r * Math.sin(th);
      out[i + 1] = v;
    }
  }
  return out;
}

let xCache: Float64Array | null = null;
let latentCache: Float32Array | null = null;
let seasonCache: Float32Array | null = null;

export function timeAxis(): Float64Array {
  if (!xCache) {
    xCache = new Float64Array(N);
    for (let i = 0; i < N; i++) xCache[i] = i * STEP_DAYS;
  }
  return xCache;
}

function shared(): { latent: Float32Array; season: Float32Array } {
  if (!latentCache || !seasonCache) {
    latentCache = ar1(mulberry32(1000), N, 0.997, 1.6);
    seasonCache = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const day = i * STEP_DAYS;
      const hour = (i % 144) / 6;
      seasonCache[i] =
        6.5 + 2.2 * Math.cos((2 * Math.PI * (day - 30)) / 365.25) + 1.0 * Math.cos((2 * Math.PI * (hour - 15)) / 24);
    }
  }
  return { latent: latentCache, season: seasonCache };
}

/** One channel of wind speed, m/s, 0..25, with NaN gap runs. Channels share the latent weather, so they correlate. */
export function genChannel(c: number): Float32Array {
  const { latent, season } = shared();
  const noise = ar1(mulberry32(2000 + c), N, 0.95, 0.5);
  const rng = mulberry32(3000 + c);
  const gain = 1 + 0.004 * c;
  const y = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const v = (season[i] + latent[i]) * gain + noise[i];
    y[i] = v < 0 ? 0 : v > 25 ? 25 : v;
  }
  for (let i = 0; i < N; i++) {
    if (rng() < 1 / 3000) {
      const len = Math.min(2000, 1 + Math.floor(-Math.log(rng() + 1e-12) * 60));
      for (let k = 0; k < len && i + k < N; k++) y[i + k] = NaN;
      i += len;
    }
  }
  return y;
}

export interface Decimated {
  x: Float64Array;
  y: Float32Array;
}

/** Min/max per horizontal pixel bucket. Two points per bucket in time order, placed at 25%/75% of the bucket. */
export function decimateMinMax(y: Float32Array, x: Float64Array, buckets: number): Decimated {
  const ox = new Float64Array(buckets * 2);
  const oy = new Float32Array(buckets * 2);
  for (let b = 0; b < buckets; b++) {
    const i0 = Math.floor((b * y.length) / buckets);
    const i1 = Math.floor(((b + 1) * y.length) / buckets);
    let lo = Infinity;
    let hi = -Infinity;
    let loI = -1;
    let hiI = -1;
    for (let i = i0; i < i1; i++) {
      const v = y[i];
      if (v !== v) continue;
      if (v < lo) { lo = v; loI = i; }
      if (v > hi) { hi = v; hiI = i; }
    }
    const xa = x[i0] + 0.25 * (x[i1 - 1] - x[i0]);
    const xb = x[i0] + 0.75 * (x[i1 - 1] - x[i0]);
    ox[2 * b] = xa;
    ox[2 * b + 1] = xb;
    if (loI < 0) {
      oy[2 * b] = NaN;
      oy[2 * b + 1] = NaN;
    } else if (loI < hiI) {
      oy[2 * b] = lo;
      oy[2 * b + 1] = hi;
    } else {
      oy[2 * b] = hi;
      oy[2 * b + 1] = lo;
    }
  }
  return { x: ox, y: oy };
}
