// Bidirectional sync between the typed `WindAnalysisConfig` and the flat backend
// `runconfig` dict (spec §1.3).
//
// Backend runconfig keys of interest (verified):
//   project_name, location {latitude, longitude, elevation_m}, measurement_type,
//   hub_height_m, sensor_mapping, cleaning_log, brighthub_uuid.
//
// ---------------------------------------------------------------------------
// The canonical/mirror contract (D20)
// ---------------------------------------------------------------------------
// The backend is the single source of truth. It STRIPS the keys below from the
// persisted runconfig, and this file is what puts them back. The mapping is
// written down once in `server/core/runconfig.py::RUNCONFIG_MIRRORS`, and
// `tests/test_runconfig_contract.py` asserts every stripped key is reproducible
// from a canonical one. Adding a mirrored field means editing three places —
// emit in `to_runconfig`, list in `RUNCONFIG_MIRRORS`, rehydrate here — and
// missing the last one fails as a Zod validation error far from its cause.
//
//   stripped mirror              <- canonical backend key
//   project.name                 <- project_name
//   project.measurementType      <- measurement_type
//   site.latitude                <- location.latitude
//   site.longitude               <- location.longitude
//   site.elevationM              <- location.elevation_m
//   site.hubHeightM              <- hub_height_m
//   shear.targetHubHeightM       <- hub_height_m
//   ltc.uncertainty.hubHeightM   <- hub_height_m
//   reanalysis.searchLatitude    <- location.latitude
//   reanalysis.searchLongitude   <- location.longitude
//
// Not a mirror, but note it: `shear.minSpeedMps` is a backend-owned key that
// lives inside a section this file also writes. The section schemas are
// non-strict, so Zod drops it from the typed model and `serializeConfigToRunconfig`
// never writes it back. It survives only because `buildRunconfigUpdates` emits
// updates key-by-key and cannot delete a key it never saw. Do not "fix" that by
// replacing a section wholesale — see BACKEND_OWNED_SECTION_KEYS.
import { createDefaultWindAnalysisConfig } from "./defaultConfig";
import type { WindAnalysisConfig } from "../types/analysis";

type AnyRecord = Record<string, unknown>;

function isRecord(value: unknown): value is AnyRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

// ---------------------------------------------------------------------------
// Hydrate: flat runconfig -> typed config (merge over defaults)
// ---------------------------------------------------------------------------

export function hydrateConfigFromRunconfig(runconfig: unknown): WindAnalysisConfig {
  const base = createDefaultWindAnalysisConfig();
  if (!isRecord(runconfig)) return base;

  const next: WindAnalysisConfig = structuredClone(base);

  // --- full-surface blocks (round-tripped by serializeConfigToRunconfig) ---
  // Deep-merge each present block over the defaults so partial runconfigs
  // (e.g. minimal server-side JSON) still hydrate cleanly.
  if (isRecord(runconfig.project)) next.project = deepMerge(next.project, runconfig.project);
  if (isRecord(runconfig.site)) next.site = deepMerge(next.site, runconfig.site);
  if (isRecord(runconfig.mast)) next.mast = deepMerge(next.mast, runconfig.mast);
  if (isRecord(runconfig.inputs)) next.inputs = deepMerge(next.inputs, runconfig.inputs);
  if (isRecord(runconfig.cleaning)) next.cleaning = deepMerge(next.cleaning, runconfig.cleaning);
  if (isRecord(runconfig.shear)) next.shear = deepMerge(next.shear, runconfig.shear);
  if (isRecord(runconfig.reanalysis)) next.reanalysis = deepMerge(next.reanalysis, runconfig.reanalysis);
  if (isRecord(runconfig.ltc)) next.ltc = deepMerge(next.ltc, runconfig.ltc);
  if (isRecord(runconfig.workflow)) next.workflow = deepMerge(next.workflow, runconfig.workflow);
  if (isRecord(runconfig.compare)) next.compare = deepMerge(next.compare, runconfig.compare);

  // Canonical backend fields win over legacy nested aliases. The typed
  // frontend model derives its convenience fields from these persisted values.
  const projectName = asString(runconfig.project_name);
  if (projectName) next.project.name = projectName;

  const measurementType = asString(runconfig.measurement_type);
  if (
    measurementType &&
    ["mast", "lidar", "sodar", "floating-lidar", "hybrid"].includes(measurementType)
  ) {
    next.project.measurementType = measurementType as WindAnalysisConfig["project"]["measurementType"];
  }

  const location = runconfig.location;
  if (isRecord(location)) {
    const lat = asNumber(location.latitude);
    const lon = asNumber(location.longitude);
    const elev = asNumber(location.elevation_m);
    if (lat !== undefined) next.site.latitude = lat;
    if (lon !== undefined) next.site.longitude = lon;
    if (elev !== undefined) next.site.elevationM = elev;
  }

  const hubHeight = asNumber(runconfig.hub_height_m);
  if (hubHeight !== undefined && hubHeight > 0) {
    next.site.hubHeightM = hubHeight;
    next.shear.targetHubHeightM = hubHeight;
    next.ltc.uncertainty.hubHeightM = hubHeight;
  }

  next.reanalysis.searchLatitude = next.site.latitude;
  next.reanalysis.searchLongitude = next.site.longitude;

  // Dataset the session loaded (written by the backend on dataset load); used
  // to repopulate the canvas "Dataset intake" node params on rebuild. Applied
  // AFTER the inputs deep-merge so the authoritative backend dataset_id wins
  // over a stale/empty persisted inputs.sharedDatasetId.
  const datasetId = asString(runconfig.dataset_id);
  if (datasetId) next.inputs.sharedDatasetId = datasetId;

  return next;
}

