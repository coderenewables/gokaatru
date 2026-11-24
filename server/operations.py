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

import copy
import functools
import inspect
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from typing import Annotated, Any, Literal, TypeVar, get_type_hints

import numpy as np
from fastmcp.tools import FunctionTool
from pydantic import Field

from server.core.scenario_result import ENGINE_VERSION
from server.state.session import SessionState, bind_session, current_operation, get_active_session

Effect = Literal["read", "change"]
EFFECTS: tuple[str, ...] = ("read", "change")

#: Who is calling, for the operation log: "user" (HTTP), "assistant:<provider>/<model>"
#: (chat), "canvas" (the workflow executor), "mcp" (an MCP client). A call none of those
#: surfaces wrapped, such as a test or a script, is "direct".
ACTOR: ContextVar[str] = ContextVar("gokaatru_actor", default="direct")
REDACTED = "[redacted]"
#: Undo and redo walk the history; every other successful change starts a new branch of it,
#: so what was undone can no longer be redone.
HISTORY_OPERATIONS = frozenset({"undo_last_change", "redo_last_change"})

#: The parameter a selectable operation gains (decisions/0011).
SELECTION_PARAMETER = "selection"
SELECTION_DESCRIPTION = "Name of a stored selection; when given, only its records are used."
#: Reported with every result computed on a selection. Records outside it are blanked, not
#: dropped: the timestamps stay, so a ramp, a calm spell or a flat line is never joined
#: across records the selection separates, and the measurement interval is still inferred
#: from the full record.
SELECTION_BASIS = (
    "records outside the selection are treated as missing, with their timestamps kept; a "
    "coverage or availability figure is therefore the share of records both selected and valid"
)


def note_undo(note: dict[str, object]) -> None:
    """Attach what undoing this call needs to its operation-log entry."""
    call = current_operation.get()
    if call is not None:
        call["undo"] = note


@contextmanager
def acting_as(actor: str) -> Iterator[None]:
    token = ACTOR.set(actor)
    try:
        yield
    finally:
        ACTOR.reset(token)

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
    "selection",
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
    #: Parameters the operation log records as "[redacted]" (credentials).
    secret_parameters: tuple[str, ...] = ()
    #: Takes a ``selection`` naming a stored selection, and then runs on its records only.
    selectable: bool = False

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"Operation name {self.name!r} is not an identifier")
        if self.effect not in EFFECTS:
            raise ValueError(f"Operation '{self.name}': effect must be one of {EFFECTS}, got {self.effect!r}")
        if self.stage not in STAGES:
            raise ValueError(f"Operation '{self.name}': unknown stage {self.stage!r}")
        if self.dry_run is not None and self.effect == "read":
            raise ValueError(f"Operation '{self.name}' reads only, so it has nothing to dry-run")
        if self.dry_run is not None and (
            inspect.signature(self.dry_run).parameters != inspect.signature(self.fn).parameters
        ):
            raise ValueError(
                f"Operation '{self.name}': its dry run must take exactly the operation's parameters, "
                "so one request previews what it would apply"
            )
        if self.selectable and self.effect != "read":
            raise ValueError(
                f"Operation '{self.name}' changes data, so it cannot run on a selection: the change "
                "would be made to a copy holding only the selected records"
            )
        unknown_secrets = set(self.secret_parameters) - set(inspect.signature(self.fn).parameters)
        if unknown_secrets:
            raise ValueError(f"Operation '{self.name}': no parameter named {sorted(unknown_secrets)} to redact")
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


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _record(
    name: str,
    effect: Effect,
    code_version: str,
    parameters: dict[str, Any],
    before: int,
    status: str,
    error: str | None,
    undo: dict[str, object] | None = None,
) -> None:
    state = get_active_session()
    entry: dict[str, object] = {
        "seq": len(state.operation_log) + 1,
        "at": datetime.now(timezone.utc).isoformat(),
        "actor": ACTOR.get(),
        "operation": name,
        "effect": effect,
        "parameters": parameters,
        "code_version": code_version,
        "data_version_before": before,
        "data_version_after": state.data_version,
        "status": status,
        "error": error,
    }
    if undo is not None:
        entry["undo"] = _json_safe(undo)
    state.operation_log.append(entry)


def _save_project() -> None:
    from server.state.project import ProjectStore

    state = get_active_session()
    if state.workspace_dir is not None:
        ProjectStore(state.workspace_dir).save(state)


def record_route_change(state: Any, method: str, route: str) -> None:
    """Log and save a change made through a hand-written HTTP route.

    Those routes call the private functions, not the operations, so the wrapper never sees
    them. The request body is not recorded: it can carry a credential (BrightHub login).
    Kept until Phases 2 and 3 move the interface onto the generated routes.
    """
    from server.state.project import ProjectStore
    from server.state.session import bind_session

    with bind_session(state), acting_as("user"):
        _record(f"http {method} {route}", "change", ENGINE_VERSION, {}, state.data_version, "ok", None)
    if state.workspace_dir is not None:
        ProjectStore(state.workspace_dir).save(state)


#: Per-record frames held beside the working data, blanked with it on a selection so a read
#: that takes its records from one of them cannot see what the selection leaves out.
PER_RECORD_FRAMES: tuple[str, ...] = ("raw_timeseries_df", "shear_timeseries_df", "roughness_timeseries_df")


