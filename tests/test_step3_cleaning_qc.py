"""Cleaning and QC filter logic — Step 3 of the logic audit.

Cleaning is the only stage that deliberately deletes measurements, so a filter that is
slightly too eager is worse than one that is slightly too lax: the removed records are
gone from every statistic downstream and nothing later can tell they were real.

Verified by 18 assertions. Magnitudes measured.

Headline: the undo machinery, the bounds disclosure and the availability denominator are
all correct — three hypotheses that measured away. The findings are filters that delete
real weather: `stuck_sensor` removes genuine calms, and `icing_filter` fires on any cold,
steady period whether or not the sensor is frozen.

The spike filter that F-72 covered has since been removed from the product entirely, so
its tests are gone with it; `_apply_rule` no longer offers a `spike_filter` rule type.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule, _undo_cleaning_rule
from server.tools.data_io import _get_data_coverage


def _cleaning_state(speed: np.ndarray, **overrides: np.ndarray) -> SessionState:
    """Return a session with a speed channel plus the paired sd/direction/temperature."""
    n = len(speed)
    index = pd.date_range("2021-01-01", periods=n, freq="10min", tz="UTC")
    columns = {
        "Spd_100m": speed,
        "Dir_100m": overrides.get("direction", np.full(n, 180.0)),
        "Spd_100m_sd": overrides.get("sd", np.full(n, 0.5)),
        "Temp": overrides.get("temperature", np.full(n, 10.0)),
    }
    other_speed = overrides.get("other_speed")
    if other_speed is not None:
        columns["Spd_60m"] = other_speed
    frame = pd.DataFrame(columns, index=index)
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        100.0: {
            "speed_col": "Spd_100m",
            "dir_col": "Dir_100m",
            "sd_col": "Spd_100m_sd",
            "temp_col": "Temp",
        }
    }
    if other_speed is not None:
        state.sensor_mapping[60.0] = {
            "speed_col": "Spd_60m",
            "dir_col": None,
            "sd_col": None,
            "temp_col": None,
        }
    state.sensor_inventory = {"Spd_100m": {"sensor_type": "wind_speed", "height_m": 100.0}}
    return state


# ---------------------------------------------------------------------------
# Verified correct — three hypotheses that measured away
# ---------------------------------------------------------------------------


def test_undo_restores_the_exact_pre_rule_state():
    """VERIFIED: undo replays the remaining rules from raw and reproduces the frame exactly."""
    rng = np.random.default_rng(7)
    speed = 6.0 + rng.weibull(2.0, 600) * 3.0
    speed[100] = 45.0
    state = _cleaning_state(speed.copy())

    _apply_cleaning_rule(state, "range_check", "Spd_100m", json.dumps({"min": 0.0, "max": 20.0}))
    _apply_cleaning_rule(state, "stuck_sensor", "Spd_100m", json.dumps({"consecutive_count": 6}))
    before_third = state.timeseries_df["Spd_100m"].copy()
    _apply_cleaning_rule(state, "tower_shadow", "Spd_100m", json.dumps({}))

    _undo_cleaning_rule(state, 2)

    assert state.timeseries_df["Spd_100m"].equals(before_third)
    assert len(state.cleaning_log) == 2


def test_range_check_reports_the_bounds_it_actually_applied():
    """VERIFIED: the documented fail-safe is real and is disclosed both ways.

    A known sensor type uses the physical table; an unknown one falls back to the sensor's
    own data range, which makes the rule a deliberate no-op. Both report `bounds_source`
    and the applied bounds, so the log cannot imply a check that did not happen.
    """
    rng = np.random.default_rng(11)
    speed = 6.0 + rng.weibull(2.0, 400) * 3.0

    known = _apply_cleaning_rule(_cleaning_state(speed.copy()), "range_check", "Spd_100m", "{}")
    assert known["bounds_source"] == "sensor_type_table"
    assert (known["min_applied"], known["max_applied"]) == (0.0, 50.0)

    unknown_state = _cleaning_state(speed.copy())
    unknown_state.sensor_inventory = {"Spd_100m": {"sensor_type": "mystery", "height_m": 100.0}}
    unknown_state.sensor_mapping = {}
    unknown = _apply_cleaning_rule(unknown_state, "range_check", "Spd_100m", "{}")
    assert unknown["bounds_source"] == "sensor_data_range"
    assert unknown["records_affected"] == 0  # a no-op, as intended


def test_availability_uses_the_nominal_campaign_grid_not_the_delivered_rows():
    """VERIFIED (hypothesis measured away): coverage is measured against the expected grid.

    If the denominator were the count of delivered rows, recovery would read ~100% for any
    campaign whose logger simply stopped writing. It does not. Measured with one week
    missing from a 30-day campaign, expressed two ways:

        rows deleted entirely : 76.67%
        values present but NaN: 76.67%

    against a true availability of 76.7%, with `largest_gap_minutes` reported as exactly
    10 080 (seven days) in both cases. This is `_cadence_aligned_series` doing its job.
    """
    rng = np.random.default_rng(7)
    n = 6 * 24 * 30
    index = pd.date_range("2021-01-01", periods=n, freq="10min", tz="UTC")
    speed = 6.0 + rng.weibull(2.0, n) * 3.0
    outage = (index >= pd.Timestamp("2021-01-08", tz="UTC")) & (index < pd.Timestamp("2021-01-15", tz="UTC"))

    deleted = pd.DataFrame({"Spd_100m": speed}, index=index).loc[~outage]
    blanked = pd.DataFrame({"Spd_100m": speed.copy()}, index=index)
    blanked.loc[outage, "Spd_100m"] = np.nan

    for frame in (deleted, blanked):
        state = SessionState()
        state.reset()
        state.timeseries_df = frame
        state.raw_timeseries_df = frame.copy()
        state.sensor_inventory = {"Spd_100m": {"sensor_type": "wind_speed", "height_m": 100.0}}
        coverage = _get_data_coverage(state, "Spd_100m")

        assert coverage["coverage_pct"] == pytest.approx((~outage).sum() / n * 100.0, abs=0.1)
        assert coverage["total_records"] == n  # the nominal grid, not the delivered rows
        assert coverage["largest_gap_minutes"] == 7 * 24 * 60


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_stuck_sensor_preserves_corroborated_calms():
    """F-68 (HIGH) — FIXED. Regression test: a real dead calm must survive.

    The bug: `stuck_sensor` flagged any run of identical values at or above
    `consecutive_count` (default 6, one hour at 10-minute cadence). A genuine calm reads
    exactly 0.0 for as long as it lasts, so it was indistinguishable from a frozen channel.
    Measured on a two-hour dead calm: all 12 records deleted, mean 8.387 -> 8.558 m/s
    (**+2.04%**), and `calm_fraction` **0.0200 -> 0.0000** — the very quantity the
    calm-inclusive WAsP m1/m3 Weibull fit (D25) depends on.

    The fix corroborates across channels: a run at or below `calm_threshold_mps` is only
    deleted when another mapped speed sensor shows the site was actually windy. With no
    second speed sensor the calm is preserved and the response says why — the fail-safe is
    to keep a measurement that cannot be disproved.
    """
    rng = np.random.default_rng(2)
    speed = 6.0 + rng.weibull(2.0, 600) * 3.0
    speed[200:212] = 0.0  # a two-hour dead calm
    original_mean = float(np.mean(speed))
    original_calm_fraction = float((speed == 0).mean())

    # A. site-wide calm: the other anemometer is also near zero -> preserve.
    other = 6.0 + rng.weibull(2.0, 600) * 3.0
    other[200:212] = 0.05
    state = _cleaning_state(speed.copy(), other_speed=other)
    result = _apply_cleaning_rule(state, "stuck_sensor", "Spd_100m", json.dumps({}))
    cleaned = state.timeseries_df["Spd_100m"]

    assert result["records_affected"] == 0
    assert result["calms_preserved"] == 12
    assert result["calm_corroboration"] == "cross_sensor"
    assert float(cleaned.mean()) == pytest.approx(original_mean, rel=1e-12)
    assert float((cleaned.dropna() == 0).mean()) == pytest.approx(original_calm_fraction)

    # B. frozen channel: the other anemometer reads 8 m/s -> still deleted.
    frozen_state = _cleaning_state(speed.copy(), other_speed=np.full(600, 8.0))
    frozen = _apply_cleaning_rule(frozen_state, "stuck_sensor", "Spd_100m", json.dumps({}))
    assert frozen["records_affected"] == 12
    assert frozen["calms_preserved"] == 0

    # C. nothing to corroborate against -> preserve, and say so.
    lone_state = _cleaning_state(speed.copy())
    lone = _apply_cleaning_rule(lone_state, "stuck_sensor", "Spd_100m", json.dumps({}))
    assert lone["records_affected"] == 0
    assert lone["calm_corroboration"] == "unavailable_no_other_speed_sensor"
    assert "warning" in lone

    # D. a sensor pinned at a non-calm value is unambiguous and still deleted.
    stuck = 6.0 + rng.weibull(2.0, 600) * 3.0
    stuck[300:312] = 12.0
    stuck_state = _cleaning_state(stuck, other_speed=np.full(600, 8.0))
    stuck_result = _apply_cleaning_rule(stuck_state, "stuck_sensor", "Spd_100m", json.dumps({}))
    assert stuck_result["records_affected"] == 12
    assert stuck_result["calms_preserved"] == 0


def test_icing_filter_requires_a_stationary_direction():
    """F-69 (MEDIUM) — FIXED. A held vane is the third signal that separates ice from calm.

    The bug: `_apply_icing_filter` tested two conditions only — speed standard deviation at
    or below `sd_threshold_mps` and temperature below `temp_threshold_c`. A cold, steady
    flow satisfies both. Measured with 20 records at zero speed-SD and -1 degC whose
    direction **swung randomly through the full circle** — which no frozen vane does: all 20
    were removed as icing.

    The fix consults the paired direction column that `sensor_mapping` already resolves and
    `tower_shadow` already uses. A swinging vane is now retained; a held one is still removed.
    """
    rng = np.random.default_rng(4)
    n = 600
    sd = np.full(n, 0.5)
    sd[300:320] = 0.0
    temperature = np.full(n, 10.0)
    temperature[300:320] = -1.0
    swinging = np.full(n, 180.0)
    swinging[300:320] = rng.uniform(0, 360, 20)  # emphatically not frozen

    state = _cleaning_state(
        6.0 + rng.weibull(2.0, n) * 3.0, sd=sd, temperature=temperature, direction=swinging
    )
    result = _apply_cleaning_rule(state, "icing_filter", "Spd_100m", json.dumps({}))

    assert result["records_affected"] == 0
    assert result["retained_by_direction_test"] == 20
    assert result["direction_basis"] == "tested"
    assert int(state.timeseries_df["Spd_100m"].iloc[300:320].isna().sum()) == 0

    # A genuinely frozen sensor holds all three signals, and is still removed.
    frozen = np.full(n, 180.0)
    iced_state = _cleaning_state(
        6.0 + rng.weibull(2.0, n) * 3.0, sd=sd, temperature=temperature, direction=frozen
    )
    iced = _apply_cleaning_rule(iced_state, "icing_filter", "Spd_100m", json.dumps({}))
    assert iced["records_affected"] == 20
    assert iced["retained_by_direction_test"] == 0


def test_icing_filter_declares_when_it_cannot_test_direction():
    """With no mapped direction column the third condition is untestable, and the rule says so."""
    n = 400
    sd = np.full(n, 0.5)
    sd[100:120] = 0.0
    temperature = np.full(n, 10.0)
    temperature[100:120] = -1.0
    rng = np.random.default_rng(5)

    state = _cleaning_state(6.0 + rng.weibull(2.0, n) * 3.0, sd=sd, temperature=temperature)
    state.sensor_mapping[100.0]["dir_col"] = None
    result = _apply_cleaning_rule(state, "icing_filter", "Spd_100m", "{}")

    assert result["records_affected"] == 20  # the pre-fix two-condition behaviour
    assert result["direction_basis"] == "skipped_no_direction_column"
    assert "cold steady flow" in result["warning"]


def test_cleaning_rules_are_order_dependent_and_say_so():
    """F-70 (MEDIUM) — FIXED. Filters do not commute, and the response now says so.

    Rules that create NaNs change what later rules see. `stuck_sensor` measures runs of
    identical values, so any earlier rule that punches a hole in the middle of a run splits
    it into shorter runs that no longer reach the threshold.

    Measured on a ten-record identical run whose middle two records meet the icing
    conditions:

        stuck_sensor then icing_filter : **10** records removed
        icing_filter then stuck_sensor : **2** records removed

    A fivefold difference from rule order alone. The order dependence is inherent — a rule
    that punches NaNs into a run really does change what a run-length rule can see, and
    forcing a canonical order would substitute one arbitrary choice for another.

    What was missing was any statement that the order is *material*, so an analyst
    reordering the rule list had no reason to expect a different answer. Every apply now
    returns an `order_dependence` block naming the rules that already touched this sensor,
    and both `list_cleaning_rules` and `get_cleaning_log` carry the note.
    """
    rng = np.random.default_rng(7)
    speed = 6.0 + rng.weibull(2.0, 400) * 3.0
    speed[100:110] = 12.0  # a ten-record identical run

    sd = np.full(400, 0.5)
    temperature = np.full(400, 10.0)
    sd[104:106] = 0.0  # icing conditions only in the middle of that run
    temperature[104:106] = -1.0

    def removed_with(order: list[str]) -> int:
        state = _cleaning_state(speed.copy(), sd=sd.copy(), temperature=temperature.copy())
        for rule in order:
            params = {"consecutive_count": 6} if rule == "stuck_sensor" else {}
            _apply_cleaning_rule(state, rule, "Spd_100m", json.dumps(params))
        return int(state.timeseries_df["Spd_100m"].isna().sum())

    stuck_first = removed_with(["stuck_sensor", "icing_filter"])
    icing_first = removed_with(["icing_filter", "stuck_sensor"])

    assert stuck_first == 10
    assert icing_first == 2
    assert stuck_first > icing_first * 4

    # The order is logged, so the run is reproducible...
    state = _cleaning_state(speed.copy(), sd=sd.copy(), temperature=temperature.copy())
    first = _apply_cleaning_rule(
        state, "stuck_sensor", "Spd_100m", json.dumps({"consecutive_count": 6})
    )
    result = _apply_cleaning_rule(state, "icing_filter", "Spd_100m", "{}")
    assert [entry["rule_type"] for entry in state.cleaning_log] == ["stuck_sensor", "icing_filter"]

    # ...and the response now names what this rule saw and warns that order matters.
    assert first["order_dependence"]["applied_before_on_this_sensor"] == []
    assert "warning" not in first["order_dependence"]

    order = result["order_dependence"]
    assert order["sequence"] == 2
    assert order["order_is_material"] is True
    assert [item["rule_type"] for item in order["applied_before_on_this_sensor"]] == ["stuck_sensor"]
    assert "different order can give a different result" in order["warning"]

    # The catalogue and the log carry the same statement, so it is discoverable up front.
    from server.tools.cleaning import _get_cleaning_log, _list_cleaning_rules

    assert _list_cleaning_rules(state)["order_is_material"] is True
    log = _get_cleaning_log(state)
    assert log["order_is_material"] is True
    assert "order-dependent" in log["order_note"]
    assert [entry["sequence"] for entry in log["entries"]] == [1, 2]


def test_date_bounded_cleaning_works_on_a_tz_aware_series():
    """F-73 (HIGH) — FIXED. Regression test: date bounds must work on real session data.

    The bug: `_date_mask` built its bounds with a bare ``pd.Timestamp(start_date)`` — naive —
    and compared them against the session index, which D8 guarantees is tz-aware UTC. pandas
    raised ``TypeError: Invalid comparison between dtype=datetime64[us, UTC] and Timestamp``,
    so the whole date-bounded capability was unreachable: `custom_period_exclude` could not
    run at all, and every other rule silently lost its `start_date` / `end_date` narrowing.

    The fix localises a naive bound onto the index's own timezone, which is what an analyst
    reading dates off the campaign means; an already-aware bound is converted rather than
    reinterpreted.
    """
    state = _cleaning_state(6.0 + np.random.default_rng(3).weibull(2.0, 200) * 3.0)
    index = state.timeseries_df.index
    assert str(index.tz) == "UTC"

    result = _apply_cleaning_rule(
        state,
        "custom_period_exclude",
        "Spd_100m",
        "{}",
        start_date="2021-01-01 10:00",
        end_date="2021-01-01 12:00",
    )

    removed = state.timeseries_df["Spd_100m"].isna()
    assert result["records_affected"] == 13  # 10:00..12:00 inclusive at 10-minute cadence
    assert index[removed].min() == pd.Timestamp("2021-01-01 10:00", tz="UTC")
    assert index[removed].max() == pd.Timestamp("2021-01-01 12:00", tz="UTC")

    # An explicitly tz-aware bound is converted, not reinterpreted.
    aware_state = _cleaning_state(6.0 + np.random.default_rng(3).weibull(2.0, 200) * 3.0)
    aware = _apply_cleaning_rule(
        aware_state,
        "custom_period_exclude",
        "Spd_100m",
        "{}",
        start_date="2021-01-01T10:00:00+00:00",
        end_date="2021-01-01T12:00:00+00:00",
    )
    assert aware["records_affected"] == 13


def test_tower_shadow_prefers_the_recorded_boom_orientation():
    """F-71 (MEDIUM) — FIXED. The shadow sector comes from geometry, not a fixed guess.

    The bug: `tower_shadow` defaulted to `exclude_sectors: [170, 190]` — a **20-degree**
    window on an arbitrary bearing, where a lattice tower shadows roughly +/-35 degrees
    behind the boom. Two better sources sat unused: IEA Task 43 records boom orientation per
    measurement point and nothing in the ingest path read it, and `compute_mast_effects`
    already *measures* the shadowed sectors and the rule never consulted it.

    The tower sits opposite the boom, so a boom at 90 degrees puts the shadow at 270.
    """
    rng = np.random.default_rng(9)
    n = 2000
    direction = rng.uniform(0, 360, n)
    state = _cleaning_state(6.0 + rng.weibull(2.0, n) * 3.0, direction=direction)
    state.sensor_inventory["Spd_100m"]["boom_orientation_deg"] = 90.0

    result = _apply_cleaning_rule(state, "tower_shadow", "Spd_100m", "{}")

    assert result["sector_basis"] == "boom_orientation"
    assert result["boom_orientation_deg"] == 90.0
    assert result["exclude_sectors"] == [235.0, 305.0]  # 270 +/- 35
    expected = int(((direction >= 235.0) & (direction <= 305.0)).sum())
    assert result["records_affected"] == expected
    # Roughly 70/360 of the record, against 20/360 before.
    assert 0.15 < result["records_affected"] / n < 0.25


def test_tower_shadow_falls_back_to_the_measured_sector():
    """With no boom orientation, the sectors `compute_mast_effects` measured are used."""
    rng = np.random.default_rng(21)
    n = 6000
    direction = rng.uniform(0, 360, n)
    speed = 6.0 + rng.weibull(2.0, n) * 3.0
    # Depress the upper sensor between 135 and 180 degrees: a measurable shadow on B.
    shadowed = (direction >= 135.0) & (direction < 180.0)
    other = speed.copy()
    speed = np.where(shadowed, speed * 0.80, speed)

    state = _cleaning_state(speed, direction=direction, other_speed=other)
    state.sensor_inventory["Spd_60m"] = {"sensor_type": "wind_speed", "height_m": 60.0}
    state.sensor_inventory["Dir_100m"] = {"sensor_type": "wind_direction", "height_m": 100.0}

    result = _apply_cleaning_rule(state, "tower_shadow", "Spd_100m", "{}")

    assert result["sector_basis"] == "measured_mast_effect"
    start, end = result["exclude_sectors"]
    # The 22.5-degree bins covering 135-180 deg, reported as their outer bounds.
    assert start == pytest.approx(146.25, abs=25.0)
    assert end == pytest.approx(191.25, abs=25.0)
    assert result["records_affected"] > 0


def test_tower_shadow_says_when_it_is_guessing():
    """The legacy 20-degree window is still reachable, but it now declares itself a guess."""
    rng = np.random.default_rng(9)
    n = 2000
    direction = rng.uniform(0, 360, n)
    state = _cleaning_state(6.0 + rng.weibull(2.0, n) * 3.0, direction=direction)

    result = _apply_cleaning_rule(state, "tower_shadow", "Spd_100m", "{}")

    assert result["sector_basis"] == "default_guess"
    assert result["exclude_sectors"] == [170.0, 190.0]
    assert "third of the affected width" in result["warning"]
    assert result["records_affected"] == int(((direction >= 170.0) & (direction <= 190.0)).sum())

    # An explicit caller sector still wins over every derived source.
    explicit = _cleaning_state(6.0 + rng.weibull(2.0, n) * 3.0, direction=direction)
    explicit.sensor_inventory["Spd_100m"]["boom_orientation_deg"] = 90.0
    chosen = _apply_cleaning_rule(
        explicit, "tower_shadow", "Spd_100m", json.dumps({"exclude_sectors": [10, 40]})
    )
    assert chosen["sector_basis"] == "caller"
    assert chosen["exclude_sectors"] == [10.0, 40.0]


def test_tower_shadow_wraps_correctly_through_north():
    """VERIFIED: a sector spanning 0 degrees is handled as a union, not an empty range."""
    rng = np.random.default_rng(13)
    n = 2000
    direction = rng.uniform(0, 360, n)
    state = _cleaning_state(6.0 + rng.weibull(2.0, n) * 3.0, direction=direction)

    result = _apply_cleaning_rule(
        state, "tower_shadow", "Spd_100m", json.dumps({"exclude_sectors": [350, 10]})
    )
    expected = int(((direction >= 350.0) | (direction <= 10.0)).sum())
    assert result["records_affected"] == expected
    assert result["records_affected"] > 0
