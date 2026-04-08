"""test_phase8 — Verification tests for GoKaatru Phase 8 LTC workbench features.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager
from server.state.session import SessionState, session
from server.tools.ltc import _run_ltc_linear_least_squares, _run_ltc_total_least_squares
from server.tools.visualization import (
    _plot_ltc_annual_convergence,
    _plot_ltc_monthly_comparison,
    _plot_ltc_residuals,
    _plot_ltc_scatter,
    _plot_uncertainty_tornado,
)


def _seed_ltc_state(state: SessionState) -> None:
    """Populate measured and reference datasets plus deterministic LTC outputs for diagnostics tests."""
    index = pd.date_range("2019-01-31", periods=60, freq="ME")
    reference = 8.0 + 1.4 * np.sin(np.linspace(0.0, 8.0 * np.pi, index.size)) + np.linspace(0.0, 1.0, index.size)
    measured = 0.94 * reference + 0.55 + 0.12 * np.cos(np.linspace(0.0, 6.0 * np.pi, index.size))
    state.timeseries_df = pd.DataFrame({"Spd_100m": measured, "Dir_100m": np.linspace(0.0, 359.0, index.size)}, index=index)
    state.era5_interpolated_df = pd.DataFrame(
        {
            "Spd_100m_hub": reference,
            "Dir_100m": (np.linspace(5.0, 364.0, index.size) % 360.0),
            "t2m": np.full(index.size, 288.15),
            "sp": np.full(index.size, 101325.0),
            "d2m": np.full(index.size, 280.15),
        },
        index=index,
    )
    _run_ltc_linear_least_squares(state, "Spd_100m", "Spd_100m_hub")
    _run_ltc_total_least_squares(state, "Spd_100m", "Spd_100m_hub")


@pytest.fixture
def api_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client backed by a temporary session manager."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def test_plot_ltc_scatter_traces() -> None:
    """Verify LTC scatter diagnostics contain sample, fit, and 1:1 reference traces."""
    _seed_ltc_state(session)

    result = _plot_ltc_scatter(session, "linear_least_squares")
    parsed = json.loads(result["plotly_json"])
    names = {trace["name"] for trace in parsed["data"]}

    assert {"Samples", "OLS fit", "1:1 reference"}.issubset(names)


def test_plot_ltc_residuals_subplots() -> None:
    """Verify LTC residual diagnostics render the expected two-subplot layout."""
    _seed_ltc_state(session)

    result = _plot_ltc_residuals(session, "linear_least_squares")
    parsed = json.loads(result["plotly_json"])

    assert "xaxis2" in parsed["layout"]
    assert "yaxis2" in parsed["layout"]


def test_plot_ltc_monthly_bar_count() -> None:
    """Verify monthly LTC comparison renders one bar trace per completed algorithm."""
    _seed_ltc_state(session)

    result = _plot_ltc_monthly_comparison(session)
    parsed = json.loads(result["plotly_json"])
    bar_traces = [trace for trace in parsed["data"] if trace["type"] == "bar"]

    assert len(bar_traces) == 2


def test_plot_ltc_convergence_lines() -> None:
    """Verify annual convergence includes one running-mean line for each completed algorithm."""
    _seed_ltc_state(session)

    result = _plot_ltc_annual_convergence(session)
    parsed = json.loads(result["plotly_json"])
    names = {trace["name"] for trace in parsed["data"]}

    assert "linear_least_squares" in names
    assert "total_least_squares" in names


def test_plot_uncertainty_tornado_sorted() -> None:
    """Verify tornado bars are ordered largest-to-smallest after the total uncertainty bar."""
    result = _plot_uncertainty_tornado(session, 6.0, 2.0, 1.0, 4.0, 3.0)
    parsed = json.loads(result["plotly_json"])
    values = parsed["data"][0]["x"]

    assert values[0] == 6.0
    assert values[1:] == sorted(values[1:], reverse=True)


def test_plot_dispatch_new_names(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify the API plot dispatch accepts all new Phase 8 LTC plot names."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    _seed_ltc_state(state)

    responses = {
        "ltc_scatter": client.post(f"/api/sessions/{session_id}/plots/ltc_scatter", headers=headers, json={"algorithm": "linear_least_squares"}),
        "ltc_residuals": client.post(f"/api/sessions/{session_id}/plots/ltc_residuals", headers=headers, json={"algorithm": "linear_least_squares"}),
        "ltc_monthly": client.post(f"/api/sessions/{session_id}/plots/ltc_monthly", headers=headers, json={}),
        "ltc_convergence": client.post(f"/api/sessions/{session_id}/plots/ltc_convergence", headers=headers, json={}),
        "uncertainty_tornado": client.post(
            f"/api/sessions/{session_id}/plots/uncertainty_tornado",
            headers=headers,
            json={"total_pct": 6.0, "measurement_pct": 2.0, "vertical_pct": 1.0, "mcp_pct": 4.0, "future_pct": 3.0},
        ),
    }

    assert all(response.status_code == 200 for response in responses.values())