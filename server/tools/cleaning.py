"""cleaning — Phase 2 MCP tools for rule-based timeseries cleaning.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import ast
import copy
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from server.core.validators import SENSOR_FIELDS, detect_timestep_minutes
from server.main import mcp
from server.state.session import SessionState, session

# Physical bounds per sensor type for range_check (D16), in the units the
# pipeline stores: m/s, degrees, degrees Celsius, Pascals, percent.  An unknown
# type is deliberately absent — it falls back to the sensor's own data range.
RANGE_CHECK_BOUNDS: dict[str, tuple[float, float]] = {
    "wind_speed": (0.0, 50.0),
    "wind_direction": (0.0, 360.0),
    "temperature": (-60.0, 60.0),
    "pressure": (80000.0, 110000.0),
    "humidity": (0.0, 100.0),
}

# A run at or below this speed may be a genuine dead calm rather than a frozen channel,
# so it is only deleted when another anemometer shows the site was actually windy.
CALM_THRESHOLD_MPS = 0.5
CALM_CORROBORATION_MPS = 1.0

# Icing (F-69).  A frozen cup holds its speed AND its vane holds its bearing; a cold,
# steady flow holds neither for long.  The third signal is what separates them, so the
# direction must also be stationary over a short window before a record is called iced.
ICING_DIRECTION_TOLERANCE_DEG = 5.0
ICING_DIRECTION_WINDOW = 3

# Tower shadow (F-71).  A lattice tower shadows roughly +/-35 degrees behind the boom.
# The historical 20-degree default is about a third of that, so it is kept only as the
# last resort and is reported as a guess when it is used.
TOWER_SHADOW_DEFAULT_WIDTH_DEG = 70.0
TOWER_SHADOW_LEGACY_SECTOR = [170.0, 190.0]

# Rule order is material (F-70): a rule that punches NaNs into the middle of a run
# changes what a later run-length rule can see.  The log records the order, which makes
# a result reproducible; this note is what makes the order visible as a choice.
RULE_ORDER_NOTE = (
    "Cleaning rules are order-dependent. Rules that introduce NaNs change what later "
    "rules observe - stuck_sensor measures runs of identical values, so an earlier rule "
    "splitting a run into shorter pieces can take its removal count from 10 to 2 on the "
    "same data. The sequence in the cleaning log is part of the method, not a "
    "presentation detail; reordering it will change the result."
)

RULES = {
    # No advertised min/max: bounds come from the sensor's type (D16). Echoing
    # 0-50 back as "the default" is what wiped direction and pressure channels.
    "range_check": {},
    "icing_filter": {
        "temp_threshold_c": 2.0,
        "sd_threshold_mps": 0.01,
        "direction_tolerance_deg": ICING_DIRECTION_TOLERANCE_DEG,
    },
    "stuck_sensor": {"consecutive_count": 6, "calm_threshold_mps": CALM_THRESHOLD_MPS},
    # No advertised sector: the default is derived per sensor from boom orientation or
    # the measured mast effect, and falls back to the legacy guess only when neither
    # exists (F-71).
    "tower_shadow": {"sector_width_deg": TOWER_SHADOW_DEFAULT_WIDTH_DEG},
    "timestamp_gap_fill": {},
    "custom_period_exclude": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
    "expression_filter": {"expression": "Spd_100m < 0 or Spd_100m > 50"},
}


def _float_param(params: dict[str, object], key: str, default: float) -> float:
    """Read a numeric cleaning-rule parameter as float from a parsed JSON object."""
    value = params.get(key, default)
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"Parameter '{key}' must be numeric, got {type(value).__name__}")
    return float(value)


def _int_param(params: dict[str, object], key: str, default: int) -> int:
    """Read an integer cleaning-rule parameter from a parsed JSON object."""
    value = params.get(key, default)
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"Parameter '{key}' must be integer-like, got {type(value).__name__}")
    return int(value)


def _sector_bounds(params: dict[str, object]) -> tuple[float, float]:
    """Read tower-shadow sector bounds from the parsed cleaning-rule parameters."""
    value = params.get("exclude_sectors", [170, 190])
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("exclude_sectors must be a list with start and end degrees")
    start_value, end_value = value[0], value[1]
    if not isinstance(start_value, (int, float, str)) or not isinstance(end_value, (int, float, str)):
        raise ValueError("exclude_sectors values must be numeric")
    return float(start_value), float(end_value)


def _require_timeseries(state: SessionState) -> pd.DataFrame:
    """Return the active timeseries dataframe required for Phase 2 cleaning operations."""
    if state.timeseries_df is None or state.raw_timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return state.timeseries_df


def _parse_params(params: str) -> dict[str, object]:
    """Parse JSON rule parameters for the Phase 2 cleaning tool interface."""
    payload = json.loads(params) if params else {}
    if not isinstance(payload, dict):
        raise ValueError("params must decode to a JSON object")
    return payload


def _bound_timestamp(value: str, index: pd.DatetimeIndex) -> pd.Timestamp:
    """Parse a cleaning date bound onto the same timezone as the series index.

    Session timeseries are tz-aware UTC (D8), while a bound typed by an analyst is naive.
    Comparing the two raises ``TypeError: Invalid comparison between dtype=datetime64[us,
    UTC] and Timestamp``, which made every date-bounded rule unusable on real data —
    ``custom_period_exclude`` could not run at all, and every other rule silently lost its
    optional ``start_date`` / ``end_date`` narrowing.

    A naive bound is interpreted in the index's own timezone, which is what an analyst
    reading dates off the campaign means. An already-aware bound is converted rather than
    reinterpreted.
    """
    stamp = pd.Timestamp(value)
    if index.tz is None:
        return stamp.tz_localize(None) if stamp.tzinfo is not None else stamp
    return stamp.tz_localize(index.tz) if stamp.tzinfo is None else stamp.tz_convert(index.tz)


def _date_mask(index: pd.DatetimeIndex, start_date: str, end_date: str) -> np.ndarray:
    """Build an inclusive timestamp mask for optional cleaning date constraints."""
    mask = np.ones(len(index), dtype=bool)
    if start_date:
        mask &= index >= _bound_timestamp(start_date, index)
    if end_date:
        mask &= index <= _bound_timestamp(end_date, index)
    return mask


def _mapping_for_sensor(state: SessionState, sensor: str) -> dict[str, str | None]:
    """Find the height-level sensor mapping entry associated with a named speed sensor."""
    for sensor_map in state.sensor_mapping.values():
        if sensor in sensor_map.values():
            return sensor_map
    raise ValueError(f"Sensor '{sensor}' is not present in session.sensor_mapping")


def _sensor_type_for(state: SessionState, sensor: str) -> str:
    """Resolve a sensor's physical type from the inventory, else the height mapping."""
    metadata = state.sensor_inventory.get(sensor)
    if isinstance(metadata, dict):
        sensor_type = str(metadata.get("sensor_type", "")).strip()
        if sensor_type and sensor_type != "unknown":
            return sensor_type
    for mapping in state.sensor_mapping.values():
        for field_name, field_type in SENSOR_FIELDS.items():
            if mapping.get(field_name) == sensor:
                return field_type
    return "unknown"


