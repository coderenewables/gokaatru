"""The sensitivity table in README.md, recomputed so it cannot go stale silently.

The series is the pipeline's long-term ensemble output from `test_step10_uncertainty_energy`
(20-year hourly, mean 8.093 m/s), rescaled to each site mean, as in docs/audit/10.
The rows below are the README's; if the default curve changes, this test fails first.
"""
from __future__ import annotations

import pytest

from server.core.powercurve import (
    DEFAULT_POWER_CURVE,
    HOURS_PER_YEAR,
    energy_sensitivity_factor,
    indicative_capacity_factor,
)
from tests import oracles
from tests.test_step10_uncertainty_energy import reconciled_run  # noqa: F401

README_ROWS = (
    (5.5, 27, 2.10),
    (6.5, 37, 1.70),
    (7.5, 46, 1.37),
    (8.5, 54, 1.10),
    (10.5, 65, 0.63),
)


def test_readme_describes_the_default_curve():
    curve = DEFAULT_POWER_CURVE
    assert (curve.rated_kw, curve.rotor_diameter_m) == (3000.0, 130.0)
    assert round(curve.specific_power_w_m2) == 226
    assert oracles.DEFAULT_CURVE == curve.name


@pytest.mark.parametrize(("mean_speed", "cf_pct", "sensitivity"), README_ROWS)
def test_readme_sensitivity_table_row(reconciled_run, mean_speed, cf_pct, sensitivity):  # noqa: F811
    long_term = reconciled_run["long_term"]
    speed = long_term * (mean_speed / long_term.mean())

    server_cf = indicative_capacity_factor(speed)
    server_s = energy_sensitivity_factor(speed)
    oracle_cf = oracles.gross_aep_mwh(speed) / (oracles.rated_kw() / 1000.0 * HOURS_PER_YEAR)
    oracle_s = oracles.energy_sensitivity_factor(speed)

    assert server_cf == pytest.approx(oracle_cf, rel=1e-9)
    assert server_s == pytest.approx(oracle_s, rel=1e-9)
    assert round(server_cf * 100.0) == cf_pct
    assert round(oracle_cf * 100.0) == cf_pct
    assert round(server_s, 2) == sensitivity
    assert round(oracle_s, 2) == sensitivity
