"""common — Shared Pydantic schemas for Phase 1 tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    """Coordinate schema constrained to valid geodetic bounds per WGS84 latitude and longitude limits."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    elevation_m: float = Field(default=0.0, ge=-500, le=9000)


class SensorInfo(BaseModel):
    """Sensor metadata schema for Phase 1 coverage reporting in the GoKaatru tool contract."""

    name: str
    height_m: float = Field(..., gt=0)
    sensor_type: Literal["wind_speed", "wind_direction", "temperature", "pressure"]
    data_coverage_pct: float = Field(..., ge=0, le=100)
    record_count: int = Field(..., ge=0)


class PeriodOfRecord(BaseModel):
    """Period-of-record schema used for IEC-style timeseries inventory summaries."""

    start: datetime
    end: datetime
    total_records: int
    timestep_minutes: int
    sensors: list[SensorInfo]


class PlotResult(BaseModel):
    """Plot payload schema for Plotly JSON and optional PNG fallback in Phase 1 outputs."""

    plotly_json: str
    png_base64: str | None = None
    title: str
