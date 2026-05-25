import { assetFitsField, buildConfigAsset, buildWindKitResultAsset, detectNormalizedFormat } from "../lib/normalization";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";

describe("normalization", () => {
  it("detects xarray datasets and geojson payloads", () => {
    expect(detectNormalizedFormat({ coords: {}, data_vars: {} })).toBe("xarray-dataset");
    expect(detectNormalizedFormat({ type: "FeatureCollection", features: [] })).toBe("geojson");
  });

  it("marks config assets as reusable json payloads", () => {
    const asset = buildConfigAsset(createDefaultWindAnalysisConfig());

    expect(asset.summary).toMatch(/hub 120m/i);
    expect(assetFitsField(asset, "dataset")).toBe(true);
  });

  it("creates windkit assets that fit dataset and geojson fields based on payload shape", () => {
    const datasetAsset = buildWindKitResultAsset("/api/windkit/climate/read_tswc", { coords: {}, data_vars: {} });
    const geoAsset = buildWindKitResultAsset("/api/windkit/topography/create_vector_map", { type: "FeatureCollection", features: [] });

    expect(assetFitsField(datasetAsset, "dataset")).toBe(true);
    expect(assetFitsField(geoAsset, "geojson_data")).toBe(true);
  });
});