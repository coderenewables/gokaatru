"""Sensor-selection *policies* — axis A of the analysis engine (design doc §3.A).

Distinct from `test_sensor_selection.py`, which covers the Data Load stage's sensor
*exclusion* flow. This file is about which of the surviving sensors a given scenario
fits shear on (A1) and extrapolates from (A2).

Before this resolver existed the axis was inexpressible: `_speed_height_map` took
every mapped sensor and `_nearest_indices` picked the nearest valid one per record,
so "nearest 2" or "everything above 90% availability" could not be stated at all.

These tests pin what each policy selects, and — more importantly — what happens at
the edges where a policy does not apply: a lidar with no booms, boom redundancy at a
single height, a mast where nothing clears the availability floor.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.sensor_selection import (
    AVAILABILITY_90,
    AVAILABILITY_BASIS_DATAMODEL,
    AVAILABILITY_BASIS_RECORD,
    AVAILABILITY_THRESHOLD_PCT,
    NEAREST_2,
    POLICIES,
    REDUNDANT_BOOM,
    WIDEST_LEVER,
    availability_measure,
    availability_pct,
    available_policies,
    distinct_selections,
    redundant_boom_heights,
    resolve_all,
    resolve_policy,
)
from server.state.session import SessionState
from tests.conftest import require_campaign_file

INDEX = pd.date_range("2021-01-01", periods=2000, freq="10min", tz="UTC")


def _mast(
    heights: tuple[float, ...],
    hub_height_m: float | None = 120.0,
    availability: dict[float, float] | None = None,
    booms: dict[float, int] | None = None,
    measurement_type: str = "mast",
) -> SessionState:
    """Build a session with mapped speed sensors, optional gaps and optional boom pairs."""
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(index=INDEX)
    for height in heights:
        column = f"Spd_{int(height)}m"
        values = 8.0 + rng.normal(0.0, 1.0, len(INDEX))
        share = (availability or {}).get(height, 1.0)
        if share < 1.0:
            drop = rng.permutation(len(INDEX))[: int(len(INDEX) * (1.0 - share))]
            values[drop] = np.nan
        frame[column] = values

    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.sensor_mapping = {
        float(h): {"speed_col": f"Spd_{int(h)}m", "dir_col": None} for h in heights
    }
    state.set_measurement_type(measurement_type)
    if hub_height_m is not None:
        state.set_hub_height_m(hub_height_m)

    inventory: dict[str, dict[str, object]] = {}
    for height in heights:
        count = (booms or {}).get(height, 1)
        for boom in range(count):
            suffix = "" if count == 1 else f"_{chr(ord('A') + boom)}"
            inventory[f"Spd_{int(height)}m{suffix}"] = {
                "height_m": float(height),
                "sensor_type": "wind_speed",
                "boom_orientation_deg": 20.0 + 180.0 * boom,
            }
    state.sensor_inventory = inventory
    return state


# ---------------------------------------------------------------------------
# What each policy selects
# ---------------------------------------------------------------------------


def test_nearest_2_takes_the_two_heights_closest_to_hub():
    state = _mast((40.0, 60.0, 80.0, 100.0), hub_height_m=120.0)
    selection = resolve_policy(state, NEAREST_2)
    assert selection.available
    assert selection.heights_m == (80.0, 100.0)
    assert selection.columns == ("Spd_80m", "Spd_100m")
    assert selection.can_fit_shear


def test_nearest_2_works_when_hub_is_bracketed_by_the_mast():
    """A bracketed hub picks the straddling pair, not the top pair."""
    state = _mast((40.0, 60.0, 80.0, 100.0), hub_height_m=70.0)
    assert resolve_policy(state, NEAREST_2).heights_m == (60.0, 80.0)


def test_nearest_2_is_unavailable_without_a_hub_height():
    state = _mast((40.0, 80.0), hub_height_m=None)
    selection = resolve_policy(state, NEAREST_2)
    assert selection.available is False
    assert "Hub height is not set" in selection.reason


def test_availability_policy_excludes_sensors_below_the_floor():
    state = _mast(
        (40.0, 60.0, 80.0, 100.0),
        availability={60.0: 0.72, 100.0: 0.95},
    )
    selection = resolve_policy(state, AVAILABILITY_90)
    assert selection.available
    assert 60.0 not in selection.heights_m
    assert selection.heights_m == (40.0, 80.0, 100.0)
    assert selection.detail["excluded_heights_m"] == [60.0]
    assert selection.detail["availability_pct"]["100.0"] == pytest.approx(95.0, abs=0.5)


def test_availability_policy_reports_the_best_it_found_when_nothing_qualifies():
    """Failing the floor must say how close the data came, not just refuse."""
    state = _mast((40.0, 80.0), availability={40.0: 0.5, 80.0: 0.6})
    selection = resolve_policy(state, AVAILABILITY_90)
    assert selection.available is False
    assert "best is 6" in selection.reason
    assert selection.detail["availability_pct"]["80.0"] == pytest.approx(60.0, abs=0.5)


def test_widest_lever_takes_the_extreme_pair():
    state = _mast((40.0, 60.0, 80.0, 100.0))
    selection = resolve_policy(state, WIDEST_LEVER)
    assert selection.heights_m == (40.0, 100.0)
    # Reported to 6 dp, which is the precision the runconfig carries it at.
    assert selection.detail["delta_ln_z"] == pytest.approx(np.log(100.0 / 40.0), abs=1e-6)


def test_widest_lever_needs_two_heights():
    state = _mast((80.0,))
    selection = resolve_policy(state, WIDEST_LEVER)
    assert selection.available is False
    assert "at least two measurement heights" in selection.reason


# ---------------------------------------------------------------------------
# Redundant booms — the policy with real applicability constraints
# ---------------------------------------------------------------------------


def test_redundant_boom_selects_the_heights_that_carry_two_sensors():
    state = _mast((40.0, 60.0, 80.0, 100.0), booms={80.0: 2, 100.0: 2})
    assert sorted(redundant_boom_heights(state)) == [80.0, 100.0]

    selection = resolve_policy(state, REDUNDANT_BOOM)
    assert selection.available
    assert selection.heights_m == (80.0, 100.0)
    assert selection.can_fit_shear
    assert selection.detail["sensors_by_height"]["80.0"] == ["Spd_80m_A", "Spd_80m_B"]


def test_redundant_boom_at_one_height_stays_usable_but_cannot_fit_shear():
    """A single redundant height is a valid reference; it just cannot fit an exponent.

    ln(z2/z1) is zero across one height, so the shear *fit* is impossible — but the
    scenario is not refused: it supplies an exponent instead (design doc §3.A.1).
    """
    state = _mast((40.0, 80.0, 100.0), booms={100.0: 2})
    selection = resolve_policy(state, REDUNDANT_BOOM)

    assert selection.available is True
    assert selection.heights_m == (100.0,)
    assert selection.can_fit_shear is False
    assert selection.detail["requires_analyst_shear"] is True


def test_redundant_boom_is_unavailable_on_a_lidar():
    """No booms means nothing to select on, and the reason says so rather than guessing."""
    state = _mast(tuple(float(h) for h in range(40, 260, 20)), measurement_type="lidar")
    selection = resolve_policy(state, REDUNDANT_BOOM)

    assert selection.available is False
    assert "no booms" in selection.reason
    assert selection.detail["measurement_type"] == "lidar"
    assert selection.can_fit_shear is False


def test_redundant_boom_says_so_when_no_inventory_is_loaded():
    state = _mast((40.0, 80.0))
    state.sensor_inventory = {}
    selection = resolve_policy(state, REDUNDANT_BOOM)
    assert selection.available is False
    assert "No sensor inventory" in selection.reason


# ---------------------------------------------------------------------------
# Axis behaviour
# ---------------------------------------------------------------------------


def test_a_lidar_drops_axis_a_to_three_levels():
    """Design doc §4.1: axis A shrinks on a lidar through inapplicability, not dedup."""
    state = _mast(tuple(float(h) for h in range(40, 260, 20)), measurement_type="lidar")
    assert set(available_policies(state)) == {NEAREST_2, AVAILABILITY_90, WIDEST_LEVER}


def test_every_policy_resolves_or_explains_itself():
    """No policy may resolve to nothing silently; an unavailable one carries a reason."""
    state = _mast((40.0, 80.0), hub_height_m=None)
    resolved = resolve_all(state)
    assert set(resolved) == set(POLICIES)
    for policy, selection in resolved.items():
        assert selection.available or selection.reason, policy
        if selection.available:
            assert selection.columns, policy


def test_policies_that_resolve_identically_are_grouped_for_deduplication():
    """Dedup keys on resolved columns, not policy names (design doc §4).

    On a two-height mast nearest-2 and widest-lever are the same pair, so the pairing
    is one computation wearing two names.
    """
    state = _mast((60.0, 100.0), hub_height_m=120.0)
    groups = distinct_selections(resolve_all(state))

    assert ("Spd_60m", "Spd_100m") in groups
    assert set(groups[("Spd_60m", "Spd_100m")]) >= {NEAREST_2, WIDEST_LEVER}
    # Three available policies collapse to one distinct sensor list here.
    assert len(groups) == 1


def test_a_rich_lidar_barely_deduplicates():
    """The counterpart: distinct heights mean distinct selections and no saving."""
    state = _mast(tuple(float(h) for h in range(40, 280, 20)), hub_height_m=150.0)
    groups = distinct_selections(resolve_all(state))
    assert len(groups) == 3  # nearest_2, availability_90 and widest_lever all differ


def test_unknown_policy_is_rejected_by_name():
    state = _mast((40.0, 80.0))
    with pytest.raises(ValueError, match="sensor policy must be one of"):
        resolve_policy(state, "top_2")


def test_selection_serialises_for_the_scenario_runconfig():
    """The runconfig records what a policy resolved to, not just what it was called."""
    state = _mast((40.0, 60.0, 80.0, 100.0), hub_height_m=120.0)
    record = resolve_policy(state, NEAREST_2).to_runconfig()

    assert record["policy"] == NEAREST_2
    assert record["resolved_heights_m"] == [80.0, 100.0]
    assert record["resolved_columns"] == ["Spd_80m", "Spd_100m"]
    assert record["can_fit_shear"] is True
    assert record["available"] is True


def test_availability_is_measured_against_the_sensors_own_deployed_period():
    """Scattered gaps still read as gaps — the denominator only excludes non-deployment.

    A column whose losses are spread across the campaign has a period of record that
    spans essentially the whole series, so this case is unchanged by the deployed-period
    fix. What changes is the *contiguous leading* gap of a late install, below.
    """
    state = _mast((80.0,), availability={80.0: 0.5})
    assert availability_pct(state, "Spd_80m") == pytest.approx(50.0, abs=1.0)
    assert availability_pct(state, "Spd_999m") == 0.0


# ---------------------------------------------------------------------------
# Deployed-period availability (§12.3) — a sensor is not charged for the campaign
# it was not installed for.
# ---------------------------------------------------------------------------


def _install_late(state: SessionState, column: str, fraction: float) -> None:
    """Blank the first `fraction` of a column, as a sensor installed mid-campaign would be."""
    cut = int(len(state.timeseries_df) * fraction)
    state.timeseries_df.loc[state.timeseries_df.index[:cut], column] = np.nan


def test_a_late_installed_sensor_is_not_charged_for_the_campaign_before_it_existed():
    """The §12.3 defect: availability measured against total records charges a sensor
    for every record before it was installed, so a perfectly healthy late-added sensor
    scores below the 90% floor and axis A silently loses a level."""
    state = _mast((80.0,))
    _install_late(state, "Spd_80m", 0.30)  # installed 30% into the campaign, no gaps after

    # Against total records this sensor reads ~70% and fails the floor.
    assert availability_measure(state, "Spd_80m").pct == pytest.approx(100.0, abs=0.5)


def test_datamodel_deployment_dates_define_the_window_when_present():
    state = _mast((80.0,))
    _install_late(state, "Spd_80m", 0.30)
    start = state.timeseries_df.index[int(len(state.timeseries_df) * 0.30)]
    state.sensor_inventory["Spd_80m"]["date_from"] = start.isoformat()

    measure = availability_measure(state, "Spd_80m")
    assert measure.basis == AVAILABILITY_BASIS_DATAMODEL
    assert measure.pct == pytest.approx(100.0, abs=0.5)


def test_a_missing_datamodel_date_falls_back_to_the_columns_own_period_of_record():
    state = _mast((80.0,))
    _install_late(state, "Spd_80m", 0.30)
    assert "date_from" not in state.sensor_inventory["Spd_80m"]

    measure = availability_measure(state, "Spd_80m")
    assert measure.basis == AVAILABILITY_BASIS_RECORD
    assert measure.pct == pytest.approx(100.0, abs=0.5)


def test_a_gap_inside_the_deployed_window_is_still_charged():
    """The fix must not forgive real downtime — only non-deployment."""
    state = _mast((80.0,))
    frame = state.timeseries_df
    _install_late(state, "Spd_80m", 0.20)
    # A contiguous outage in the middle of the deployed period.
    mid = slice(int(len(frame) * 0.50), int(len(frame) * 0.70))
    frame.loc[frame.index[mid], "Spd_80m"] = np.nan

    measure = availability_measure(state, "Spd_80m")
    # Deployed window is the last 80%; a fifth of the campaign is missing inside it.
    assert measure.pct == pytest.approx(75.0, abs=1.5)
    assert measure.pct < AVAILABILITY_THRESHOLD_PCT


def test_the_policy_reports_which_basis_each_sensor_used():
    """Disclosure: a reader must be able to tell a deployed-period figure from a
    whole-campaign one, because they are not comparable."""
    state = _mast((80.0, 100.0))
    _install_late(state, "Spd_80m", 0.30)
    state.sensor_inventory["Spd_100m"]["date_from"] = state.timeseries_df.index[0].isoformat()

    selection = resolve_policy(state, AVAILABILITY_90)
    bases = selection.detail["availability_basis"]
    assert bases["100.0"] == AVAILABILITY_BASIS_DATAMODEL
    assert bases["80.0"] == AVAILABILITY_BASIS_RECORD


def test_a_sensor_removed_early_is_not_charged_for_the_campaign_after_it_left():
    state = _mast((80.0,))
    frame = state.timeseries_df
    cut = int(len(frame) * 0.70)
    frame.loc[frame.index[cut:], "Spd_80m"] = np.nan
    state.sensor_inventory["Spd_80m"]["date_to"] = frame.index[cut - 1].isoformat()

    measure = availability_measure(state, "Spd_80m")
    assert measure.basis == AVAILABILITY_BASIS_DATAMODEL
    assert measure.pct == pytest.approx(100.0, abs=0.5)


# ---------------------------------------------------------------------------
# Deployment dates read from the real Task 43 datamodels
# ---------------------------------------------------------------------------


@pytest.fixture
def horns_rev_session():
    """Horns Rev carries genuinely staggered installs — Spd_58m predates the rest by ~13 months."""
    from server.state.session import session as _session
    from server.tools.data_io import _parse_datamodel, _parse_timeseries

    _parse_timeseries(_session, str(require_campaign_file("HornsRev-MAST_timeseries_data.csv")))
    _parse_datamodel(_session, str(require_campaign_file("HornsRev-MAST_data_model.json")))
    return _session


def test_deployment_dates_are_carried_from_the_datamodel_into_the_inventory(horns_rev_session):
    """The datamodel states when each instrument went up; nothing read it before."""
    entry = horns_rev_session.sensor_inventory["Spd_58m"]
    assert entry["date_from"].startswith("1999-05-24")

    later = horns_rev_session.sensor_inventory["Spd_62m"]
    assert later["date_from"].startswith("2000-06-21")


def test_a_real_late_installed_sensor_clears_the_floor_once_measured_over_its_own_deployment(
    horns_rev_session,
):
    """Spd_62m went up ~13 months into the record. Charged for the whole campaign it fails
    the 90% floor; measured over its own deployment it passes — this is the §12.3 defect
    on real data, not a synthetic construction."""
    measure = availability_measure(horns_rev_session, "Spd_62m")
    assert measure.basis == AVAILABILITY_BASIS_DATAMODEL
    assert measure.pct >= AVAILABILITY_THRESHOLD_PCT

    whole_campaign = (
        horns_rev_session.timeseries_df["Spd_62m"].notna().sum()
        / len(horns_rev_session.timeseries_df)
        * 100.0
    )
    assert whole_campaign < AVAILABILITY_THRESHOLD_PCT
