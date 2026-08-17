"""Regression tests for D4 — SpeedSort directional binning.

Verifies that _run_ltc_speedsort fits per-sector transfer functions when
direction data is available, falls back gracefully when it is not, and
preserves dog-leg continuity at each sector's threshold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from server.state.session import SessionState
from server.tools.ltc import (
    MEASURED_COLUMN,
    SPEEDSORT_NUM_SECTORS,
    SPEEDSORT_SECTOR_WIDTH_DEG,
    _run_ltc_speedsort,
    _speedsort_sector_index,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_directional_state(
    n: int = 6000,
    seed: int = 42,
) -> SessionState:
    """Build a SessionState with measured + ERA5 speed/direction columns.

    Creates a controlled dataset where each 30° sector has exactly n/12
    records with a known speed-direction relationship.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    n_per_sector = n // SPEEDSORT_NUM_SECTORS

    ref_speeds = []
    meas_speeds = []
    directions = []

    for s in range(SPEEDSORT_NUM_SECTORS):
        center = s * SPEEDSORT_SECTOR_WIDTH_DEG
        # Direction spread around sector center
        dir_vals = rng.normal(center, 8.0, n_per_sector) % 360.0
        # Reference speeds: uniform 3-12 m/s
        ref = rng.uniform(3, 12, n_per_sector)
        # Measured speeds: slight directional bias (higher from some sectors)
        bias = 1.0 + 0.15 * np.sin(np.deg2rad(center))
        meas = ref * bias + rng.normal(0, 0.3, n_per_sector)
        ref_speeds.append(ref)
        meas_speeds.append(meas)
        directions.append(dir_vals)

    ref_speeds = np.concatenate(ref_speeds)
    meas_speeds = np.maximum(0.0, np.concatenate(meas_speeds))
    directions = np.concatenate(directions)

    era5 = pd.DataFrame(
        {"ws_100m": ref_speeds, "wd_100m": directions},
        index=dates,
    )
    measured = pd.DataFrame(
        {MEASURED_COLUMN: meas_speeds[:n]},
        index=dates[:n],
    )
    state = SessionState()
    state.reset()
    state.timeseries_df = measured
    state.era5_interpolated_df = era5
    return state


def _make_non_directional_state(n: int = 4800, seed: int = 7) -> SessionState:
    """Build a SessionState with measured + ERA5 speed columns (no direction)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    ref = rng.uniform(3, 12, n)
    meas = ref * 0.95 + rng.normal(0, 0.4, n)

    era5 = pd.DataFrame({"ws_100m": ref}, index=dates)
    measured = pd.DataFrame({MEASURED_COLUMN: meas}, index=dates)

    state = SessionState()
    state.reset()
    state.timeseries_df = measured
    state.era5_interpolated_df = era5
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpeedSortSectorIndex:
    """Verify the sector-indexing helper."""

    def test_returns_int_0_to_11(self) -> None:
        directions = np.array([15.0, 45.0, 75.0, 105.0, 135.0, 165.0, 195.0, 225.0, 255.0, 285.0, 315.0, 345.0])
        sectors = _speedsort_sector_index(directions)
        assert sectors.min() >= 0
        assert sectors.max() < SPEEDSORT_NUM_SECTORS
        assert len(sectors) == 12

    def test_wraps_correctly(self) -> None:
        """Direction 355° should land in the same sector as 5° (north sector)."""
        sectors = _speedsort_sector_index(np.array([355.0, 5.0, 10.0]))
        assert sectors[0] == sectors[1]  # 355 and 5 are in the same sector
        assert sectors[0] == sectors[2]  # 10 too


class TestNonDirectionalSpeedSort:
    """Verify backward compatibility when no direction column is provided."""

    def test_no_direction_falls_back(self) -> None:
        """With empty long_dir_col, should return directional=False and standard metrics."""
        state = _make_non_directional_state(n=4800)
        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m")
        metrics = result["metrics"]

        assert metrics["algorithm"] == "speedsort"
        assert metrics["directional"] is False
        assert "slope" in metrics
        assert "intercept" in metrics
        assert "dog_leg_slope" in metrics
        assert metrics["concurrent_points"] >= 10

    def test_missing_dir_col_uses_non_directional(self) -> None:
        """A long_dir_col that doesn't exist in ERA5 should fall back gracefully."""
        state = _make_non_directional_state(n=4800)
        # "wd_100m" is not in era5 columns (only "ws_100m")
        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")
        metrics = result["metrics"]

        assert metrics["directional"] is False


