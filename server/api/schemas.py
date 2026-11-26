"""schemas — Thin FastAPI request and response models for the web layer.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

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


class CalculateUncertaintyRequest(BaseModel):
    """Request uncertainty evaluation for one annual energy estimate."""

    measurement_uncertainty_pct: float = Field(..., ge=0)
    measurement_height_m: float = Field(..., gt=0)
    hub_height_m: float = Field(..., gt=0)
    shear_method: Literal[
        "calculate_shear", "simple_power_law", "log_law", "analyst_supplied", "power_law"
    ]
    mcp_r_squared: float = Field(..., ge=0, le=1)
    concurrent_hours: float = Field(..., gt=0)
    algorithm: str = "speedsort"
    iav_pct: float = Field(6.0, ge=0)
    shear_std: float = Field(0.0, ge=0)
    is_interpolation: bool = False
    # F-32: u_future = iav / sqrt(life); 15 years gives 1.55% where 20 gives 1.34%.
    project_life_years: float = Field(20.0, gt=0)
    # F-31: the 3/sqrt(months) sampling term stops improving at the cap.
    concurrent_months_cap: float = Field(12.0, ge=1)
    # F-33: correlation between the three components derived from the same measured series.
    component_correlation: float = Field(0.0, ge=-1.0, le=1.0)


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
    weibull_k: float | None
    weibull_A: float | None
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


