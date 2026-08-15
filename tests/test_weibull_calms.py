"""Regression tests for D24+D31 — Weibull calm-handling and plot/statistics consistency.

D24: ``_compute_weibull_params`` must report ``mean_speed`` over the full series
(including calms) and expose ``calm_fraction``, ``record_count_total``, and
``fit_excludes_calms`` so the exclusion is visible.

D31: ``_plot_weibull`` must route through ``_compute_weibull_params`` so the
plot legend always agrees with the tabulated values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.statistics import _compute_weibull_params


def _weibull_series_with_calms(
    calm_fraction: float = 0.03,
    n: int = 100_000,
    k: float = 2.0,
    a: float = 8.0,
    seed: int = 42,
) -> pd.Series:
    """Create a wind-speed series with a known calm fraction.

    Uses a simple rejection-free approach: sample from Weibull(k, A) and
    replace the first ``calm_fraction * n`` sorted values with 0.
    """
    rng = np.random.RandomState(seed)
    values = rng.weibull(k, n) * a
    n_calms = int(round(calm_fraction * n))
    # Replace the lowest n_calms values with 0 (they are naturally close to 0)
    indices = np.argpartition(values, n_calms)[:n_calms]
    values[indices] = 0.0
    return pd.Series(values, name="Spd_100m")


def _load_series_into_state(state: SessionState, series: pd.Series) -> None:
    """Load a series into a session state's timeseries_df."""
    index = pd.date_range("2023-01-01", periods=len(series), freq="10min")
    state.timeseries_df = series.to_frame()
    state.timeseries_df.index = index


class TestWeibullCalmHandling:
    """D24: mean_speed, calm_fraction, record_count_total must reflect full series."""

    def test_mean_speed_includes_calms(self) -> None:
        """mean_speed must equal the full-series arithmetic mean, not the positive-only mean."""
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.03)
        _load_series_into_state(state, series)
        result = _compute_weibull_params(state, "Spd_100m")
        full_mean = float(series.mean())
        positive_mean = float(series[series > 0].mean())
        assert result["mean_speed"] == pytest.approx(full_mean, rel=1e-3), (
            f"mean_speed ({result['mean_speed']}) should match full-series mean ({full_mean}), "
            f"not positive-only mean ({positive_mean})"
        )
        # The two means should differ by ~3% at 3% calm fraction
        assert abs(result["mean_speed"] - positive_mean) > 0.01, (
            "Positive-only mean should differ from full-series mean when calms are present"
        )

    def test_calm_fraction_is_reported(self) -> None:
        """calm_fraction must be present and accurate."""
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.03)
        _load_series_into_state(state, series)
        result = _compute_weibull_params(state, "Spd_100m")
        assert "calm_fraction" in result
        assert result["calm_fraction"] == pytest.approx(0.03, abs=0.01)

    def test_record_count_total_is_full_length(self) -> None:
        """record_count_total must equal len(series.dropna())."""
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.05)
        _load_series_into_state(state, series)
        result = _compute_weibull_params(state, "Spd_100m")
        assert result["record_count_total"] == len(series)

    def test_record_count_excludes_calms(self) -> None:
        """record_count must equal the number of positive values used in the fit."""
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.05)
        _load_series_into_state(state, series)
        result = _compute_weibull_params(state, "Spd_100m")
        assert result["record_count"] == int((series > 0).sum())

    def test_fit_excludes_calms_flag(self) -> None:
        """fit_excludes_calms must report the basis each method actually used.

        The default WAsP m1/m3 fit takes its moments over the full series
        including calms (D25), matching the reported mean_speed (D24).  MLE
        must drop calms because weibull_min with floc=0 cannot accept zeros.
        """
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.03)
        _load_series_into_state(state, series)
        assert _compute_weibull_params(state, "Spd_100m")["fit_excludes_calms"] is False
        assert _compute_weibull_params(state, "Spd_100m", method="mle")["fit_excludes_calms"] is True

    def test_wasp_moments_use_full_series(self) -> None:
        """The WAsP fit must differ from MLE — moments on positives only make it a no-op.

        Excluding calms inflates m1 and m3, which pulls the moment fit onto the
        MLE answer and silently defeats the point of the m1/m3 method (D25).
        """
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.03)
        _load_series_into_state(state, series)
        wasp = _compute_weibull_params(state, "Spd_100m")
        mle = _compute_weibull_params(state, "Spd_100m", method="mle")
        assert wasp["k"] < mle["k"] - 0.05, f"WAsP k {wasp['k']:.4f} too close to MLE k {mle['k']:.4f}"
        assert wasp["A"] < mle["A"] - 0.1, f"WAsP A {wasp['A']:.4f} too close to MLE A {mle['A']:.4f}"

    def test_zero_calm_fraction_series(self) -> None:
        """A series with no calms should have calm_fraction == 0.0."""
        state = SessionState()
        rng = np.random.RandomState(99)
        values = rng.weibull(2.0, 1000) * 8.0
        series = pd.Series(values, name="Spd_100m")
        _load_series_into_state(state, series)
        result = _compute_weibull_params(state, "Spd_100m")
        assert result["calm_fraction"] == 0.0

    def test_k_and_a_remain_valid(self) -> None:
        """k and A must still be positive and physically reasonable."""
        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.03)
        _load_series_into_state(state, series)
        result = _compute_weibull_params(state, "Spd_100m")
        assert result["k"] > 1.0
        assert result["A"] > 5.0


class TestPlotWeibullUsesStatisticsHelper:
    """D31: _plot_weibull must call _compute_weibull_params for consistent k/A/mean."""

    def test_plot_routes_through_statistics_helper(self) -> None:
        """_plot_weibull source must contain a call to _compute_weibull_params."""
        import ast
        import inspect

        from server.tools.visualization import _plot_weibull

        source = inspect.getsource(_plot_weibull)
        tree = ast.parse(source)
        calls = [
            node.func.id if isinstance(node.func, ast.Name) else None
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        assert "_compute_weibull_params" in calls, (
            "_plot_weibull must call _compute_weibull_params to ensure plot/table consistency"
        )

    def test_plot_and_table_k_agree(self) -> None:
        """The k/A/mean in the plot trace name must match _compute_weibull_params output."""
        import json
        import re

        from server.tools.visualization import _plot_weibull

        state = SessionState()
        series = _weibull_series_with_calms(calm_fraction=0.03, n=5000)
        _load_series_into_state(state, series)

        params = _compute_weibull_params(state, "Spd_100m")
        plot_result = _plot_weibull(state, "Spd_100m")
        figure = json.loads(plot_result["plotly_json"])
        trace_names = [t["name"] for t in figure.get("data", []) if "name" in t]
        weibull_trace = [n for n in trace_names if "Weibull" in n][0]

        # Extract k, A, mean from the trace name
        match = re.search(r"k=([\d.]+).*A=([\d.]+).*mean=([\d.]+)", weibull_trace)
        assert match is not None, f"Could not parse k/A/mean from trace name: {weibull_trace}"
        plot_k = float(match.group(1))
        plot_a = float(match.group(2))
        plot_mean = float(match.group(3))

        assert plot_k == pytest.approx(params["k"], rel=0.01)
        assert plot_a == pytest.approx(params["A"], rel=0.01)
        assert plot_mean == pytest.approx(params["mean_speed"], rel=0.01)