def selection_view(state: SessionState, name: str) -> tuple[SessionState, dict[str, object]]:
    """A copy of the session whose records outside the selection are missing.

    The working frame and every per-record frame beside it are blanked; the copy shares
    everything else with the session, which is safe because only a read runs on it
    (``Operation`` refuses a selectable change) and every read is tested to leave the
    session unchanged.
    """
    from server.tools.selections import selection_mask

    mask = selection_mask(state, name)
    frame = state.timeseries_df
    replica = copy.copy(state)
    replica.timeseries_df = frame.where(np.broadcast_to(mask[:, None], frame.shape))
    selected = frame.index[mask]
    for attribute in PER_RECORD_FRAMES:
        other = getattr(state, attribute)
        if other is not None:
            kept = other.index.isin(selected)
            setattr(replica, attribute, other.where(np.broadcast_to(kept[:, None], other.shape)))
    return replica, selection_disclosure(name, mask)


def selection_disclosure(name: str, mask: np.ndarray) -> dict[str, object]:
    """What a result computed on a selection reports about it."""
    return {
        "name": name,
        "records": int(mask.sum()),
        "of_records": int(mask.size),
        "basis": SELECTION_BASIS,
    }


def _selectable_signature(fn: Callable[..., Any], name: str) -> tuple[inspect.Signature, dict[str, Any]]:
    """The function's signature and resolved annotations with the selection parameter added."""
    signature = inspect.signature(fn)
    if SELECTION_PARAMETER in signature.parameters:
        raise ValueError(f"Operation '{name}' already has a parameter named '{SELECTION_PARAMETER}'")
    hints = get_type_hints(fn, include_extras=True)
    if hints.get("return") is not dict:
        raise ValueError(f"Operation '{name}' must return a dict to report the selection it ran on")
    annotation = Annotated[str, Field(description=SELECTION_DESCRIPTION)]
    parameters = [
        parameter.replace(annotation=hints.get(parameter.name, parameter.annotation))
        for parameter in signature.parameters.values()
    ]
    parameters.append(
        inspect.Parameter(SELECTION_PARAMETER, inspect.Parameter.KEYWORD_ONLY, default="", annotation=annotation)
    )
    return (
        signature.replace(parameters=parameters, return_annotation=dict),
        {**hints, SELECTION_PARAMETER: annotation},
    )


def _logged(
    fn: F,
    name: str,
    effect: Effect,
    code_version: str,
    secrets: tuple[str, ...],
    selectable: bool = False,
) -> F:
    """Wrap an operation so every call is logged and every successful change is saved.

    ``functools.wraps`` keeps the signature and annotations, so the MCP schema and the
    generated routes read exactly what they read from the bare function. A selectable
    operation's wrapper publishes one more parameter, ``selection``, and with it names
    runs the function on a copy of the session holding only the selected records.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def logged(*args: Any, **kwargs: Any) -> Any:
        selection = str(kwargs.pop(SELECTION_PARAMETER, "") or "") if selectable else ""
        try:
            bound = signature.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
        except TypeError:
            arguments = {}
        logged_arguments = {key: REDACTED if key in secrets else value for key, value in arguments.items()}
        if selection:
            logged_arguments[SELECTION_PARAMETER] = selection
        parameters = _json_safe(logged_arguments)
        state = get_active_session()
        before = state.data_version
        call = {
            "operation": name,
            "seq": len(state.operation_log) + 1,
            "parameters": parameters,
            "code_version": code_version,
        }
        token = current_operation.set(call)
        try:
            if selection:
                replica, disclosure = selection_view(state, selection)
                with bind_session(replica):
                    result = fn(*args, **kwargs)
                if SELECTION_PARAMETER in result:
                    raise RuntimeError(f"Operation '{name}' already returns a '{SELECTION_PARAMETER}' field")
                result = {**result, SELECTION_PARAMETER: disclosure}
            else:
                result = fn(*args, **kwargs)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            for key in secrets:
                secret = arguments.get(key)
                if isinstance(secret, str) and secret:
                    message = message.replace(secret, REDACTED)
            _record(name, effect, code_version, parameters, before, "error", message)
            raise
        finally:
            current_operation.reset(token)
        _record(name, effect, code_version, parameters, before, "ok", None, call.get("undo"))
        if effect == "change":
            if name not in HISTORY_OPERATIONS:
                state.undo_stack.clear()
            _save_project()
        return result

    if selectable:
        logged.__signature__, logged.__annotations__ = _selectable_signature(fn, name)  # type: ignore[attr-defined]
    return logged  # type: ignore[return-value]


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
    secret_parameters: tuple[str, ...] = (),
    selectable: bool = False,
    name: str | None = None,
    registry: OperationRegistry | None = None,
) -> Callable[[F], F]:
    """Declare a tool function as an operation and publish it as an MCP tool.

    The global registry's operations are logged (``state.operation_log``) on every call and
    save the project after every successful change; the logging wrapper is what is published
    and returned. A declaration into another registry is neither wrapped nor published, so
    tests can build registries of their own.
    """

    def declare(fn: F) -> F:
        operation_name = name or fn.__name__
        published = (
            fn
            if registry is not None
            else _logged(fn, operation_name, effect, ENGINE_VERSION, tuple(secret_parameters), selectable)
        )
        declared = (REGISTRY if registry is None else registry).register(
            Operation(
                name=operation_name,
                fn=published,
                effect=effect,
                stage=stage,
                canvas=canvas,
                assistant=assistant,
                network=network,
                disclosure=tuple(disclosure),
                standards=tuple(standards),
                dry_run=dry_run,
                secret_parameters=tuple(secret_parameters),
                selectable=selectable,
            )
        )
        if registry is None:
            _publish_to_mcp(declared)
        return published

    return declare
