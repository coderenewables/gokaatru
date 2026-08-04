import { describe, expect, it } from "vitest";

import {
  buildConfigAsset,
  buildDatasetPreviewAsset,
  buildOperationResultAsset,
  buildPlotAsset,
  buildSensorInventoryAsset,
  buildSummaryAsset,
  upsertAssets,
} from "../lib/normalization";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import type { AnalysisSummary, SensorRow } from "../types/analysis";

describe("asset builders", () => {
  it("buildConfigAsset prompts for hub height until it is configured", () => {
    const config = createDefaultWindAnalysisConfig();
    const asset = buildConfigAsset(config);
    expect(asset.kind).toBe("config");
    expect(asset.id).toBe("config");
    expect(asset.summary).toContain("hub height required");
    expect(asset.summary).toContain("power_law");
  });

  it("buildSummaryAsset reports completed steps + sensor count", () => {
    const summary: AnalysisSummary = { completed_steps: ["timeseries", "datamodel"], sensor_count: 5 };
    const asset = buildSummaryAsset(summary);
    expect(asset.kind).toBe("summary");
    expect(asset.summary).toContain("2 step(s)");
    expect(asset.summary).toContain("5 sensor(s)");
  });

  it("buildSensorInventoryAsset counts anemometers", () => {
    const sensors: SensorRow[] = [
      { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
      { name: "Dir_80m", height_m: 80, sensor_type: "wind_direction", data_coverage_pct: 95, record_count: 1000 },
      { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 92, record_count: 980 },
    ];
    const asset = buildSensorInventoryAsset(sensors);
    expect(asset.summary).toContain("3 sensor(s)");
    expect(asset.summary).toContain("2 anemometer(s)");
  });

  it("buildDatasetPreviewAsset uses total_rows when present", () => {
    const asset = buildDatasetPreviewAsset("abc123", { total_rows: 52560, columns: ["a", "b"] });
    expect(asset.summary).toContain("52560 row(s)");
    expect(asset.summary).toContain("2 column(s)");
  });

  it("buildOperationResultAsset summarizes rows / coverage / algorithm", () => {
    expect(buildOperationResultAsset("upload", { rows: 52560 }).summary).toContain("52560 rows");
    expect(buildOperationResultAsset("ltc", { algorithm: "speedsort" }).summary).toBe("speedsort");
    expect(buildOperationResultAsset("cov", { coverage_pct: 87.654 }).summary).toBe("87.7% coverage");
    expect(buildOperationResultAsset("ok", { status: "ok" }).summary).toBe("Completed");
  });

  it("buildPlotAsset carries the plot title", () => {
    const asset = buildPlotAsset("weibull", "Weibull fit · Spd_80m");
    expect(asset.kind).toBe("plot");
    expect(asset.label).toBe("Weibull fit · Spd_80m");
  });
});

describe("upsertAssets", () => {
  it("inserts new assets and replaces by id", () => {
    const a1 = buildConfigAsset(createDefaultWindAnalysisConfig());
    const start = upsertAssets([], [a1]);
    expect(start).toHaveLength(1);

    // Replace config with a renamed project.
    const renamed = createDefaultWindAnalysisConfig();
    renamed.project.name = "Site Beta";
    const a2 = buildConfigAsset(renamed);
    const next = upsertAssets(start, [a2]);
    expect(next).toHaveLength(1);
    expect(next[0].summary).toContain("Site Beta");
  });

  it("dedupes by id and groups by kind in canonical order", () => {
    const config = buildConfigAsset(createDefaultWindAnalysisConfig());
    const summary = buildSummaryAsset({ completed_steps: [], sensor_count: 0 });
    const plot = buildPlotAsset("windrose", "Wind Rose");
    const result = upsertAssets([], [plot, summary, config]);
    // Canonical order: config, summary, ..., plot
    expect(result.map((a) => a.kind)).toEqual(["config", "summary", "plot"]);
  });

  it("preserves existing assets not in the incoming batch", () => {
    const config = buildConfigAsset(createDefaultWindAnalysisConfig());
    const summary = buildSummaryAsset({ completed_steps: [], sensor_count: 0 });
    const existing = upsertAssets([], [config]);
    const next = upsertAssets(existing, [summary]);
    expect(next.map((a) => a.kind)).toEqual(["config", "summary"]);
  });
});
