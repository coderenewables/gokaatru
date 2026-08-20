"""sweep — HTTP surface for the scenario-sweep engine (design doc §7.6).

Five things the frontend needs: cost a sweep before launching it, run one, watch it,
read a finished one back, and take away the runconfig of whichever scenario the analyst
decides to stand behind.

The estimate endpoint exists because the Sweep Designer's counter is the element that
stops an accidental multi-hour run (§9.1), and it has to be able to price a specification
without executing it.
"""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.api.deps import get_session_state, to_bad_request
from server.core.admissibility import DEFAULT_THRESHOLDS, GateThresholds
from server.core.powercurve import power_curve_names
from server.core.reanalysis import reference_source_names
from server.core.scenario_pipeline import SHEAR_MODELS, UNIMPLEMENTED_SHEAR_MODELS
from server.core.sensor_selection import POLICIES, resolve_all
from server.core.sweep import (
    SweepSpec,
    list_sweeps,
    load_scenario_runconfig,
    load_sweep,
    run_sweep,
)
from server.state.session import SessionState

router = APIRouter(prefix="/sessions/{session_id}/sweep", tags=["sweep"])


class SweepRequest(BaseModel):
    """The axis levels to cross, plus optional overrides."""

    shear_fit_policies: list[str] = Field(default_factory=lambda: ["nearest_2"])
    reference_policies: list[str] = Field(default_factory=lambda: ["nearest_2"])
    shear_models: list[str] = Field(default_factory=lambda: ["power_law_mean"])
    reference_sources: list[str] = Field(default_factory=lambda: list(reference_source_names()))
    ltc_algorithms: list[str] = Field(default_factory=lambda: ["variance_ratio"])
    hub_height_m: float | None = None
    analyst_shear_alpha: float | None = None
    thresholds: dict[str, float] | None = None
    sweep_id: str | None = None

    def to_spec(self) -> SweepSpec:
        return SweepSpec(
            shear_fit_policies=tuple(self.shear_fit_policies),
            reference_policies=tuple(self.reference_policies),
            shear_models=tuple(self.shear_models),
            reference_sources=tuple(self.reference_sources),
            ltc_algorithms=tuple(self.ltc_algorithms),
            hub_height_m=self.hub_height_m,
            analyst_shear_alpha=self.analyst_shear_alpha,
        )

    def to_thresholds(self) -> GateThresholds:
        if not self.thresholds:
            return DEFAULT_THRESHOLDS
        known = set(DEFAULT_THRESHOLDS.as_runconfig())
        unknown = set(self.thresholds) - known
        if unknown:
            raise ValueError(f"unknown admissibility thresholds: {sorted(unknown)}")
        return GateThresholds(**{**DEFAULT_THRESHOLDS.as_runconfig(), **self.thresholds})


@router.get("/axes")
def get_sweep_axes(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, Any]:
    """Report which axis levels this session can actually run.

    Applicability is a property of the data, not of the analyst's knowledge: a lidar has
    no boom redundancy and a single-height mast cannot fit an exponent. Returning the
    resolved state lets the designer disable a level *with its reason* rather than
    letting a user select something that will fail every leaf (§9.1).
    """
    del session_id
    try:
        resolved = resolve_all(state)
    except Exception as exc:  # noqa: BLE001 — surfaced as a 400 with the reason
        raise to_bad_request(ValueError(str(exc))) from exc
    return {
        "sensor_policies": [
            {
                "name": name,
                **selection.to_runconfig(),
            }
            for name, selection in resolved.items()
        ],
        "shear_models": [
            {"name": name, "available": True} for name in SHEAR_MODELS
        ]
        + [
            {"name": name, "available": False, "reason": reason}
            for name, reason in UNIMPLEMENTED_SHEAR_MODELS.items()
        ],
        "reference_sources": [
            {"name": name, "available": state.has_reference_series(name)}
            for name in reference_source_names()
        ],
        "power_curves": list(power_curve_names()),
        "known_sensor_policies": list(POLICIES),
        "default_thresholds": DEFAULT_THRESHOLDS.as_runconfig(),
    }


@router.post("/estimate")
def estimate_sweep(
    session_id: str,
    body: SweepRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, Any]:
    """Price a specification without running it — the designer's cost counter (§9.1)."""
    del session_id, state
    spec = body.to_spec()
    return {
        "leaf_count": spec.leaf_count(),
        "prefix_count": spec.prefix_count(),
        "spec": spec.as_runconfig(),
    }


@router.post("/run")
def start_sweep(
    session_id: str,
    body: SweepRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, Any]:
    """Run a sweep to completion and return its manifest and result table."""
    del session_id
    try:
        outcome = run_sweep(
            state,
            body.to_spec(),
            thresholds=body.to_thresholds(),
            sweep_id=body.sweep_id,
        )
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    return outcome


@router.post("/run/stream")
async def stream_sweep(
    session_id: str,
    body: SweepRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> StreamingResponse:
    """Run a sweep, streaming one event per scenario as it completes (§9.2)."""
    del session_id
    spec = body.to_spec()
    try:
        thresholds = body.to_thresholds()
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_progress(event: Any) -> None:
        # Called from the worker thread; hand the event to the event loop safely.
        loop.call_soon_threadsafe(queue.put_nowait, event.as_record())

    async def run() -> None:
        try:
            await asyncio.to_thread(
                run_sweep,
                state,
                spec,
                thresholds=thresholds,
                sweep_id=body.sweep_id,
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001 — reported to the client as an event
            loop.call_soon_threadsafe(
                queue.put_nowait, {"event": "sweep_error", "error": repr(exc)}
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            await task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("")
def get_sweeps(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, Any]:
    """List every persisted sweep for this session, newest first."""
    del session_id
    return {"sweeps": list_sweeps(state)}


@router.get("/{sweep_id}")
def get_sweep(
    session_id: str,
    sweep_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, Any]:
    """Return one persisted sweep's manifest and full result table."""
    del session_id
    try:
        return load_sweep(state, sweep_id)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/{sweep_id}/scenarios/{config_hash}/runconfig")
def get_scenario_runconfig(
    session_id: str,
    sweep_id: str,
    config_hash: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, Any]:
    """Return one scenario's materialised runconfig — the file an analyst takes away."""
    del session_id
    try:
        return load_scenario_runconfig(state, sweep_id, config_hash)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
