"""windkit_schemas — Pydantic request/response models for WindKit API routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue


# ---------------------------------------------------------------------------
# Generic response
# ---------------------------------------------------------------------------

class WindKitResponse(BaseModel):
    """Standard envelope for all WindKit API responses."""
    status: str = "ok"
    result: JsonValue = None


# ---------------------------------------------------------------------------
# Wind functions
# ---------------------------------------------------------------------------

class VectorComponentsRequest(BaseModel):
    """Request with u,v wind component arrays."""
    u: list[float]
    v: list[float]


class SpeedDirectionRequest(BaseModel):
    """Request with wind speed and direction arrays."""
    ws: list[float]
    wd: list[float]


class DirectionDifferenceRequest(BaseModel):
    wd_obs: list[float]
    wd_mod: list[float]


class WdToSectorRequest(BaseModel):
    wd: list[float]
    sectors: int = 12
    output_type: str = "int"


class VinterpRequest(BaseModel):
    data: dict = Field(..., description="Serialized xarray DataArray")
    height: float


class VinterpWindSpeedRequest(VinterpRequest):
    method: str = "log"


class RotorEquivRequest(BaseModel):
    wind_speed_data: dict
    wind_direction_data: dict
    hub_height: float
    rotor_diameter: float


class ShearExtrapolateRequest(BaseModel):
    wind_speed_data: dict
    height: float
    method: str = "power_law"


class DataArrayRequest(BaseModel):
    """Generic request carrying a single DataArray."""
    data: dict = Field(..., description="Serialized xarray DataArray")


class DatasetRequest(BaseModel):
    """Generic request carrying a single Dataset."""
    dataset: dict = Field(..., description="Serialized xarray Dataset")


# ---------------------------------------------------------------------------
# Climate
# ---------------------------------------------------------------------------

class CreateSpatialRequest(BaseModel):
    west_east: list[float]
    south_north: list[float]
    height: list[float]
    crs: str = "EPSG:4326"


class CreateTswcRequest(CreateSpatialRequest):
    date_range_start: str = ""
    date_range_end: str = ""
    freq: str = "h"


class ReadFileRequest(BaseModel):
    filename: str
    crs: str = ""
    file_format: str = ""


class TswcFromDataFrameRequest(BaseModel):
    dataframe: dict = Field(..., description="Split-orient DataFrame dict")
    west_east: float
    south_north: float
    height: float
    crs: str = "EPSG:4326"


class TswcResampleRequest(BaseModel):
    dataset: dict
    freq: str


class CreateBwcRequest(CreateSpatialRequest):
    n_sectors: int = 12
    n_wsbins: int = 30


class BwcFromTswcRequest(BaseModel):
    tswc_dataset: dict
    wsbin_width: float = 1.0
    n_wsbins: int = 40
    n_sectors: int = 12


class WriteFileRequest(BaseModel):
    dataset: dict
    filename: str
    file_format: str = ""


class CombineBwcsRequest(BaseModel):
    datasets: list[dict]


class WeibullFitRequest(BaseModel):
    bwc_dataset: dict
    include_met_fields: bool = False


class CreateWwcRequest(CreateSpatialRequest):
    n_sectors: int = 12


class ReadMfwwcRequest(BaseModel):
    filenames: list[str]
    file_format: str = ""


class WwcToBwcRequest(BaseModel):
    dataset: dict
    ws_bins: list[float]


class CreateGwcRequest(CreateSpatialRequest):
    n_sectors: int = 12


# ---------------------------------------------------------------------------
# Climate stats
# ---------------------------------------------------------------------------

class MeanWsMomentRequest(BaseModel):
    wc_dataset: dict
    moment: int = 1
    bysector: bool = False


class WindClimateStatsRequest(BaseModel):
    wc_dataset: dict
    bysector: bool = False


class MeanPowerDensityRequest(WindClimateStatsRequest):
    air_density: float = 1.225


class CrossPredictionsRequest(BaseModel):
    wcs_dataset: dict
    wcs_src_dataset: dict | None = None


# ---------------------------------------------------------------------------
# LTC
# ---------------------------------------------------------------------------

class LtcRequest(BaseModel):
    measured_dataset: dict
    reference_dataset: dict
    ws_cutoff: float = 0.0
    n_sectors: int = 12


class LtcVarRatRequest(LtcRequest):
    fit_intercept: bool = True


# ---------------------------------------------------------------------------
# Topography
# ---------------------------------------------------------------------------

class GeoJsonRequest(BaseModel):
    geojson_data: dict


class LandcoverTableRequest(BaseModel):
    geojson_data: dict
    lctable: dict


class BboxRequest(BaseModel):
    bbox: list[float] = Field(..., description="[west, south, east, north, crs_string(opt)]")


class GetRasterMapRequest(BboxRequest):
    dataset: str = "copernicus_dem_30"
    band: str = ""
    source: str = ""


class CreateVectorMapRequest(BboxRequest):
    map_type: str = "elevation"


class GetVectorMapRequest(BboxRequest):
    dataset: str = ""
    source: str = ""


class PolygonsToLinesRequest(BaseModel):
    geojson_data: dict
    lctable: dict | None = None
    map_type: str = ""


class SnapToLayerRequest(BaseModel):
    geojson_data: dict
    tolerance: float = 1.0


# ---------------------------------------------------------------------------
# Wind farm
# ---------------------------------------------------------------------------

class CreateTurbinesFromArraysRequest(CreateSpatialRequest):
    wtg_keys: list[str] = Field(default_factory=list)


class WtgOperationRequest(BaseModel):
    wtg_dataset: dict
    ws: list[float] = Field(default_factory=list)
    interp_method: str = "linear"


class WtgCpRequest(BaseModel):
    wtg_dataset: dict
    ws: list[float] = Field(default_factory=list)
    air_density: float = 1.225


class UncertaintyTableRequest(BaseModel):
    table: dict = Field(..., description="Split-orient DataFrame dict")


class GetUncertaintyTableRequest(BaseModel):
    table_name: str = ""


# ---------------------------------------------------------------------------
# Spatial
# ---------------------------------------------------------------------------

class SetCrsRequest(BaseModel):
    dataset: dict
    crs: str


class TwoDatasetsRequest(BaseModel):
    dataset_a: dict
    dataset_b: dict


class GdfToDsRequest(BaseModel):
    geojson_data: dict
    height: float = 0.0
    struct: str = "point"


class DsToGdfRequest(BaseModel):
    dataset: dict
    include_height: bool = False


class ClipRequest(BaseModel):
    dataset: dict
    mask_geojson: dict


class ClipWithMarginRequest(BaseModel):
    dataset: dict
    clipper_dataset: dict
    margin: float = 0.0


class ReprojectRequest(BaseModel):
    dataset: dict
    to_crs: str


class WarpRequest(ReprojectRequest):
    resolution: float = 0.0


class NearestPointsRequest(BaseModel):
    ref_dataset: dict
    target_dataset: dict


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

class PlotHistogramRequest(BaseModel):
    bwc_dataset: dict
    style: str = "bar"
    weibull: bool = False


class PlotWindRoseRequest(BaseModel):
    bwc_dataset: dict
    wind_speed_bins: list[float] = Field(default_factory=list)
    style: str = "bar"


class PlotTimeSeriesRequest(BaseModel):
    tswc_dataset: dict
    range_slider: bool = False


class PlotRasterRequest(BaseModel):
    data_array: dict
    contour: bool = False


class PlotRoughnessRoseRequest(BaseModel):
    dataset: dict
    style: str = "bar"


class PlotLandcoverMapRequest(BaseModel):
    geojson_data: dict
    column: str = ""


# ---------------------------------------------------------------------------
# Weibull
# ---------------------------------------------------------------------------

class WeibullM1M3FgtmRequest(BaseModel):
    m1: float
    m3: float
    fgtm: float


class WeibullM1M3Request(BaseModel):
    m1: float
    m3: float


class WeibullMomentRequest(BaseModel):
    A: float
    k: float
    n: int = 1


class WeibullPdfCdfRequest(BaseModel):
    A: float
    k: float
    x: list[float]


class WeibullAKRequest(BaseModel):
    A: float
    k: float


class WeibullProbabilityRequest(BaseModel):
    A: float
    k: float
    speed_range: str


# ---------------------------------------------------------------------------
# ERA5
# ---------------------------------------------------------------------------

class GetEra5Request(BaseModel):
    datetime_range: str
    bbox: list[float] = Field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------

class CreateSectorCoordsRequest(BaseModel):
    bins: int = 12
    start: float = 0.0


class CreateWsbinCoordsRequest(BaseModel):
    bins: int = 30
    width: float = 1.0
    start: float = 0.0
