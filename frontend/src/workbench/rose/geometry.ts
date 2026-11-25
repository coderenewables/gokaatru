import type { Definition, Sector } from "../selection/store";

// The rose's sectors as compute_windrose_data bins them (server/tools/statistics.py): sector
// k is centred on k × width, so it covers [k·w − w/2, k·w + w/2), north's wrapping through 0.
// A clicked sector becomes the selection term with exactly those half-open bounds, so the
// sector drawn and the records selected are the same ones.

export const SECTORS = 12;
export const WIDTH = 360 / SECTORS;

export const LABELS = Array.from({ length: SECTORS }, (_, k) =>
  k === 0 ? "N" : k === 3 ? "E" : k === 6 ? "S" : k === 9 ? "W" : `${k * WIDTH}°`,
);

/** The selection term of sector k on a direction channel. */
export function sectorTerm(k: number, channel: string): Sector {
  const from = (((k * WIDTH - WIDTH / 2) % 360) + 360) % 360;
  const to = k * WIDTH + WIDTH / 2;
  return { kind: "sector", channel, from_deg: from, to_deg: to };
}

/** The sector a bearing (degrees from north, clockwise) falls in. */
export function sectorOf(bearing: number): number {
  return Math.floor(((((bearing + WIDTH / 2) % 360) + 360) % 360) / WIDTH) % SECTORS;
}

/** The bearing of a point from the rose's centre, degrees clockwise from north (screen y down). */
export function bearingOf(dx: number, dy: number): number {
  return ((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360;
}

/** The sectors a rose term holds: one sector term, or a union of them. */
export function sectorsOf(term: Definition | undefined, channel: string): number[] {
  if (!term) return [];
  const parts = term.kind === "union" ? term.of : [term];
  return parts.flatMap((part) => {
    if (part.kind !== "sector" || part.channel !== channel) return [];
    const k = sectorOf(part.from_deg + WIDTH / 2);
    const expected = sectorTerm(k, channel);
    return expected.from_deg === part.from_deg && expected.to_deg === part.to_deg ? [k] : [];
  });
}

/** The rose term after a click on sector k: alone, added with Shift, or removed if it was
 * the one selected. */
export function toggled(current: number[], k: number, extend: boolean): number[] {
  if (current.includes(k)) return extend ? current.filter((sector) => sector !== k) : current.length === 1 ? [] : [k];
  return extend ? [...current, k].sort((a, b) => a - b) : [k];
}

export function termOf(sectors: number[], channel: string): Definition | null {
  if (sectors.length === 0) return null;
  const terms = sectors.map((k) => sectorTerm(k, channel));
  return terms.length === 1 ? terms[0] : { kind: "union", of: terms };
}

/** An SVG path of a wedge of sector k reaching radius r around (0, 0). */
export function wedge(k: number, r: number): string {
  if (r <= 0.5) return "";
  const a0 = ((k * WIDTH - WIDTH / 2) * Math.PI) / 180;
  const a1 = ((k * WIDTH + WIDTH / 2) * Math.PI) / 180;
  const point = (a: number) => `${(r * Math.sin(a)).toFixed(2)} ${(-r * Math.cos(a)).toFixed(2)}`;
  return `M0 0L${point(a0)}A${r.toFixed(2)} ${r.toFixed(2)} 0 0 1 ${point(a1)}Z`;
}
