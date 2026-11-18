"""SpeedSort fits through rank-sorted pairs (T3).

The published method sorts the reference and measured speeds independently and fits through
the ranked pairs. Fitting time-paired data instead overshoots the slope when the correlation is
modest. These tests pin the helper's contract and the real-campaign effect on Launakalana.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from server.core.regression import total_least_squares_fit
from server.state.session import session
from server.tools.data_io import _parse_datamodel, _parse_timeseries
from server.tools.era5 import _era5_key, _interpolate_era5_to_site, _store_coordinate
from server.tools.extrapolation import _extrapolate_to_hub_height
from server.tools.ltc import _run_ltc_speedsort, _speedsort_fit
from server.tools.shear import _build_shear_table, _calculate_shear_timeseries
from tests.conftest import require_campaign_file, require_fixture_file

REPO_ROOT = Path(__file__).resolve().parents[1]
REANALYSIS_CACHE = REPO_ROOT / "data" / "e2e-real" / "brighthub_cache"
LAUNAKALANA_NODES = [(-9.977, 147.656), (-9.977, 147.938), (-9.696, 147.656), (-9.696, 147.938)]
LAUNAKALANA_SITE = (-9.925861, 147.78058)

# Measured on the 2-year campaign, hub 120 m from the 60 m and 80 m sensors, ERA5 native
# 100 m reference, after T3. Before T3 these were -0.3975 and -0.3947 (LT mean 4.4903 / 4.4064).
# The residual is the dog-leg segment below the threshold, a method decision not addressed here.
NON_DIRECTIONAL_MBE_BAND = (-0.15, 0.05)
DIRECTIONAL_MBE_BAND = (-0.25, 0.05)


class TestSpeedSortFitHelper:
    def test_sorted_fit_equals_time_paired_fit_when_perfectly_correlated(self) -> None:
        """A monotone relationship pairs identically by rank and by time, so both fits agree."""
        rng = np.random.default_rng(3)
        reference = rng.uniform(1.0, 12.0, 2000)
        measured = 1.07 * reference + 0.2

        threshold = 4.0
        sorted_slope, sorted_intercept = _speedsort_fit(reference, measured, threshold)
        mask = reference >= threshold
        paired_slope, paired_intercept = total_least_squares_fit(reference[mask], measured[mask])

        assert abs(sorted_slope - paired_slope) < 1e-9
        assert abs(sorted_intercept - paired_intercept) < 1e-9

    def test_returns_none_when_no_reference_value_reaches_threshold(self) -> None:
        reference = np.array([1.0, 2.0, 3.0, 3.5])
        measured = np.array([1.1, 2.2, 2.9, 3.4])
        assert _speedsort_fit(reference, measured, 4.0) is None

    def test_threshold_applies_to_sorted_reference(self) -> None:
        """The fit uses the highest-ranked reference values, not the time-paired ones above threshold."""
        reference = np.array([5.0, 1.0, 6.0, 2.0])
        measured = np.array([2.0, 9.0, 3.0, 1.0])
        slope, intercept = _speedsort_fit(reference, measured, 4.0)
        # Sorted reference above 4 is [5, 6] (ranks 3 and 4); the measured values at those ranks are [3, 9].
        expected_slope, expected_intercept = total_least_squares_fit(
            np.array([5.0, 6.0]), np.array([3.0, 9.0])
        )
        assert abs(slope - expected_slope) < 1e-12
        assert abs(intercept - expected_intercept) < 1e-12


def _load_launakalana_hub120() -> tuple[object, str]:
    """Launakalana with ERA5 interpolated to site and the 120 m hub extrapolated from 60 m and 80 m."""
    timeseries = require_campaign_file("WB-ESMAP_Launakalana_timeseries_data.csv")
    datamodel = require_campaign_file("WB-ESMAP_Launakalana_data_model.json")
    for la, lo in LAUNAKALANA_NODES:
        require_fixture_file(REANALYSIS_CACHE / f"ERA5_{la}_{lo}.parquet")

    session.reset()
    _parse_timeseries(session, str(timeseries))
    _parse_datamodel(session, str(datamodel))
    _store_coordinate(session, *LAUNAKALANA_SITE)
    session.era5_nodes = [{"latitude": la, "longitude": lo} for la, lo in LAUNAKALANA_NODES]
    session.era5_data = {
        _era5_key(la, lo): pd.read_parquet(REANALYSIS_CACHE / f"ERA5_{la}_{lo}.parquet")
        for la, lo in LAUNAKALANA_NODES
    }
    _interpolate_era5_to_site(session, "era5")
    fit = {"60": "Spd3_60m_25deg", "80": "Spd1_80m_25deg"}
    _calculate_shear_timeseries(session, json.dumps(fit))
    _build_shear_table(session, "mean")
    hub = _extrapolate_to_hub_height(session, 120, "power_law", reference_columns=list(fit.values()))
    assert hub["status"] == "ok"
    return session, hub["column_name"]


class TestLaunakalanaSpeedSortBias:
    def test_non_directional_concurrent_bias_is_within_band(self) -> None:
        state, hub = _load_launakalana_hub120()
        result = _run_ltc_speedsort(state, hub, "Spd_100m")
        metrics = result["metrics"]

        assert metrics["directional"] is False
        assert metrics["fit_basis"] == "rank_sorted"
        low, high = NON_DIRECTIONAL_MBE_BAND
        assert low < metrics["mbe"] < high, f"non-directional mbe {metrics['mbe']:.4f} m/s"

    def test_directional_concurrent_bias_is_within_band(self) -> None:
        state, hub = _load_launakalana_hub120()
        result = _run_ltc_speedsort(state, hub, "Spd_100m", long_dir_col="Dir_100m")
        metrics = result["metrics"]

        assert metrics["directional"] is True
        assert metrics["fit_basis"] == "rank_sorted"
        low, high = DIRECTIONAL_MBE_BAND
        assert low < metrics["mbe"] < high, f"directional mbe {metrics['mbe']:.4f} m/s"
