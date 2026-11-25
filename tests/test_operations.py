"""The operation registry core (P1-1, decisions/0009-operation-registry.md)."""
from __future__ import annotations

import asyncio

import pytest

from server.api.routes.chat import _MUTATING_TOOLS, _READ_ONLY_TOOLS
from server.core.executor import _tool_registry
from server.main import mcp
from server.operations import REGISTRY, STAGES, Operation, OperationRegistry, operation


def _mcp_tools() -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def _noop(sensor: str, height_m: float = 80.0) -> dict:
    """A stand-in tool."""
    return {"sensor": sensor, "height_m": height_m}


def test_an_operation_reads_the_same_schema_and_description_as_its_mcp_tool() -> None:
    """The registry takes the schema from the signature with the MCP tool's own parser, so
    generating the tool from the registry cannot change what a client sees."""
    tools = _mcp_tools()
    for name, tool in tools.items():
        declared = Operation(name=name, fn=tool.fn, effect="read", stage="statistics")
        assert declared.parameters == tool.parameters, name
        assert declared.description == tool.description, name


def test_the_decorator_returns_the_function_unchanged_and_registers_it() -> None:
    registry = OperationRegistry()
    declared = operation(effect="read", stage="statistics", registry=registry)(_noop)

    assert declared is _noop
    assert "_noop" in registry
    assert registry.get("_noop").parameters["required"] == ["sensor"]


def test_a_name_declared_twice_is_refused() -> None:
    registry = OperationRegistry()
    operation(effect="read", stage="statistics", registry=registry)(_noop)
    with pytest.raises(ValueError, match="declared twice"):
        operation(effect="read", stage="statistics", registry=registry)(_noop)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"effect": "write"}, "effect must be one of"),
        ({"stage": "somewhere"}, "unknown stage"),
        ({"dry_run": _noop}, "nothing to dry-run"),
        ({"disclosure": ("Bad Field",)}, "not a field path"),
        ({"standards": ("Compliant with IEC 61400-12-1",)}, "claims conformance"),
        ({"standards": ("Follows MEASNET",)}, "claims conformance"),
    ],
)
def test_an_invalid_declaration_is_refused(overrides: dict, message: str) -> None:
    fields = {"name": "noop", "fn": _noop, "effect": "read", "stage": "statistics"} | overrides
    with pytest.raises(ValueError, match=message):
        Operation(**fields)


def test_a_dry_run_with_other_parameters_than_its_operation_is_refused() -> None:
    def preview(sensor: str) -> dict:
        return {"sensor": sensor}

    with pytest.raises(ValueError, match="exactly the operation's parameters"):
        Operation(name="noop", fn=_noop, effect="change", stage="cleaning", dry_run=preview)


def test_a_traced_reference_and_a_dotted_disclosure_field_are_accepted() -> None:
    declared = Operation(
        name="noop",
        fn=_noop,
        effect="read",
        stage="shear",
        disclosure=("clamp_stats.records_clamped",),
        standards=("Traced to IEC 61400-12-1:2017 Annex B; clause text not read",),
    )
    assert declared.stage_rank == STAGES.index("shear")


def test_tiers_and_canvas_set_follow_the_declarations() -> None:
    registry = OperationRegistry()
    registry.register(Operation(name="looks", fn=_noop, effect="read", stage="statistics"))
    registry.register(Operation(name="writes", fn=_noop, effect="change", stage="cleaning"))
    registry.register(
        Operation(name="logs_in", fn=_noop, effect="change", stage="reanalysis_download", assistant=False)
    )
    registry.register(Operation(name="reads_sweep", fn=_noop, effect="read", stage="sweep", canvas=False))
    registry.register(Operation(name="fetches", fn=_noop, effect="read", stage="reanalysis", network=True))

    assert registry.assistant_tier("read") == {"looks", "reads_sweep"}
    assert registry.assistant_tier("change") == {"writes", "fetches"}
    assert set(registry.canvas_operations()) == {"looks", "writes", "logs_in", "fetches"}
    assert [op.name for op in registry] == ["fetches", "logs_in", "looks", "reads_sweep", "writes"]


def test_stages_are_unique() -> None:
    assert len(STAGES) == len(set(STAGES))


# ---------------------------------------------------------------------------
# The declarations, pinned. Moving an operation between tiers, onto or off the canvas,
# or to another stage is a deliberate change and has to edit these lists (P1-2, P1-4).
# ---------------------------------------------------------------------------

