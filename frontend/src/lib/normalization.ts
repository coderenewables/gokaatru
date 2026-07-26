// Asset normalization for the Assets drawer (spec §3.1 / §10 Phase B).
//
// Backend responses are reshaped into a uniform `NormalizedAsset` shape so the
// drawer can render datasets, sensor inventories, operation results, plots,
// and config snapshots from one component.
import type { AnalysisSummary, SensorRow, WindAnalysisConfig } from "../types/analysis";

export type AssetKind =
  | "config"
  | "summary"
  | "sensor_inventory"
  | "dataset_preview"
  | "operation_result"
  | "plot";

export interface NormalizedAsset {
  id: string;
  kind: AssetKind;
  label: string;
  stage?: string;
  summary: string;
  /** Original payload for expandable detail views. */
  payload: unknown;
  updatedAt?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// ---------------------------------------------------------------------------
// Builders
// ---------------------------------------------------------------------------

export function buildConfigAsset(config: WindAnalysisConfig): NormalizedAsset {
  return {
    id: "config",
    kind: "config",
    label: "Central config",
    summary: `${config.project.name} · hub ${config.site.hubHeightM}m · ${config.shear.method}`,
    payload: config,
    updatedAt: new Date().toISOString(),
  };
}

export function buildSummaryAsset(summary: AnalysisSummary): NormalizedAsset {
  const steps = summary.completed_steps?.length ?? 0;
  const sensors = summary.sensor_count ?? 0;
  return {
    id: "summary",
    kind: "summary",
    label: "Analysis summary",
    summary: `${steps} step(s) done · ${sensors} sensor(s)`,
    payload: summary,
    updatedAt: new Date().toISOString(),
  };
}

export function buildSensorInventoryAsset(sensors: SensorRow[]): NormalizedAsset {
  const speedSensors = sensors.filter((s) => s.sensor_type === "wind_speed").length;
  return {
    id: "sensor_inventory",
    kind: "sensor_inventory",
    label: "Sensor inventory",
    summary: `${sensors.length} sensor(s) · ${speedSensors} anemometer(s)`,
    payload: sensors,
    updatedAt: new Date().toISOString(),
  };
}

export interface DatasetPreviewLike {
  dataset_id?: string;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  preview_rows?: Array<Record<string, unknown>>;
  total_rows?: number;
  start?: string;
  end?: string;
  [key: string]: unknown;
}

export function buildDatasetPreviewAsset(datasetId: string, preview: DatasetPreviewLike): NormalizedAsset {
  const rows = preview.total_rows ?? preview.rows?.length ?? preview.preview_rows?.length ?? 0;
  return {
    id: `dataset_preview:${datasetId}`,
    kind: "dataset_preview",
    label: `Dataset preview · ${datasetId.slice(0, 8)}`,
    summary: `${rows} row(s) · ${(preview.columns ?? []).length} column(s)`,
    payload: preview,
    updatedAt: new Date().toISOString(),
  };
}

export function buildOperationResultAsset(label: string, result: unknown): NormalizedAsset {
  const id = `operation:${label}`;
  const summary = summarizeResult(result);
  return {
    id,
    kind: "operation_result",
    label,
    summary,
    payload: result,
    updatedAt: new Date().toISOString(),
  };
}

export function buildPlotAsset(plotName: string, title: string): NormalizedAsset {
  return {
    id: `plot:${plotName}`,
    kind: "plot",
    label: title,
    summary: plotName,
    payload: { plotName, title },
    updatedAt: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// upsertAssets: insert-or-replace by id (keeps the array bounded & deduped)
// ---------------------------------------------------------------------------

export function upsertAssets(existing: NormalizedAsset[], incoming: NormalizedAsset[]): NormalizedAsset[] {
  const byId = new Map<string, NormalizedAsset>();
  for (const asset of existing) byId.set(asset.id, asset);
  for (const asset of incoming) byId.set(asset.id, asset);
  // Order: stable by kind, then label.
  const kindOrder: AssetKind[] = [
    "config",
    "summary",
    "sensor_inventory",
    "dataset_preview",
    "operation_result",
    "plot",
  ];
  return Array.from(byId.values()).sort((a, b) => {
    const ka = kindOrder.indexOf(a.kind);
    const kb = kindOrder.indexOf(b.kind);
    if (ka !== kb) return ka - kb;
    return a.label.localeCompare(b.label);
  });
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function summarizeResult(result: unknown): string {
  if (!isRecord(result)) return "Completed";
  if (typeof result.message === "string") return result.message;
  if (typeof result.status === "string" && result.status !== "ok") return result.status;
  const countKeys = ["rows", "count", "records", "record_count"];
  for (const key of countKeys) {
    const value = result[key];
    if (typeof value === "number") return `${value} ${key}`;
  }
  if (Array.isArray(result.algorithms)) return `${result.algorithms.length} algorithm(s)`;
  if (typeof result.algorithm === "string") return result.algorithm;
  if (typeof result.coverage_pct === "number") return `${result.coverage_pct.toFixed(1)}% coverage`;
  return "Completed";
}
