/**
 * windkitApi — Frontend API client for all WindKit endpoints.
 *
 * Part of GoKaatru Frontend.
 */

import { useWorkspaceStore } from "../stores/workspaceStore";

const API_BASE = "/api";
const SESSION_HEADER = "X-GoKaatru-Session";

export interface WindKitResponse {
  status: string;
  result: unknown;
}

function resolveSessionId(): string | undefined {
  return useWorkspaceStore.getState().sessionId ?? undefined;
}

async function wkPost(path: string, body: Record<string, unknown> = {}): Promise<WindKitResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const sessionId = resolveSessionId();
  if (sessionId) headers[SESSION_HEADER] = sessionId;

  const res = await fetch(`${API_BASE}/windkit${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.detail ?? `WindKit request failed: ${res.status}`);
  return payload as WindKitResponse;
}

// ============================================================================
// Wind functions
// ============================================================================

export const windApi = {
  windSpeed: (u: number[], v: number[]) => wkPost("/wind/wind_speed", { u, v }),
  windDirection: (u: number[], v: number[]) => wkPost("/wind/wind_direction", { u, v }),
  windSpeedAndDirection: (u: number[], v: number[]) => wkPost("/wind/wind_speed_and_direction", { u, v }),
  windVectors: (ws: number[], wd: number[]) => wkPost("/wind/wind_vectors", { ws, wd }),
  windDirectionDifference: (wd_obs: number[], wd_mod: number[]) =>
    wkPost("/wind/wind_direction_difference", { wd_obs, wd_mod }),
  wdToSector: (wd: number[], sectors = 12, output_type = "int") =>
    wkPost("/wind/wd_to_sector", { wd, sectors, output_type }),
  vinterpWindDirection: (data: Record<string, unknown>, height: number) =>
    wkPost("/wind/vinterp_wind_direction", { data, height }),
  vinterpWindSpeed: (data: Record<string, unknown>, height: number, method = "log") =>
    wkPost("/wind/vinterp_wind_speed", { data, height, method }),
  rotorEquivalentWindSpeed: (
    wind_speed_data: Record<string, unknown>,
    wind_direction_data: Record<string, unknown>,
    hub_height: number,
    rotor_diameter: number,
  ) => wkPost("/wind/rotor_equivalent_wind_speed", { wind_speed_data, wind_direction_data, hub_height, rotor_diameter }),
  shearExtrapolate: (wind_speed_data: Record<string, unknown>, height: number, method = "power_law") =>
    wkPost("/wind/shear_extrapolate", { wind_speed_data, height, method }),
  shearExponent: (data: Record<string, unknown>) => wkPost("/wind/shear_exponent", { data }),
  veerExtrapolate: (data: Record<string, unknown>, height: number) =>
    wkPost("/wind/veer_extrapolate", { data, height }),
  windVeer: (data: Record<string, unknown>) => wkPost("/wind/wind_veer", { data }),
};

// ============================================================================
// Climate (TSWC, BWC, WWC, GWC, GeoWC)
// ============================================================================

export const climateApi = {
  // TSWC
  validateTswc: (dataset: Record<string, unknown>) => wkPost("/climate/validate_tswc", { dataset }),
  isTswc: (dataset: Record<string, unknown>) => wkPost("/climate/is_tswc", { dataset }),
  createTswc: (params: Record<string, unknown>) => wkPost("/climate/create_tswc", params),
  readTswc: (filename: string, file_format = "") => wkPost("/climate/read_tswc", { filename, file_format }),
  tswcFromDataframe: (params: Record<string, unknown>) => wkPost("/climate/tswc_from_dataframe", params),
  tswcResample: (dataset: Record<string, unknown>, freq: string) =>
    wkPost("/climate/tswc_resample", { dataset, freq }),

  // BWC
  validateBwc: (dataset: Record<string, unknown>) => wkPost("/climate/validate_bwc", { dataset }),
  isBwc: (dataset: Record<string, unknown>) => wkPost("/climate/is_bwc", { dataset }),
  createBwc: (params: Record<string, unknown>) => wkPost("/climate/create_bwc", params),
  readBwc: (filename: string, crs = "", file_format = "") =>
    wkPost("/climate/read_bwc", { filename, crs, file_format }),
  bwcFromTswc: (tswc_dataset: Record<string, unknown>, wsbin_width = 1.0, n_wsbins = 40, n_sectors = 12) =>
    wkPost("/climate/bwc_from_tswc", { tswc_dataset, wsbin_width, n_wsbins, n_sectors }),
  bwcToFile: (dataset: Record<string, unknown>, filename: string, file_format = "") =>
    wkPost("/climate/bwc_to_file", { dataset, filename, file_format }),
  combineBwcs: (datasets: Record<string, unknown>[]) => wkPost("/climate/combine_bwcs", { datasets }),
  weibullFit: (bwc_dataset: Record<string, unknown>, include_met_fields = false) =>
    wkPost("/climate/weibull_fit", { bwc_dataset, include_met_fields }),

  // WWC
  validateWwc: (dataset: Record<string, unknown>) => wkPost("/climate/validate_wwc", { dataset }),
  isWwc: (dataset: Record<string, unknown>) => wkPost("/climate/is_wwc", { dataset }),
  createWwc: (params: Record<string, unknown>) => wkPost("/climate/create_wwc", params),
  readWwc: (filename: string, file_format = "") => wkPost("/climate/read_wwc", { filename, file_format }),
  readMfwwc: (filenames: string[], file_format = "") => wkPost("/climate/read_mfwwc", { filenames, file_format }),
  wwcToFile: (dataset: Record<string, unknown>, filename: string, file_format = "") =>
    wkPost("/climate/wwc_to_file", { dataset, filename, file_format }),
  wwcToBwc: (dataset: Record<string, unknown>, ws_bins: number[]) =>
    wkPost("/climate/wwc_to_bwc", { dataset, ws_bins }),
  weibullCombined: (dataset: Record<string, unknown>) => wkPost("/climate/weibull_combined", { dataset }),

  // GWC
  validateGwc: (dataset: Record<string, unknown>) => wkPost("/climate/validate_gwc", { dataset }),
  isGwc: (dataset: Record<string, unknown>) => wkPost("/climate/is_gwc", { dataset }),
  createGwc: (params: Record<string, unknown>) => wkPost("/climate/create_gwc", params),
  readGwc: (filename: string, crs = "", file_format = "") =>
    wkPost("/climate/read_gwc", { filename, crs, file_format }),
  gwcToFile: (dataset: Record<string, unknown>, filename: string, file_format = "") =>
    wkPost("/climate/gwc_to_file", { dataset, filename, file_format }),

  // GeoWC
  validateGeowc: (dataset: Record<string, unknown>) => wkPost("/climate/validate_geowc", { dataset }),
  isGeowc: (dataset: Record<string, unknown>) => wkPost("/climate/is_geowc", { dataset }),
};

// ============================================================================
// Climate stats
// ============================================================================

export const climateStatsApi = {
  createMetFields: (params: Record<string, unknown>) => wkPost("/climate-stats/create_met_fields", params),
  meanWsMoment: (wc_dataset: Record<string, unknown>, moment = 1, bysector = false) =>
    wkPost("/climate-stats/mean_ws_moment", { wc_dataset, moment, bysector }),
  wsCdf: (wc_dataset: Record<string, unknown>, bysector = false) =>
    wkPost("/climate-stats/ws_cdf", { wc_dataset, bysector }),
  wsFreqGtMean: (wc_dataset: Record<string, unknown>, bysector = false) =>
    wkPost("/climate-stats/ws_freq_gt_mean", { wc_dataset, bysector }),
  meanWindSpeed: (wc_dataset: Record<string, unknown>, bysector = false) =>
    wkPost("/climate-stats/mean_wind_speed", { wc_dataset, bysector }),
  meanPowerDensity: (wc_dataset: Record<string, unknown>, bysector = false, air_density = 1.225) =>
    wkPost("/climate-stats/mean_power_density", { wc_dataset, bysector, air_density }),
  getCrossPredictions: (wcs_dataset: Record<string, unknown>, wcs_src_dataset?: Record<string, unknown>) =>
    wkPost("/climate-stats/get_cross_predictions", { wcs_dataset, wcs_src_dataset }),
};

// ============================================================================
// LTC
// ============================================================================

export const ltcApi = {
  linregMcp: (
    measured_dataset: Record<string, unknown>,
    reference_dataset: Record<string, unknown>,
    ws_cutoff = 0.0,
    n_sectors = 12,
  ) => wkPost("/ltc/linreg_mcp", { measured_dataset, reference_dataset, ws_cutoff, n_sectors }),
  varratMcp: (
    measured_dataset: Record<string, unknown>,
    reference_dataset: Record<string, unknown>,
    fit_intercept = true,
    ws_cutoff = 0.0,
    n_sectors = 12,
  ) => wkPost("/ltc/varrat_mcp", { measured_dataset, reference_dataset, fit_intercept, ws_cutoff, n_sectors }),
};

// ============================================================================
// Topography
// ============================================================================

export const topographyApi = {
  getLandcoverTable: (dataset: Record<string, unknown>) =>
    wkPost("/topography/get_landcover_table", { dataset }),
  addLandcoverTable: (geojson_data: Record<string, unknown>, lctable: Record<string, unknown>) =>
    wkPost("/topography/add_landcover_table", { geojson_data, lctable }),
  roughnessToLandcover: (dataset: Record<string, unknown>) =>
    wkPost("/topography/roughness_to_landcover", { dataset }),
  landcoverToRoughness: (geojson_data: Record<string, unknown>, lctable: Record<string, unknown>) =>
    wkPost("/topography/landcover_to_roughness", { geojson_data, lctable }),
  readRoughnessMap: (filename: string, crs = "") =>
    wkPost("/topography/read_roughness_map", { filename, crs }),
  readLandcoverMap: (filename: string, crs = "") =>
    wkPost("/topography/read_landcover_map", { filename, crs }),
  landcoverMapToFile: (dataset: Record<string, unknown>, filename: string) =>
    wkPost("/topography/landcover_map_to_file", { dataset, filename }),
  roughnessMapToFile: (dataset: Record<string, unknown>, filename: string) =>
    wkPost("/topography/roughness_map_to_file", { dataset, filename }),
  readElevationMap: (filename: string, crs = "") =>
    wkPost("/topography/read_elevation_map", { filename, crs }),
  elevationMapToFile: (dataset: Record<string, unknown>, filename: string) =>
    wkPost("/topography/elevation_map_to_file", { dataset, filename }),
  createRasterMap: (params: Record<string, unknown>) =>
    wkPost("/topography/create_raster_map", params),
  getRasterMap: (bbox: number[], dataset = "copernicus_dem_30", band = "", source = "") =>
    wkPost("/topography/get_raster_map", { bbox, dataset, band, source }),
  createVectorMap: (bbox: number[], map_type = "elevation") =>
    wkPost("/topography/create_vector_map", { bbox, map_type }),
  getVectorMap: (bbox: number[], dataset = "", source = "") =>
    wkPost("/topography/get_vector_map", { bbox, dataset, source }),
  linesToPolygons: (geojson_data: Record<string, unknown>) =>
    wkPost("/topography/lines_to_polygons", { geojson_data }),
  polygonsToLines: (geojson_data: Record<string, unknown>, lctable?: Record<string, unknown>, map_type = "") =>
    wkPost("/topography/polygons_to_lines", { geojson_data, lctable, map_type }),
  snapToLayer: (geojson_data: Record<string, unknown>, tolerance = 1.0) =>
    wkPost("/topography/snap_to_layer", { geojson_data, tolerance }),
  checkDeadEnds: (geojson_data: Record<string, unknown>) =>
    wkPost("/topography/check_dead_ends", { geojson_data }),
  checkLinesCross: (geojson_data: Record<string, unknown>) =>
    wkPost("/topography/check_lines_cross", { geojson_data }),
};

// ============================================================================
// Wind farm
// ============================================================================

export const windfarmApi = {
  validateWindturbines: (dataset: Record<string, unknown>) =>
    wkPost("/windfarm/validate_windturbines", { dataset }),
  isWindturbines: (dataset: Record<string, unknown>) =>
    wkPost("/windfarm/is_windturbines", { dataset }),
  checkWtgKeys: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/windfarm/check_wtg_keys", { dataset_a, dataset_b }),
  createWindTurbinesFromDataframe: (dataset: Record<string, unknown>) =>
    wkPost("/windfarm/create_wind_turbines_from_dataframe", { dataset }),
  createWindTurbinesFromArrays: (params: Record<string, unknown>) =>
    wkPost("/windfarm/create_wind_turbines_from_arrays", params),
  windTurbinesToGeodataframe: (dataset: Record<string, unknown>) =>
    wkPost("/windfarm/wind_turbines_to_geodataframe", { dataset }),
  validateWtg: (dataset: Record<string, unknown>) => wkPost("/windfarm/validate_wtg", { dataset }),
  isWtg: (dataset: Record<string, unknown>) => wkPost("/windfarm/is_wtg", { dataset }),
  estimateRegulationType: (dataset: Record<string, unknown>) =>
    wkPost("/windfarm/estimate_regulation_type", { dataset }),
  readWtg: (filename: string, file_format = "") =>
    wkPost("/windfarm/read_wtg", { filename, file_format }),
  wtgPower: (wtg_dataset: Record<string, unknown>, ws: number[] = [], interp_method = "linear") =>
    wkPost("/windfarm/wtg_power", { wtg_dataset, ws, interp_method }),
  wtgCp: (wtg_dataset: Record<string, unknown>, ws: number[] = [], air_density = 1.225) =>
    wkPost("/windfarm/wtg_cp", { wtg_dataset, ws, air_density }),
  wtgCt: (wtg_dataset: Record<string, unknown>, ws: number[] = [], interp_method = "linear") =>
    wkPost("/windfarm/wtg_ct", { wtg_dataset, ws, interp_method }),
  validateUncertaintyTable: (table: Record<string, unknown>) =>
    wkPost("/windfarm/validate_uncertainty_table", { table }),
  getUncertaintyTable: (table_name = "") =>
    wkPost("/windfarm/get_uncertainty_table", { table_name }),
  totalUncertainty: (table: Record<string, unknown>) =>
    wkPost("/windfarm/total_uncertainty", { table }),
  uncertaintyTableSummary: (table: Record<string, unknown>) =>
    wkPost("/windfarm/uncertainty_table_summary", { table }),
  totalUncertaintyFactor: (table: Record<string, unknown>) =>
    wkPost("/windfarm/total_uncertainty_factor", { table }),
};

// ============================================================================
// Spatial
// ============================================================================

export const spatialApi = {
  getCrs: (dataset: Record<string, unknown>) => wkPost("/spatial/get_crs", { dataset }),
  setCrs: (dataset: Record<string, unknown>, crs: string) => wkPost("/spatial/set_crs", { dataset, crs }),
  crsAreEqual: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/spatial/crs_are_equal", { dataset_a, dataset_b }),
  createDataset: (params: Record<string, unknown>) => wkPost("/spatial/create_dataset", params),
  createRaster: (params: Record<string, unknown>) => wkPost("/spatial/create_raster", params),
  createPoint: (params: Record<string, unknown>) => wkPost("/spatial/create_point", params),
  createStackedPoint: (params: Record<string, unknown>) => wkPost("/spatial/create_stacked_point", params),
  createCuboid: (params: Record<string, unknown>) => wkPost("/spatial/create_cuboid", params),
  isPoint: (dataset: Record<string, unknown>) => wkPost("/spatial/is_point", { dataset }),
  isStackedPoint: (dataset: Record<string, unknown>) => wkPost("/spatial/is_stacked_point", { dataset }),
  isCuboid: (dataset: Record<string, unknown>) => wkPost("/spatial/is_cuboid", { dataset }),
  isRaster: (dataset: Record<string, unknown>) => wkPost("/spatial/is_raster", { dataset }),
  toPoint: (dataset: Record<string, unknown>) => wkPost("/spatial/to_point", { dataset }),
  toCuboid: (dataset: Record<string, unknown>) => wkPost("/spatial/to_cuboid", { dataset }),
  toStackedPoint: (dataset: Record<string, unknown>) => wkPost("/spatial/to_stacked_point", { dataset }),
  toRaster: (dataset: Record<string, unknown>) => wkPost("/spatial/to_raster", { dataset }),
  gdfToDs: (geojson_data: Record<string, unknown>, height = 0.0, struct = "point") =>
    wkPost("/spatial/gdf_to_ds", { geojson_data, height, struct }),
  dsToGdf: (dataset: Record<string, unknown>, include_height = false) =>
    wkPost("/spatial/ds_to_gdf", { dataset, include_height }),
  interpStructuredLike: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/spatial/interp_structured_like", { dataset_a, dataset_b }),
  interpUnstructured: (dataset: Record<string, unknown>) =>
    wkPost("/spatial/interp_unstructured", { dataset }),
  interpUnstructuredLike: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/spatial/interp_unstructured_like", { dataset_a, dataset_b }),
  areSpatiallyEqual: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/spatial/are_spatially_equal", { dataset_a, dataset_b }),
  equalSpatialShape: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/spatial/equal_spatial_shape", { dataset_a, dataset_b }),
  covers: (dataset_a: Record<string, unknown>, dataset_b: Record<string, unknown>) =>
    wkPost("/spatial/covers", { dataset_a, dataset_b }),
  clip: (dataset: Record<string, unknown>, mask_geojson: Record<string, unknown>) =>
    wkPost("/spatial/clip", { dataset, mask_geojson }),
  clipWithMargin: (dataset: Record<string, unknown>, clipper_dataset: Record<string, unknown>, margin = 0.0) =>
    wkPost("/spatial/clip_with_margin", { dataset, clipper_dataset, margin }),
  mask: (dataset: Record<string, unknown>, mask_geojson: Record<string, unknown>) =>
    wkPost("/spatial/mask", { dataset, mask_geojson }),
  nearestPoints: (ref_dataset: Record<string, unknown>, target_dataset: Record<string, unknown>) =>
    wkPost("/spatial/nearest_points", { ref_dataset, target_dataset }),
  reproject: (dataset: Record<string, unknown>, to_crs: string) =>
    wkPost("/spatial/reproject", { dataset, to_crs }),
  warp: (dataset: Record<string, unknown>, to_crs: string, resolution = 0.0) =>
    wkPost("/spatial/warp", { dataset, to_crs, resolution }),
  countSpatialPoints: (dataset: Record<string, unknown>) =>
    wkPost("/spatial/count_spatial_points", { dataset }),
};

// ============================================================================
// Plotting
// ============================================================================

export const plottingApi = {
  histogram: (bwc_dataset: Record<string, unknown>, style = "bar", weibull = false) =>
    wkPost("/plotting/histogram", { bwc_dataset, style, weibull }),
  histogramLines: (dataset: Record<string, unknown>) =>
    wkPost("/plotting/histogram_lines", { dataset }),
  operationalCurves: (dataset: Record<string, unknown>) =>
    wkPost("/plotting/operational_curves", { dataset }),
  rasterPlot: (data_array: Record<string, unknown>, contour = false) =>
    wkPost("/plotting/raster_plot", { data_array, contour }),
  roughnessRose: (dataset: Record<string, unknown>, style = "bar") =>
    wkPost("/plotting/roughness_rose", { dataset, style }),
  timeSeries: (tswc_dataset: Record<string, unknown>, range_slider = false) =>
    wkPost("/plotting/time_series", { tswc_dataset, range_slider }),
  verticalProfile: (data?: Record<string, unknown>) =>
    wkPost("/plotting/vertical_profile", data ? { data } : {}),
  windRose: (bwc_dataset: Record<string, unknown>, wind_speed_bins: number[] = [], style = "bar") =>
    wkPost("/plotting/wind_rose", { bwc_dataset, wind_speed_bins, style }),
  landcoverMap: (geojson_data: Record<string, unknown>, column = "") =>
    wkPost("/plotting/landcover_map", { geojson_data, column }),
};

// ============================================================================
// Weibull
// ============================================================================

export const weibullApi = {
  fitWaspM1M3Fgtm: (m1: number, m3: number, fgtm: number) =>
    wkPost("/weibull/fit_wasp_m1_m3_fgtm", { m1, m3, fgtm }),
  fitWaspM1M3: (m1: number, m3: number) =>
    wkPost("/weibull/fit_wasp_m1_m3", { m1, m3 }),
  fitKSumlogm: (data: unknown) =>
    wkPost("/weibull/fit_k_sumlogm", { data }),
  moment: (A: number, k: number, n = 1) =>
    wkPost("/weibull/moment", { A, k, n }),
  pdf: (A: number, k: number, x: number[]) =>
    wkPost("/weibull/pdf", { A, k, x }),
  cdf: (A: number, k: number, x: number[]) =>
    wkPost("/weibull/cdf", { A, k, x }),
  freqGtMean: (A: number, k: number) =>
    wkPost("/weibull/freq_gt_mean", { A, k }),
  probability: (A: number, k: number, lower: number, upper: number) =>
    wkPost("/weibull/probability", { A, k, lower, upper }),
};

// ============================================================================
// Other (WAsP, Coordinates, ERA5, Tutorial)
// ============================================================================

export const windkitOtherApi = {
  readCfdres: (filename: string, crs: string) =>
    wkPost("/other/read_cfdres", { filename, crs }),
  createSectorCoords: (bins = 12, start = 0.0) =>
    wkPost("/other/create_sector_coords", { bins, start }),
  createWsbinCoords: (bins = 30, width = 1.0, start = 0.0) =>
    wkPost("/other/create_wsbin_coords", { bins, width, start }),
  getEra5: (datetime_range: string, bbox: number[] = [], source = "") =>
    wkPost("/other/get_era5", { datetime_range, bbox, source }),
  getTutorialData: (name: string) =>
    wkPost(`/other/get_tutorial_data?name=${encodeURIComponent(name)}`),
  loadTutorialData: (name: string) =>
    wkPost(`/other/load_tutorial_data?name=${encodeURIComponent(name)}`),
};
