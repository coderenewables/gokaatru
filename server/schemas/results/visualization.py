"""Results of the chart operations: a Plotly figure as JSON (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import PlotResult, SelectablePlotResult


class PlotAnnualMeansResult(PlotResult):
    pass


class PlotDataCoverageResult(PlotResult):
    pass


class PlotDiurnalResult(SelectablePlotResult):
    pass


class PlotLtcComparisonResult(PlotResult):
    pass


class PlotMonthlyMeansResult(SelectablePlotResult):
    pass


class PlotScatterResult(SelectablePlotResult):
    pass


class PlotShearTableResult(PlotResult):
    pass


class PlotTimeseriesResult(SelectablePlotResult):
    pass


class PlotUncertaintyBreakdownResult(PlotResult):
    pass


class PlotWeibullResult(SelectablePlotResult):
    pass


class PlotWindroseResult(SelectablePlotResult):
    pass