/** Recursively merge `incoming` over `base`, returning a new object. */
function deepMerge<T>(base: T, incoming: Record<string, unknown>): T {
  if (!isRecord(base)) {
    return (isRecord(incoming) ? structuredClone(incoming) : base) as T;
  }
  const out: Record<string, unknown> = structuredClone(base as Record<string, unknown>);
  for (const [key, value] of Object.entries(incoming)) {
    if (value === undefined) continue;
    const currentValue = out[key];
    if (isRecord(value) && isRecord(currentValue)) {
      out[key] = deepMerge(currentValue, value);
    } else {
      out[key] = structuredClone(value);
    }
  }
  return out as T;
}

// ---------------------------------------------------------------------------
// Serialize: typed config -> flat runconfig (persist the full editing surface)
// ---------------------------------------------------------------------------
//
// The backend runconfig is a free-form JSON dict persisted to runconfig.json;
// it tolerates extra keys. We persist every editable field so that save→load
// round-trips losslessly and runconfig remains the single source of truth.
// The backend-recognized keys (project_name, location, hub_height_m, …) are
// preserved with their canonical names so server-side tools keep working.

export function serializeConfigToRunconfig(config: WindAnalysisConfig): AnyRecord {
  const { hubHeightM: _uncertaintyHubHeightM, ...uncertainty } = config.ltc.uncertainty;
  return {
    // --- backend-canonical keys (recognized by server-side tools) ---
    project_name: config.project.name,
    measurement_type: config.project.measurementType,
    location: {
      latitude: config.site.latitude,
      longitude: config.site.longitude,
      elevation_m: config.site.elevationM,
    },
    hub_height_m: config.site.hubHeightM,
    // Shared dataset loaded into the session; round-tripped so saves never
    // drop the dataset intake node's parameter on the backend.
    dataset_id: config.inputs.sharedDatasetId,

    // --- full frontend editing surface (round-tripped) ---
    project: {
      client: config.project.client,
      notes: config.project.notes,
    },
    site: {
      region: config.site.region,
      timeZone: config.site.timeZone,
      rotorDiameterM: config.site.rotorDiameterM,
    },
    mast: config.mast,
    inputs: config.inputs,
    cleaning: config.cleaning,
    shear: {
      method: config.shear.method,
      speedSensorPair: config.shear.speedSensorPair,
      directionSensor: config.shear.directionSensor,
      aggregation: config.shear.aggregation,
      useWindKit: config.shear.useWindKit,
    },
    reanalysis: {
      preferredProvider: config.reanalysis.preferredProvider,
      startDate: config.reanalysis.startDate,
      endDate: config.reanalysis.endDate,
      nodes: config.reanalysis.nodes,
    },
    ltc: {
      ...config.ltc,
      uncertainty,
    },
    workflow: config.workflow,
    compare: config.compare,
  };
}

// ---------------------------------------------------------------------------
// setConfigValue: dotted-path immutable update
// ---------------------------------------------------------------------------

function setOnPath(target: AnyRecord, pathParts: string[], value: unknown): void {
  let cursor: unknown = target;
  for (let i = 0; i < pathParts.length - 1; i += 1) {
    const key = pathParts[i];
    if (!isRecord(cursor)) return;
    if (!isRecord(cursor[key])) {
      (cursor[key] as unknown) = {};
    }
    cursor = cursor[key];
  }
  if (isRecord(cursor)) {
    cursor[pathParts[pathParts.length - 1]] = value;
  }
}

export function setConfigValue(config: WindAnalysisConfig, path: string, value: unknown): WindAnalysisConfig {
  const pathParts = path.split(".").filter((part) => part.length > 0);
  if (pathParts.length === 0) return config;
  const next = structuredClone(config) as unknown as AnyRecord;
  setOnPath(next, pathParts, value);
  return next as WindAnalysisConfig;
}

// ---------------------------------------------------------------------------
// buildRunconfigUpdates: diff server runconfig vs next config -> dotted updates
// ---------------------------------------------------------------------------

export interface RunconfigUpdate {
  key: string;
  value: unknown;
}

function flatten(prefix: string, value: unknown, out: RunconfigUpdate[]): void {
  if (isRecord(value)) {
    for (const [k, v] of Object.entries(value)) {
      flatten(prefix ? `${prefix}.${k}` : k, v, out);
    }
  } else {
    out.push({ key: prefix, value });
  }
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (isRecord(a) && isRecord(b)) {
    const aKeys = Object.keys(a);
    const bKeys = Object.keys(b);
    if (aKeys.length !== bKeys.length) return false;
    return aKeys.every((k) => deepEqual(a[k], b[k]));
  }
  return false;
}

export function buildRunconfigUpdates(
  serverRunconfig: AnyRecord,
  nextRunconfig: AnyRecord,
): RunconfigUpdate[] {
  const flatNext: RunconfigUpdate[] = [];
  flatten("", nextRunconfig, flatNext);

  const flatServer: RunconfigUpdate[] = [];
  flatten("", serverRunconfig, flatServer);
  const serverMap = new Map(flatServer.map((u) => [u.key, u.value]));

  const updates: RunconfigUpdate[] = [];
  for (const entry of flatNext) {
    if (!deepEqual(serverMap.get(entry.key), entry.value)) {
      updates.push(entry);
    }
  }
  return updates;
}
