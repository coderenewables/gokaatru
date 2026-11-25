import type { Schemas } from "../../api/client";

// The mast diagram's model: drafted columns (or the spec in force) as chips at heights, and
// the spec a build sends. Pure, so each rule is testable without a page. A chip's height is
// never defaulted: a column the draft could not place stays at `null` and blocks the build.

export type Drafted = Schemas["DraftedColumn"];

export const MEASUREMENT_TYPES: Record<string, string> = {
  wind_speed: "Wind speed",
  wind_direction: "Wind direction",
  temperature: "Temperature",
  pressure: "Pressure",
  relative_humidity: "Humidity",
};

export interface StatisticColumn {
  column_name: string;
  statistic_type_id: string;
}

export interface Chip {
  name: string;
  type: string;
  height: number | null;
  boom: number | null;
  isPrimary: boolean | null;
  statistics: StatisticColumn[];
  /** Why the draft could not place the column, for the "No height yet" tray. */
  reason: string | null;
}

export interface Location {
  name: string;
  latitude: string;
  longitude: string;
  elevation: string;
  offset: string;
  timezone: string;
}

export const EMPTY_LOCATION: Location = { name: "", latitude: "", longitude: "", elevation: "", offset: "", timezone: "" };

export interface DraftChips {
  chips: Chip[];
  /** Columns not built, each with the reason: not a sensor, or a statistic other than sd. */
  notBuilt: Array<{ name: string; reason: string }>;
}

export function chipsFromDraft(columns: Drafted[]): DraftChips {
  const chips: Chip[] = [];
  const notBuilt: Array<{ name: string; reason: string }> = [];
  for (const column of columns) {
    if (column.role === "measurement") {
      chips.push({
        name: column.name,
        type: column.measurement_type_id ?? "wind_speed",
        height: column.height_m,
        boom: null,
        isPrimary: null,
        statistics: [],
        reason: column.reason,
      });
    }
  }
  for (const column of columns) {
    if (column.role === "statistic") {
      const parent = chips.find((chip) => chip.name === column.parent);
      if (parent && column.statistic_type_id === "sd") {
        parent.statistics.push({ column_name: column.name, statistic_type_id: "sd" });
      } else {
        notBuilt.push({
          name: column.name,
          reason: `${column.statistic_type_id ?? "statistic"} column${column.parent ? ` of ${column.parent}` : ""}; only standard deviations are kept`,
        });
      }
    } else if (column.role === "ignored") {
      notBuilt.push({ name: column.name, reason: column.reason ?? "not a sensor" });
    }
  }
  return { chips, notBuilt };
}

const numberOrNull = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/** The chips of the spec in force, plus the drafted measurement columns it does not hold
 * (placed nowhere yet, so a rebuild waits for them). */
export function chipsFromSpec(spec: Record<string, unknown>, drafted: DraftChips): Chip[] {
  const points = Array.isArray(spec.points) ? (spec.points as Array<Record<string, unknown>>) : [];
  const chips: Chip[] = points.map((point) => ({
    name: String(point.name),
    type: String(point.measurement_type_id),
    height: numberOrNull(point.height_m),
    boom: numberOrNull(point.boom_orientation_deg),
    isPrimary: typeof point.is_primary === "boolean" ? point.is_primary : null,
    statistics: Array.isArray(point.statistics) ? (point.statistics as StatisticColumn[]) : [],
    reason: null,
  }));
  const held = new Set(chips.map((chip) => chip.name));
  for (const chip of drafted.chips) if (!held.has(chip.name)) chips.push({ ...chip, height: null });
  return chips;
}

export function locationFromSpec(spec: Record<string, unknown>): Location {
  const raw = (spec.location ?? {}) as Record<string, unknown>;
  const text = (value: unknown) => (value === undefined || value === null ? "" : String(value));
  return {
    name: text(raw.name),
    latitude: text(raw.latitude_ddeg),
    longitude: text(raw.longitude_ddeg),
    elevation: text(raw.elevation_m),
    offset: text(raw.offset_from_utc_hrs),
    timezone: text(raw.timezone),
  };
}

