import type { AnalysisSummary, DatasetPreview } from "./api";
import type { WindAnalysisConfig } from "../types/analysis";

export type NormalizedAssetFormat =
  | "json"
  | "table-records"
  | "xarray-dataset"
  | "xarray-dataarray"
  | "geojson"
  | "plotly";

export interface NormalizedAsset {
  id: string;
  label: string;
  source: "standard" | "windkit" | "workflow" | "ui";
  kind: "config" | "summary" | "sensor-inventory" | "dataset-preview" | "windkit-result" | "operation-result";
  format: NormalizedAssetFormat;
  compatibility: string[];
  payload: unknown;
  summary: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function summarizePayload(value: unknown): string {
  if (Array.isArray(value)) {
    return `${value.length} records`;
  }
  if (isRecord(value)) {
    return `${Object.keys(value).length} top-level keys`;
  }
  if (value === null || value === undefined) {
    return "empty payload";
  }
  return String(value);
}

export function detectNormalizedFormat(payload: unknown): NormalizedAssetFormat {
  if (Array.isArray(payload)) {
    return "table-records";
  }
  if (isRecord(payload)) {
    if (Array.isArray(payload.features) && typeof payload.type === "string") {
      return "geojson";
    }
    if (Array.isArray(payload.data) && isRecord(payload.layout)) {
      return "plotly";
    }
    if (isRecord(payload.coords) && isRecord(payload.data_vars)) {
      return "xarray-dataset";
    }
    if (isRecord(payload.coords) && payload.data !== undefined) {
      return "xarray-dataarray";
    }
  }
  return "json";
}

function compatibilityForFormat(format: NormalizedAssetFormat): string[] {
  switch (format) {
    case "geojson":
      return ["geojson", "dataset", "json"];
    case "xarray-dataset":
      return ["dataset", "json"];
    case "xarray-dataarray":
      return ["dataarray", "dataset", "json"];
    case "table-records":
      return ["table", "dataset", "json"];
    case "plotly":
      return ["plotly", "json"];
    default:
      return ["json"];
  }
}

export function assetFitsField(asset: NormalizedAsset, fieldName: string): boolean {
  const lower = fieldName.toLowerCase();
  if (lower.includes("geojson") || lower.includes("bbox")) {
    return asset.compatibility.includes("geojson") || asset.compatibility.includes("json");
  }
  if (lower.includes("dataset") || lower.includes("tswc") || lower.includes("bwc") || lower.includes("wwc") || lower.includes("gwc")) {
    return asset.compatibility.includes("dataset") || asset.compatibility.includes("json");
  }
  if (lower === "data" || lower.endsWith("_data") || lower.includes("wind_speed_data") || lower.includes("wind_direction_data")) {
    return asset.compatibility.includes("dataarray") || asset.compatibility.includes("dataset") || asset.compatibility.includes("json");
  }
  return asset.compatibility.includes("json");
}

export function buildConfigAsset(config: WindAnalysisConfig): NormalizedAsset {
  return {
    id: "core:config",
    label: "Central wind analysis config",
    source: "ui",
    kind: "config",
    format: "json",
    compatibility: ["json", "dataset"],
    payload: config,
    summary: `${config.project.name} · ${config.project.measurementType} · hub ${config.site.hubHeightM}m`,
  };
}

export function buildSummaryAsset(summary: AnalysisSummary | null): NormalizedAsset | null {
  if (summary === null) {
    return null;
  }
  return {
    id: "core:summary",
    label: "Session analysis summary",
    source: "standard",
    kind: "summary",
    format: "json",
    compatibility: ["json"],
    payload: summary,
    summary: `Sensors ${summary.sensor_count ?? 0} · LTC ${(summary.ltc_algorithms_run ?? []).length}`,
  };
}

export function buildSensorInventoryAsset(sensors: Array<Record<string, unknown>>): NormalizedAsset {
  return {
    id: "core:sensors",
    label: "Sensor inventory",
    source: "standard",
    kind: "sensor-inventory",
    format: "table-records",
    compatibility: ["table", "json"],
    payload: sensors,
    summary: `${sensors.length} sensors mapped`,
  };
}

export function buildDatasetPreviewAsset(datasetId: string, preview: DatasetPreview): NormalizedAsset {
  const rows = preview.rows ?? preview.preview_rows ?? [];
  return {
    id: `dataset:${datasetId}`,
    label: `Dataset preview ${datasetId}`,
    source: "standard",
    kind: "dataset-preview",
    format: "table-records",
    compatibility: ["table", "dataset", "json"],
    payload: rows,
    summary: `${rows.length} preview rows`,
  };
}

export function buildWindKitResultAsset(toolPath: string, result: unknown): NormalizedAsset {
  const format = detectNormalizedFormat(result);
  return {
    id: `windkit:${toolPath}`,
    label: toolPath.replace("/api/windkit/", "WindKit / "),
    source: "windkit",
    kind: "windkit-result",
    format,
    compatibility: compatibilityForFormat(format),
    payload: result,
    summary: summarizePayload(result),
  };
}

export function buildOperationResultAsset(label: string, result: unknown): NormalizedAsset {
  const format = detectNormalizedFormat(result);
  return {
    id: `operation:${label}`,
    label,
    source: "workflow",
    kind: "operation-result",
    format,
    compatibility: compatibilityForFormat(format),
    payload: result,
    summary: summarizePayload(result),
  };
}

export function previewAssetJson(asset: NormalizedAsset): string {
  return JSON.stringify(asset.payload, null, 2).slice(0, 1200);
}

export function upsertAssets(existing: NormalizedAsset[], incoming: Array<NormalizedAsset | null | undefined>): NormalizedAsset[] {
  const next = new Map(existing.map((asset) => [asset.id, asset]));
  for (const asset of incoming) {
    if (!asset) {
      continue;
    }
    next.set(asset.id, asset);
  }
  return Array.from(next.values());
}