def _resolve_range_bounds(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    params: dict[str, object],
) -> tuple[float, float, str, str]:
    """Resolve range_check bounds from explicit params, the sensor type, or the data (D16).

    The rule is sensor-agnostic but the old defaults (0-50) were wind-speed
    specific: applied to a direction channel they destroyed everything above
    50 degrees, and to pressure in Pa or temperature in K they wiped the column
    entirely — silently, and logged as a legitimate step.
    """
    explicit_min = params.get("min")
    explicit_max = params.get("max")
    if explicit_min is not None and explicit_max is not None:
        return _float_param(params, "min", 0.0), _float_param(params, "max", 50.0), "explicit", "explicit"

    sensor_type = _sensor_type_for(state, sensor)
    bounds = RANGE_CHECK_BOUNDS.get(sensor_type)
    if bounds is not None:
        table_min, table_max = bounds
        # A partial override still wins for the side that was supplied.
        min_value = _float_param(params, "min", table_min) if explicit_min is not None else table_min
        max_value = _float_param(params, "max", table_max) if explicit_max is not None else table_max
        return min_value, max_value, "sensor_type_table", sensor_type

    # DECIDED: unknown type falls back to the sensor's own data range. Bounds
    # taken from the data can never exclude any of it, so the rule is a no-op —
    # that is the intended fail-safe (do nothing rather than destroy good
    # records), but the response must not imply a check occurred.
    series = df[sensor].dropna()
    if series.empty:
        return float("-inf"), float("inf"), "sensor_data_range", sensor_type
    return float(series.min()), float(series.max()), "sensor_data_range", sensor_type


