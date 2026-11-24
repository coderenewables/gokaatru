"""Results of the air density operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class ComputeAirDensityResult(Result):
    status: str
    pressure_pa: Number
    temperature_k: Number
    dewpoint_k: Number
    air_density_kg_m3: Number
    #: Present when the dew point exceeded the temperature and was clamped to it.
    warning: str | None = None


class DensityUnits(Result):
    temperature: str
    dewpoint: str
    pressure: str


class ComputeAirDensityTimeseriesResult(Result):
    status: str
    mean_density: Number
    min_density: Number
    max_density: Number
    record_count: int
    units_detected: DensityUnits
    height_basis: str
    height_note: str
    dewpoint_clamped_count: int
    warning: str
