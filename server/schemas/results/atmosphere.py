"""Results of the atmospheric conditions operation (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class SeriesSummary(Result):
    record_count: int
    mean: Number
    min: Number
    max: Number
    std: Number
    monthly_means: list[Number]
    diurnal_means: list[Number]


class AirDensitySummary(SeriesSummary):
    density_correction_factor: Number
    density_correction_is_applied_to: str
    humidity_basis: str
    height_basis: str
    #: Present when no humidity sensor was available and the air was treated as dry.
    warning: str | None = None


class ComputeAtmosphericConditionsResult(Result):
    temperature_sensor: str
    pressure_sensor: str
    humidity_sensor: str | None
    temperature: SeriesSummary
    pressure: SeriesSummary
    air_density: AirDensitySummary
    humidity: SeriesSummary | None
