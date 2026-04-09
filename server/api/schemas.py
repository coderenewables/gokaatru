"""schemas — Thin FastAPI request and response models for the web layer.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, JsonValue


class CreateSessionResponse(BaseModel):
    """Return the identifier and workspace metadata for a new browser session."""

    status: str = "ok"
    session_id: str
    workspace_dir: str
    created_at: datetime | None
    completed_steps: list[str] = Field(default_factory=list)


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
    completed_steps: list[str]


class RunConfigUpdate(BaseModel):
    """Represent one dotted-key runconfig mutation in a batched config update request."""

    key: str = Field(..., min_length=1)
    value: JsonValue


class UpdateRunConfigRequest(BaseModel):
    """Submit a partial run configuration payload for a session."""

    updates: list[RunConfigUpdate] = Field(default_factory=list)


class ApplyCleaningRuleRequest(BaseModel):
    """Describe a cleaning rule request for the workflow API."""

    rule_type: str
    sensor: str = ""
    params: dict[str, JsonValue] = Field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""


class UndoCleaningRuleRequest(BaseModel):
    """Select one cleaning log entry to remove and replay around."""

    entry_index: int = Field(..., ge=0)


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


class EnsembleRequest(BaseModel):
    """Request multi-algorithm ensemble blending using one measured reference column."""

    measured_col: str


class ClippingRequest(BaseModel):
    """Request clipping analysis for one corrected wind-speed column and source."""

    speed_col: str
    source: str = "ensemble"


class HomogeneityAnalyzeRequest(BaseModel):
    """Request Pettitt homogeneity analysis using annual or monthly aggregation."""

    method: str = "annual"


class HomogeneityApplyRequest(BaseModel):
    """Request trimming ERA5 interpolated data to a selected homogeneous start year."""

    cutoff_year: int


class CalculateUncertaintyRequest(BaseModel):
    """Request uncertainty evaluation for one annual energy estimate."""

    measurement_uncertainty_pct: float = Field(..., ge=0)
    measurement_height_m: float = Field(..., gt=0)
    hub_height_m: float = Field(..., gt=0)
    shear_method: str
    mcp_r_squared: float = Field(..., ge=0, le=1)
    concurrent_hours: float = Field(..., gt=0)
    algorithm: str = "speedsort"
    iav_pct: float = Field(6.0, ge=0)
    shear_std: float = Field(0.0, ge=0)
    is_interpolation: bool = False


class SaveScenarioRequest(BaseModel):
    """Name one saved scenario snapshot captured from the current analysis state."""

    name: str = Field(..., min_length=1, max_length=100)


class ImportRunconfigRequest(BaseModel):
    """Import a complete runconfig JSON payload into the current session."""

    runconfig: dict[str, JsonValue]


class RunScenarioRequest(BaseModel):
    """Import a runconfig, execute the LTC \u2192 ensemble \u2192 uncertainty pipeline, and save the result."""

    name: str = Field(..., min_length=1, max_length=100)
    runconfig: dict[str, JsonValue] = Field(default_factory=dict)
    ltc_algorithms: list[str] = Field(default_factory=lambda: ["speedsort"])
    uncertainty: CalculateUncertaintyRequest | None = None


class SensorStatisticsResponse(BaseModel):
    """Return detailed descriptive statistics for one loaded sensor in the data explorer UI."""

    sensor_name: str
    mean: float
    median: float
    std: float
    min_value: float
    max_value: float
    count: int
    coverage_pct: float
    weibull_k: float
    weibull_A: float
    monthly_means: list[float]
    diurnal_means: list[float]
    percentiles: dict[str, float]


class PlotRequest(BaseModel):
    """Request a named plot with simple string-based arguments from the workflow UI."""

    speed_sensor: str = ""
    sensor_name: str = ""
    sensor_names: str = ""
    direction_sensor: str = ""
    sensor_a: str = ""
    sensor_b: str = ""
    algorithm: str = ""
    table_type: str = "shear"
    total_pct: float = Field(0.0, ge=0)
    measurement_pct: float = Field(0.0, ge=0)
    vertical_pct: float = Field(0.0, ge=0)
    mcp_pct: float = Field(0.0, ge=0)
    future_pct: float = Field(0.0, ge=0)
