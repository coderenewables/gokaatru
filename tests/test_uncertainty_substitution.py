"""Folding a sweep's spread into the uncertainty budget (design doc §8.1, finding F9).

The substitution lived only in the browser (`SubstitutionExplainer.tsx`), so the server's
totals never carried it and the Copilot could not see it. It also measured the wrong thing:
the swing of `total_uncertainty_pct` across an axis, which is a spread of the uncertainty
figure, not of the answer. By owner decision (2026-11-17) the empirical term for an axis is
the sample standard deviation of the long-term mean speed across that axis's level means,
as a percentage of the sweep's mean speed, and an axis with fewer than three levels cannot
displace or add anything.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.sweep_analysis import MIN_LEVELS_FOR_EMPIRICAL, uncertainty_substitution
from tests import oracles

U_MEAS, U_VERT, U_MCP, U_FUTURE = 2.0, 1.5, 2.5, 1.34


def _row(config_hash: str, speed: float, **overrides) -> dict:
    row = {
        "config_hash": config_hash,
        "status": "ok",
        "admissible": True,
        "shear_fit_policy": "nearest_2",
        "reference_policy": "nearest_2",
        "shear_model": "power_law_mean",
        "reference_source": "era5",
        "ltc_algorithm": "variance_ratio",
        "long_term_mean_speed_mps": speed,
        "u_measurement_pct": U_MEAS,
        "u_vertical_pct": U_VERT,
        "u_mcp_pct": U_MCP,
        "u_future_pct": U_FUTURE,
    }
    row.update(overrides)
    return row


def _component(result: dict, name: str) -> dict:
    return next(entry for entry in result["components"] if entry["component"] == name)


def _ltc_rows(speeds: dict[str, list[float]]) -> list[dict]:
    rows, n = [], 0
    for algorithm, values in speeds.items():
        for value in values:
            n += 1
            rows.append(_row(f"h{n}", value, ltc_algorithm=algorithm))
    return rows


def test_min_levels_is_three():
    assert MIN_LEVELS_FOR_EMPIRICAL == 3


def test_ltc_spread_matches_the_oracle_and_displaces_a_smaller_parametric_term():
    # Level means 7.0, 8.0, 9.0, 10.0 with one level carrying two scenarios.
    rows = _ltc_rows(
        {"variance_ratio": [7.0], "linear_least_squares": [8.0], "speedsort": [9.0],
         "xgboost": [9.5, 10.5]}
    )
    result = uncertainty_substitution(rows)
    mcp = _component(result, "mcp")
    expected = oracles.level_mean_spread_pct(
        [row["ltc_algorithm"] for row in rows], [row["long_term_mean_speed_mps"] for row in rows]
    )
    assert mcp["empirical_pct"] == pytest.approx(expected, rel=1e-12)
    assert expected > U_MCP
    assert mcp["basis"] == "empirical"
    assert mcp["applied_pct"] == pytest.approx(expected, rel=1e-12)

    substituted = math.sqrt(U_MEAS**2 + U_VERT**2 + expected**2 + U_FUTURE**2)
    parametric = math.sqrt(U_MEAS**2 + U_VERT**2 + U_MCP**2 + U_FUTURE**2)
    totals = result["totals"]
    assert totals["scenarios"] == len(rows)
    assert totals["substituted"]["median"] == pytest.approx(substituted, rel=1e-12)
    assert totals["parametric"]["median"] == pytest.approx(parametric, rel=1e-12)
    assert totals["raised"] == len(rows)


def test_a_spread_below_the_parametric_term_leaves_the_total_unchanged():
    rows = _ltc_rows({"variance_ratio": [8.00], "linear_least_squares": [8.01], "speedsort": [8.02]})
    result = uncertainty_substitution(rows)
    mcp = _component(result, "mcp")
    assert 0.0 < mcp["empirical_pct"] < U_MCP
    assert mcp["basis"] == "parametric"
    assert mcp["applied_pct"] == pytest.approx(U_MCP)
    assert result["totals"]["raised"] == 0
    assert result["totals"]["substituted"]["median"] == pytest.approx(
        result["totals"]["parametric"]["median"]
    )


def test_an_axis_with_two_levels_is_under_resolved_and_displaces_nothing():
    rows = _ltc_rows({"variance_ratio": [6.0], "linear_least_squares": [12.0]})
    result = uncertainty_substitution(rows)
    mcp = _component(result, "mcp")
    assert mcp["empirical_pct"] is None
    assert mcp["axes_under_resolved"] == ["ltc_algorithm"]
    assert mcp["basis"] == "parametric"
    assert result["axes"]["ltc_algorithm"]["levels"] == 2
    assert result["axes"]["ltc_algorithm"]["spread_pct"] is None
    assert result["totals"]["raised"] == 0


def test_an_axis_never_varied_is_not_reported_as_under_resolved():
    rows = _ltc_rows({"variance_ratio": [7.0], "linear_least_squares": [8.0], "speedsort": [9.0]})
    vertical = _component(uncertainty_substitution(rows), "vertical_extrapolation")
    assert vertical["empirical_pct"] is None
    assert vertical["axes_under_resolved"] == []
    assert vertical["axes_not_varied"] == ["shear_fit_policy", "reference_policy", "shear_model"]


def test_a_component_with_several_resolved_axes_combines_them_in_quadrature():
    rows, n = [], 0
    for model, offset in (("power_law_mean", 0.0), ("power_law_median", 0.6), ("log_law", 1.2)):
        for policy, shift in (("nearest_2", 0.0), ("widest_lever", 0.3), ("redundant_boom", 0.9)):
            n += 1
            rows.append(
                _row(f"h{n}", 8.0 + offset + shift, shear_model=model, shear_fit_policy=policy)
            )
    result = uncertainty_substitution(rows)
    speeds = [row["long_term_mean_speed_mps"] for row in rows]
    by_model = oracles.level_mean_spread_pct([row["shear_model"] for row in rows], speeds)
    by_policy = oracles.level_mean_spread_pct([row["shear_fit_policy"] for row in rows], speeds)
    vertical = _component(result, "vertical_extrapolation")
    assert vertical["axes_used"] == ["shear_fit_policy", "shear_model"]
    assert vertical["empirical_pct"] == pytest.approx(math.hypot(by_model, by_policy), rel=1e-12)


def test_reference_source_spread_is_added_when_resolved():
    rows = [
        _row("h1", 7.8, reference_source="era5"),
        _row("h2", 8.4, reference_source="merra2"),
        _row("h3", 8.1, reference_source="analyst_series"),
    ]
    result = uncertainty_substitution(rows)
    reference = _component(result, "long_term_reference")
    expected = oracles.level_mean_spread_pct(
        [row["reference_source"] for row in rows], [row["long_term_mean_speed_mps"] for row in rows]
    )
    assert reference["treatment"] == "add"
    assert reference["parametric_mean_pct"] is None
    assert reference["basis"] == "added"
    assert reference["applied_pct"] == pytest.approx(expected, rel=1e-12)
    added = math.sqrt(U_MEAS**2 + U_VERT**2 + U_MCP**2 + U_FUTURE**2 + expected**2)
    assert result["totals"]["substituted"]["median"] == pytest.approx(added, rel=1e-12)


def test_two_reference_sources_cannot_add_a_term():
    rows = [_row("h1", 7.8, reference_source="era5"), _row("h2", 8.4, reference_source="merra2")]
    reference = _component(uncertainty_substitution(rows), "long_term_reference")
    assert reference["applied_pct"] is None
    assert reference["basis"] == "not_resolved"
    assert reference["axes_under_resolved"] == ["reference_source"]


def test_rows_without_every_parametric_component_are_counted_not_guessed():
    rows = _ltc_rows({"variance_ratio": [7.0], "linear_least_squares": [8.0], "speedsort": [9.0]})
    rows[0]["u_future_pct"] = None
    totals = uncertainty_substitution(rows)["totals"]
    assert totals["scenarios"] == 2
    assert totals["scenarios_missing_components"] == 1


def test_too_few_rows_is_reported_as_unavailable():
    result = uncertainty_substitution([_row("h1", 8.0)])
    assert result["available"] is False
    assert "reason" in result


def _persisted(workspace: Path) -> None:
    root = workspace / "sweeps" / "sw01"
    root.mkdir(parents=True, exist_ok=True)
    rows = _ltc_rows(
        {"variance_ratio": [7.0], "linear_least_squares": [8.0], "speedsort": [9.0], "xgboost": [10.0]}
    )
    (root / "manifest.json").write_text(json.dumps({"sweep_id": "sw01"}), encoding="utf-8")
    (root / "results.json").write_text(json.dumps(rows), encoding="utf-8")


def test_the_spread_tool_carries_the_substitution_for_the_callers_selection(tmp_path: Path):
    from server.state.session import SessionState
    from server.tools.sweep_analysis import _sweep_spread

    state = SessionState()
    state.reset()
    state.workspace_dir = tmp_path
    _persisted(tmp_path)

    full = _sweep_spread(state, "sw01")["uncertainty_substitution"]
    assert _component(full, "mcp")["axes_used"] == ["ltc_algorithm"]
    narrowed = _sweep_spread(state, "sw01", config_hashes=["h1", "h2"])["uncertainty_substitution"]
    assert _component(narrowed, "mcp")["axes_under_resolved"] == ["ltc_algorithm"]