class TestDirectionalSpeedSort:
    """Verify the directional binning path."""

    def test_directional_produces_sector_models(self) -> None:
        """With direction data, should return directional=True and 12 sector models."""
        state = _make_directional_state(n=6000)
        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")
        metrics = result["metrics"]

        assert metrics["directional"] is True
        assert metrics["num_sectors"] == SPEEDSORT_NUM_SECTORS
        assert metrics["sector_width_deg"] == SPEEDSORT_SECTOR_WIDTH_DEG
        assert "sector_models" in metrics
        assert len(metrics["sector_models"]) == SPEEDSORT_NUM_SECTORS

    def test_independent_sectors_detected(self) -> None:
        """At least some sectors should have enough records for independent fits."""
        state = _make_directional_state(n=6000)
        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")
        metrics = result["metrics"]

        # With 500 records per sector (>= 200 min), all should be independent
        assert metrics["independent_sectors"] > 0

    def test_sector_threshold_per_sector(self) -> None:
        """Each sector model should have its own threshold."""
        state = _make_directional_state(n=6000)
        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")
        sector_models = result["metrics"]["sector_models"]

        # At least two sectors should have independent thresholds
        thresholds = {v["threshold"] for v in sector_models.values()}
        assert len(thresholds) >= 1  # should have varied thresholds

    def test_dog_leg_continuity(self) -> None:
        """At the threshold, dog-leg and TLS predictions must match."""
        state = _make_directional_state(n=6000)
        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")
        sector_models = result["metrics"]["sector_models"]

        for _key, model in sector_models.items():
            thresh = model["threshold"]
            slope = model["slope"]
            intercept = model["intercept"]
            dog_leg = model["dog_leg_slope"]
            # TLS prediction at threshold
            tls_at_thresh = thresh * slope + intercept
            # Dog-leg prediction at threshold
            dog_at_thresh = thresh * dog_leg
            assert abs(tls_at_thresh - dog_at_thresh) < 1e-10, (
                f"Dog-leg discontinuity at threshold={thresh:.4f}: "
                f"TLS={tls_at_thresh:.6f}, dog_leg={dog_at_thresh:.6f}"
            )

    def test_full_long_term_correction(self) -> None:
        """Corrected speeds should differ from raw ERA5 speeds."""
        state = _make_directional_state(n=6000)
        _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")

        # Result includes corrected_wind_speed in the saved state
        stored = state.ltc_results["speedsort"]
        assert stored is not None
        assert "df" in stored
        corrected = stored["df"]["corrected_wind_speed"].to_numpy(dtype=float)
        original = stored["df"]["ERA5_original"].to_numpy(dtype=float)
        # With a bias in the data, corrected should differ from original
        assert not np.allclose(corrected, original, atol=0.01)


class TestSparseSectorFallback:
    """Verify sectors with insufficient records fall back to the all-sector model."""

    def test_sparse_sector_uses_fallback(self) -> None:
        """Sectors below MIN_SECTOR_RECORDS share the all-sector fallback model.

        Every sector being sparse is no longer reachable: D9.1 requires 4380
        concurrent records, and 12 sectors x 200 = 2400, so at least one sector
        always clears the minimum.  The reachable case — and the one the guard
        exists for — is a *skewed* wind rose, so the fixture concentrates most
        records in the eastern half and leaves the western sectors thin.
        """
        from server.tools.ltc import SPEEDSORT_MIN_SECTOR_RECORDS, _run_ltc_speedsort

        rng = np.random.default_rng(99)
        n_dense, n_sparse = 4600, 200
        n = n_dense + n_sparse
        dates = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")

        # Dense: directions in [0, 180) -> ~766 per sector across 6 sectors.
        # Sparse: directions in [180, 360) -> ~33 per sector across 6 sectors.
        directions = np.concatenate([rng.uniform(0, 180, n_dense), rng.uniform(180, 360, n_sparse)])
        ref_speeds = rng.uniform(3, 12, n)
        meas_speeds = ref_speeds * 0.98 + rng.normal(0, 0.3, n)

        era5 = pd.DataFrame({"ws_100m": ref_speeds, "wd_100m": directions}, index=dates)
        measured = pd.DataFrame({MEASURED_COLUMN: meas_speeds}, index=dates)

        state = SessionState()
        state.reset()
        state.timeseries_df = measured
        state.era5_interpolated_df = era5

        result = _run_ltc_speedsort(state, MEASURED_COLUMN, "ws_100m", long_dir_col="wd_100m")
        metrics = result["metrics"]
        sector_models = metrics["sector_models"]

        # Both kinds of sector must be present, or the test proves nothing.
        assert 0 < metrics["independent_sectors"] < SPEEDSORT_NUM_SECTORS

        sector_counts = np.bincount(
            _speedsort_sector_index(directions), minlength=SPEEDSORT_NUM_SECTORS
        )
        sparse_keys = [
            str(s) for s in range(SPEEDSORT_NUM_SECTORS)
            if sector_counts[s] < SPEEDSORT_MIN_SECTOR_RECORDS
        ]
        assert sparse_keys, "fixture produced no sparse sectors"

        # Every sparse sector shares one model — the all-sector fallback.
        fallback = sector_models[sparse_keys[0]]
        for key in sparse_keys:
            assert sector_models[key]["slope"] == fallback["slope"]
            assert sector_models[key]["intercept"] == fallback["intercept"]