def _apply_range_check(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> tuple[int, dict[str, object]]:
    """Apply min-max threshold cleaning to a single sensor column using type-aware bounds."""
    min_value, max_value, bounds_source, sensor_type = _resolve_range_bounds(state, df, sensor, params)
    affected = mask & ((df[sensor] < min_value) | (df[sensor] > max_value)) & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    detail: dict[str, object] = {
        "bounds_source": bounds_source,
        "sensor_type": sensor_type,
        "min_applied": min_value,
        "max_applied": max_value,
    }
    if bounds_source == "sensor_data_range":
        detail["note"] = (
            f"Sensor type for '{sensor}' is unknown, so bounds were taken from the sensor's own "
            "data range. Bounds derived from the data cannot exclude any of it — this rule was a "
            "no-op. Supply explicit min/max to perform a real range check."
        )
    return int(affected.sum()), detail


def _direction_is_stationary(
    directions: pd.Series,
    tolerance_deg: float,
    window: int,
) -> np.ndarray:
    """Return a mask of records whose wind direction is frozen over a short window.

    Bearings are circular, so successive records are compared through the shortest arc
    (``wrap`` to +/-180) rather than by subtraction — otherwise 359 deg followed by 1 deg
    reads as a 358-degree swing when the vane barely moved.  A record counts as stationary
    when every step inside the surrounding window stays within *tolerance_deg*.

    A missing direction leaves the question unanswerable, and the fail-safe on an
    unanswerable question is to keep the measurement: those records return False.
    """
    values = directions.to_numpy(dtype=float)
    step = np.abs((np.diff(values, prepend=values[:1]) + 180.0) % 360.0 - 180.0)
    step[0] = 0.0
    step[~np.isfinite(step)] = np.inf
    within = pd.Series(step <= float(tolerance_deg))
    span = max(int(window), 1)
    # Centred window: a record is only frozen if its neighbourhood is frozen too, so a
    # single coincidental repeat between two swings does not qualify.
    sustained = within.rolling(span, center=True, min_periods=1).min().to_numpy().astype(bool)
    return sustained & np.isfinite(values)


def _apply_icing_filter(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> tuple[int, dict[str, object]]:
    """Remove frozen instrumentation, identified by held speed, low temperature and a held vane.

    Speed standard deviation at or below ``sd_threshold_mps`` with temperature below
    ``temp_threshold_c`` describes a cold, steady flow just as well as it describes ice.
    What it cannot describe is a vane that has stopped moving, and that third signal is
    the one that separates the two (F-69): 20 records at zero speed-SD and -1 degC whose
    direction swung through the full circle were all removed as icing, which no frozen
    vane could have produced.

    The paired direction column is already resolved in ``sensor_mapping`` and already used
    by ``tower_shadow``, so the signal costs nothing to consult.  When no direction column
    exists the condition cannot be tested; the rule then behaves as it did before and the
    response says the test was skipped.
    """
    sensor_map = _mapping_for_sensor(state, sensor)
    sd_col = sensor_map.get("sd_col")
    temp_col = sensor_map.get("temp_col")
    direction_col = sensor_map.get("dir_col")
    if sd_col not in df.columns or temp_col not in df.columns:
        raise ValueError("icing_filter requires matching sd and temperature columns in the timeseries")
    threshold = _float_param(params, "temp_threshold_c", 2.0)
    sd_threshold = _float_param(params, "sd_threshold_mps", 0.01)
    tolerance = _float_param(params, "direction_tolerance_deg", ICING_DIRECTION_TOLERANCE_DEG)
    window = _int_param(params, "direction_window", ICING_DIRECTION_WINDOW)

    frozen_speed = (
        mask
        & (df[sd_col].fillna(np.nan) <= sd_threshold).to_numpy()
        & (df[temp_col] < threshold).fillna(False).to_numpy()
    )
    detail: dict[str, object] = {
        "temp_threshold_c": float(threshold),
        "sd_threshold_mps": float(sd_threshold),
    }
    if isinstance(direction_col, str) and direction_col in df.columns:
        stationary = _direction_is_stationary(df[direction_col], tolerance, window)
        affected = frozen_speed & stationary
        detail["direction_basis"] = "tested"
        detail["direction_sensor"] = direction_col
        detail["direction_tolerance_deg"] = float(tolerance)
        detail["direction_window"] = int(window)
        detail["retained_by_direction_test"] = int((frozen_speed & ~stationary).sum())
    else:
        affected = frozen_speed
        detail["direction_basis"] = "skipped_no_direction_column"
        detail["warning"] = (
            "No paired wind-direction column is mapped for this sensor, so the "
            "direction-stationarity condition could not be tested. Records were removed on "
            "held speed and low temperature alone, which a cold steady flow also satisfies."
        )
    df.loc[affected, sensor] = np.nan
    return int(affected.sum()), detail


def _other_speed_columns(state: SessionState, df: pd.DataFrame, sensor: str) -> list[str]:
    """Return the other mapped wind-speed columns available for corroboration."""
    columns: list[str] = []
    for sensor_map in state.sensor_mapping.values():
        candidate = sensor_map.get("speed_col")
        if isinstance(candidate, str) and candidate != sensor and candidate in df.columns:
            columns.append(candidate)
    return columns


def _apply_stuck_sensor(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> tuple[int, dict[str, object]]:
    """Remove runs of repeated identical values using a minimum consecutive-count threshold.

    A genuine dead calm reads exactly 0.0 for as long as it lasts, so by run length alone it
    is indistinguishable from a frozen channel — and deleting it was measurably destructive:
    a two-hour calm removed raised the mean 2.04% and took the reported ``calm_fraction``
    from 0.0200 to **zero**, which is the very quantity the calm-inclusive WAsP m1/m3
    Weibull fit (D25) depends on.

    The two *are* separable. A frozen cup holds one value while the other anemometers keep
    moving; a real calm shows near-zero speed across every height at once.  So a run at or
    below ``calm_threshold_mps`` is only removed when another mapped speed sensor was
    reading above ``corroboration_speed_mps`` at the same timestamps.  With no other speed
    sensor to compare against, the calm is preserved — the fail-safe is to keep a
    measurement that cannot be disproved rather than delete it.

    Runs above the calm threshold are unambiguous (a sensor pinned at 12 m/s is stuck) and
    are removed as before.
    """
    threshold = _int_param(params, "consecutive_count", 6)
    calm_threshold = _float_param(params, "calm_threshold_mps", CALM_THRESHOLD_MPS)
    corroboration_speed = _float_param(params, "corroboration_speed_mps", CALM_CORROBORATION_MPS)

    series = df[sensor]
    groups = series.ne(series.shift()) | series.isna()
    run_ids = groups.cumsum()
    run_lengths = series.groupby(run_ids).transform("size")
    long_runs = mask & series.notna().to_numpy() & (run_lengths >= threshold).to_numpy()

    calm_runs = long_runs & (series <= calm_threshold).fillna(False).to_numpy()
    others = _other_speed_columns(state, df, sensor)
    if others:
        # Windy elsewhere at the same moment => this channel really is stuck.
        elsewhere_windy = (df[others] > corroboration_speed).any(axis=1).to_numpy()
        preserved = calm_runs & ~elsewhere_windy
        corroboration = "cross_sensor"
    else:
        preserved = calm_runs
        corroboration = "unavailable_no_other_speed_sensor"

    affected = long_runs & ~preserved
    df.loc[affected, sensor] = np.nan
    detail: dict[str, object] = {
        "consecutive_count": int(threshold),
        "calm_threshold_mps": float(calm_threshold),
        "calms_preserved": int(preserved.sum()),
        "calm_corroboration": corroboration,
        "corroborating_sensors": others,
    }
    if int(preserved.sum()) and corroboration == "unavailable_no_other_speed_sensor":
        detail["warning"] = (
            f"{int(preserved.sum()):,} records in long runs at or below "
            f"{calm_threshold:g} m/s were preserved as possible calms because no other "
            "wind-speed sensor was available to confirm the channel was stuck. Map a second "
            "speed sensor to let this rule tell a frozen anemometer from a real calm."
        )
    return int(affected.sum()), detail


def _sector_from_centre(centre_deg: float, width_deg: float) -> list[float]:
    """Return an inclusive [start, end] bearing pair spanning *width_deg* about *centre_deg*."""
    half = float(width_deg) / 2.0
    return [(float(centre_deg) - half) % 360.0, (float(centre_deg) + half) % 360.0]


def _measured_shadow_sectors(state: SessionState, sensor: str) -> list[float] | None:
    """Return the sector the mast-effect diagnostic measured for *sensor*, if it found one.

    ``compute_mast_effects`` already measures which 22.5-degree bins are shadowed, on both
    sides of the comparison pair and with a 50-record minimum.  It was the same
    "computed, displayed, discarded" pattern as the measured IAV until this call.  The
    flagged bins are merged into the single contiguous span this rule can express; a
    non-contiguous result is rejected rather than silently widened to cover the gap.
    """
    from server.tools.diagnostics import COMPASS_16, _compute_mast_effects

    try:
        effects = _compute_mast_effects(state)
    except (ValueError, KeyError):
        return None
    labels: list[str] = []
    if effects.get("sensor_a") == sensor:
        labels = [str(item) for item in effects.get("affected_sectors_a", [])]
    elif effects.get("sensor_b") == sensor:
        labels = [str(item) for item in effects.get("affected_sectors_b", [])]
    indices = sorted(COMPASS_16.index(label) for label in labels if label in COMPASS_16)
    if not indices:
        return None
    # Merge across north by rotating so the run starts at the first gap.
    ordered = indices
    if len(indices) > 1:
        gaps = [i for i in range(len(indices)) if (indices[i] - indices[i - 1]) % 16 != 1]
        if len(gaps) > 1:
            return None
        if gaps:
            ordered = indices[gaps[0]:] + indices[: gaps[0]]
    return [(ordered[0] * 22.5 - 11.25) % 360.0, (ordered[-1] * 22.5 + 11.25) % 360.0]


def _resolve_shadow_sector(
    state: SessionState,
    sensor: str,
    params: dict[str, object],
) -> tuple[float, float, dict[str, object]]:
    """Choose the tower-shadow sector, preferring measured or recorded geometry over a guess.

    The old default of ``[170, 190]`` is a 20-degree window on an arbitrary bearing, where a
    lattice tower shadows roughly +/-35 degrees behind the boom — about a third of the
    affected width, centred on nothing in particular (F-71).  Two better sources already
    exist in the session and were simply not consulted: the boom orientation recorded per
    measurement point in IEA Task 43, and the sectors ``compute_mast_effects`` measures.

    Preference order: an explicit caller sector, then boom orientation, then the measured
    sectors, then the legacy guess — which is still available, but now says what it is.
    """
    width = _float_param(params, "sector_width_deg", TOWER_SHADOW_DEFAULT_WIDTH_DEG)
    if "exclude_sectors" in params:
        start_deg, end_deg = _sector_bounds(params)
        return start_deg, end_deg, {"sector_basis": "caller"}

    metadata = state.sensor_inventory.get(sensor)
    boom = metadata.get("boom_orientation_deg") if isinstance(metadata, dict) else None
    if isinstance(boom, (int, float)):
        # The tower sits directly opposite the boom, so the shadow is centred 180 deg away.
        start_deg, end_deg = _sector_from_centre(float(boom) + 180.0, width)
        return start_deg, end_deg, {
            "sector_basis": "boom_orientation",
            "boom_orientation_deg": float(boom),
            "sector_width_deg": float(width),
        }

    measured = _measured_shadow_sectors(state, sensor)
    if measured is not None:
        return measured[0], measured[1], {
            "sector_basis": "measured_mast_effect",
            "sector_width_deg": round((measured[1] - measured[0]) % 360.0, 2),
        }

    start_deg, end_deg = TOWER_SHADOW_LEGACY_SECTOR
    return start_deg, end_deg, {
        "sector_basis": "default_guess",
        "sector_width_deg": float(end_deg - start_deg),
        "warning": (
            f"No boom orientation is recorded for '{sensor}' and the mast-effect diagnostic "
            "flagged no sector for it, so the legacy 20-degree window at 170-190 deg was used. "
            "A lattice tower shadows roughly +/-35 degrees behind the boom, so this is about a "
            "third of the affected width on an arbitrary bearing. Record boom_orientation_deg "
            "in the datamodel, run compute_mast_effects, or pass exclude_sectors explicitly."
        ),
    }


def _apply_tower_shadow(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> tuple[int, dict[str, object]]:
    """Remove tower-shadow sectors using the paired direction sensor at the same measurement height."""
    sensor_map = _mapping_for_sensor(state, sensor)
    direction_col = sensor_map.get("dir_col")
    if direction_col not in df.columns:
        raise ValueError("tower_shadow requires a paired direction column in session.sensor_mapping")
    start_deg, end_deg, detail = _resolve_shadow_sector(state, sensor, params)
    directions = df[direction_col].to_numpy(dtype=float)
    sector_mask = (
        (directions >= start_deg) & (directions <= end_deg)
        if start_deg <= end_deg
        else (directions >= start_deg) | (directions <= end_deg)
    )
    affected = mask & sector_mask & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    detail["exclude_sectors"] = [round(start_deg, 2), round(end_deg, 2)]
    return int(affected.sum()), detail


def _apply_timestamp_gap_fill(state: SessionState, df: pd.DataFrame, start_date: str, end_date: str) -> int:
    """Insert missing timestamps at the inferred base frequency to expose data gaps explicitly."""
    timestep_minutes = detect_timestep_minutes(df)
    full_index = pd.date_range(df.index.min(), df.index.max(), freq=f"{timestep_minutes}min")
    before_index = df.index
    state.timeseries_df = df.reindex(full_index)
    inserted = state.timeseries_df.index.difference(before_index)
    inserted_mask = (
        _date_mask(pd.DatetimeIndex(inserted), start_date, end_date)
        if len(inserted)
        else np.array([], dtype=bool)
    )
    return int(inserted_mask.sum())


def _apply_custom_period_exclude(df: pd.DataFrame, sensor: str, mask: np.ndarray) -> int:
    """Set a sensor to NaN over a user-defined inclusive date range."""
    affected = mask & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


_COMPARE_OPS = {
    ast.Lt: "__lt__",
    ast.LtE: "__le__",
    ast.Gt: "__gt__",
    ast.GtE: "__ge__",
    ast.Eq: "__eq__",
    ast.NotEq: "__ne__",
}


def _eval_expression_node(node: ast.AST, df: pd.DataFrame) -> pd.Series:
    """Recursively evaluate a validated cleaning-filter AST node into a boolean Series."""
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ValueError("Only 'and' / 'or' boolean operators are allowed")
        operands = [_eval_expression_node(value, df) for value in node.values]
        result = operands[0]
        for operand in operands[1:]:
            result = (result & operand) if isinstance(node.op, ast.And) else (result | operand)
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return ~_eval_expression_node(node.operand, df)
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("Chained comparisons are not allowed in cleaning filters")
        left = node.left
        right = node.comparators[0]
        op = node.ops[0]
        # Column must be on one side, a numeric constant on the other.
        if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
            column, value = left.id, right.value
        elif isinstance(right, ast.Name) and isinstance(left, ast.Constant):
            column, value = right.id, left.value
            op = _flip_compare_op(op)
        else:
            raise ValueError("Each comparison must be '<column> <op> <number>'")
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found in loaded timeseries")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("Cleaning filter comparison value must be a number")
        method = _COMPARE_OPS.get(type(op))
        if method is None:
            raise ValueError("Only <, <=, >, >=, ==, != comparisons are allowed")
        series = pd.to_numeric(df[column], errors="coerce")
        result = getattr(series, method)(value)
        return result.fillna(False)
    raise ValueError("Cleaning filters may only use column comparisons combined with and/or/not")


def _flip_compare_op(op: ast.cmpop) -> ast.cmpop:
    """Mirror a comparison operator when the constant is on the left side."""
    flip = {ast.Lt: ast.Gt, ast.LtE: ast.GtE, ast.Gt: ast.Lt, ast.GtE: ast.LtE, ast.Eq: ast.Eq, ast.NotEq: ast.NotEq}
    return flip[type(op)]()


def _expression_mask(df: pd.DataFrame, expression: str) -> np.ndarray:
    """Parse and evaluate a Windographer-style boolean filter into a row mask."""
    text = (expression or "").strip()
    if not text:
        raise ValueError("expression_filter requires a non-empty 'expression' param")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid cleaning filter expression: {exc.msg}") from exc
    mask = _eval_expression_node(tree.body, df)
    return mask.to_numpy(dtype=bool)


def _apply_expression_filter(
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> int:
    """Flag-and-remove rows matching a boolean expression (AND/OR combinations) as NA."""
    expression = params.get("expression", "")
    if not isinstance(expression, str):
        raise ValueError("expression_filter 'expression' param must be a string")
    expression_mask = _expression_mask(df, expression)
    affected = mask & expression_mask & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_rule(
    state: SessionState,
    rule_type: str,
    sensor: str,
    params: dict[str, object],
    start_date: str,
    end_date: str,
) -> tuple[int, dict[str, object]]:
    """Dispatch a cleaning rule, returning records affected plus any rule-specific detail."""
    df = _require_timeseries(state)
    if rule_type != "timestamp_gap_fill" and sensor not in df.columns:
        raise ValueError(f"Sensor column '{sensor}' not found in loaded timeseries")
    mask = _date_mask(pd.DatetimeIndex(df.index), start_date, end_date)
    if rule_type == "range_check":
        return _apply_range_check(state, df, sensor, mask, params)
    if rule_type == "icing_filter":
        return _apply_icing_filter(state, df, sensor, mask, params)
    if rule_type == "stuck_sensor":
        return _apply_stuck_sensor(state, df, sensor, mask, params)
    if rule_type == "tower_shadow":
        return _apply_tower_shadow(state, df, sensor, mask, params)
    if rule_type == "expression_filter":
        return _apply_expression_filter(df, sensor, mask, params), {}
    if rule_type == "timestamp_gap_fill":
        return _apply_timestamp_gap_fill(state, df, start_date, end_date), {}
    return _apply_custom_period_exclude(df, sensor, mask), {}


def _list_cleaning_rules(_state: SessionState) -> dict:
    """List supported cleaning rules and default parameters for the GoKaatru Phase 2 cleaning workflow."""
    rules = [
        {"name": name, "description": name.replace("_", " "), "default_params": params}
        for name, params in RULES.items()
    ]
    return {
        "rules": rules,
        # F-70: the order these are applied in changes the answer, and nothing said so.
        "order_is_material": True,
        "order_note": RULE_ORDER_NOTE,
        # F-72: recorded here so the absence is discoverable from the tool itself.
        "outlier_detection": "none",
        "outlier_note": (
            "No outlier or spike detection exists. range_check bounds by sensor type, "
            "stuck_sensor catches frozen channels and icing_filter catches iced ones, but a "
            "single wild excursion inside the physical bounds passes through untouched."
        ),
    }


def _apply_cleaning_rule(
    state: SessionState,
    rule_type: str,
    sensor: str,
    params: str,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Apply one named cleaning rule to the active timeseries and log the operation for undo."""
    if rule_type not in RULES:
        raise ValueError(f"Unknown cleaning rule '{rule_type}'")
    parsed = _parse_params(params)
    # Captured before the rule runs, so it names what this rule actually saw (F-70).
    preceding = [
        {"sequence": index + 1, "rule_type": str(item.get("rule_type")), "sensor": str(item.get("sensor"))}
        for index, item in enumerate(state.cleaning_log)
    ]
    records_affected, detail = _apply_rule(state, rule_type, sensor, parsed, start_date, end_date)
    # The working data just changed, so anything already derived from it is stale (F-11).
    state.bump_data_version()
    sequence = len(state.cleaning_log) + 1
    entry: dict[str, object] = {
        "rule_type": rule_type,
        "sensor": sensor,
        "sequence": sequence,
        "records_affected": records_affected,
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": parsed,
        "start_date": start_date,
        "end_date": end_date,
        # The log must record the bounds actually applied, not just the params
        # asked for, or it implies a check that may not have happened (D16).
        **detail,
    }
    state.cleaning_log.append(entry)
    # Rules on the same sensor are the ones that can have changed what this rule saw.
    same_sensor = [item for item in preceding if item["sensor"] == sensor]
    order_dependence: dict[str, object] = {
        "sequence": sequence,
        "order_is_material": True,
        "note": RULE_ORDER_NOTE,
        "applied_before_on_this_sensor": same_sensor,
    }
    if same_sensor:
        names = ", ".join(sorted({str(item["rule_type"]) for item in same_sensor}))
        order_dependence["warning"] = (
            f"'{rule_type}' saw data already modified by {names} on '{sensor}'. Applying the "
            "same rules in a different order can give a different result."
        )
    return {
        "status": "ok",
        "rule": rule_type,
        "sensor": sensor,
        "records_affected": records_affected,
        "order_dependence": order_dependence,
        **detail,
    }


def _get_cleaning_log(state: SessionState) -> dict:
    """Return the recorded cleaning operations applied to the active session timeseries."""
    return {
        "entries": [entry.copy() for entry in state.cleaning_log],
        # The log has always been reproducible; what was missing is that the order it
        # records is part of the method rather than a presentation detail (F-70).
        "order_is_material": True,
        "order_note": RULE_ORDER_NOTE,
    }


def _undo_cleaning_rule(state: SessionState, entry_index: int) -> dict:
    """Restore raw data and replay all cleaning steps except the selected log entry."""
    if state.raw_timeseries_df is None:
        raise ValueError("Raw timeseries backup is not available")
    if entry_index < 0 or entry_index >= len(state.cleaning_log):
        raise ValueError(f"Cleaning log entry_index out of range: {entry_index}")
    target = state.cleaning_log[entry_index]
    if not target.get("undoable", True):
        raise ValueError(
            f"Cleaning log entry {entry_index} ('{target.get('rule_type')}') records upstream "
            "processing that GoKaatru did not perform and cannot reverse. Re-import without the "
            "corresponding flag to obtain the unprocessed series."
        )
    retained = [entry.copy() for idx, entry in enumerate(state.cleaning_log) if idx != entry_index]
    # Provenance entries describe work done before GoKaatru saw the data; they are
    # carried through untouched rather than replayed (D27).
    provenance = [entry for entry in retained if not entry.get("undoable", True)]
    replayable = [entry for entry in retained if entry.get("undoable", True)]
    replay_state = SessionState()
    replay_state.timeseries_df = state.raw_timeseries_df.copy(deep=True)
    replay_state.raw_timeseries_df = state.raw_timeseries_df.copy(deep=True)
    replay_state.sensor_mapping = copy.deepcopy(state.sensor_mapping)
    # range_check resolves its bounds from the sensor type (D16), so the replay
    # must see the same inventory or it would silently become a no-op.
    replay_state.sensor_inventory = copy.deepcopy(state.sensor_inventory)
    replay_state.cleaning_log = []
    for entry in replayable:
        params = json.dumps(entry.get("params", {}))
        _apply_cleaning_rule(
            replay_state,
            str(entry["rule_type"]),
            str(entry["sensor"]),
            params,
            str(entry.get("start_date", "")),
            str(entry.get("end_date", "")),
        )
    # Undo rebuilds the working frame from raw, which drops any column a later stage wrote
    # into it — the hub-height series and shear_coefficient among them (F-12).  Bumping the
    # data version marks everything derived from the old frame as stale, so an LTC or
    # ensemble that depended on a now-deleted column is flagged rather than left looking
    # current.
    dropped_columns = [
        str(column)
        for column in state.timeseries_df.columns
        if column not in replay_state.timeseries_df.columns
    ] if state.timeseries_df is not None else []
    state.timeseries_df = replay_state.timeseries_df
    state.cleaning_log = provenance + replay_state.cleaning_log
    state.bump_data_version()
    result: dict[str, object] = {
        "status": "ok",
        "remaining_rules": len(replay_state.cleaning_log),
        "dropped_columns": dropped_columns,
        **state.staleness_report(),
    }
    if dropped_columns:
        result["warning"] = (
            f"Undo rebuilt the working data from the raw import, which removed "
            f"{len(dropped_columns)} derived column(s): {', '.join(dropped_columns)}. "
            "Anything computed from them — hub-height extrapolation, LTC, ensemble, "
            "uncertainty — must be re-run."
        )
    return result


@mcp.tool()
def list_cleaning_rules() -> dict:
    """List supported cleaning rules and default parameters for the GoKaatru Phase 2 cleaning workflow."""
    return _list_cleaning_rules(session)


@mcp.tool()
def apply_cleaning_rule(rule_type: str, sensor: str, params: str, start_date: str = "", end_date: str = "") -> dict:
    """Apply one named cleaning rule to the active timeseries and log the operation for undo."""
    return _apply_cleaning_rule(session, rule_type, sensor, params, start_date, end_date)


@mcp.tool()
def get_cleaning_log() -> dict:
    """Return the recorded cleaning operations applied to the active session timeseries."""
    return _get_cleaning_log(session)


@mcp.tool()
def undo_cleaning_rule(entry_index: int) -> dict:
    """Restore raw data and replay all cleaning steps except the selected log entry."""
    return _undo_cleaning_rule(session, entry_index)
