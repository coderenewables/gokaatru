"""config — Runconfig and workflow summary routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends

from server.api.deps import completed_steps, get_session_state, to_bad_request
from server.api.schemas import UpdateRunConfigRequest
from server.state.session import SessionState
from server.tools.config import _get_analysis_summary, _get_run_config, _save_run_config, _update_run_config

router = APIRouter(prefix="/sessions/{session_id}", tags=["config"])


@router.get("/config")
def get_config(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return the current session run configuration for the workflow UI."""
    del session_id
    return _get_run_config(state)


@router.put("/config")
def update_config(
    session_id: str,
    body: UpdateRunConfigRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Apply batched dotted-path runconfig updates and persist the session runconfig file."""
    del session_id
    try:
        for update in body.updates:
            _update_run_config(state, update.key, json.dumps(update.value))
        saved = _save_run_config(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    return {"status": "ok", "runconfig": _get_run_config(state), "file_path": saved["file_path"]}


@router.get("/summary")
def get_summary(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return an analysis-oriented workflow summary for the current session."""
    del session_id
    summary = _get_analysis_summary(state)
    summary["completed_steps"] = completed_steps(state)
    return summary
