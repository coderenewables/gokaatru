"""Air density and atmospheric normalisation — Step 6 of the logic audit.

Density scales power density linearly, so a 1% density error is a 1% energy error.
Magnitudes below were measured against Buck (1996) as an independent reference, not
estimated.

Headline: the density equation itself is right — the vapour-pressure relation is within
0.004% of reference in density terms, and two hypotheses (ice phase, coefficient drift
between the duplicated implementations) measured away to nothing. What is missing is
everything *around* it: no pressure height correction, no density normalisation of wind
speed, and until this step a vectorised path that could not run at all.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.formulas import (
    adjust_density_to_height,
    air_density_iec,
    moist_air_density,
    saturation_vapour_pressure_pa,
)
from server.state.session import SessionState, bind_session
from server.tools.advanced_analysis import _compute_energy_metrics
from server.tools.air_density import compute_air_density_timeseries
from server.tools.atmosphere import _compute_atmospheric_conditions, _density_series

ISA_PRESSURE_PA = 101325.0


def buck_water_hpa(temperature_c: np.ndarray | float):
    """Buck (1996) saturation vapour pressure over water — the independent reference."""
    t = np.asarray(temperature_c, dtype=float)
    return 6.1121 * np.exp((18.678 - t / 234.5) * (t / (257.14 + t)))


def buck_ice_hpa(temperature_c: np.ndarray | float):
    """Buck (1996) saturation vapour pressure over ice."""
    t = np.asarray(temperature_c, dtype=float)
    return 6.1115 * np.exp((23.036 - t / 333.7) * (t / (279.82 + t)))


def _atmos_state(
    temperature_c: np.ndarray,
    pressure_pa: np.ndarray,
    relative_humidity: np.ndarray | None,
    index: pd.DatetimeIndex,
    speed: np.ndarray | None = None,
) -> SessionState:
    """Return a session carrying measured temperature, pressure and optional humidity."""
    columns: dict[str, np.ndarray] = {"Temp": temperature_c, "Press": pressure_pa}
    inventory: dict[str, dict[str, object]] = {
        "Temp": {"sensor_type": "temperature"},
        "Press": {"sensor_type": "pressure"},
    }
    if relative_humidity is not None:
        columns["RH"] = relative_humidity
        inventory["RH"] = {"sensor_type": "humidity"}
    if speed is not None:
        columns["Spd_80m"] = speed
        inventory["Spd_80m"] = {"sensor_type": "wind_speed"}
    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(columns, index=index)
    state.sensor_inventory = inventory
    return state


# ---------------------------------------------------------------------------
# Verified correct — including two hypotheses that measured away
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("temperature_c", [-20.0, -5.0, 0.0, 15.0, 25.0, 35.0, 45.0])
def test_saturation_vapour_pressure_matches_buck_reference(temperature_c: float) -> None:
    """The Magnus relation must track Buck (1996) closely enough for density work."""
    ours = saturation_vapour_pressure_pa(temperature_c) / 100.0
    reference = float(buck_water_hpa(temperature_c))
    assert ours == pytest.approx(reference, rel=0.01)


@pytest.mark.parametrize("temperature_c", [-20.0, -10.0, 0.0, 15.0, 30.0, 45.0])
def test_density_is_insensitive_to_the_vapour_pressure_relation(temperature_c: float) -> None:
    """VERIFIED (hypothesis measured away): the choice of Magnus coefficients is immaterial.

    The codebase carried three separate vapour-pressure expressions with two different
    coefficient sets. Against Buck (1996) on saturated air, the resulting density error
    is at most **0.004%** across -20 to +45 degC. The triplication was a maintenance
    hazard, not a numerical one; it is now consolidated into
    ``core.formulas.saturation_vapour_pressure_pa`` regardless.
    """
    temperature_k = temperature_c + 273.15
    ours, _ = air_density_iec(ISA_PRESSURE_PA, temperature_k, temperature_k)
    reference = float(
        moist_air_density(ISA_PRESSURE_PA, temperature_k, float(buck_water_hpa(temperature_c)) * 100.0)
    )
    assert ours == pytest.approx(reference, rel=1e-4)


@pytest.mark.parametrize("temperature_c", [-25.0, -20.0, -10.0, -5.0])
def test_ice_phase_omission_is_negligible_for_density(temperature_c: float) -> None:
    """F-06 — DOWNGRADED to non-finding. The over-water curve below freezing barely matters.

    Step 1 recorded this as a medium-severity systematic bias. Measured: at -25 degC the
    over-water saturation pressure is **27.7% above** the over-ice value, but because
    vapour is such a small fraction of total pressure when it is that cold, the density
    error is **under 0.011%** at every temperature tested. Not worth a phase switch, and
    the docstring in ``saturation_vapour_pressure_pa`` now says so.
    """
    temperature_k = temperature_c + 273.15
    over_water = float(moist_air_density(90000.0, temperature_k, float(buck_water_hpa(temperature_c)) * 100.0))
    over_ice = float(moist_air_density(90000.0, temperature_k, float(buck_ice_hpa(temperature_c)) * 100.0))

    # The vapour pressures genuinely differ...
    assert float(buck_water_hpa(temperature_c)) / float(buck_ice_hpa(temperature_c)) - 1.0 > 0.04
    # ...and the densities essentially do not.
    assert abs(over_water / over_ice - 1.0) < 0.0002


def test_gas_constants_and_moist_air_is_lighter_than_dry():
    """VERIFIED: the partial-pressure combination has the right constants and the right sign."""
    temperature_k = 288.15
    dry = float(moist_air_density(ISA_PRESSURE_PA, temperature_k, 0.0))
    saturated, _ = air_density_iec(ISA_PRESSURE_PA, temperature_k, temperature_k)

    assert dry == pytest.approx(ISA_PRESSURE_PA / (287.05 * temperature_k), rel=1e-12)
    assert dry == pytest.approx(1.225, abs=5e-4)  # ISA sea level
    assert saturated < dry  # water vapour is lighter than the air it displaces


# ---------------------------------------------------------------------------
# F-00 / F-04 — fixed in this step
# ---------------------------------------------------------------------------


def test_vectorised_density_runs_and_agrees_with_the_scalar_path():
    """F-00 (HIGH) — FIXED. The tool raised NameError on every call; now it runs."""
    index = pd.date_range("2021-01-01", periods=48, freq="h", tz="UTC")
    state = SessionState()
    state.reset()
    state.era5_interpolated_df = pd.DataFrame(
        {
            "sp": np.full(len(index), ISA_PRESSURE_PA),
            "t2m": np.full(len(index), 288.15),
            "d2m": np.full(len(index), 283.15),
        },
        index=index,
    )
    with bind_session(state):
        result = compute_air_density_timeseries("sp", "t2m", "d2m", "era5")

    scalar, _ = air_density_iec(ISA_PRESSURE_PA, 288.15, 283.15)
    assert result["mean_density"] == pytest.approx(scalar, rel=1e-12)
    assert result["units_detected"]["temperature"] == "K"


def test_vectorised_density_detects_celsius_instead_of_assuming_kelvin():
    """F-04 (HIGH) — FIXED. Celsius input must give the same answer as Kelvin, not 19x it.

    The function assumed Kelvin while measured campaign data is stored in Celsius. With
    the numpy import restored but no unit guard, ``source="measured"`` would have divided
    by ~15 instead of ~288 — a roughly nineteenfold overstatement, silently. That is why
    F-00 was deliberately left unfixed until this step.
    """
    index = pd.date_range("2021-01-01", periods=48, freq="h", tz="UTC")

    def density_for(temperature: np.ndarray, pressure: np.ndarray, dewpoint: np.ndarray) -> dict:
        state = SessionState()
        state.reset()
        state.timeseries_df = pd.DataFrame(
            {"Press": pressure, "Temp": temperature, "Dew": dewpoint}, index=index
        )
        with bind_session(state):
            return compute_air_density_timeseries("Press", "Temp", "Dew", "measured")

    kelvin = density_for(
        np.full(len(index), 288.15), np.full(len(index), ISA_PRESSURE_PA), np.full(len(index), 283.15)
    )
    celsius = density_for(
        np.full(len(index), 15.0), np.full(len(index), 1013.25), np.full(len(index), 10.0)
    )

    assert celsius["mean_density"] == pytest.approx(kelvin["mean_density"], rel=1e-12)
    assert celsius["units_detected"] == {"temperature": "degC", "dewpoint": "degC", "pressure": "hPa"}
    # And a plausible density, not 19x one.
    assert 1.0 < celsius["mean_density"] < 1.4


def test_vectorised_density_refuses_an_unrecognisable_unit():
    """A column matching neither band must raise rather than guess."""
    index = pd.date_range("2021-01-01", periods=24, freq="h", tz="UTC")
    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {
            "Press": np.full(len(index), ISA_PRESSURE_PA),
            "Temp": np.full(len(index), 500.0),  # neither Kelvin nor Celsius
            "Dew": np.full(len(index), 283.15),
        },
        index=index,
    )
    with bind_session(state), pytest.raises(ValueError, match="neither a plausible"):
        compute_air_density_timeseries("Press", "Temp", "Dew", "measured")


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_density_height_correction_matches_the_speed_sensor():
    """F-54 (HIGH) — FIXED. Regression test: density must match the height it is used at.

    The bug: no barometric or hypsometric correction existed anywhere. Pressure is measured
    at 2-10 m, density derived from it, and that density then multiplied a hub-height wind
    speed. Air thins by roughly 1.2% per 100 m, so density — and power density, which scales
    linearly with it — was overstated:

        2 m  -> 100 m hub : +1.17%
        2 m  -> 150 m hub : +1.77%
        3 m  -> 200 m hub : +2.36%

    The fix applies the isothermal hypsometric relation using the campaign's own mean
    temperature, matched to the height of the **speed series it multiplies** rather than to
    hub height, since the speed sensor is not always at hub.
    """
    # The arithmetic itself.
    for sensor_height, target_height, expected in ((2, 100, -0.0116), (2, 150, -0.0174), (3, 200, -0.0231)):
        ratio = float(adjust_density_to_height(1.0, 288.15, sensor_height, target_height))
        assert ratio - 1.0 == pytest.approx(expected, abs=0.0005)

    index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    rng = np.random.default_rng(3)
    speed = 7.0 + rng.weibull(2.0, len(index)) * 3.0
    state = _atmos_state(
        np.full(len(index), 15.0),
        np.full(len(index), ISA_PRESSURE_PA),
        np.full(len(index), 70.0),
        index,
        speed=speed,
    )
    state.sensor_inventory["Spd_80m"]["height_m"] = 150.0
    state.sensor_inventory["Press"]["height_m"] = 2.0

    metrics = _compute_energy_metrics(state, "Spd_80m")

    assert metrics["density_height_basis"] == "corrected_to_speed_sensor_height"
    assert metrics["pressure_sensor_height_m"] == pytest.approx(2.0)
    assert metrics["speed_sensor_height_m"] == pytest.approx(150.0)
    assert metrics["density_height_adjustment"] == pytest.approx(0.9826, abs=0.001)

    # A speed sensor at the pressure sensor's own height needs no adjustment.
    state.sensor_inventory["Spd_80m"]["height_m"] = 2.0
    same_height = _compute_energy_metrics(state, "Spd_80m")
    assert same_height["density_height_adjustment"] == pytest.approx(1.0, abs=1e-9)
    assert metrics["wind_power_density_w_m2"] / same_height["wind_power_density_w_m2"] == pytest.approx(
        0.9826, abs=0.001
    )


def test_missing_humidity_sensor_assumes_dry_air_and_says_so():
    """FINDING F-55 (M, now disclosed): no humidity sensor means dry air, which overstates density.

    With no humidity input ``_density_series`` sets vapour pressure to zero. Measured over
    a temperate year (15 +/- 12 degC, 70 +/- 15% RH): density comes out **+0.46%** high
    over the year and **+0.72%** over warm hours, and power density scales linearly with
    density. The assumption is the only option available, but it is not neutral, so the
    response now reports `humidity_basis` and warns.
    """
    index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    doy = index.dayofyear.to_numpy()
    temperature = 15.0 + 12.0 * np.cos(2 * np.pi * (doy - 200) / 365.25)
    humidity = 70.0 + 15.0 * np.cos(2 * np.pi * (doy - 30) / 365.25)
    pressure = np.full(len(index), ISA_PRESSURE_PA)

    with_humidity = _density_series(
        pd.Series(temperature, index=index), pd.Series(pressure, index=index), pd.Series(humidity, index=index)
    )
    without = _density_series(
        pd.Series(temperature, index=index), pd.Series(pressure, index=index), None
    )

    bias = float(without.mean() / with_humidity.mean() - 1.0)
    assert 0.003 < bias < 0.008  # ~0.46%

    warm = temperature > 25
    warm_bias = float(without[warm].mean() / with_humidity[warm].mean() - 1.0)
    assert warm_bias > bias  # worse in warm air, where vapour matters more

    dry_state = _atmos_state(temperature, pressure, None, index)
    dry_result = _compute_atmospheric_conditions(dry_state)
    assert dry_result["air_density"]["humidity_basis"] == "assumed_dry"
    assert "warning" in dry_result["air_density"]

    wet_state = _atmos_state(temperature, pressure, humidity, index)
    wet_result = _compute_atmospheric_conditions(wet_state)
    assert wet_result["air_density"]["humidity_basis"] == "measured"
    assert "warning" not in wet_result["air_density"]


def test_monthly_power_density_carries_seasonal_density():
    """F-56 — FIXED. Regression test: monthly power density must use per-record density.

    The bug: ``_compute_energy_metrics`` took a single annual-mean density and applied it
    to every month. Density varies about **9%** between winter and summer at a temperate
    site, so monthly power density was wrong by **-4.3% in January and +4.5% in July**
    while cancelling to -0.03% in the annual total — invisible in the headline number,
    but the monthly profile is what seasonal revenue and curtailment planning read.

    The fix pairs each record with its own density before averaging.
    """
    index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    doy = index.dayofyear.to_numpy()
    temperature = 15.0 + 12.0 * np.cos(2 * np.pi * (doy - 200) / 365.25)
    humidity = 70.0 + 15.0 * np.cos(2 * np.pi * (doy - 30) / 365.25)
    pressure = np.full(len(index), ISA_PRESSURE_PA)
    rng = np.random.default_rng(3)
    speed = 7.0 + rng.weibull(2.0, len(index)) * 3.0

    state = _atmos_state(temperature, pressure, humidity, index, speed=speed)
    metrics = _compute_energy_metrics(state, "Spd_80m")

    assert metrics["density_source"] == "measured"
    assert metrics["monthly_density_basis"] == "per_record"

    density = _density_series(
        pd.Series(temperature, index=index), pd.Series(pressure, index=index), pd.Series(humidity, index=index)
    )
    monthly_density = density.groupby(density.index.month).mean()
    assert monthly_density.max() / monthly_density.min() - 1.0 > 0.05  # real seasonality

    speed_series = pd.Series(speed, index=index)
    expected = np.array(
        [
            0.5 * float(monthly_density[month]) * float((speed_series[speed_series.index.month == month] ** 3).mean())
            for month in range(1, 13)
        ]
    )
    reported = np.asarray(metrics["monthly_power_density_w_m2"], dtype=float)
    # Within a fraction of a percent: the residue is the within-month speed/density
    # covariance, which the per-record pairing captures and the monthly means do not.
    assert np.max(np.abs(reported / expected - 1.0)) < 0.01

    # A constant annual mean would have been several percent out in both directions.
    annual_mean_version = np.array(
        [
            0.5 * float(density.mean()) * float((speed_series[speed_series.index.month == month] ** 3).mean())
            for month in range(1, 13)
        ]
    )
    assert np.max(np.abs(annual_mean_version / expected - 1.0)) > 0.03


def test_wind_speed_is_never_density_normalised():
    """FINDING F-57 (M): no density normalisation of wind speed exists anywhere.

    IEC 61400-12-1 normalises measured speed to a reference density before power-curve
    work — ``U_n = U * (rho/rho_0)^(1/3)`` for stall-regulated machines, with a different
    treatment for pitch-regulated ones. Grepping the codebase finds no such expression:
    ``np.cbrt`` appears only for the cube-mean speed. ``windkit_estimate_regulation_type``
    exists as a WindKit passthrough that no pipeline stage calls.

    This is currently harmless — there is no power curve to normalise against (F-29), and
    power density correctly uses actual density with actual speed, so no double correction
    is possible. It becomes a live requirement the moment an AEP calculation is added, and
    is recorded here so that work starts from the right place.

    ``density_correction_factor`` is computed and displayed but applied to nothing.
    """
    index = pd.date_range("2021-01-01", periods=200, freq="h", tz="UTC")
    rng = np.random.default_rng(5)
    speed = 8.0 + rng.normal(0, 1.5, len(index))
    state = _atmos_state(
        np.full(len(index), 25.0),  # warm, thin air: normalisation would matter
        np.full(len(index), 90000.0),
        np.full(len(index), 60.0),
        index,
        speed=speed,
    )

    metrics = _compute_energy_metrics(state, "Spd_80m")
    conditions = _compute_atmospheric_conditions(state)

    density = float(metrics["air_density_kg_m3"])
    assert density < 1.15  # genuinely off-standard

    # The correction factor is reported...
    factor = float(conditions["air_density"]["density_correction_factor"])
    assert factor == pytest.approx(density / 1.225, rel=1e-6)
    assert factor < 0.95

    # ...and the reported mean speed is unchanged by it: no normalisation is applied.
    assert metrics["mean_cube_speed_m_s"] == pytest.approx(
        float(np.cbrt(np.mean(speed**3))), rel=1e-12
    )
    assert "normalised_speed" not in metrics
    assert "density_normalisation" not in metrics
