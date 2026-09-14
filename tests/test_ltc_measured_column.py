"""The LTC must correct the hub-height series, not whichever sensor sits highest.

`_resolve_ltc_columns` re-derived the measured column from ``sensor_mapping`` as "the
highest-height speed sensor", ignoring the runconfig and ignoring the hub-height series
the extrapolation stage had just built. A hub column is never in ``sensor_mapping`` — it
is appended to ``timeseries_df`` — so the function could not return one at any site.

The consequence on a real 167 m campaign (session 378bca..., lidar at 140/160/180/200 m):
the sweep fitted every LTC on ``Spd_200m`` and reported the corrected result as the hub
answer. The measured level was 2.05% high (9.2166 vs 9.0316 m/s), and axes A1, A2 and B
could not move any published metric at all, because everything downstream of the shear
and extrapolation stages was bypassed. The Interrogate page duly attributed 100% of the
spread to the LTC axis — the only axis still able to vary.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.api.routes.analysis import DIRECTIONAL_LTC_ALGORITHMS, _resolve_ltc_columns
from server.state.session import SessionState

HEIGHTS = (140.0, 160.0, 180.0, 200.0)
HUB_M = 167.0
INDEX = pd.date_range("2021-01-01", periods=500, freq="10min", tz="UTC")


def _state(*, with_hub: bool = True, hub_height: float | None = HUB_M) -> SessionState:
    """A mast whose highest sensor is deliberately not the hub height."""
    rng = np.random.default_rng(3)
    top = 8.0 + rng.weibull(2.0, len(INDEX)) * 2.0
    frame = pd.DataFrame(
        {f"Spd_{int(h)}m": top * (h / max(HEIGHTS)) ** 0.14 for h in HEIGHTS}, index=INDEX
    )
    frame["Dir_200m"] = rng.uniform(0.0, 360.0, len(INDEX))
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.sensor_mapping = {
        float(h): {
            "speed_col": f"Spd_{int(h)}m",
            "dir_col": "Dir_200m" if h == 200.0 else None,
        }
        for h in HEIGHTS
    }
    if hub_height is not None:
        state.set_hub_height_m(hub_height)
    if with_hub:
        state.timeseries_df[f"Spd_{int(HUB_M)}m_hub"] = top * (HUB_M / max(HEIGHTS)) ** 0.14
    state.set_active_reference_source("era5")
    return state


class TestTheMeasuredColumnIsTheHubSeries:
    def test_the_hub_series_is_chosen_over_the_highest_sensor(self) -> None:
        short_col, _long, _sdir, _ldir = _resolve_ltc_columns(_state())
        assert short_col == "Spd_167m_hub"

    def test_the_highest_sensor_is_never_returned_when_a_hub_series_exists(self) -> None:
        """The exact defect: Spd_200m is 2% faster than the 167 m hub level, and correcting
        it reported a 200 m answer under a hub-height label."""
        short_col, *_ = _resolve_ltc_columns(_state())
        assert short_col != "Spd_200m"
        assert not any(short_col == f"Spd_{int(h)}m" for h in HEIGHTS)

    def test_a_missing_hub_series_is_refused_by_name(self) -> None:
        """Convention 1 — refuse rather than guess. Substituting a different measurement
        height for the hub height is undetectable in every downstream number."""
        with pytest.raises(ValueError, match="Spd_167m_hub"):
            _resolve_ltc_columns(_state(with_hub=False))

    def test_the_refusal_names_the_step_that_would_fix_it(self) -> None:
        with pytest.raises(ValueError, match="(?i)extrapolat"):
            _resolve_ltc_columns(_state(with_hub=False))

    def test_an_unset_hub_height_is_refused(self) -> None:
        with pytest.raises(ValueError, match="[Hh]ub height"):
            _resolve_ltc_columns(_state(with_hub=False, hub_height=None))

    def test_a_non_integer_hub_height_resolves_to_its_own_column(self) -> None:
        state = _state(with_hub=False, hub_height=167.5)
        state.timeseries_df["Spd_167.5m_hub"] = 9.0
        short_col, *_ = _resolve_ltc_columns(state)
        assert short_col == "Spd_167.5m_hub"


class TestTheDirectionColumnLookup:
    def test_the_measured_direction_column_is_found(self) -> None:
        """The slot is named ``dir_col``; the lookup asked for ``direction_col``, so it
        returned "" at every site that has ever run."""
        _short, _long, short_dir_col, _ldir = _resolve_ltc_columns(_state())
        assert short_dir_col == "Dir_200m"

    def test_no_direction_sensor_yields_an_empty_string_not_an_error(self) -> None:
        state = _state()
        for mapping in state.sensor_mapping.values():
            mapping["dir_col"] = None
        _short, _long, short_dir_col, _ldir = _resolve_ltc_columns(state)
        assert short_dir_col == ""


class TestDirectionalAlgorithmsAreDispatchedConsistently:
    """SpeedSort's per-sector transfer functions are what distinguish it from TLS.

    The sweep called every non-XGBoost algorithm as ``runner(state, short, long)``, so
    SpeedSort's ``long_dir_col`` defaulted to "" and it ran direction-agnostically in
    every sweep ever executed — while XGBoost kept its directional feature. Axis D was
    comparing the two on unequal terms.
    """

    def test_speedsort_and_xgboost_are_both_declared_directional(self) -> None:
        assert DIRECTIONAL_LTC_ALGORITHMS == frozenset({"speedsort", "xgboost"})

    def test_the_non_directional_algorithms_are_not_listed(self) -> None:
        for algorithm in ("linear_least_squares", "total_least_squares", "variance_ratio"):
            assert algorithm not in DIRECTIONAL_LTC_ALGORITHMS

    def test_every_dispatch_site_uses_the_shared_set(self) -> None:
        """Three call sites dispatched on the algorithm name independently; the sweep's
        was the one that drifted. A shared constant is what stops it drifting again."""
        import inspect

        from server.api.routes import analysis
        from server.core import scenario_pipeline

        for module in (analysis, scenario_pipeline):
            source = inspect.getsource(module)
            assert 'algorithm == "xgboost"' not in source, (
                f"{module.__name__} still dispatches on a hardcoded algorithm name"
            )
