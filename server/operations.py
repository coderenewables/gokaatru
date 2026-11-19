"""operations — every analysis step declared once (decisions/0009-operation-registry.md).

An operation wraps an existing tool function, unchanged, with what every surface needs to
know about it: whether it reads or changes data, the pipeline stage it belongs to, whether
the canvas may dispatch it and the assistant may call it, the response fields that disclose
a default or a fallback, and the standards material it is traced to. The MCP tool, the
HTTP route, the canvas dispatch, the assistant's tiers and the README checks are generated
from these declarations, so a capability is written in one place and the copies that
drifted (F3, F7, F8) have nothing left to drift from.

The parameter schema is not declared: it is read from the function's signature by the same
parser that builds the MCP tool, so the two cannot disagree.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal, TypeVar

from fastmcp.tools import FunctionTool

from server.core.scenario_result import ENGINE_VERSION

Effect = Literal["read", "change"]
EFFECTS: tuple[str, ...] = ("read", "change")

#: Pipeline order, used to break a tie between two canvas nodes that no edge orders (F-09:
#: canvas edges are advisory; the real dependency runs through session state). It follows
#: the data flow, not import order: ``reanalysis_download`` (BrightHub) writes the node frames
#: that ``reanalysis`` reads, so it comes first. Within a stage, ties fall back to node id.
STAGES: tuple[str, ...] = (
    "ingest",
    "cleaning",
    "reanalysis_download",
    "reanalysis",
    "homogeneity",
    "shear",
    "extrapolation",
    "air_density",
    "ltc",
    "ltc_ml",
    "ensemble",
    "clipping",
    "uncertainty",
    "statistics",
    "visualization",
    "map",
    "config",
    "analysis",
    "atmosphere",
    "diagnostics",
    "sweep",
)

# Standards references may only say what a method is traced to (decisions/0004).
_CONFORMANCE_WORDING = re.compile(r"(?i)\b(complian\w*|conform\w*|certif\w*|follows)\b")
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class Operation:
    """One analysis step and everything the surfaces generated from it need to know.

    ``effect`` is ``"read"`` when the step changes no session state and writes no file;
    anything else is ``"change"``. ``network`` marks a step that reaches an external
    service, whichever its effect. ``canvas`` says whether a workflow node may dispatch
    it, and ``assistant`` whether the chat assistant may be offered it at all; there, a
    network call needs the same opt-in as a change.
    """

    name: str
    fn: Callable[..., Any]
    effect: Effect
    stage: str
    canvas: bool = True
    assistant: bool = True
    network: bool = False
    disclosure: tuple[str, ...] = ()
    standards: tuple[str, ...] = ()
    code_version: str = ENGINE_VERSION
    dry_run: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"Operation name {self.name!r} is not an identifier")
        if self.effect not in EFFECTS:
            raise ValueError(f"Operation '{self.name}': effect must be one of {EFFECTS}, got {self.effect!r}")
        if self.stage not in STAGES:
            raise ValueError(f"Operation '{self.name}': unknown stage {self.stage!r}")
        if self.dry_run is not None and self.effect == "read":
            raise ValueError(f"Operation '{self.name}' reads only, so it has nothing to dry-run")
        for field_name in self.disclosure:
            if not _FIELD_NAME.match(field_name):
                raise ValueError(f"Operation '{self.name}': disclosure field {field_name!r} is not a field path")
        for reference in self.standards:
            if _CONFORMANCE_WORDING.search(reference):
                raise ValueError(
                    f"Operation '{self.name}': standards reference {reference!r} claims conformance; "
                    "a method is only ever traced to a standard"
                )

    @property
    def module(self) -> str:
        return str(self.fn.__module__)

    @cached_property
    def _tool(self) -> FunctionTool:
        return FunctionTool.from_function(self.fn, name=self.name)

    @property
    def parameters(self) -> dict[str, Any]:
        """The JSON schema of the inputs, from the signature, exactly as the MCP tool has it."""
        return dict(self._tool.parameters)

    @property
    def description(self) -> str:
        return str(self._tool.description or "")

    @property
    def stage_rank(self) -> int:
        return STAGES.index(self.stage)


class OperationRegistry:
    """The declared operations, by name. Iteration is in name order."""

    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}

    def register(self, operation: Operation) -> Operation:
        if operation.name in self._operations:
            raise ValueError(f"Operation '{operation.name}' is declared twice")
        self._operations[operation.name] = operation
        return operation

    def get(self, name: str) -> Operation:
        try:
            return self._operations[name]
        except KeyError:
            raise KeyError(f"No operation named '{name}' is declared") from None

    def __contains__(self, name: object) -> bool:
        return name in self._operations

    def __iter__(self) -> Iterator[Operation]:
        return iter(sorted(self._operations.values(), key=lambda operation: operation.name))

    def __len__(self) -> int:
        return len(self._operations)

    def names(self) -> frozenset[str]:
        return frozenset(self._operations)

    def assistant_tier(self, effect: Effect) -> frozenset[str]:
        """The operations the assistant may be offered at this tier.

        The read tier's contract is no session change, no file written and no network
        call; everything else the assistant may see needs the per-request opt-in.
        """
        if effect == "read":
            return frozenset(op.name for op in self if op.assistant and op.effect == "read" and not op.network)
        return frozenset(op.name for op in self if op.assistant and (op.effect == "change" or op.network))

    def canvas_operations(self) -> dict[str, Operation]:
        return {op.name: op for op in self if op.canvas}


REGISTRY = OperationRegistry()


def _publish_to_mcp(declared: Operation) -> None:
    # Imported here, not at module level: server.main imports every tool module, and each of
    # those imports this one, so the server object exists by the time a tool is declared.
    from server.main import mcp

    mcp.tool(name=declared.name)(declared.fn)


def operation(
    *,
    effect: Effect,
    stage: str,
    canvas: bool = True,
    assistant: bool = True,
    network: bool = False,
    disclosure: tuple[str, ...] = (),
    standards: tuple[str, ...] = (),
    dry_run: Callable[..., Any] | None = None,
    name: str | None = None,
    registry: OperationRegistry | None = None,
) -> Callable[[F], F]:
    """Declare a tool function as an operation and publish it as an MCP tool.

    The function itself is returned unchanged. A declaration into a registry other than the
    global one is not published, so tests can build registries of their own.
    """

    def declare(fn: F) -> F:
        declared = (REGISTRY if registry is None else registry).register(
            Operation(
                name=name or fn.__name__,
                fn=fn,
                effect=effect,
                stage=stage,
                canvas=canvas,
                assistant=assistant,
                network=network,
                disclosure=tuple(disclosure),
                standards=tuple(standards),
                dry_run=dry_run,
            )
        )
        if registry is None:
            _publish_to_mcp(declared)
        return fn

    return declare
