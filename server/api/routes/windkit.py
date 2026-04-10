"""windkit — FastAPI routes for all WindKit functions.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from server.api.deps import get_session_state, to_bad_request
from server.api.windkit_schemas import (
    BboxRequest,
    BwcFromTswcRequest,
    ClipRequest,
    ClipWithMarginRequest,
    CombineBwcsRequest,
    CreateBwcRequest,
    CreateGwcRequest,
    CreateSectorCoordsRequest,
    CreateSpatialRequest,
    CreateTswcRequest,
    CreateTurbinesFromArraysRequest,
    CreateVectorMapRequest,
    CreateWsbinCoordsRequest,
    CreateWwcRequest,
    CrossPredictionsRequest,
    DataArrayRequest,
    DatasetRequest,
    DirectionDifferenceRequest,
    DsToGdfRequest,
    GdfToDsRequest,
    GeoJsonRequest,
    GetEra5Request,
    GetRasterMapRequest,
    GetUncertaintyTableRequest,
    GetVectorMapRequest,
    LandcoverTableRequest,
    LtcRequest,
    LtcVarRatRequest,
    MeanPowerDensityRequest,
    MeanWsMomentRequest,
    NearestPointsRequest,
    PlotHistogramRequest,
    PlotLandcoverMapRequest,
    PlotRasterRequest,
    PlotRoughnessRoseRequest,
    PlotTimeSeriesRequest,
    PlotWindRoseRequest,
    PolygonsToLinesRequest,
    ReadFileRequest,
    ReadMfwwcRequest,
    ReprojectRequest,
    RotorEquivRequest,
    SetCrsRequest,
    ShearExtrapolateRequest,
    SnapToLayerRequest,
    SpeedDirectionRequest,
    TswcFromDataFrameRequest,
    TswcResampleRequest,
    TwoDatasetsRequest,
    UncertaintyTableRequest,
    VectorComponentsRequest,
    VinterpRequest,
    VinterpWindSpeedRequest,
    WarpRequest,
    WdToSectorRequest,
    WeibullAKRequest,
    WeibullM1M3FgtmRequest,
    WeibullM1M3Request,
    WeibullMomentRequest,
    WeibullPdfCdfRequest,
    WeibullProbabilityRequest,
    WeibullFitRequest,
    WindClimateStatsRequest,
    WindKitResponse,
    WriteFileRequest,
    WtgCpRequest,
    WtgOperationRequest,
    WwcToBwcRequest,
)
from server.state.session import SessionState

# Import the underscore-free MCP tool functions — they work standalone too.
from server.tools.windkit import wind as _wind
from server.tools.windkit import climate as _climate
from server.tools.windkit import climate_stats as _cstats
from server.tools.windkit import ltc as _ltc
from server.tools.windkit import topography as _topo
from server.tools.windkit import windfarm as _wf
from server.tools.windkit import spatial as _sp
from server.tools.windkit import plotting as _plt
from server.tools.windkit import other as _other

router = APIRouter(prefix="/windkit", tags=["windkit"])


def _call(fn, *args, **kwargs) -> WindKitResponse:
    """Call a WindKit tool function and wrap exceptions as 400s."""
    try:
        result = fn(*args, **kwargs)
        return WindKitResponse(status="ok", result=result.get("result", result))
    except (ValueError, TypeError, KeyError) as exc:
        raise to_bad_request(exc) from exc


# ============================================================================
# Wind functions
# ============================================================================

@router.post("/wind/wind_speed", response_model=WindKitResponse)
def wind_speed(req: VectorComponentsRequest):
    return _call(_wind.windkit_wind_speed, json.dumps(req.u), json.dumps(req.v))


@router.post("/wind/wind_direction", response_model=WindKitResponse)
def wind_direction(req: VectorComponentsRequest):
    return _call(_wind.windkit_wind_direction, json.dumps(req.u), json.dumps(req.v))


@router.post("/wind/wind_speed_and_direction", response_model=WindKitResponse)
def wind_speed_and_direction(req: VectorComponentsRequest):
    return _call(_wind.windkit_wind_speed_and_direction, json.dumps(req.u), json.dumps(req.v))


@router.post("/wind/wind_vectors", response_model=WindKitResponse)
def wind_vectors(req: SpeedDirectionRequest):
    return _call(_wind.windkit_wind_vectors, json.dumps(req.ws), json.dumps(req.wd))


@router.post("/wind/wind_direction_difference", response_model=WindKitResponse)
def wind_direction_difference(req: DirectionDifferenceRequest):
    return _call(_wind.windkit_wind_direction_difference, json.dumps(req.wd_obs), json.dumps(req.wd_mod))


@router.post("/wind/wd_to_sector", response_model=WindKitResponse)
def wd_to_sector(req: WdToSectorRequest):
    return _call(_wind.windkit_wd_to_sector, json.dumps(req.wd), req.sectors, req.output_type)


@router.post("/wind/vinterp_wind_direction", response_model=WindKitResponse)
def vinterp_wind_direction(req: VinterpRequest):
    return _call(_wind.windkit_vinterp_wind_direction, json.dumps(req.data), req.height)


@router.post("/wind/vinterp_wind_speed", response_model=WindKitResponse)
def vinterp_wind_speed(req: VinterpWindSpeedRequest):
    return _call(_wind.windkit_vinterp_wind_speed, json.dumps(req.data), req.height, req.method)


@router.post("/wind/rotor_equivalent_wind_speed", response_model=WindKitResponse)
def rotor_equivalent_wind_speed(req: RotorEquivRequest):
    return _call(
        _wind.windkit_rotor_equivalent_wind_speed,
        json.dumps(req.wind_speed_data), json.dumps(req.wind_direction_data),
        req.hub_height, req.rotor_diameter,
    )


@router.post("/wind/shear_extrapolate", response_model=WindKitResponse)
def shear_extrapolate(req: ShearExtrapolateRequest):
    return _call(_wind.windkit_shear_extrapolate, json.dumps(req.wind_speed_data), req.height, req.method)


@router.post("/wind/shear_exponent", response_model=WindKitResponse)
def shear_exponent(req: DataArrayRequest):
    return _call(_wind.windkit_shear_exponent, json.dumps(req.data))


@router.post("/wind/veer_extrapolate", response_model=WindKitResponse)
def veer_extrapolate(req: VinterpRequest):
    return _call(_wind.windkit_veer_extrapolate, json.dumps(req.data), req.height)


@router.post("/wind/wind_veer", response_model=WindKitResponse)
def wind_veer(req: DataArrayRequest):
    return _call(_wind.windkit_wind_veer, json.dumps(req.data))


# ============================================================================
# Climate — TSWC
# ============================================================================

@router.post("/climate/validate_tswc", response_model=WindKitResponse)
def validate_tswc(req: DatasetRequest):
    return _call(_climate.windkit_validate_tswc, json.dumps(req.dataset))


@router.post("/climate/is_tswc", response_model=WindKitResponse)
def is_tswc(req: DatasetRequest):
    return _call(_climate.windkit_is_tswc, json.dumps(req.dataset))


@router.post("/climate/create_tswc", response_model=WindKitResponse)
def create_tswc(req: CreateTswcRequest):
    return _call(
        _climate.windkit_create_tswc,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height),
        req.crs, req.date_range_start, req.date_range_end, req.freq,
    )


@router.post("/climate/read_tswc", response_model=WindKitResponse)
def read_tswc(req: ReadFileRequest):
    return _call(_climate.windkit_read_tswc, req.filename, req.file_format)


@router.post("/climate/tswc_from_dataframe", response_model=WindKitResponse)
def tswc_from_dataframe(req: TswcFromDataFrameRequest):
    return _call(
        _climate.windkit_tswc_from_dataframe,
        json.dumps(req.dataframe), req.west_east, req.south_north, req.height, req.crs,
    )


@router.post("/climate/tswc_resample", response_model=WindKitResponse)
def tswc_resample(req: TswcResampleRequest):
    return _call(_climate.windkit_tswc_resample, json.dumps(req.dataset), req.freq)


# ============================================================================
# Climate — BWC
# ============================================================================

@router.post("/climate/validate_bwc", response_model=WindKitResponse)
def validate_bwc(req: DatasetRequest):
    return _call(_climate.windkit_validate_bwc, json.dumps(req.dataset))


@router.post("/climate/is_bwc", response_model=WindKitResponse)
def is_bwc(req: DatasetRequest):
    return _call(_climate.windkit_is_bwc, json.dumps(req.dataset))


@router.post("/climate/create_bwc", response_model=WindKitResponse)
def create_bwc(req: CreateBwcRequest):
    return _call(
        _climate.windkit_create_bwc,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height),
        req.crs, req.n_sectors, req.n_wsbins,
    )


@router.post("/climate/read_bwc", response_model=WindKitResponse)
def read_bwc(req: ReadFileRequest):
    return _call(_climate.windkit_read_bwc, req.filename, req.crs, req.file_format)


@router.post("/climate/bwc_from_tswc", response_model=WindKitResponse)
def bwc_from_tswc(req: BwcFromTswcRequest):
    return _call(
        _climate.windkit_bwc_from_tswc,
        json.dumps(req.tswc_dataset), req.wsbin_width, req.n_wsbins, req.n_sectors,
    )


@router.post("/climate/bwc_to_file", response_model=WindKitResponse)
def bwc_to_file(req: WriteFileRequest):
    return _call(_climate.windkit_bwc_to_file, json.dumps(req.dataset), req.filename, req.file_format)


@router.post("/climate/combine_bwcs", response_model=WindKitResponse)
def combine_bwcs(req: CombineBwcsRequest):
    return _call(_climate.windkit_combine_bwcs, json.dumps(req.datasets))


@router.post("/climate/weibull_fit", response_model=WindKitResponse)
def weibull_fit(req: WeibullFitRequest):
    return _call(_climate.windkit_weibull_fit, json.dumps(req.bwc_dataset), req.include_met_fields)


# ============================================================================
# Climate — WWC
# ============================================================================

@router.post("/climate/validate_wwc", response_model=WindKitResponse)
def validate_wwc(req: DatasetRequest):
    return _call(_climate.windkit_validate_wwc, json.dumps(req.dataset))


@router.post("/climate/is_wwc", response_model=WindKitResponse)
def is_wwc(req: DatasetRequest):
    return _call(_climate.windkit_is_wwc, json.dumps(req.dataset))


@router.post("/climate/create_wwc", response_model=WindKitResponse)
def create_wwc(req: CreateWwcRequest):
    return _call(
        _climate.windkit_create_wwc,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height),
        req.crs, req.n_sectors,
    )


@router.post("/climate/read_wwc", response_model=WindKitResponse)
def read_wwc(req: ReadFileRequest):
    return _call(_climate.windkit_read_wwc, req.filename, req.file_format)


@router.post("/climate/read_mfwwc", response_model=WindKitResponse)
def read_mfwwc(req: ReadMfwwcRequest):
    return _call(_climate.windkit_read_mfwwc, json.dumps(req.filenames), req.file_format)


@router.post("/climate/wwc_to_file", response_model=WindKitResponse)
def wwc_to_file(req: WriteFileRequest):
    return _call(_climate.windkit_wwc_to_file, json.dumps(req.dataset), req.filename, req.file_format)


@router.post("/climate/wwc_to_bwc", response_model=WindKitResponse)
def wwc_to_bwc(req: WwcToBwcRequest):
    return _call(_climate.windkit_wwc_to_bwc, json.dumps(req.dataset), json.dumps(req.ws_bins))


@router.post("/climate/weibull_combined", response_model=WindKitResponse)
def weibull_combined(req: DatasetRequest):
    return _call(_climate.windkit_weibull_combined, json.dumps(req.dataset))


# ============================================================================
# Climate — GWC
# ============================================================================

@router.post("/climate/validate_gwc", response_model=WindKitResponse)
def validate_gwc(req: DatasetRequest):
    return _call(_climate.windkit_validate_gwc, json.dumps(req.dataset))


@router.post("/climate/is_gwc", response_model=WindKitResponse)
def is_gwc(req: DatasetRequest):
    return _call(_climate.windkit_is_gwc, json.dumps(req.dataset))


@router.post("/climate/create_gwc", response_model=WindKitResponse)
def create_gwc(req: CreateGwcRequest):
    return _call(
        _climate.windkit_create_gwc,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height),
        req.crs, req.n_sectors,
    )


@router.post("/climate/read_gwc", response_model=WindKitResponse)
def read_gwc(req: ReadFileRequest):
    return _call(_climate.windkit_read_gwc, req.filename, req.crs, req.file_format)


@router.post("/climate/gwc_to_file", response_model=WindKitResponse)
def gwc_to_file(req: WriteFileRequest):
    return _call(_climate.windkit_gwc_to_file, json.dumps(req.dataset), req.filename, req.file_format)


# ============================================================================
# Climate — GeoWC
# ============================================================================

@router.post("/climate/validate_geowc", response_model=WindKitResponse)
def validate_geowc(req: DatasetRequest):
    return _call(_climate.windkit_validate_geowc, json.dumps(req.dataset))


@router.post("/climate/is_geowc", response_model=WindKitResponse)
def is_geowc(req: DatasetRequest):
    return _call(_climate.windkit_is_geowc, json.dumps(req.dataset))


# ============================================================================
# Climate stats
# ============================================================================

@router.post("/climate-stats/create_met_fields", response_model=WindKitResponse)
def create_met_fields(req: CreateSpatialRequest):
    return _call(
        _cstats.windkit_create_met_fields,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height), req.crs,
    )


@router.post("/climate-stats/mean_ws_moment", response_model=WindKitResponse)
def mean_ws_moment(req: MeanWsMomentRequest):
    return _call(_cstats.windkit_mean_ws_moment, json.dumps(req.wc_dataset), req.moment, req.bysector)


@router.post("/climate-stats/ws_cdf", response_model=WindKitResponse)
def ws_cdf(req: WindClimateStatsRequest):
    return _call(_cstats.windkit_ws_cdf, json.dumps(req.wc_dataset), req.bysector)


@router.post("/climate-stats/ws_freq_gt_mean", response_model=WindKitResponse)
def ws_freq_gt_mean(req: WindClimateStatsRequest):
    return _call(_cstats.windkit_ws_freq_gt_mean, json.dumps(req.wc_dataset), req.bysector)


@router.post("/climate-stats/mean_wind_speed", response_model=WindKitResponse)
def mean_wind_speed(req: WindClimateStatsRequest):
    return _call(_cstats.windkit_mean_wind_speed, json.dumps(req.wc_dataset), req.bysector)


@router.post("/climate-stats/mean_power_density", response_model=WindKitResponse)
def mean_power_density(req: MeanPowerDensityRequest):
    return _call(
        _cstats.windkit_mean_power_density,
        json.dumps(req.wc_dataset), req.bysector, req.air_density,
    )


@router.post("/climate-stats/get_cross_predictions", response_model=WindKitResponse)
def get_cross_predictions(req: CrossPredictionsRequest):
    src = json.dumps(req.wcs_src_dataset) if req.wcs_src_dataset else ""
    return _call(_cstats.windkit_get_cross_predictions, json.dumps(req.wcs_dataset), src)


# ============================================================================
# LTC
# ============================================================================

@router.post("/ltc/linreg_mcp", response_model=WindKitResponse)
def ltc_linreg_mcp(req: LtcRequest):
    return _call(
        _ltc.windkit_ltc_linreg_mcp,
        json.dumps(req.measured_dataset), json.dumps(req.reference_dataset),
        req.ws_cutoff, req.n_sectors,
    )


@router.post("/ltc/varrat_mcp", response_model=WindKitResponse)
def ltc_varrat_mcp(req: LtcVarRatRequest):
    return _call(
        _ltc.windkit_ltc_varrat_mcp,
        json.dumps(req.measured_dataset), json.dumps(req.reference_dataset),
        req.fit_intercept, req.ws_cutoff, req.n_sectors,
    )


# ============================================================================
# Topography — Landcover
# ============================================================================

@router.post("/topography/get_landcover_table", response_model=WindKitResponse)
def get_landcover_table(req: DatasetRequest):
    return _call(_topo.windkit_get_landcover_table, json.dumps(req.dataset))


@router.post("/topography/add_landcover_table", response_model=WindKitResponse)
def add_landcover_table(req: LandcoverTableRequest):
    return _call(_topo.windkit_add_landcover_table, json.dumps(req.geojson_data), json.dumps(req.lctable))


@router.post("/topography/roughness_to_landcover", response_model=WindKitResponse)
def roughness_to_landcover(req: DatasetRequest):
    return _call(_topo.windkit_roughness_to_landcover, json.dumps(req.dataset))


@router.post("/topography/landcover_to_roughness", response_model=WindKitResponse)
def landcover_to_roughness(req: LandcoverTableRequest):
    return _call(_topo.windkit_landcover_to_roughness, json.dumps(req.geojson_data), json.dumps(req.lctable))


@router.post("/topography/read_roughness_map", response_model=WindKitResponse)
def read_roughness_map(req: ReadFileRequest):
    return _call(_topo.windkit_read_roughness_map, req.filename, req.crs)


@router.post("/topography/read_landcover_map", response_model=WindKitResponse)
def read_landcover_map(req: ReadFileRequest):
    return _call(_topo.windkit_read_landcover_map, req.filename, req.crs)


@router.post("/topography/landcover_map_to_file", response_model=WindKitResponse)
def landcover_map_to_file(req: WriteFileRequest):
    return _call(_topo.windkit_landcover_map_to_file, json.dumps(req.dataset), req.filename)


@router.post("/topography/roughness_map_to_file", response_model=WindKitResponse)
def roughness_map_to_file(req: WriteFileRequest):
    return _call(_topo.windkit_roughness_map_to_file, json.dumps(req.dataset), req.filename)


# ============================================================================
# Topography — Elevation
# ============================================================================

@router.post("/topography/read_elevation_map", response_model=WindKitResponse)
def read_elevation_map(req: ReadFileRequest):
    return _call(_topo.windkit_read_elevation_map, req.filename, req.crs)


@router.post("/topography/elevation_map_to_file", response_model=WindKitResponse)
def elevation_map_to_file(req: WriteFileRequest):
    return _call(_topo.windkit_elevation_map_to_file, json.dumps(req.dataset), req.filename)


# ============================================================================
# Topography — Raster/Vector maps
# ============================================================================

@router.post("/topography/create_raster_map", response_model=WindKitResponse)
def create_raster_map(req: CreateSpatialRequest):
    return _call(
        _topo.windkit_create_raster_map,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height), req.crs,
    )


@router.post("/topography/get_raster_map", response_model=WindKitResponse)
def get_raster_map(req: GetRasterMapRequest):
    return _call(_topo.windkit_get_raster_map, json.dumps(req.bbox), req.dataset, req.band, req.source)


@router.post("/topography/create_vector_map", response_model=WindKitResponse)
def create_vector_map(req: CreateVectorMapRequest):
    return _call(_topo.windkit_create_vector_map, json.dumps(req.bbox), req.map_type)


@router.post("/topography/get_vector_map", response_model=WindKitResponse)
def get_vector_map(req: GetVectorMapRequest):
    return _call(_topo.windkit_get_vector_map, json.dumps(req.bbox), req.dataset, req.source)


# ============================================================================
# Topography — Map conversion
# ============================================================================

@router.post("/topography/lines_to_polygons", response_model=WindKitResponse)
def lines_to_polygons(req: GeoJsonRequest):
    return _call(_topo.windkit_lines_to_polygons, json.dumps(req.geojson_data))


@router.post("/topography/polygons_to_lines", response_model=WindKitResponse)
def polygons_to_lines(req: PolygonsToLinesRequest):
    lct = json.dumps(req.lctable) if req.lctable else ""
    return _call(_topo.windkit_polygons_to_lines, json.dumps(req.geojson_data), lct, req.map_type)


@router.post("/topography/snap_to_layer", response_model=WindKitResponse)
def snap_to_layer(req: SnapToLayerRequest):
    return _call(_topo.windkit_snap_to_layer, json.dumps(req.geojson_data), req.tolerance)


@router.post("/topography/check_dead_ends", response_model=WindKitResponse)
def check_dead_ends(req: GeoJsonRequest):
    return _call(_topo.windkit_check_dead_ends, json.dumps(req.geojson_data))


@router.post("/topography/check_lines_cross", response_model=WindKitResponse)
def check_lines_cross(req: GeoJsonRequest):
    return _call(_topo.windkit_check_lines_cross, json.dumps(req.geojson_data))


# ============================================================================
# Wind farm — Turbines
# ============================================================================

@router.post("/windfarm/validate_windturbines", response_model=WindKitResponse)
def validate_windturbines(req: DatasetRequest):
    return _call(_wf.windkit_validate_windturbines, json.dumps(req.dataset))


@router.post("/windfarm/is_windturbines", response_model=WindKitResponse)
def is_windturbines(req: DatasetRequest):
    return _call(_wf.windkit_is_windturbines, json.dumps(req.dataset))


@router.post("/windfarm/check_wtg_keys", response_model=WindKitResponse)
def check_wtg_keys(req: TwoDatasetsRequest):
    return _call(_wf.windkit_check_wtg_keys, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


@router.post("/windfarm/create_wind_turbines_from_dataframe", response_model=WindKitResponse)
def create_wind_turbines_from_dataframe(req: DatasetRequest):
    return _call(_wf.windkit_create_wind_turbines_from_dataframe, json.dumps(req.dataset))


@router.post("/windfarm/create_wind_turbines_from_arrays", response_model=WindKitResponse)
def create_wind_turbines_from_arrays(req: CreateTurbinesFromArraysRequest):
    return _call(
        _wf.windkit_create_wind_turbines_from_arrays,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height),
        req.crs, json.dumps(req.wtg_keys) if req.wtg_keys else "",
    )


@router.post("/windfarm/wind_turbines_to_geodataframe", response_model=WindKitResponse)
def wind_turbines_to_geodataframe(req: DatasetRequest):
    return _call(_wf.windkit_wind_turbines_to_geodataframe, json.dumps(req.dataset))


# ============================================================================
# Wind farm — WTG
# ============================================================================

@router.post("/windfarm/validate_wtg", response_model=WindKitResponse)
def validate_wtg(req: DatasetRequest):
    return _call(_wf.windkit_validate_wtg, json.dumps(req.dataset))


@router.post("/windfarm/is_wtg", response_model=WindKitResponse)
def is_wtg(req: DatasetRequest):
    return _call(_wf.windkit_is_wtg, json.dumps(req.dataset))


@router.post("/windfarm/estimate_regulation_type", response_model=WindKitResponse)
def estimate_regulation_type(req: DatasetRequest):
    return _call(_wf.windkit_estimate_regulation_type, json.dumps(req.dataset))


@router.post("/windfarm/read_wtg", response_model=WindKitResponse)
def read_wtg(req: ReadFileRequest):
    return _call(_wf.windkit_read_wtg, req.filename, req.file_format)


@router.post("/windfarm/wtg_power", response_model=WindKitResponse)
def wtg_power(req: WtgOperationRequest):
    return _call(
        _wf.windkit_wtg_power,
        json.dumps(req.wtg_dataset), json.dumps(req.ws) if req.ws else "", req.interp_method,
    )


@router.post("/windfarm/wtg_cp", response_model=WindKitResponse)
def wtg_cp(req: WtgCpRequest):
    return _call(
        _wf.windkit_wtg_cp,
        json.dumps(req.wtg_dataset), json.dumps(req.ws) if req.ws else "", req.air_density,
    )


@router.post("/windfarm/wtg_ct", response_model=WindKitResponse)
def wtg_ct(req: WtgOperationRequest):
    return _call(
        _wf.windkit_wtg_ct,
        json.dumps(req.wtg_dataset), json.dumps(req.ws) if req.ws else "", req.interp_method,
    )


# ============================================================================
# Wind farm — Losses & Uncertainty
# ============================================================================

@router.post("/windfarm/validate_uncertainty_table", response_model=WindKitResponse)
def validate_uncertainty_table(req: UncertaintyTableRequest):
    return _call(_wf.windkit_validate_uncertainty_table, json.dumps(req.table))


@router.post("/windfarm/get_uncertainty_table", response_model=WindKitResponse)
def get_uncertainty_table(req: GetUncertaintyTableRequest):
    return _call(_wf.windkit_get_uncertainty_table, req.table_name)


@router.post("/windfarm/total_uncertainty", response_model=WindKitResponse)
def total_uncertainty(req: UncertaintyTableRequest):
    return _call(_wf.windkit_total_uncertainty, json.dumps(req.table))


@router.post("/windfarm/uncertainty_table_summary", response_model=WindKitResponse)
def uncertainty_table_summary(req: UncertaintyTableRequest):
    return _call(_wf.windkit_uncertainty_table_summary, json.dumps(req.table))


@router.post("/windfarm/total_uncertainty_factor", response_model=WindKitResponse)
def total_uncertainty_factor(req: UncertaintyTableRequest):
    return _call(_wf.windkit_total_uncertainty_factor, json.dumps(req.table))


# ============================================================================
# Spatial — CRS
# ============================================================================

@router.post("/spatial/get_crs", response_model=WindKitResponse)
def get_crs(req: DatasetRequest):
    return _call(_sp.windkit_get_crs, json.dumps(req.dataset))


@router.post("/spatial/set_crs", response_model=WindKitResponse)
def set_crs(req: SetCrsRequest):
    return _call(_sp.windkit_set_crs, json.dumps(req.dataset), req.crs)


@router.post("/spatial/crs_are_equal", response_model=WindKitResponse)
def crs_are_equal(req: TwoDatasetsRequest):
    return _call(_sp.windkit_crs_are_equal, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


# ============================================================================
# Spatial — Create
# ============================================================================

@router.post("/spatial/create_dataset", response_model=WindKitResponse)
def create_dataset(req: CreateSpatialRequest):
    return _call(
        _sp.windkit_create_dataset,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height), req.crs,
    )


@router.post("/spatial/create_raster", response_model=WindKitResponse)
def create_raster(req: CreateSpatialRequest):
    return _call(_sp.windkit_create_raster, json.dumps(req.west_east), json.dumps(req.south_north), req.crs)


@router.post("/spatial/create_point", response_model=WindKitResponse)
def create_point(req: CreateSpatialRequest):
    return _call(
        _sp.windkit_create_point,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height), req.crs,
    )


@router.post("/spatial/create_stacked_point", response_model=WindKitResponse)
def create_stacked_point(req: CreateSpatialRequest):
    return _call(
        _sp.windkit_create_stacked_point,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height), req.crs,
    )


@router.post("/spatial/create_cuboid", response_model=WindKitResponse)
def create_cuboid(req: CreateSpatialRequest):
    return _call(
        _sp.windkit_create_cuboid,
        json.dumps(req.west_east), json.dumps(req.south_north), json.dumps(req.height), req.crs,
    )


# ============================================================================
# Spatial — Validate
# ============================================================================

@router.post("/spatial/is_point", response_model=WindKitResponse)
def is_point(req: DatasetRequest):
    return _call(_sp.windkit_is_point, json.dumps(req.dataset))


@router.post("/spatial/is_stacked_point", response_model=WindKitResponse)
def is_stacked_point(req: DatasetRequest):
    return _call(_sp.windkit_is_stacked_point, json.dumps(req.dataset))


@router.post("/spatial/is_cuboid", response_model=WindKitResponse)
def is_cuboid(req: DatasetRequest):
    return _call(_sp.windkit_is_cuboid, json.dumps(req.dataset))


@router.post("/spatial/is_raster", response_model=WindKitResponse)
def is_raster(req: DatasetRequest):
    return _call(_sp.windkit_is_raster, json.dumps(req.dataset))


# ============================================================================
# Spatial — Convert
# ============================================================================

@router.post("/spatial/to_point", response_model=WindKitResponse)
def to_point(req: DatasetRequest):
    return _call(_sp.windkit_to_point, json.dumps(req.dataset))


@router.post("/spatial/to_cuboid", response_model=WindKitResponse)
def to_cuboid(req: DatasetRequest):
    return _call(_sp.windkit_to_cuboid, json.dumps(req.dataset))


@router.post("/spatial/to_stacked_point", response_model=WindKitResponse)
def to_stacked_point(req: DatasetRequest):
    return _call(_sp.windkit_to_stacked_point, json.dumps(req.dataset))


@router.post("/spatial/to_raster", response_model=WindKitResponse)
def to_raster(req: DatasetRequest):
    return _call(_sp.windkit_to_raster, json.dumps(req.dataset))


@router.post("/spatial/gdf_to_ds", response_model=WindKitResponse)
def gdf_to_ds(req: GdfToDsRequest):
    return _call(_sp.windkit_gdf_to_ds, json.dumps(req.geojson_data), req.height, req.struct)


@router.post("/spatial/ds_to_gdf", response_model=WindKitResponse)
def ds_to_gdf(req: DsToGdfRequest):
    return _call(_sp.windkit_ds_to_gdf, json.dumps(req.dataset), req.include_height)


# ============================================================================
# Spatial — Interpolation
# ============================================================================

@router.post("/spatial/interp_structured_like", response_model=WindKitResponse)
def interp_structured_like(req: TwoDatasetsRequest):
    return _call(_sp.windkit_interp_structured_like, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


@router.post("/spatial/interp_unstructured", response_model=WindKitResponse)
def interp_unstructured(req: DatasetRequest):
    return _call(_sp.windkit_interp_unstructured, json.dumps(req.dataset))


@router.post("/spatial/interp_unstructured_like", response_model=WindKitResponse)
def interp_unstructured_like(req: TwoDatasetsRequest):
    return _call(_sp.windkit_interp_unstructured_like, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


# ============================================================================
# Spatial — Comparison
# ============================================================================

@router.post("/spatial/are_spatially_equal", response_model=WindKitResponse)
def are_spatially_equal(req: TwoDatasetsRequest):
    return _call(_sp.windkit_are_spatially_equal, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


@router.post("/spatial/equal_spatial_shape", response_model=WindKitResponse)
def equal_spatial_shape(req: TwoDatasetsRequest):
    return _call(_sp.windkit_equal_spatial_shape, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


@router.post("/spatial/covers", response_model=WindKitResponse)
def covers(req: TwoDatasetsRequest):
    return _call(_sp.windkit_covers, json.dumps(req.dataset_a), json.dumps(req.dataset_b))


# ============================================================================
# Spatial — Operations
# ============================================================================

@router.post("/spatial/clip", response_model=WindKitResponse)
def clip(req: ClipRequest):
    return _call(_sp.windkit_clip, json.dumps(req.dataset), json.dumps(req.mask_geojson))


@router.post("/spatial/clip_with_margin", response_model=WindKitResponse)
def clip_with_margin(req: ClipWithMarginRequest):
    return _call(
        _sp.windkit_clip_with_margin,
        json.dumps(req.dataset), json.dumps(req.clipper_dataset), req.margin,
    )


@router.post("/spatial/mask", response_model=WindKitResponse)
def mask(req: ClipRequest):
    return _call(_sp.windkit_mask, json.dumps(req.dataset), json.dumps(req.mask_geojson))


@router.post("/spatial/nearest_points", response_model=WindKitResponse)
def nearest_points(req: NearestPointsRequest):
    return _call(_sp.windkit_nearest_points, json.dumps(req.ref_dataset), json.dumps(req.target_dataset))


@router.post("/spatial/reproject", response_model=WindKitResponse)
def reproject(req: ReprojectRequest):
    return _call(_sp.windkit_reproject, json.dumps(req.dataset), req.to_crs)


@router.post("/spatial/warp", response_model=WindKitResponse)
def warp(req: WarpRequest):
    return _call(_sp.windkit_warp, json.dumps(req.dataset), req.to_crs, req.resolution)


@router.post("/spatial/count_spatial_points", response_model=WindKitResponse)
def count_spatial_points(req: DatasetRequest):
    return _call(_sp.windkit_count_spatial_points, json.dumps(req.dataset))


# ============================================================================
# Plotting
# ============================================================================

@router.post("/plotting/histogram", response_model=WindKitResponse)
def plot_histogram(req: PlotHistogramRequest):
    return _call(_plt.windkit_plot_histogram, json.dumps(req.bwc_dataset), req.style, req.weibull)


@router.post("/plotting/histogram_lines", response_model=WindKitResponse)
def plot_histogram_lines(req: DatasetRequest):
    return _call(_plt.windkit_plot_histogram_lines, json.dumps(req.dataset))


@router.post("/plotting/operational_curves", response_model=WindKitResponse)
def plot_operational_curves(req: DatasetRequest):
    return _call(_plt.windkit_plot_operational_curves, json.dumps(req.dataset))


@router.post("/plotting/raster_plot", response_model=WindKitResponse)
def plot_raster(req: PlotRasterRequest):
    return _call(_plt.windkit_plot_raster, json.dumps(req.data_array), req.contour)


@router.post("/plotting/roughness_rose", response_model=WindKitResponse)
def plot_roughness_rose(req: PlotRoughnessRoseRequest):
    return _call(_plt.windkit_plot_roughness_rose, json.dumps(req.dataset), req.style)


@router.post("/plotting/time_series", response_model=WindKitResponse)
def plot_time_series(req: PlotTimeSeriesRequest):
    return _call(_plt.windkit_plot_time_series, json.dumps(req.tswc_dataset), req.range_slider)


@router.post("/plotting/vertical_profile", response_model=WindKitResponse)
def plot_vertical_profile(req: DataArrayRequest | None = None):
    data = json.dumps(req.data) if req and req.data else ""
    return _call(_plt.windkit_plot_vertical_profile, data)


@router.post("/plotting/wind_rose", response_model=WindKitResponse)
def plot_wind_rose(req: PlotWindRoseRequest):
    return _call(
        _plt.windkit_plot_wind_rose,
        json.dumps(req.bwc_dataset),
        json.dumps(req.wind_speed_bins) if req.wind_speed_bins else "",
        req.style,
    )


@router.post("/plotting/landcover_map", response_model=WindKitResponse)
def plot_landcover_map(req: PlotLandcoverMapRequest):
    return _call(_plt.windkit_plot_landcover_map, json.dumps(req.geojson_data), req.column)


# ============================================================================
# Other — Weibull
# ============================================================================

@router.post("/weibull/fit_wasp_m1_m3_fgtm", response_model=WindKitResponse)
def fit_weibull_wasp_m1_m3_fgtm(req: WeibullM1M3FgtmRequest):
    return _call(_other.windkit_fit_weibull_wasp_m1_m3_fgtm, req.m1, req.m3, req.fgtm)


@router.post("/weibull/fit_wasp_m1_m3", response_model=WindKitResponse)
def fit_weibull_wasp_m1_m3(req: WeibullM1M3Request):
    return _call(_other.windkit_fit_weibull_wasp_m1_m3, req.m1, req.m3)


@router.post("/weibull/fit_k_sumlogm", response_model=WindKitResponse)
def fit_weibull_k_sumlogm(req: DataArrayRequest):
    return _call(_other.windkit_fit_weibull_k_sumlogm, req.data)


@router.post("/weibull/moment", response_model=WindKitResponse)
def weibull_moment(req: WeibullMomentRequest):
    return _call(_other.windkit_weibull_moment, req.A, req.k, req.n)


@router.post("/weibull/pdf", response_model=WindKitResponse)
def weibull_pdf(req: WeibullPdfCdfRequest):
    return _call(_other.windkit_weibull_pdf, req.A, req.k, json.dumps(req.x))


@router.post("/weibull/cdf", response_model=WindKitResponse)
def weibull_cdf(req: WeibullPdfCdfRequest):
    return _call(_other.windkit_weibull_cdf, req.A, req.k, json.dumps(req.x))


@router.post("/weibull/freq_gt_mean", response_model=WindKitResponse)
def weibull_freq_gt_mean(req: WeibullAKRequest):
    return _call(_other.windkit_weibull_freq_gt_mean, req.A, req.k)


@router.post("/weibull/probability", response_model=WindKitResponse)
def weibull_probability(req: WeibullProbabilityRequest):
    return _call(_other.windkit_get_weibull_probability, req.A, req.k, req.speed_range)


# ============================================================================
# Other — WAsP, Coordinates, ERA5
# ============================================================================

@router.post("/other/read_cfdres", response_model=WindKitResponse)
def read_cfdres(req: ReadFileRequest):
    return _call(_other.windkit_read_cfdres, req.filename, req.crs)


@router.post("/other/create_sector_coords", response_model=WindKitResponse)
def create_sector_coords(req: CreateSectorCoordsRequest):
    return _call(_other.windkit_create_sector_coords, req.bins, req.start)


@router.post("/other/create_wsbin_coords", response_model=WindKitResponse)
def create_wsbin_coords(req: CreateWsbinCoordsRequest):
    return _call(_other.windkit_create_wsbin_coords, req.bins, req.width, req.start)


@router.post("/other/get_era5", response_model=WindKitResponse)
def get_era5(req: GetEra5Request):
    bbox = json.dumps(req.bbox) if req.bbox else ""
    return _call(_other.windkit_get_era5, req.datetime_range, bbox, req.source)


@router.post("/other/get_tutorial_data", response_model=WindKitResponse)
def get_tutorial_data(name: str):
    return _call(_other.windkit_get_tutorial_data, name)


@router.post("/other/load_tutorial_data", response_model=WindKitResponse)
def load_tutorial_data(name: str):
    return _call(_other.windkit_load_tutorial_data, name)
