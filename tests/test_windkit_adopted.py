"""The WindKit functions GoKaatru adopts (decisions/0009), pinned against independent references.

WindKit is pinned to one exact version, so an upgrade that moves a number fails here rather
than in a published result. Only the Weibull fit feeds a computed result today
(``server/tools/statistics.py``). WindKit's two sectorwise long-term corrections feed no
result; they run here as a second implementation that GoKaatru's own variance-ratio and
linear corrections are checked against.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.state.session import SessionState
from server.tools.ltc import _run_ltc_linear_least_squares, _run_ltc_variance_ratio
from tests.oracles import weibull_moment

windkit = pytest.importorskip("windkit")

TRUE_SLOPE, TRUE_INTERCEPT = 1.08, 0.35
# GoKaatru's linear correction is Huber IRLS, not OLS; its estimator_note discloses a
# -0.03% slope difference against OLS on clean data. 0.25% leaves room for the seed.
HUBER_VS_OLS_CLEAN_DATA_TOLERANCE = 0.0025


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    mean_x, mean_y = x.mean(), y.mean()
    slope = float(np.sum((x - mean_x) * (y - mean_y)) / np.sum((x - mean_x) ** 2))
    return slope, float(mean_y - slope * mean_x)


def _campaign(seed: int = 9) -> dict[str, object]:
    """Three years of hourly reference and one year of measured data on a known line."""
    rng = np.random.default_rng(seed)
    long_index = pd.date_range("2019-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference = np.clip(rng.weibull(2.0, len(long_index)) * 8.0, 0.1, None)
    direction = rng.uniform(0.0, 360.0, len(long_index))
    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    concurrent = long_index.isin(measured_index)
    measured = np.clip(
        TRUE_SLOPE * reference[concurrent] + TRUE_INTERCEPT + rng.normal(0, 1.0, int(concurrent.sum())),
        0.05,
        None,
    )
    state = SessionState()
    state.reset()
    state.persist_result_files = False
    state.timeseries_df = pd.DataFrame({"Spd_hub": measured}, index=measured_index)
    state.era5_interpolated_df = pd.DataFrame({"Spd_hub": reference}, index=long_index)
    return {
        "state": state,
        "reference": reference,
        "direction": direction,
        "long_index": long_index,
        "concurrent": concurrent,
        "measured": measured,
    }


def _tswc(speed: np.ndarray, direction: np.ndarray, index: pd.DatetimeIndex):
    frame = pd.DataFrame({"ws": speed, "wd": direction}, index=index.tz_convert(None))
    return windkit.tswc_from_dataframe(frame, 0.0, 0.0, 4326, {100.0: ("ws", "wd")})


def _fit_windkit(model, campaign: dict[str, object]):
    """Fit on the concurrent year and predict the full reference record.

    WindKit's validator reads ``fit``'s datasets positionally, so they cannot be passed by
    keyword; the order is (reference, target). The removed wrapper had them swapped.
    """
    concurrent = campaign["concurrent"]
    long_index = campaign["long_index"]
    model.fit(
        _tswc(campaign["reference"][concurrent], campaign["direction"][concurrent], long_index[concurrent]),
        _tswc(campaign["measured"], campaign["direction"][concurrent], long_index[concurrent]),
    )
    predicted = model.predict(_tswc(campaign["reference"], campaign["direction"], long_index))
    return model, predicted.wind_speed.values.ravel()


def test_installed_windkit_is_the_pinned_version() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pin = re.search(r'"windkit==([^"]+)"', pyproject.read_text(encoding="utf-8"))
    assert pin is not None, "pyproject.toml must pin windkit to one exact version"
    assert windkit.__version__ == pin.group(1)


@pytest.mark.parametrize(("scale_a", "shape_k"), [(6.0, 1.6), (8.0, 2.0), (10.5, 2.6)])
def test_weibull_fit_recovers_the_distribution_from_its_exact_moments(scale_a: float, shape_k: float) -> None:
    from windkit.weibull import fit_weibull_wasp_m1_m3

    fitted_a, fitted_k = fit_weibull_wasp_m1_m3(
        weibull_moment(scale_a, shape_k, 1), weibull_moment(scale_a, shape_k, 3)
    )
    assert float(fitted_a) == pytest.approx(scale_a, rel=1e-6)
    assert float(fitted_k) == pytest.approx(shape_k, rel=1e-6)


def test_variance_ratio_agrees_with_windkit_varrat() -> None:
    """Both scale the reference by sd ratio about the concurrent means; one sector makes them
    the same estimator, so they must agree to rounding."""
    campaign = _campaign()
    state = campaign["state"]
    _run_ltc_variance_ratio(state, "Spd_hub", "Spd_hub")
    native = state.ltc_results["variance_ratio"]["df"]["corrected_wind_speed"].to_numpy()

    _, predicted = _fit_windkit(windkit.ltc.VarRatMCP(fit_intercept=True, ws_cutoff=0.0, n_sectors=1), campaign)

    assert np.allclose(native, predicted, rtol=1e-9, atol=1e-9)


def test_linear_correction_agrees_with_windkit_ols_within_the_disclosed_huber_band() -> None:
    campaign = _campaign()
    state = campaign["state"]
    result = _run_ltc_linear_least_squares(state, "Spd_hub", "Spd_hub")
    native_slope = float(result["metrics"]["slope"])
    native = state.ltc_results["linear_least_squares"]["df"]["corrected_wind_speed"].to_numpy()

    model, predicted = _fit_windkit(windkit.ltc.LinRegMCP(ws_cutoff=0.0, n_sectors=1), campaign)
    windkit_slope = float(model.models_[0].slope)

    reference_slope, _ = _ols(campaign["reference"][campaign["concurrent"]], campaign["measured"])
    assert windkit_slope == pytest.approx(reference_slope, rel=1e-9)
    assert windkit_slope == pytest.approx(TRUE_SLOPE, rel=0.02)
    assert native_slope == pytest.approx(windkit_slope, rel=HUBER_VS_OLS_CLEAN_DATA_TOLERANCE)
    assert float(native.mean()) == pytest.approx(float(predicted.mean()), rel=HUBER_VS_OLS_CLEAN_DATA_TOLERANCE)
