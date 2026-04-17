"""datasets - Shared dataset pool routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from server.api.deps import get_dataset_pool_manager, get_session_state, to_bad_request
from server.state.dataset_pool import DatasetPoolManager
from server.state.session import SessionState
from server.tools.data_io import _parse_datamodel, _parse_timeseries

router = APIRouter(tags=["datasets"])


@router.post("/datasets")
def create_dataset(
    timeseries: UploadFile = File(...),
    datamodel: UploadFile = File(...),
    name: str | None = Form(default=None),
    manager: Annotated[DatasetPoolManager, Depends(get_dataset_pool_manager)] = None,
) -> dict[str, object]:
    """Upload one timeseries/datamodel pair into the shared dataset pool."""
    timeseries_bytes = timeseries.file.read()
    datamodel_bytes = datamodel.file.read()
    if not timeseries_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Timeseries upload is empty")
    if not datamodel_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Datamodel upload is empty")

    try:
        return manager.create_dataset(
            name=name,
            timeseries_filename=timeseries.filename or "timeseries.csv",
            timeseries_bytes=timeseries_bytes,
            datamodel_filename=datamodel.filename or "datamodel.json",
            datamodel_bytes=datamodel_bytes,
        )
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/datasets")
def list_datasets(
    manager: Annotated[DatasetPoolManager, Depends(get_dataset_pool_manager)],
) -> dict[str, list[dict[str, object]]]:
    """List shared datasets available to all workflow branches."""
    return {"datasets": manager.list_datasets()}


@router.get("/datasets/{dataset_id}/preview")
def get_dataset_preview(
    dataset_id: str,
    limit: int = 20,
    manager: Annotated[DatasetPoolManager, Depends(get_dataset_pool_manager)] = None,
) -> dict[str, object]:
    """Return parsed timeseries preview rows for one shared dataset."""
    try:
        return manager.get_dataset_preview(dataset_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: str,
    manager: Annotated[DatasetPoolManager, Depends(get_dataset_pool_manager)],
) -> dict[str, object]:
    """Return one shared dataset metadata payload by id."""
    try:
        return manager.get_dataset(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/datasets/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    manager: Annotated[DatasetPoolManager, Depends(get_dataset_pool_manager)],
) -> dict[str, str]:
    """Delete one shared dataset and all of its stored files."""
    try:
        manager.delete_dataset(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"status": "ok", "dataset_id": dataset_id}


@router.post("/sessions/{session_id}/datasets/{dataset_id}/load")
def load_dataset_into_session(
    session_id: str,
    dataset_id: str,
    state: Annotated[SessionState, Depends(get_session_state)] = None,
    manager: Annotated[DatasetPoolManager, Depends(get_dataset_pool_manager)] = None,
) -> dict[str, object]:
    """Load a shared dataset into one workflow session's in-memory state."""
    del session_id
    try:
        paths = manager.get_dataset_paths(dataset_id)
        timeseries_result = _parse_timeseries(state, str(paths["timeseries"]))
        datamodel_result = _parse_datamodel(state, str(paths["datamodel"]))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    state.touch()
    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "timeseries": timeseries_result,
        "datamodel": datamodel_result,
    }
