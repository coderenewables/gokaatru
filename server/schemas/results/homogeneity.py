"""Results of the homogeneity operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class DatasetHomogeneity(Result):
    name: str
    recommended_start_year: int
    pettitt_p_value: Number
    trend_per_year: Number


class AnalyzeHomogeneityResult(Result):
    datasets: list[DatasetHomogeneity]


class ApplyHomogeneityCutoffResult(Result):
    status: str
    rows_before: int
    rows_after: int
    cutoff_year: int
