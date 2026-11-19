"""The operation registry core (P1-1, decisions/0009-operation-registry.md)."""
from __future__ import annotations

import asyncio

import pytest

from server.api.routes.chat import _MUTATING_TOOLS, _READ_ONLY_TOOLS
from server.core.executor import CANONICAL_STAGE_ORDER, _tool_registry
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
    assert len(tools) == 90
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
# P1-2: the declarations reproduce today's surfaces exactly
# ---------------------------------------------------------------------------


def test_every_mcp_tool_is_declared_once_as_the_same_function() -> None:
    tools = _mcp_tools()
    assert REGISTRY.names() == set(tools)
    for name, tool in tools.items():
        assert REGISTRY.get(name).fn is tool.fn, name


def test_the_declared_tiers_are_todays_chat_tiers() -> None:
    assert REGISTRY.assistant_tier("read") == _READ_ONLY_TOOLS
    assert REGISTRY.assistant_tier("change") == _MUTATING_TOOLS


def test_the_canvas_operations_are_todays_executor_dispatch() -> None:
    dispatch = _tool_registry()
    canvas = REGISTRY.canvas_operations()
    assert set(canvas) == set(dispatch)
    for name, declared in canvas.items():
        assert declared.fn is dispatch[name][1], name


def test_stage_order_reproduces_the_executor_module_order() -> None:
    """Stages map one-to-one onto the executor's modules, in the same order, so a canvas
    tie breaks exactly as before (F-09)."""
    pairs = {
        (CANONICAL_STAGE_ORDER.index(declared.module), declared.stage_rank)
        for declared in REGISTRY.canvas_operations().values()
    }
    assert len({module for module, _ in pairs}) == len(pairs) == len({stage for _, stage in pairs})
    stage_ranks = [stage for _, stage in sorted(pairs)]
    assert stage_ranks == sorted(stage_ranks)


def test_no_network_operation_is_in_the_read_tier() -> None:
    network = {declared.name for declared in REGISTRY if declared.network}
    assert network
    assert network.isdisjoint(REGISTRY.assistant_tier("read"))
