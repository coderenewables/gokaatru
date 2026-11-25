"""Results of the BrightHub operations (P1-19).

What BrightHub itself returns (the IEA Task 43 data model, its reanalysis node records) is
passed through as BrightHub sends it, so it is typed as an open object here.
"""
from __future__ import annotations

from typing import Any

from server.schemas.results._base import Number, Result
from server.schemas.results.era5 import InterpolateEra5ToSiteResult


class AuthenticationResult(Result):
    status: str
    authenticated: bool


class BrighthubLoginResult(AuthenticationResult):
    pass


class BrighthubLogoutResult(AuthenticationResult):
    pass


class BrighthubStatusResult(Result):
    authenticated: bool
    has_token: bool


class BrighthubLocation(Result):
    uuid: str
    name: str
    latitude_ddeg: Number
    longitude_ddeg: Number
    measurement_station_type_id: str | None


class BrighthubListLocationsResult(Result):
    locations: list[BrighthubLocation]
    count: int


class BrighthubGetDataModelResult(Result):
    uuid: str
    #: The IEA Task 43 data model, as BrightHub serves it.
    data_model: dict[str, Any]


class UpstreamProcessing(Result):
    apply_cleaning_log: bool
    apply_cleaning_rules: bool
    apply_calibration: bool
    apply_wind_vane_deadband_offset: bool
    apply_device_orientation_offset: bool


class BrighthubImportLocationResult(Result):
    status: str
    uuid: str
    timeseries_rows: int
    timeseries_columns: list[str]
    timeseries_start: str | None
    timeseries_end: str | None
    datamodel_heights: list[Number]
    project_name: str | None
    measurement_type: str | None
    #: The processing BrightHub applied before import, which GoKaatru cannot reverse.
    upstream_processing: UpstreamProcessing
    upstream_processing_note: str


class BrighthubFindReanalysisNodesResult(Result):
    #: BrightHub's node records, as it sends them.
    era5_nodes: list[dict[str, Any]]
    merra2_nodes: list[dict[str, Any]]
    era5_count: int
    merra2_count: int


class DownloadedNode(Result):
    latitude: Number
    longitude: Number
    #: Null when the node returned no data.
    rows: int | None


class BrighthubDownloadReanalysisResult(Result):
    dataset: str
    source: str
    items: list[DownloadedNode]
    count: int


class CachedInterpolation(Result):
    """A source whose site series was already interpolated for this site and was reused."""

    status: str
    rows: int
    method: str
    variables: list[str]


class BrighthubPrepareReanalysisResult(Result):
    status: str
    source: str
    cached: bool
    era5_nodes: int
    merra2_nodes: int
    #: By reference source.
    interpolation: dict[str, InterpolateEra5ToSiteResult | CachedInterpolation]
