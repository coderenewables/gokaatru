"""operations — one HTTP route per declared operation (decisions/0009-operation-registry.md).

Generated from the registry, beside the hand-written routes the current interface calls,
which stay until Phases 2 and 3 move it across. Each route takes the operation's parameters
as a JSON body, validated against a model built from the function's signature with extra
fields refused (the MCP schema refuses them too), runs the function with the session bound
as the MCP transport and the chat route bind it, and maps ``ValueError`` to 400 and
``RuntimeError`` to 502.
"""
# No ``from __future__ import annotations``: FastAPI reads each generated route's body type
# from its signature, and a postponed annotation would name a model it cannot resolve.

import inspect
from typing import Annotated, Any, get_type_hints

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

import server.main  # noqa: F401 — importing it declares every operation
from server.api.deps import get_session_state
from server.operations import REGISTRY, Operation, acting_as
from server.schemas.results._base import ErrorDetail
from server.state.session import SessionState, bind_session

router = APIRouter(tags=["operations"])

OPERATION_PATH = "/sessions/{session_id}/operations/{name}"


def _model_name(declared: Operation) -> str:
    return "".join(part.capitalize() for part in declared.name.split("_")) + "Parameters"


def request_model(declared: Operation) -> type[BaseModel]:
    """The operation's parameters as a Pydantic model, from the function's signature."""
    hints = get_type_hints(declared.fn)
    fields: dict[str, Any] = {}
    for parameter in inspect.signature(declared.fn).parameters.values():
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (hints.get(parameter.name, Any), default)
    return create_model(_model_name(declared), __config__=ConfigDict(extra="forbid"), **fields)


def run_operation(function: Any, state: SessionState, arguments: dict[str, Any]) -> Any:
    with bind_session(state), acting_as("user"):
        try:
            return function(**arguments)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


def _endpoint(declared: Operation, model: type[BaseModel], function: Any, suffix: str = ""):
    def endpoint(
        session_id: str,
        state: Annotated[SessionState, Depends(get_session_state)],
        body: Annotated[model | None, Body()] = None,
    ) -> Any:
        del session_id
        if body is None:
            try:
                body = model()
            except ValidationError as exc:
                raise RequestValidationError(exc.errors()) from exc
        return run_operation(function, state, body.model_dump())

    endpoint.__name__ = f"operation_{declared.name}{suffix}"
    endpoint.__doc__ = declared.description
    return endpoint


def _responses(result: type[BaseModel] | None) -> dict[int | str, dict[str, Any]]:
    """The documented responses. Documentation only: the route returns what the operation
    returns, so a result model can never turn a working call into an error."""
    responses: dict[int | str, dict[str, Any]] = {
        400: {"model": ErrorDetail, "description": "Refused: the request cannot be answered as asked"},
        502: {"model": ErrorDetail, "description": "An upstream service failed"},
    }
    if result is not None:
        responses[200] = {"model": result, "description": "The operation's result"}
    return responses


def _add_routes() -> None:
    for declared in REGISTRY:
        model = request_model(declared)
        path = OPERATION_PATH.replace("{name}", declared.name)
        router.add_api_route(
            path,
            _endpoint(declared, model, declared.fn),
            methods=["POST"],
            name=f"operation_{declared.name}",
            summary=declared.name,
            responses=_responses(declared.result),
        )
        if declared.dry_run is not None:
            # The same body as the operation itself: the preview is of exactly that request.
            router.add_api_route(
                f"{path}/preview",
                _endpoint(declared, model, declared.dry_run, "_preview"),
                methods=["POST"],
                name=f"operation_{declared.name}_preview",
                summary=f"{declared.name} (dry run)",
                responses=_responses(declared.preview_result),
            )


@router.get("/operations")
def list_operations() -> list[dict[str, Any]]:
    """Every declared operation: what it does to data, where it sits, and its parameters."""
    return [
        {
            "name": declared.name,
            "description": declared.description,
            "effect": declared.effect,
            "stage": declared.stage,
            "canvas": declared.canvas,
            "assistant": declared.assistant,
            "network": declared.network,
            "disclosure": list(declared.disclosure),
            "standards": list(declared.standards),
            "code_version": declared.code_version,
            "dry_run": declared.dry_run is not None,
            "selectable": declared.selectable,
            "parameters": declared.parameters,
        }
        for declared in REGISTRY
    ]


_add_routes()
