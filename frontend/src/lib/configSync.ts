import { createDefaultWindAnalysisConfig } from "./defaultConfig";
import type { WindAnalysisConfig } from "../types/analysis";
import { measurementTypeSchema, windAnalysisConfigSchema } from "../types/analysis";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneValue<T>(value: T): T {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

function mergeDeep(target: Record<string, unknown>, source: Record<string, unknown>) {
  for (const [key, value] of Object.entries(source)) {
    if (Array.isArray(value)) {
      target[key] = [...value];
      continue;
    }
    if (isRecord(value)) {
      const existing = isRecord(target[key]) ? (target[key] as Record<string, unknown>) : {};
      target[key] = mergeDeep({ ...existing }, value);
      continue;
    }
    target[key] = value;
  }
  return target;
}

function flattenConfig(value: unknown, prefix = "", output: Record<string, unknown> = {}): Record<string, unknown> {
  if (Array.isArray(value) || !isRecord(value)) {
    output[prefix] = value;
    return output;
  }

  for (const [key, child] of Object.entries(value)) {
    const nextPrefix = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(child) || !isRecord(child)) {
      output[nextPrefix] = child;
      continue;
    }
    flattenConfig(child, nextPrefix, output);
  }
  return output;
}

export function hydrateConfigFromRunconfig(runconfig: Record<string, unknown>): WindAnalysisConfig {
  const next = cloneValue(createDefaultWindAnalysisConfig()) as Record<string, unknown>;

  const projectName = runconfig.project_name;
  if (typeof projectName === "string" && projectName.length > 0) {
    (next.project as Record<string, unknown>).name = projectName;
  }

  const measurementType = runconfig.measurement_type;
  if (typeof measurementType === "string") {
    const parsed = measurementTypeSchema.safeParse(measurementType);
    if (parsed.success) {
      (next.project as Record<string, unknown>).measurementType = parsed.data;
    }
  }

  const hubHeight = runconfig.hub_height_m;
  if (typeof hubHeight === "number") {
    (next.site as Record<string, unknown>).hubHeightM = hubHeight;
    ((next.ltc as Record<string, unknown>).uncertainty as Record<string, unknown>).hubHeightM = hubHeight;
    (next.shear as Record<string, unknown>).targetHubHeightM = hubHeight;
  }

  const location = runconfig.location;
  if (isRecord(location)) {
    if (typeof location.latitude === "number") {
      (next.site as Record<string, unknown>).latitude = location.latitude;
      (next.reanalysis as Record<string, unknown>).searchLatitude = location.latitude;
      const primaryMast = (((next.mast as Record<string, unknown>).masts as unknown[])?.[0] ?? {}) as Record<string, unknown>;
      primaryMast.latitude = location.latitude;
    }
    if (typeof location.longitude === "number") {
      (next.site as Record<string, unknown>).longitude = location.longitude;
      (next.reanalysis as Record<string, unknown>).searchLongitude = location.longitude;
      const primaryMast = (((next.mast as Record<string, unknown>).masts as unknown[])?.[0] ?? {}) as Record<string, unknown>;
      primaryMast.longitude = location.longitude;
    }
    if (typeof location.elevation_m === "number") {
      (next.site as Record<string, unknown>).elevationM = location.elevation_m;
    }
  }

  for (const sectionName of ["project", "site", "mast", "standardization", "inputs", "cleaning", "shear", "reanalysis", "ltc", "workflow", "windkit", "compare"]) {
    const section = runconfig[sectionName];
    if (isRecord(section) && isRecord(next[sectionName])) {
      next[sectionName] = mergeDeep(next[sectionName] as Record<string, unknown>, section);
    }
  }

  return windAnalysisConfigSchema.parse(next);
}

export function serializeConfigToRunconfig(config: WindAnalysisConfig): Record<string, unknown> {
  return {
    project_name: config.project.name,
    measurement_type: config.project.measurementType,
    hub_height_m: config.site.hubHeightM,
    location: {
      latitude: config.site.latitude,
      longitude: config.site.longitude,
      elevation_m: config.site.elevationM,
    },
    project: config.project,
    site: config.site,
    mast: config.mast,
    standardization: config.standardization,
    inputs: config.inputs,
    cleaning: config.cleaning,
    shear: config.shear,
    reanalysis: config.reanalysis,
    ltc: config.ltc,
    workflow: config.workflow,
    windkit: config.windkit,
    compare: config.compare,
  };
}

export function buildRunconfigUpdates(
  previousRunconfig: Record<string, unknown>,
  nextRunconfig: Record<string, unknown>,
): Array<{ key: string; value: unknown }> {
  const previousFlat = flattenConfig(previousRunconfig);
  const nextFlat = flattenConfig(nextRunconfig);
  const keys = new Set([...Object.keys(previousFlat), ...Object.keys(nextFlat)]);
  const updates: Array<{ key: string; value: unknown }> = [];

  for (const key of Array.from(keys).sort()) {
    if (JSON.stringify(previousFlat[key]) === JSON.stringify(nextFlat[key])) {
      continue;
    }
    updates.push({ key, value: nextFlat[key] ?? null });
  }

  return updates;
}

export function setConfigValue(config: WindAnalysisConfig, path: string, value: unknown): WindAnalysisConfig {
  const next = cloneValue(config) as Record<string, unknown>;
  const parts = path.split(".");
  let cursor: Record<string, unknown> = next;

  for (const part of parts.slice(0, -1)) {
    const child = cursor[part];
    if (isRecord(child)) {
      cursor = child;
      continue;
    }
    cursor[part] = {};
    cursor = cursor[part] as Record<string, unknown>;
  }

  cursor[parts[parts.length - 1]] = value;
  return windAnalysisConfigSchema.parse(next);
}