"""schemas — Thin FastAPI request and response models for the web layer.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateSessionResponse(BaseModel):
    """Return the identifier and workspace metadata for a new browser session."""

    status: str = "ok"
    session_id: str
    workspace_dir: str
    created_at: datetime | None


class SessionSummaryResponse(BaseModel):
    """Summarize the current state of a workflow session for the UI shell."""

    session_id: str
    workspace_dir: str | None
    created_at: datetime | None
    updated_at: datetime | None
    project_name: str | None
    measurement_type: str | None
    hub_height_m: float | None
    timeseries_loaded: bool
    datamodel_loaded: bool
    era5_nodes_loaded: bool
    era5_interpolated_loaded: bool
    ltc_algorithms: list[str]


class UpdateRunConfigRequest(BaseModel):
    """Submit a partial run configuration payload for a session."""

    runconfig: dict[str, str | int | float | bool | None | list[str] | list[float] | dict[str, str]]


class ApplyCleaningRuleRequest(BaseModel):
    """Describe a cleaning rule request for the workflow API."""

    rule_name: str
    sensor_name: str = ""
    threshold: float | None = None
    replacement: float | None = None


class CalculateShearRequest(BaseModel):
    """Request shear or roughness calculations using one or more speed sensors."""

    height_sensors: str = Field(..., min_length=1)


class BuildTableRequest(BaseModel):
    """Request a 12x24 aggregation table with a selected aggregation statistic."""

    aggregation: str = "mean"


class ExtrapolateHubRequest(BaseModel):
    """Request hub-height extrapolation from loaded shear or roughness inputs."""

    hub_height_m: float = Field(..., gt=0)
    shear_model: str = "power_law"


class FindEra5NodesRequest(BaseModel):
    """Request ERA5 node lookup for a site coordinate."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ExtractEra5Request(BaseModel):
    """Request ERA5 extraction over a date range for one node."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    start_date: str = "2000-01-01"
    end_date: str = "2025-12-31"


class RunLtcRequest(BaseModel):
    """Request a long-term correction run using the selected measured and reference columns."""

    short_col: str
    long_col: str
    short_dir_col: str = ""
    long_dir_col: str = ""


class CalculateUncertaintyRequest(BaseModel):
    """Request uncertainty evaluation for one annual energy estimate."""

    aep_mwh: float = Field(..., gt=0)
    measurement_unc_pct: float = Field(3.0, ge=0)
    model_unc_pct: float = Field(4.0, ge=0)
    interannual_unc_pct: float = Field(3.0, ge=0)
    long_term_unc_pct: float = Field(2.0, ge=0)


class PlotRequest(BaseModel):
    """Request a named plot with simple string-based arguments from the workflow UI."""

    sensor_name: str = ""
    sensor_names: str = ""
    direction_sensor: str = ""
    sensor_a: str = ""
    sensor_b: str = ""
    table_type: str = "shear"
