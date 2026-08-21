"""Sweep HTTP surface — design doc §7.6.

The frontend needs five things: price a sweep before launching it, run one, watch it,
read a finished one back, and take away the runconfig of whichever scenario the analyst
decides to stand behind. These tests cover each, including the case the designer depends
on most — knowing which axis levels this session can actually run, and why not.
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
from server.state.session import SessionState

HEIGHTS = (40.0, 60.0, 80.0, 100.0)
HUB_M = 120.0
ALPHA = 0.22
MEASURED_INDEX = pd.date_range("2019-01-01", "2020-12-31 23:50", freq="10min", tz="UTC")
LONG_INDEX = pd.date_range("2013-01-01", "2020-12-31 23:00", freq="h", tz="UTC")


@pytest.fixture
def api(tmp_path: Path):
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as client:
        yield client, manager
    app.dependency_overrides.clear()


def _headers(session_id: str) -> dict[str, str]:
    """Every session-scoped route requires the session header."""
    return {"X-GoKaatru-Session": session_id}


def _prepare(manager: SessionManager, client: TestClient, *, measurement_type: str = "mast") -> str:
    """Create a session and populate it with a correlated mast + both reanalyses."""
    session_id = client.post("/api/sessions").json()["session_id"]
    state: SessionState = manager.get_session(session_id)

    rng = np.random.default_rng(41)
    long_rng = np.random.default_rng(43)
    era5 = 8.0 + long_rng.weibull(2.0, len(LONG_INDEX)) * 3.0
    era5_series = pd.Series(era5, index=LONG_INDEX)
    concurrent = era5_series.reindex(MEASURED_INDEX, method="ffill").to_numpy()
    top = np.clip(concurrent * 0.92 + rng.normal(0.0, 0.6, len(MEASURED_INDEX)), 0.1, None)

    measured = pd.DataFrame(
        {f"Spd_{int(h)}m": top * (h / max(HEIGHTS)) ** ALPHA for h in HEIGHTS},
        index=MEASURED_INDEX,
    )
    measured["Dir_100m"] = rng.uniform(0.0, 360.0, len(MEASURED_INDEX))

    state.timeseries_df = measured
    state.raw_timeseries_df = measured.copy()
    state.sensor_mapping = {
        float(h): {"speed_col": f"Spd_{int(h)}m", "dir_col": "Dir_100m" if h == 100.0 else None}
        for h in HEIGHTS
    }
    state.sensor_inventory = {
        f"Spd_{int(h)}m": {"height_m": float(h), "sensor_type": "wind_speed"} for h in HEIGHTS
    }
    state.set_measurement_type(measurement_type)
    state.set_hub_height_m(HUB_M)
    state.reanalysis_interpolated = {
        "era5": pd.DataFrame(
            {"Spd_100m": era5, "Dir_100m": long_rng.uniform(0, 360, len(LONG_INDEX))},
            index=LONG_INDEX,
        ),
        "merra2": pd.DataFrame(
            {
                "Spd_50m": np.clip(
                    era5 * 0.86 + 0.4 + long_rng.normal(0, 0.8, len(LONG_INDEX)), 0.0, None
                ),
                "Dir_50m": long_rng.uniform(0, 360, len(LONG_INDEX)),
            },
            index=LONG_INDEX,
        ),
    }
    return session_id


def _body(**overrides) -> dict:
    payload = {
        "shear_fit_policies": ["nearest_2"],
        "reference_policies": ["nearest_2"],
        "shear_models": ["power_law_mean"],
        "reference_sources": ["era5", "merra2"],
        "ltc_algorithms": ["variance_ratio"],
        "hub_height_m": HUB_M,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# What this session can run
# ---------------------------------------------------------------------------


def test_axes_report_which_levels_apply_to_this_session(api):
    client, manager = api
    session_id = _prepare(manager, client)

    payload = client.get(f"/api/sessions/{session_id}/sweep/axes", headers=_headers(session_id)).json()

    by_name = {entry["name"]: entry for entry in payload["sensor_policies"]}
    assert by_name["nearest_2"]["available"] is True
    assert by_name["nearest_2"]["resolved_columns"] == ["Spd_80m", "Spd_100m"]
    # No boom redundancy on this mast, and the response says why rather than omitting it.
    assert by_name["redundant_boom"]["available"] is False
    assert by_name["redundant_boom"]["reason"]

    assert [s["name"] for s in payload["reference_sources"]] == ["era5", "merra2"]
    assert all(source["available"] for source in payload["reference_sources"])


def test_axes_mark_unimplemented_shear_models_unavailable_with_the_reason(api):
    """A declared level the extrapolation path cannot consume must not look selectable."""
    client, manager = api
    session_id = _prepare(manager, client)

    payload = client.get(f"/api/sessions/{session_id}/sweep/axes", headers=_headers(session_id)).json()
    models = {entry["name"]: entry for entry in payload["shear_models"]}

    assert models["power_law_mean"]["available"] is True
    assert models["power_law_sector_12"]["available"] is False
    assert "extrapolation reads only" in models["power_law_sector_12"]["reason"]


def test_axes_report_the_default_thresholds(api):
    client, manager = api
    session_id = _prepare(manager, client)
    payload = client.get(f"/api/sessions/{session_id}/sweep/axes", headers=_headers(session_id)).json()
    assert payload["default_thresholds"]["extrapolation_ratio_fail"] == 2.0
    assert "ltc_r_squared_fail" not in payload["default_thresholds"]
    assert "generic-3.0MW-130m-IIA" in payload["power_curves"]


# ---------------------------------------------------------------------------
# Pricing before launching
# ---------------------------------------------------------------------------


def test_estimate_prices_a_sweep_without_running_it(api):
    """The counter that stops an accidental multi-hour run (§9.1)."""
    client, manager = api
    session_id = _prepare(manager, client)

    body = _body(
        shear_fit_policies=["nearest_2", "widest_lever"],
        shear_models=["power_law_mean", "power_law_momm"],
        ltc_algorithms=["variance_ratio", "linear_least_squares"],
    )
    payload = client.post(f"/api/sessions/{session_id}/sweep/estimate", json=body, headers=_headers(session_id)).json()

    assert payload["leaf_count"] == 2 * 1 * 2 * 2 * 2
    assert payload["prefix_count"] == 4
    # Nothing was persisted, because nothing ran.
    assert client.get(f"/api/sessions/{session_id}/sweep", headers=_headers(session_id)).json()["sweeps"] == []


# ---------------------------------------------------------------------------
# Running, reading back, exporting
# ---------------------------------------------------------------------------


def test_running_a_sweep_returns_a_manifest_and_result_table(api):
    client, manager = api
    session_id = _prepare(manager, client)

    response = client.post(
        f"/api/sessions/{session_id}/sweep/run",
        json=_body(sweep_id="run1"),
        headers=_headers(session_id),
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["manifest"]["counts"]["planned"] == 2
    assert len(payload["results"]) == 2
    for row in payload["results"]:
        assert row["long_term_mean_speed_mps"] > 0.0
        assert row["indicative_gross_aep_mwh"] > 0.0


def test_a_finished_sweep_is_listed_and_readable(api):
    client, manager = api
    session_id = _prepare(manager, client)
    client.post(f"/api/sessions/{session_id}/sweep/run", json=_body(sweep_id="run2"), headers=_headers(session_id))

    listing = client.get(f"/api/sessions/{session_id}/sweep", headers=_headers(session_id)).json()["sweeps"]
    assert [entry["sweep_id"] for entry in listing] == ["run2"]

    loaded = client.get(f"/api/sessions/{session_id}/sweep/run2", headers=_headers(session_id)).json()
    assert loaded["manifest"]["sweep_id"] == "run2"
    assert len(loaded["results"]) == 2


def test_each_scenario_runconfig_is_downloadable(api):
    """The file the analyst takes away once they decide which scenario to stand behind."""
    client, manager = api
    session_id = _prepare(manager, client)
    client.post(f"/api/sessions/{session_id}/sweep/run", json=_body(sweep_id="run3"), headers=_headers(session_id))

    manifest = client.get(f"/api/sessions/{session_id}/sweep/run3", headers=_headers(session_id)).json()["manifest"]
    for entry in manifest["scenarios"]:
        response = client.get(
            f"/api/sessions/{session_id}/sweep/run3/scenarios/{entry['config_hash']}/runconfig",
            headers=_headers(session_id),
        )
        assert response.status_code == 200
        config = response.json()
        assert config["scenario"]["config_hash"] == entry["config_hash"]
        assert config["scenario"]["reference_source"] in {"era5", "merra2"}
        assert config["admissibility"]["thresholds"]["extrapolation_ratio_fail"] == 2.0


def test_custom_thresholds_are_honoured_and_recorded(api):
    client, manager = api
    session_id = _prepare(manager, client)

    body = _body(sweep_id="strict", thresholds={"extrapolation_ratio_fail": 1.001})
    payload = client.post(f"/api/sessions/{session_id}/sweep/run", json=body, headers=_headers(session_id)).json()

    assert payload["manifest"]["thresholds"]["extrapolation_ratio_fail"] == 1.001
    assert payload["manifest"]["counts"]["admissible"] == 0


def test_an_unknown_threshold_is_rejected(api):
    client, manager = api
    session_id = _prepare(manager, client)
    body = _body(thresholds={"made_up_limit": 1.0})
    response = client.post(f"/api/sessions/{session_id}/sweep/run", json=body, headers=_headers(session_id))
    assert response.status_code == 400
    assert "made_up_limit" in response.json()["detail"]


def test_a_missing_sweep_is_a_client_error(api):
    client, manager = api
    session_id = _prepare(manager, client)
    assert client.get(f"/api/sessions/{session_id}/sweep/nope", headers=_headers(session_id)).status_code == 400


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def test_the_stream_emits_one_event_per_scenario_as_it_completes(api):
    """The Run Monitor watches the spread form, so events must arrive during the run."""
    client, manager = api
    session_id = _prepare(manager, client)

    with client.stream(
        "POST",
        f"/api/sessions/{session_id}/sweep/run/stream",
        json=_body(sweep_id="streamed"),
        headers=_headers(session_id),
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    names = [event["event"] for event in events]
    assert names[0] == "sweep_started"
    assert names[-1] == "sweep_finished"
    assert names.count("scenario_completed") == 2
    assert events[-1]["total"] == 2
    # And the run really persisted, not just streamed.
    assert client.get(f"/api/sessions/{session_id}/sweep/streamed", headers=_headers(session_id)).status_code == 200


def test_the_stream_carries_the_manifest_so_the_client_can_load_the_results(api):
    """The finished event must name the sweep, or the results are stranded on disk.

    The browser client does not supply a `sweep_id` — the server mints one. Its only
    route back to the persisted table is the manifest the stream hands it when the run
    ends. Without that it holds a completed sweep it cannot identify, and the Spread
    view sits on its empty state while `results.json` exists in the session (§9.2).
    """
    client, manager = api
    session_id = _prepare(manager, client)

    body = _body()
    body.pop("sweep_id", None)
    with client.stream(
        "POST",
        f"/api/sessions/{session_id}/sweep/run/stream",
        json=body,
        headers=_headers(session_id),
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    finished = events[-1]
    assert finished["event"] == "sweep_finished"
    manifest = finished.get("manifest")
    assert manifest is not None, "the finished event carried no manifest"
    assert manifest["sweep_id"]

    # Exactly what the client does next: fetch the table using only the streamed id.
    loaded = client.get(
        f"/api/sessions/{session_id}/sweep/{manifest['sweep_id']}",
        headers=_headers(session_id),
    )
    assert loaded.status_code == 200
    assert len(loaded.json()["results"]) == manifest["counts"]["run"]