# No session change, no file written, no network: always offered to the assistant.
PINNED_READ_TIER = frozenset({
    "get_operation_log", "list_selections", "resolve_selection", "get_series_window",
    "analyze_homogeneity", "analyze_sweep_spread", "build_sector_shear_tables", "compute_air_density",
    "compute_air_density_timeseries", "compute_diurnal_profile",
    "compute_energy_metrics", "compute_energy_sensitivity", "compute_extreme_winds", "compute_mast_effects",
    "compute_mcp_readiness", "compute_momm", "compute_monthly_stats", "compute_qc_diagnostics",
    "compute_scatter_stats", "compute_sensor_comparison", "compute_turbulence_analysis",
    "compute_turbulence_intensity", "compute_vertical_structure", "compute_weibull_params",
    "compute_wind_climate", "compute_wind_persistence", "compute_wind_ramps", "compute_windrose_data",
    "draft_data_model", "get_analysis_summary", "get_cleaning_log", "get_data_coverage",
    "get_era5_node_markers", "get_fixed_prefix_hash", "get_mast_marker", "get_period_of_record",
    "get_run_config", "get_site_overview_map", "get_sweep_summary", "list_cleaning_rules", "list_sensors",
    "list_sweeps", "plot_annual_means", "plot_data_coverage", "plot_diurnal", "plot_ltc_comparison",
    "plot_monthly_means", "plot_scatter", "plot_shear_table", "plot_timeseries", "plot_uncertainty_breakdown",
    "plot_weibull", "plot_windrose",
})
# Changes, file writes and network calls: offered only with allow_mutating_tools.
PINNED_CHANGE_TIER = frozenset({
    "undo_last_change", "redo_last_change", "define_selection", "delete_selection",
    "apply_cleaning_rule", "apply_homogeneity_cutoff", "build_aggr_momm_shear_table", "build_data_model",
    "build_roughness_table", "build_shear_table", "calculate_roughness_timeseries",
    "calculate_shear_timeseries", "calculate_uncertainty", "compute_atmospheric_conditions", "compute_era5_wind_speed",
    "extract_era5_data",
    "extrapolate_reanalysis_to_hub", "extrapolate_to_hub_height", "find_era5_nodes",
    "interpolate_era5_to_site", "load_run_config", "parse_datamodel", "parse_timeseries", "run_ensemble",
    "run_ltc_linear_least_squares", "run_ltc_speedsort", "run_ltc_total_least_squares",
    "run_ltc_variance_ratio", "run_ltc_xgboost", "save_run_config", "undo_cleaning_rule", "update_run_config",
    "run_clipping_analysis",
})
# Never offered: network and credential tools.
PINNED_UNEXPOSED = frozenset({
    "brighthub_download_reanalysis", "brighthub_find_reanalysis_nodes", "brighthub_get_data_model",
    "brighthub_import_location", "brighthub_list_locations", "brighthub_login", "brighthub_logout",
    "brighthub_prepare_reanalysis", "brighthub_status", "earthdatahub_clear_credential",
    "earthdatahub_set_credential", "earthdatahub_status",
})
PINNED_NOT_ON_CANVAS = frozenset({
    "get_operation_log", "undo_last_change", "redo_last_change",
    "define_selection", "delete_selection", "list_selections", "resolve_selection",
    "analyze_sweep_spread", "build_data_model", "draft_data_model", "get_fixed_prefix_hash",
    "get_sweep_summary", "list_sweeps",
})
# Module to stage, in the executor's pipeline order before P1-4 (F-09).
PINNED_STAGE_BY_MODULE = {
    "data_io": "ingest", "datamodel_builder": "ingest", "cleaning": "cleaning",
    "brighthub": "reanalysis_download", "era5": "reanalysis", "homogeneity": "homogeneity",
    "shear": "shear", "extrapolation": "extrapolation", "air_density": "air_density", "ltc": "ltc",
    "ltc_ml": "ltc_ml", "ensemble": "ensemble", "clipping": "clipping", "uncertainty": "uncertainty",
    "statistics": "statistics", "visualization": "visualization", "map": "map", "config": "config",
    "advanced_analysis": "analysis", "atmosphere": "atmosphere", "diagnostics": "diagnostics",
    "scenario_result": "sweep", "sweep_analysis": "sweep", "history": "config", "selections": "selection",
    "series": "visualization",
}
PINNED_STAGES = (
    "ingest", "cleaning", "reanalysis_download", "reanalysis", "homogeneity", "shear", "extrapolation",
    "air_density", "ltc", "ltc_ml", "ensemble", "clipping", "uncertainty", "statistics", "visualization",
    "map", "config", "analysis", "atmosphere", "diagnostics", "sweep", "selection",
)


def test_every_mcp_tool_is_declared_once_as_the_same_function() -> None:
    tools = _mcp_tools()
    assert REGISTRY.names() == set(tools)
    for name, tool in tools.items():
        assert REGISTRY.get(name).fn is tool.fn, name


def test_the_assistant_tiers_are_the_pinned_ones() -> None:
    assert REGISTRY.assistant_tier("read") == PINNED_READ_TIER
    assert REGISTRY.assistant_tier("change") == PINNED_CHANGE_TIER
    assert {declared.name for declared in REGISTRY if not declared.assistant} == PINNED_UNEXPOSED
    assert PINNED_READ_TIER | PINNED_CHANGE_TIER | PINNED_UNEXPOSED == REGISTRY.names()


def test_the_chat_route_offers_exactly_the_declared_tiers() -> None:
    assert _READ_ONLY_TOOLS == PINNED_READ_TIER
    assert _MUTATING_TOOLS == PINNED_CHANGE_TIER


def test_the_canvas_dispatches_exactly_the_declared_canvas_operations() -> None:
    dispatch = _tool_registry()
    assert REGISTRY.names() - set(dispatch) == PINNED_NOT_ON_CANVAS
    for name, (_module, function) in dispatch.items():
        assert function is REGISTRY.get(name).fn, name


def test_stages_and_their_order_are_the_pinned_ones() -> None:
    """The canvas tie-break order (F-09) is the stage order, so it is pinned as well."""
    assert STAGES == PINNED_STAGES
    for declared in REGISTRY:
        assert declared.stage == PINNED_STAGE_BY_MODULE[declared.module.rsplit(".", 1)[-1]], declared.name


def test_no_network_operation_is_in_the_read_tier() -> None:
    network = {declared.name for declared in REGISTRY if declared.network}
    assert network
    assert network.isdisjoint(REGISTRY.assistant_tier("read"))