/** The distinct heights, highest first. */
export function levels(chips: Chip[]): number[] {
  const heights = new Set<number>();
  for (const chip of chips) if (chip.height !== null) heights.add(chip.height);
  return [...heights].sort((a, b) => b - a);
}

export const unplaced = (chips: Chip[]): Chip[] => chips.filter((chip) => chip.height === null);

export function edit(chips: Chip[], name: string, change: Partial<Pick<Chip, "height" | "type" | "boom">>): Chip[] {
  return chips.map((chip) =>
    chip.name === name ? { ...chip, ...change, reason: change.height === undefined ? chip.reason : null } : chip,
  );
}

/** A typed number, or null for an empty field. NaN means the text is not a number. */
export function parseNumber(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  return /^[-+]?(\d+\.?\d*|\.\d+)$/.test(trimmed) ? Number(trimmed) : Number.NaN;
}

/** Why a build cannot be sent yet, one sentence each; empty when it can. */
export function blockers(chips: Chip[], location: Location): string[] {
  const reasons: string[] = [];
  const missing = unplaced(chips);
  if (missing.length > 0) {
    reasons.push(`Give a height to ${missing.map((chip) => chip.name).join(", ")}.`);
  }
  if (chips.length === 0) reasons.push("No measurement column to build from.");

  const offset = parseNumber(location.offset);
  if (Number.isNaN(offset) || (offset !== null && Math.abs(offset) > 14)) {
    reasons.push("The UTC offset must be a number of hours between -14 and 14.");
  } else if (offset === null && location.timezone.trim() === "") {
    reasons.push("Give the timezone: a UTC offset in hours or an IANA zone name.");
  }

  const latitude = parseNumber(location.latitude);
  const longitude = parseNumber(location.longitude);
  if (Number.isNaN(latitude) || (latitude !== null && Math.abs(latitude) > 90)) {
    reasons.push("The latitude must be a number between -90 and 90.");
  }
  if (Number.isNaN(longitude) || (longitude !== null && Math.abs(longitude) > 180)) {
    reasons.push("The longitude must be a number between -180 and 180.");
  }
  if ((latitude === null) !== (longitude === null)) reasons.push("Give both the latitude and the longitude, or neither.");
  if (Number.isNaN(parseNumber(location.elevation))) reasons.push("The elevation must be a number of metres.");
  for (const chip of chips) {
    if (chip.boom !== null && (chip.boom < 0 || chip.boom >= 360)) {
      reasons.push(`The boom orientation of ${chip.name} must be from 0 to under 360 degrees.`);
    }
  }
  return reasons;
}

/** The spec `build_data_model` takes. Only called when `blockers` is empty. */
export function buildSpec(chips: Chip[], location: Location): Record<string, unknown> {
  const place: Record<string, unknown> = {};
  if (location.name.trim()) place.name = location.name.trim();
  const latitude = parseNumber(location.latitude);
  const longitude = parseNumber(location.longitude);
  if (latitude !== null && longitude !== null) {
    place.latitude_ddeg = latitude;
    place.longitude_ddeg = longitude;
  }
  const elevation = parseNumber(location.elevation);
  if (elevation !== null) place.elevation_m = elevation;
  const offset = parseNumber(location.offset);
  if (offset !== null) place.offset_from_utc_hrs = offset;
  if (location.timezone.trim()) place.timezone = location.timezone.trim();

  const points = chips.map((chip) => {
    const point: Record<string, unknown> = { name: chip.name, measurement_type_id: chip.type, height_m: chip.height };
    if (chip.boom !== null) point.boom_orientation_deg = chip.boom;
    if (chip.isPrimary !== null) point.is_primary = chip.isPrimary;
    if (chip.statistics.length > 0) point.statistics = chip.statistics;
    return point;
  });
  return { location: place, points };
}

/** The height typed into a "New level" field: a finite number, never an empty field. */
export function parseLevel(text: string): number | null {
  const value = parseNumber(text);
  return value === null || Number.isNaN(value) ? null : value;
}

export const levelLabel = (height: number): string => `${height} m`;
