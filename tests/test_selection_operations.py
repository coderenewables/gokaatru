"""Statistics and charts on a selection (P1-16, decisions/0011).

A selectable operation publishes a ``selection`` parameter on every surface. Named, the
operation runs on a copy of the session whose records outside the selection are missing,
and its result reports which selection, how many records and on what basis. The
acceptance check: for every selectable operation, the result equals the same operation run
without a selection on a session pre-filtered independently, with the mask from
``tests/oracles.py``.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.operations import REGISTRY, SELECTION_BASIS, OperationRegistry, operation
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session
from tests.oracles import selection_mask_oracle
from tests.test_operation_routes import ARGUMENT_VALUES, _fingerprint, _new_session, _populate

SELECTABLE = {
    "build_sector_shear_tables",
    "compute_diurnal_profile",
    "compute_energy_metrics",
    "compute_mast_effects",
    "compute_momm",
    "compute_monthly_stats",
    "compute_qc_diagnostics",
    "compute_scatter_stats",
    "compute_sensor_comparison",
    "compute_turbulence_analysis",
    "compute_turbulence_intensity",
    "compute_vertical_structure",
    "compute_weibull_params",
    "compute_wind_climate",
    "compute_wind_persistence",
    "compute_wind_ramps",
    "compute_windrose_data",
    "get_series_window",
    "plot_diurnal",
    "plot_monthly_means",
    "plot_scatter",
    "plot_timeseries",
    "plot_weibull",
    "plot_windrose",
}

_INVENTORY = "describes what was measured; under a selection every unselected record would read as a gap"
_LONG_TERM = "reads the long-term corrected results, which a selection of measured records does not restrict"
_STORED = "reads configuration, a log or a stored object, not records"
_NUMBERS = "takes its inputs as numbers, not records"
NOT_SELECTABLE = {
    "analyze_homogeneity": "screens the reanalysis series, not the measured records",
    "analyze_sweep_spread": _STORED,
    "brighthub_find_reanalysis_nodes": _STORED,
    "brighthub_get_data_model": _STORED,
    "brighthub_list_locations": _STORED,
    "brighthub_status": _STORED,
    "compute_air_density": _NUMBERS,
    "compute_air_density_timeseries": "its default source is the reanalysis frame, which a selection does not restrict",
    "compute_energy_sensitivity": _LONG_TERM,
    "compute_extreme_winds": "its default source is the long-term corrected series, which no selection restricts",
    "compute_mcp_readiness": "says whether the correction can run, and the correction always uses every record",
    "draft_data_model": _INVENTORY,
    "earthdatahub_status": _STORED,
    "get_analysis_summary": _STORED,
    "get_cleaning_log": _STORED,
    "get_data_coverage": _INVENTORY,
    "get_era5_node_markers": _STORED,
    "get_fixed_prefix_hash": _STORED,
    "get_scatter_pairs": "marks a selection's records with its highlight instead, so the scatter still draws the rest",
    "get_flag_intervals": "draws the flag table, which records what cleaning removed from every record",
    "get_mast_marker": _STORED,
    "get_operation_log": _STORED,
    "get_period_of_record": _INVENTORY,
    "get_run_config": _STORED,
    "get_site_overview_map": _STORED,
    "get_sweep_summary": _STORED,
    "list_cleaning_rules": _STORED,
    "list_selections": _STORED,
    "list_sensors": _INVENTORY,
    "list_sweeps": _STORED,
    "plot_annual_means": _LONG_TERM,
    "plot_data_coverage": _INVENTORY,
    "plot_ltc_comparison": _LONG_TERM,
    "plot_shear_table": "draws the stored shear table, which was built from every record",
    "plot_uncertainty_breakdown": _NUMBERS,
    "resolve_selection": "resolves a selection itself",
}

HEIGHTS = '["Spd_60m", "Spd_80m", "Spd_100m"]'

# Wraps through north, then a February band: a union of a sector and an intersection.
DEFINITION = {
    "kind": "union",
    "of": [
        {"kind": "sector", "channel": "Dir_100m", "from_deg": 300.0, "to_deg": 60.0},
        {
            "kind": "intersection",
            "of": [
                {"kind": "time_range", "start": "2023-02-01T00:00:00+00:00", "end": "2023-03-01T00:00:00+00:00"},
                {"kind": "band", "channel": "Spd_100m", "min": 4.0, "max": 12.0},
            ],
        },
    ],
}


def _session() -> SessionState:
    """The route tests' mast, with cleaning gaps in the working frame that raw still holds,
    and the per-record shear and roughness series built from it."""
    state = SessionState()
    _populate(state)
    frame = state.timeseries_df
    frame.loc[frame.index[::53], "Spd_100m"] = np.nan
    frame.loc[frame.index[4000:4300], ["Spd_100m", "Spd_80m"]] = np.nan
    with bind_session(state):
        REGISTRY.get("calculate_shear_timeseries").fn(height_sensors=HEIGHTS)
        REGISTRY.get("calculate_roughness_timeseries").fn(height_sensors=HEIGHTS)
    return state


def _oracle_mask(frame: pd.DataFrame) -> np.ndarray:
    channels = {column: [float(v) for v in frame[column]] for column in ("Dir_100m", "Spd_100m")}
    return np.array(selection_mask_oracle(DEFINITION, list(frame.index), channels))


def _pre_filtered(mask: np.ndarray) -> SessionState:
    state = _session()
    for name in ("timeseries_df", "raw_timeseries_df", "shear_timeseries_df", "roughness_timeseries_df"):
        frame = getattr(state, name).astype(float)
        frame.loc[~mask, :] = np.nan
        setattr(state, name, frame)
    return state


def _arguments(name: str) -> dict[str, object]:
    signature = inspect.signature(REGISTRY.get(name).fn)
    return {
        parameter.name: ARGUMENT_VALUES[parameter.name]
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
    }


def _outcome(state: SessionState, name: str, **extra: object) -> tuple[str, object]:
    with bind_session(state):
        try:
            result = REGISTRY.get(name).fn(**_arguments(name), **extra)
        except (ValueError, RuntimeError) as exc:
            return ("refused", f"{type(exc).__name__}: {exc}")
    return ("ok", result)


def _wire(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


@pytest.fixture(scope="module")
def selected() -> tuple[SessionState, np.ndarray]:
    state = _session()
    with bind_session(state):
        REGISTRY.get("define_selection").fn(name="north_or_feb", definition=DEFINITION)
    return state, _oracle_mask(state.timeseries_df)


def test_the_selectable_operations_are_pinned() -> None:
    assert {op.name for op in REGISTRY if op.selectable} == SELECTABLE


def test_every_other_read_says_why_it_takes_no_selection() -> None:
    reads = {op.name for op in REGISTRY if op.effect == "read"}
    assert reads - SELECTABLE == set(NOT_SELECTABLE)
    assert SELECTABLE <= reads


def test_selection_is_published_on_every_surface() -> None:
    for name in sorted(SELECTABLE):
        declared = REGISTRY.get(name)
        properties = declared.parameters["properties"]
        assert properties["selection"]["default"] == ""
        assert "selection" not in declared.parameters.get("required", [])
        assert "selection" in inspect.signature(declared.fn).parameters
        bare = inspect.signature(inspect.unwrap(declared.fn)).parameters
        assert set(properties) == set(bare) | {"selection"}, name


def test_a_change_cannot_be_selectable() -> None:
    with pytest.raises(ValueError, match="cannot run on a selection"):

        @operation(effect="change", stage="statistics", selectable=True, registry=OperationRegistry())
        def changes(sensor_name: str) -> dict:
            return {}


@pytest.mark.parametrize("name", sorted(SELECTABLE))
def test_on_a_selection_equals_the_pre_filtered_session(name: str, selected) -> None:
    state, mask = selected
    assert 0 < mask.sum() < mask.size
    status, result = _outcome(state, name, selection="north_or_feb")
    expected_status, expected = _outcome(_pre_filtered(mask), name)
    assert status == expected_status == "ok", (result, expected)
    disclosure = result.pop("selection")
    assert disclosure == {
        "name": "north_or_feb",
        "inline": False,
        "records": int(mask.sum()),
        "of_records": int(mask.size),
        "basis": SELECTION_BASIS,
    }
    assert _wire(result) == _wire(expected)


@pytest.mark.parametrize("name", sorted(SELECTABLE))
def test_an_inline_definition_equals_the_same_one_saved(name: str, selected) -> None:
    state, mask = selected
    saved = _outcome(state, name, selection="north_or_feb")
    logged = len(state.operation_log)
    inline = _outcome(state, name, selection=json.dumps(DEFINITION))
    assert len(state.operation_log) == logged, "a read on an inline definition is not logged"
    assert saved[0] == inline[0] == "ok", inline
    saved_disclosure, inline_disclosure = saved[1].pop("selection"), inline[1].pop("selection")
    assert inline_disclosure == {**saved_disclosure, "name": None, "inline": True}
    assert inline_disclosure["records"] == int(mask.sum())
    assert _wire(inline[1]) == _wire(saved[1])


def test_an_inline_definition_that_is_not_an_object_is_refused(selected) -> None:
    state, _ = selected
    with bind_session(state):
        weibull = REGISTRY.get("compute_weibull_params").fn
        with pytest.raises(ValueError, match="must be a JSON object: Expecting"):
            weibull(sensor_name="Spd_100m", selection="{kind: band}")
        with pytest.raises(ValueError, match="Inline selection: Channel 'Nope'"):
            weibull(sensor_name="Spd_100m", selection='{"kind": "band", "channel": "Nope", "min": 1}')


def test_a_saved_selection_cannot_be_named_like_a_definition(selected) -> None:
    state, _ = selected
    with bind_session(state), pytest.raises(ValueError, match="cannot start with"):
        REGISTRY.get("define_selection").fn(name=" {x", definition={"kind": "band", "channel": "Spd_100m", "min": 1})


def test_without_a_selection_nothing_changes(selected) -> None:
    state, _ = selected
    with bind_session(state):
        bare = REGISTRY.get("compute_weibull_params").fn(sensor_name="Spd_100m")
        unwrapped = inspect.unwrap(REGISTRY.get("compute_weibull_params").fn)(sensor_name="Spd_100m")
    assert "selection" not in bare
    assert _wire(bare) == _wire(unwrapped)


def test_a_selection_leaves_the_session_alone_and_is_logged(selected) -> None:
    state, _ = selected
    before = _fingerprint(state)
    raw = state.raw_timeseries_df.copy()
    with bind_session(state):
        REGISTRY.get("compute_monthly_stats").fn(sensor_name="Spd_100m", selection="north_or_feb")
    assert _fingerprint(state) == before
    pd.testing.assert_frame_equal(state.raw_timeseries_df, raw)
    entry = state.operation_log[-1]
    assert entry["operation"] == "compute_monthly_stats"
    assert entry["parameters"]["selection"] == "north_or_feb"


def test_an_unknown_selection_is_refused(selected) -> None:
    state, _ = selected
    with bind_session(state), pytest.raises(ValueError, match="No selection named 'nowhere'"):
        REGISTRY.get("compute_weibull_params").fn(sensor_name="Spd_100m", selection="nowhere")


def test_a_ramp_never_spans_records_the_selection_separates() -> None:
    """Records outside a selection are blanked, not dropped, so the timestamps stay.

    A steady 8 m/s, then every other record at 20 m/s with the ones between alternating 10
    and 4. Selecting below 15 m/s leaves no two neighbouring records in the second part.
    Dropped instead of blanked, the second part reads as 6 m/s ramps every 20 minutes, a
    cadence the timestep check refuses.
    """
    state = _session()
    frame = state.timeseries_df
    values = np.full(len(frame), 8.0)
    tail = np.arange(len(frame) - 500)
    values[500:] = np.where(tail % 2 == 1, 20.0, np.where((tail // 2) % 2 == 0, 10.0, 4.0))
    frame["Spd_100m"] = values
    state.raw_timeseries_df = frame.copy()
    definition = {"kind": "band", "channel": "Spd_100m", "max": 15.0}
    with bind_session(state):
        REGISTRY.get("define_selection").fn(name="below_15", definition=definition)
        ramps = REGISTRY.get("compute_wind_ramps").fn(speed_sensor="Spd_100m", selection="below_15")
    assert ramps["selection"]["records"] == int((values < 15.0).sum())
    assert ramps["timestep_minutes"] == 10
    assert ramps["record_count"] == 500
    assert ramps["event_count"] == 0

    dropped = _session()
    dropped.timeseries_df = frame[values < 15.0].copy()
    with bind_session(dropped), pytest.raises(ValueError, match="not a supported cadence"):
        inspect.unwrap(REGISTRY.get("compute_wind_ramps").fn)(speed_sensor="Spd_100m")


def test_the_generated_route_takes_a_selection(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            session_id, state = _new_session(client, manager)
            base = f"/api/sessions/{session_id}/operations"

            def post(name: str, body: dict[str, object]):
                return client.post(f"{base}/{name}", headers={"X-GoKaatru-Session": session_id}, json=body)

            defined = post("define_selection", {"name": "s", "definition": DEFINITION})
            assert defined.status_code == 200, defined.text
            response = post("compute_weibull_params", {"sensor_name": "Spd_100m", "selection": "s"})
            assert response.status_code == 200, response.text
            assert response.json()["selection"]["records"] == int(_oracle_mask(state.timeseries_df).sum())
            inline = post("compute_weibull_params", {"sensor_name": "Spd_100m", "selection": json.dumps(DEFINITION)})
            assert inline.status_code == 200, inline.text
            assert {**inline.json(), "selection": None} == {**response.json(), "selection": None}
            assert inline.json()["selection"]["inline"] is True
            assert post("compute_weibull_params", {"sensor_name": "Spd_100m", "selection": "x"}).status_code == 400
            listed = {row["name"]: row for row in client.get("/api/operations").json()}
            assert {name for name, row in listed.items() if row["selectable"]} == SELECTABLE
    finally:
        app.dependency_overrides.clear()
