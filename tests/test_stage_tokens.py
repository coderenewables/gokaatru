"""test_stage_tokens — cross-stack contract: backend completed_steps must emit
every token the frontend stepper requires to mark a stage "done".

The frontend (frontend/src/lib/stages.ts STAGE_META.requiredSteps) treats these
tokens as the gating signal. If the backend ever stops emitting one of them, a
stage would stay permanently locked. This test pins the contract.
"""
from __future__ import annotations

import pandas as pd

from server.api.deps import completed_steps
from server.schemas.common import Coordinate
from server.state.session import SessionState


def _configured_session() -> SessionState:
    """Return a session with every workflow artifact populated."""
    state = SessionState()
    state.reset()
    index = pd.date_range("2024-01-01", periods=4, freq="10min")
    state.timeseries_df = pd.DataFrame({"Spd_80m": [8.0, 8.1, 8.2, 8.3]}, index=index)
    state.raw_timeseries_df = state.timeseries_df.copy()
    state.sensor_mapping = {
        80.0: {
            "speed_col": "Spd_80m",
            "dir_col": None,
            "sd_col": None,
            "temp_col": None,
            "pressure_col": None,
        }
    }
    state.set_project_name("Token Site")
    state.set_coordinate(Coordinate(latitude=52.0, longitude=5.0, elevation_m=10.0))
    state.set_measurement_type("mast")
    state.set_hub_height_m(120.0)
    state.cleaning_log = [{"rule_type": "range_check", "sensor": "Spd_80m", "records_affected": 1}]
    state.shear_timeseries_df = pd.DataFrame({"shear_coefficient": [0.14, 0.15]}, index=index[:2])
    state.shear_table = pd.DataFrame([[0.14] * 24] * 12)
    state.roughness_timeseries_df = pd.DataFrame({"roughness_length": [0.001, 0.001]}, index=index[:2])
    state.roughness_table = pd.DataFrame([[0.001] * 24] * 12)
    state.era5_nodes = [{"latitude": 52.25, "longitude": 5.0, "distance_km": 27.8, "bearing": "N"}]
    state.era5_data = {"52.0_5.0": pd.DataFrame({"Spd_100m": [7.0, 7.1]}, index=index[:2])}
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m": [7.0, 7.1]}, index=index[:2])
    state.ltc_results = {"speedsort": {"df": pd.DataFrame(), "metrics": {}, "file": None}}
    state.ensemble_df = pd.DataFrame({"Ensemble_Speed": [7.2, 7.3]}, index=index[:2])
    return state


# Every token the frontend STAGE_META.requiredSteps references. This list is the
# contract; if either side changes a token, this test must be updated deliberately.
REQUIRED_TOKENS = {
    "timeseries",
    "datamodel",
    "config",
    "era5_nodes",
    "era5_extract",
    "era5_interpolate",
    "shear_table",
    "roughness_table",
    "ltc",
    "ensemble",
}


def test_completed_steps_emits_every_frontend_required_token() -> None:
    """A fully-populated session must emit every token the stepper gates on."""
    state = _configured_session()
    emitted = set(completed_steps(state))
    missing = REQUIRED_TOKENS - emitted
    assert missing == set(), f"backend completed_steps is missing tokens the frontend requires: {sorted(missing)}"


def test_completed_steps_token_set_is_stable() -> None:
    """Pin the full emitted token vocabulary so renames surface here first."""
    state = _configured_session()
    emitted = set(completed_steps(state))
    # The backend may emit extra tokens (windkit, cleaning, shear_timeseries,
    # roughness_timeseries) — that's fine. The known vocabulary is:
    expected_vocabulary = {
        "timeseries",
        "datamodel",
        "config",
        "cleaning",
        "shear_timeseries",
        "shear_table",
        "roughness_timeseries",
        "roughness_table",
        "era5_nodes",
        "era5_extract",
        "era5_interpolate",
        "ltc",
        "ensemble",
        "windkit",
    }
    # Every emitted token must be in the documented vocabulary (no surprises).
    unexpected = emitted - expected_vocabulary
    assert unexpected == set(), f"unexpected new completed_steps token(s): {sorted(unexpected)}"
