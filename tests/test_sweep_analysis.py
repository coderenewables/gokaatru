"""Variance decomposition (design doc §7.9), moved from the browser into the server.

The decomposition lived only in `frontend/src/lib/sweepAnalysis.ts`, so the one question
an analyst most wants answered about a sweep — *which choice actually moved the number* —
was computable only inside the Interrogate page. The Copilot had no tool that could read a
sweep at all, and when asked about a spread it confabulated an explanation from the live
session state it could see. These tests cover the Python implementation that both the
HTTP route and the MCP tool now call; the TypeScript copy is deleted, so there is one
implementation and nothing to drift.

The cases mirror the TypeScript suite they replace.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.sweep_analysis import AXIS_COLUMNS, decompose_variance
from server.state.session import SessionState


def _row(config_hash: str, **overrides) -> dict:
    base = {
        "config_hash": config_hash,
        "fixed_prefix_hash": "prefix",
        "status": "ok",
        "admissible": True,
        "shear_fit_policy": "nearest_2",
        "reference_policy": "nearest_2",
        "shear_model": "power_law_mean",
        "reference_source": "era5",
        "ltc_algorithm": "variance_ratio",
        "long_term_mean_speed_mps": 8.0,
    }
    base.update(overrides)
    return base


class TestDecomposition:
    def test_it_attributes_the_spread_to_the_axis_that_moves_the_answer(self) -> None:
        rows = [
            _row("a", ltc_algorithm="variance_ratio", long_term_mean_speed_mps=8),
            _row("b", ltc_algorithm="variance_ratio", long_term_mean_speed_mps=8),
            _row("c", ltc_algorithm="linear_least_squares", long_term_mean_speed_mps=10),
            _row("d", ltc_algorithm="linear_least_squares", long_term_mean_speed_mps=10),
        ]
        contributions = decompose_variance(rows, "long_term_mean_speed_mps")
        assert contributions[0]["axis"] == "ltc_algorithm"
        assert contributions[0]["share"] == pytest.approx(1.0, abs=1e-9)
        assert contributions[0]["swing"] == pytest.approx(2.0, abs=1e-9)

    def test_a_single_level_axis_gets_no_share(self) -> None:
        """Its level mean *is* the grand mean, so its between-group sum of squares is zero
        by construction. Reported as 0.0% it reads like 'this choice does not matter',
        when the truth is 'this choice was never varied' — `levels` is what distinguishes
        them, so it travels with the share."""
        rows = [
            _row("a", long_term_mean_speed_mps=8),
            _row("b", long_term_mean_speed_mps=9),
        ]
        shear = next(
            entry for entry in decompose_variance(rows, "long_term_mean_speed_mps")
            if entry["axis"] == "shear_model"
        )
        assert shear["levels"] == 1
        assert shear["share"] == 0.0
        assert shear["swing"] == 0.0

    def test_nothing_to_decompose_returns_nothing(self) -> None:
        assert decompose_variance([_row("a")], "long_term_mean_speed_mps") == []

    def test_level_means_carry_the_count_behind_each(self) -> None:
        rows = [
            _row("a", reference_source="era5", long_term_mean_speed_mps=8),
            _row("b", reference_source="merra2", long_term_mean_speed_mps=9),
            _row("c", reference_source="merra2", long_term_mean_speed_mps=11),
        ]
        entry = next(
            item for item in decompose_variance(rows, "long_term_mean_speed_mps")
            if item["axis"] == "reference_source"
        )
        merra = next(level for level in entry["level_means"] if level["level"] == "merra2")
        assert merra["mean"] == pytest.approx(10.0)
        assert merra["count"] == 2

    def test_shares_are_normalised_and_ordered(self) -> None:
        rows = [
            _row("a", ltc_algorithm="variance_ratio", shear_model="power_law_mean", long_term_mean_speed_mps=8),
            _row("b", ltc_algorithm="linear_least_squares", shear_model="power_law_mean", long_term_mean_speed_mps=10),
            _row("c", ltc_algorithm="variance_ratio", shear_model="log_law_mean", long_term_mean_speed_mps=8.2),
            _row("d", ltc_algorithm="linear_least_squares", shear_model="log_law_mean", long_term_mean_speed_mps=10.2),
        ]
        contributions = decompose_variance(rows, "long_term_mean_speed_mps")
        assert sum(entry["share"] for entry in contributions) == pytest.approx(1.0, abs=1e-9)
        shares = [entry["share"] for entry in contributions]
        assert shares == sorted(shares, reverse=True)

    def test_every_axis_is_reported_even_when_it_contributes_nothing(self) -> None:
        contributions = decompose_variance(
            [_row("a", long_term_mean_speed_mps=8), _row("b", long_term_mean_speed_mps=9)],
            "long_term_mean_speed_mps",
        )
        assert {entry["axis"] for entry in contributions} == set(AXIS_COLUMNS)

    def test_rows_missing_the_metric_are_excluded_not_counted_as_zero(self) -> None:
        rows = [
            _row("a", long_term_mean_speed_mps=8),
            _row("b", long_term_mean_speed_mps=10),
            _row("c", long_term_mean_speed_mps=None),
        ]
        contributions = decompose_variance(rows, "long_term_mean_speed_mps")
        total = sum(level["count"] for level in contributions[0]["level_means"])
        assert total == 2


class TestSweepPathConfinement:
    """A sweep id is now reachable from the chat tool surface, so it addresses a path."""

    def test_a_traversing_sweep_id_is_refused(self, tmp_path: Path) -> None:
        from server.core.sweep import load_sweep

        state = SessionState()
        state.reset()
        state.workspace_dir = tmp_path

        # A readable manifest planted outside the session, as a sibling session would be.
        outside = tmp_path.parent / "other_session" / "sweeps" / "victim"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "manifest.json").write_text(json.dumps({"sweep_id": "victim"}), encoding="utf-8")
        (outside / "results.json").write_text("[]", encoding="utf-8")

        with pytest.raises(ValueError):
            load_sweep(state, "../../other_session/sweeps/victim")

    @pytest.mark.parametrize("sweep_id", ["..", "../x", "a/../../b", "/etc"])
    def test_ids_that_leave_the_sweeps_directory_are_refused(self, tmp_path: Path, sweep_id: str) -> None:
        from server.core.sweep import load_sweep

        state = SessionState()
        state.reset()
        state.workspace_dir = tmp_path
        with pytest.raises(ValueError):
            load_sweep(state, sweep_id)


def _persisted_sweep(workspace: Path, sweep_id: str = "sw01") -> None:
    """Write a two-axis sweep to disk: LTC moves the metric, shear-fit never varied."""
    root = workspace / "sweeps" / sweep_id
    (root).mkdir(parents=True, exist_ok=True)
    rows = [
        _row("h1", ltc_algorithm="variance_ratio", long_term_mean_speed_mps=8.0),
        _row("h2", ltc_algorithm="linear_least_squares", long_term_mean_speed_mps=10.0),
        _row("h3", ltc_algorithm="speedsort", long_term_mean_speed_mps=9.0),
        _row("h4", ltc_algorithm="xgboost", long_term_mean_speed_mps=11.0,
             admissible=False, failed_gates="roughness_clipping"),
    ]
    (root / "manifest.json").write_text(
        json.dumps({"sweep_id": sweep_id, "fixed_prefix_hash": "abc123"}), encoding="utf-8"
    )
    (root / "results.json").write_text(json.dumps(rows), encoding="utf-8")


class TestSweepReadingSurface:
    """Dual interface — the route and the tool reach the same helper (root CLAUDE.md)."""

    @pytest.fixture
    def client(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from server.api.deps import get_session_manager
        from server.api.main import create_app
        from server.state.manager import SessionManager

        manager = SessionManager(base_dir=tmp_path / "sessions")
        app = create_app()
        app.dependency_overrides[get_session_manager] = lambda: manager
        with TestClient(app) as test_client:
            yield test_client, manager
        app.dependency_overrides.clear()

    def test_the_spread_route_names_the_axis_that_moved_the_metric(self, client) -> None:
        test_client, manager = client
        session_id = test_client.post("/api/sessions").json()["session_id"]
        _persisted_sweep(manager.get_session(session_id).workspace_dir)

        response = test_client.post(
            f"/api/sessions/{session_id}/sweep/sw01/spread",
            json={"metric": "long_term_mean_speed_mps"},
            headers={"X-GoKaatru-Session": session_id},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["contributions"][0]["axis"] == "ltc_algorithm"
        assert payload["scenarios_analysed"] == 3  # the inadmissible row is excluded
        assert "shear_fit_policy" in payload["single_level_axes"]

    def test_the_route_restricts_to_the_callers_own_row_selection(self, client) -> None:
        """Interrogate filters client-side; re-implementing that filter here would be a
        second copy of logic that has to agree."""
        test_client, manager = client
        session_id = test_client.post("/api/sessions").json()["session_id"]
        _persisted_sweep(manager.get_session(session_id).workspace_dir)

        response = test_client.post(
            f"/api/sessions/{session_id}/sweep/sw01/spread",
            json={"metric": "long_term_mean_speed_mps", "config_hashes": ["h1", "h2"]},
            headers={"X-GoKaatru-Session": session_id},
        )
        assert response.json()["scenarios_analysed"] == 2

    def test_an_unknown_sweep_is_a_bad_request_not_a_crash(self, client) -> None:
        test_client, _ = client
        session_id = test_client.post("/api/sessions").json()["session_id"]
        response = test_client.post(
            f"/api/sessions/{session_id}/sweep/nope/spread",
            json={"metric": "long_term_mean_speed_mps"},
            headers={"X-GoKaatru-Session": session_id},
        )
        assert response.status_code == 400

    def test_the_summary_reports_which_axes_the_gates_collapsed(self, tmp_path: Path) -> None:
        """The finding behind the whole exercise: an axis showing 0% may never have been
        varied among the admissible set, which is not the same as not mattering."""
        from server.tools.sweep_analysis import _sweep_summary

        state = SessionState()
        state.reset()
        state.workspace_dir = tmp_path
        _persisted_sweep(tmp_path)

        summary = _sweep_summary(state, "sw01")
        assert summary["scenarios_total"] == 4
        assert summary["scenarios_admissible"] == 3
        assert summary["axes"]["shear_fit_policy"]["collapsed_to_one_level"] is True
        assert summary["axes"]["ltc_algorithm"]["collapsed_to_one_level"] is False
        assert summary["gate_failures"] == {"roughness_clipping": 1}
        # xgboost was designed into the sweep and rejected by a gate — the difference
        # between "designed" and "admissible" is exactly what a 0% share hides.
        assert "xgboost" in summary["axes"]["ltc_algorithm"]["levels_designed"]
        assert "xgboost" not in summary["axes"]["ltc_algorithm"]["levels_admissible"]


class TestDuplicateLevels:
    """D3 follow-up: a level whose every leaf was a duplicate has no rows of its own, so
    without this it reads as never designed and its axis as 'not varied'."""

    def _dup(self, same_as: str, fit: str = "nearest_2", ref: str = "redundant_boom") -> dict:
        return {"shear_fit_policy": fit, "reference_policy": ref, "same_as": same_as}

    def test_a_skipped_level_names_the_level_whose_results_it_shares(self) -> None:
        from server.core.sweep_analysis import duplicate_levels

        rows = [
            _row("h1", reference_policy="availability_90"),
            _row("h2", reference_policy="availability_90", ltc_algorithm="speedsort"),
        ]
        found = duplicate_levels(rows, [self._dup("h1"), self._dup("h2")])
        assert found == {
            "reference_policy": {
                "redundant_boom": {"same_as": ["availability_90"], "scenarios": 2}
            }
        }

    def test_an_axis_where_the_policies_agree_reports_nothing(self) -> None:
        from server.core.sweep_analysis import duplicate_levels

        rows = [_row("h1", reference_policy="availability_90")]
        assert "shear_fit_policy" not in duplicate_levels(rows, [self._dup("h1")])

    def test_a_duplicate_of_a_row_out_of_view_is_not_counted(self) -> None:
        """Filtered out or inadmissible: its results are not in what is being analysed."""
        from server.core.sweep_analysis import duplicate_levels

        rows = [_row("h1", reference_policy="availability_90")]
        assert duplicate_levels(rows, [self._dup("elsewhere")]) == {}

    def test_summary_and_spread_report_duplicates_from_a_real_sweep(self, tmp_path: Path) -> None:
        """End to end: run_sweep persists the duplicate, and both readers surface it."""
        from server.core.sweep import run_sweep
        from server.tools.sweep_analysis import _sweep_spread, _sweep_summary
        from tests.test_sweep import _small_spec, _two_sensor_state

        base = _two_sensor_state(tmp_path)
        spec = _small_spec(
            reference_policies=("nearest_2", "availability_90"),
            reference_sources=("era5", "merra2"),
            ltc_algorithms=("variance_ratio",),
        )
        outcome = run_sweep(base, spec, persist=True)
        sweep_id = outcome["manifest"]["sweep_id"]
        assert outcome["manifest"]["counts"]["duplicates_skipped"] == 2

        summary = _sweep_summary(base, sweep_id)
        reference = summary["axes"]["reference_policy"]
        assert summary["duplicates_skipped"] == 2
        assert reference["levels_designed"] == ["availability_90", "nearest_2"]
        assert reference["levels_admissible"] == ["nearest_2"]
        assert reference["duplicate_levels"] == {
            "availability_90": {"same_as": ["nearest_2"], "scenarios": 2}
        }

        spread = _sweep_spread(base, sweep_id)
        by_axis = {entry["axis"]: entry for entry in spread["contributions"]}
        assert by_axis["reference_policy"]["levels"] == 1
        assert by_axis["reference_policy"]["duplicate_levels"] == {
            "availability_90": {"same_as": ["nearest_2"], "scenarios": 2}
        }
        assert by_axis["ltc_algorithm"]["duplicate_levels"] == {}
        assert "duplicate_note" in spread and "duplicate_note" in summary


class TestDualInterfaceParity:
    def test_the_sweep_reading_tools_are_registered(self) -> None:
        import asyncio

        from server.main import mcp

        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        assert {"list_sweeps", "get_sweep_summary", "analyze_sweep_spread"} <= names

    def test_they_are_answerable_without_the_mutating_flag(self) -> None:
        from server.api.routes.chat import _READ_ONLY_TOOLS, _allowed_tools, _build_registries

        _, callables = _build_registries()
        for tool in ("list_sweeps", "get_sweep_summary", "analyze_sweep_spread"):
            assert tool in _READ_ONLY_TOOLS
            assert tool in _allowed_tools(False)
            assert tool in callables
