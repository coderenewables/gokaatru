"""Air-density normalisation of wind speed (workbench audit F1).

IEC 61400-12-1 normalises the measured *wind speed* for a turbine with active power control
(pitch-regulated) and the measured *power* for a stall-regulated turbine with constant pitch
and constant rotational speed. The function used to carry those two labels the wrong way
round: it applied the speed correction under the name "stall" and refused "pitch". The
arithmetic was the right one for the generic pitch-regulated curves; the labels were not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.core.powercurve import REFERENCE_AIR_DENSITY, normalise_speed_to_reference_density
from server.state.session import SessionState
from server.tools.uncertainty import _density_normalised
from tests import oracles


def test_reference_density_matches_the_oracle_anchor():
    assert REFERENCE_AIR_DENSITY == oracles.ISA_DRY_DENSITY


@pytest.mark.parametrize("density", [0.95, 1.10, 1.225, 1.30])
def test_pitch_regulated_speed_matches_the_equal_power_oracle(density: float):
    speed = np.linspace(0.5, 28.0, 56)
    rho = np.full(speed.shape, density)
    normalised = normalise_speed_to_reference_density(speed, rho, regulation="pitch")
    np.testing.assert_allclose(
        normalised, oracles.equal_kinetic_power_speed(speed, rho), rtol=1e-12
    )


def test_pitch_is_the_default_regulation():
    speed = np.array([4.0, 8.0, 12.0])
    rho = np.full(speed.shape, 1.10)
    np.testing.assert_array_equal(
        normalise_speed_to_reference_density(speed, rho),
        normalise_speed_to_reference_density(speed, rho, regulation="pitch"),
    )


def test_thinner_air_lowers_the_normalised_speed():
    normalised = normalise_speed_to_reference_density(
        np.array([10.0]), np.array([1.10]), regulation="pitch"
    )
    assert normalised[0] == pytest.approx(10.0 * (1.10 / 1.225) ** (1.0 / 3.0))
    assert normalised[0] < 10.0


def test_stall_regulated_speed_normalisation_is_refused():
    with pytest.raises(ValueError, match="power output, not the wind speed"):
        normalise_speed_to_reference_density(
            np.array([10.0]), np.array([1.10]), regulation="stall"
        )


def test_unknown_regulation_is_refused():
    with pytest.raises(ValueError, match="regulation must be"):
        normalise_speed_to_reference_density(
            np.array([10.0]), np.array([1.10]), regulation="active"
        )


def test_session_normalisation_reports_the_pitch_regulated_method():
    # The density is measured from the session's own temperature and pressure (P3-4): dry air
    # at 15 C and 950 hPa.
    state = SessionState()
    state.reset()
    index = pd.date_range("2024-01-01", periods=144, freq="10min", tz="UTC")
    state.timeseries_df = pd.DataFrame({"Tmp_2m": 15.0, "Prs_2m": 950.0}, index=index)
    state.sensor_inventory = {
        "Tmp_2m": {"height_m": 2.0, "sensor_type": "temperature"},
        "Prs_2m": {"height_m": 2.0, "sensor_type": "pressure"},
    }
    density = oracles.dry_air_density(95_000.0, 288.15)
    speed = np.linspace(3.0, 20.0, 18)
    normalised, basis = _density_normalised(state, speed)
    np.testing.assert_allclose(
        normalised,
        oracles.equal_kinetic_power_speed(speed, np.full(speed.shape, density)),
        rtol=1e-4,
    )
    assert basis["applied"] is True
    assert basis["method"] == "iec_61400_12_1_wind_speed_normalisation"
    assert basis["turbine_regulation"] == "pitch"
    assert basis["site_density_kgm3"] == pytest.approx(density, rel=1e-4)
    assert (basis["temperature_sensor"], basis["pressure_sensor"]) == ("Tmp_2m", "Prs_2m")
    assert "stall" not in basis["method"]


def test_a_density_left_in_the_run_configuration_is_not_read():
    state = SessionState()
    state.reset()
    state.runconfig["mean_air_density_kgm3"] = 1.10
    _, basis = _density_normalised(state, np.linspace(3.0, 20.0, 18))
    assert basis["applied"] is False
