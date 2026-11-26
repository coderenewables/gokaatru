"""ltc_runs — which long-term correction runs how, and on which columns.

Moved out of ``server/api/routes/analysis.py`` (P3-7a): the sweep's long-term stage imported
them from a hand-written route module, so the engine depended on the layer that Phase 3
retires. Not an operation module: these dispatch to the operations' own functions.
"""
from __future__ import annotations

from collections.abc import Callable

from server.state.session import SessionState
from server.tools.extrapolation import _hub_column_name
from server.tools.ltc import (
    _run_ltc_linear_least_squares,
    _run_ltc_speedsort,
    _run_ltc_total_least_squares,
    _run_ltc_variance_ratio,
)
from server.tools.ltc_ml import _run_ltc_xgboost

LTC_ALGORITHMS: dict[str, Callable[..., dict]] = {
    "linear_least_squares": _run_ltc_linear_least_squares,
    "total_least_squares": _run_ltc_total_least_squares,
    "speedsort": _run_ltc_speedsort,
    "variance_ratio": _run_ltc_variance_ratio,
    "xgboost": _run_ltc_xgboost,
}

#: Algorithms that take direction columns as well as speed columns. Three call sites used
#: to test the algorithm name inline and one of them drifted: the sweep passed direction
#: only to XGBoost, so SpeedSort ran direction-agnostically in every sweep ever executed —
#: losing the per-sector transfer functions that are the whole reason to choose it, while
#: XGBoost kept its directional feature. Axis D was comparing them on unequal terms.
DIRECTIONAL_LTC_ALGORITHMS: frozenset[str] = frozenset({"speedsort", "xgboost"})


def run_ltc_algorithm(
    state: SessionState,
    algorithm: str,
    runner: Callable[..., dict],
    short_col: str,
    long_col: str,
    short_dir_col: str = "",
    long_dir_col: str = "",
) -> dict:
    """Call one LTC algorithm with the arguments its signature actually accepts."""
    if algorithm in DIRECTIONAL_LTC_ALGORITHMS:
        return runner(state, short_col, long_col, short_dir_col, long_dir_col)
    return runner(state, short_col, long_col)


def resolve_ltc_columns(state: SessionState) -> tuple[str, str, str, str]:
    """Resolve the measured/reference speed and direction columns for an LTC run.

    The measured column is the **hub-height series**, because that is the height the
    corrected answer is reported at. This used to be "the highest-height speed sensor in
    ``sensor_mapping``" — a hub column is never in the mapping (extrapolation appends it
    to ``timeseries_df``), so the function could not return one at any site, and the
    extrapolation stage's output was computed and discarded. On a real 167 m campaign the
    sweep fitted every LTC on ``Spd_200m`` and published it as the hub answer: a measured
    level 2.05% high, and axes A1/A2/B unable to move any metric because everything
    downstream of them was bypassed.

    A missing hub series is refused rather than substituted (convention 1). Silently
    correcting a sensor from a different height is undetectable in every number that
    follows it, which is precisely how this survived so long.
    """
    hub_height_m = state.get_hub_height_m()
    if hub_height_m is None:
        raise ValueError(
            "Hub height is not set, so there is no hub-height series to correct. Set "
            "hub_height_m and extrapolate the measured data to it before running an LTC."
        )
    short_col = _hub_column_name(float(hub_height_m))
    if state.timeseries_df is None or short_col not in state.timeseries_df.columns:
        raise ValueError(
            f"The hub-height series '{short_col}' has not been built. Extrapolate the "
            "measured data to hub height before running an LTC — correcting a raw sensor "
            "instead reports a measurement from a different height as the hub answer, "
            "which nothing downstream can detect."
        )
    # Direction is optional and stays sensor-based: the hub series carries speed only.
    # The slot is ``dir_col``; this asked for ``direction_col``, so it returned "" at
    # every site that has ever run.
    short_dir_col = ""
    for _height, mapping in sorted(state.sensor_mapping.items(), reverse=True):
        if isinstance(mapping.get("dir_col"), str):
            short_dir_col = str(mapping["dir_col"])
            break
    # Resolved from the active reference source rather than hardcoded to ERA5's 100 m
    # columns: MERRA-2 is served at 50 m, so a fixed `Spd_100m` made it impossible to
    # run an LTC against it at all (design doc §6.3).
    descriptor = state.get_active_reference_source()
    return short_col, descriptor.speed_col, short_dir_col, descriptor.dir_col
