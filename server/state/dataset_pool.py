"""dataset_pool - Shared dataset pool storage and metadata management.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from server.state.session import SessionState
from server.tools.data_io import _list_sensors, _parse_datamodel, _parse_timeseries


# The ingest loader resolves every file inside `<workspace>/uploads` and refuses anything
# that escapes it — a deliberate traversal guard.  The dataset pool stored its files flat in
# the dataset directory and handed the loader an absolute path, which the guard correctly
# rejected: `create_dataset` returned 400 "Input file is not available" on every upload, so
# the shared-dataset feature has been entirely non-functional.
#
# The fix is to give the pool the same layout the loader expects rather than to loosen the
# guard: files live under `<dataset_dir>/uploads`, and the throwaway session used for
# parsing has its workspace pointed at `<dataset_dir>`, so the resolved path is inside the
# boundary by construction.
UPLOADS_SUBDIR = "uploads"


def _safe_name(value: str | None, fallback: str) -> str:
    """Return a cleaned display name for a dataset entry."""
    if value is None:
        return fallback
    cleaned = value.strip()
    return cleaned or fallback


def _safe_suffix(filename: str | None, fallback: str) -> str:
    """Return a lowercase file suffix while preserving parser compatibility."""
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix else fallback


class DatasetPoolManager:
    """Manage shared dataset assets stored under data/datasets/{dataset_id}."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path("data") / "datasets" if base_dir is None else Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _dataset_dir(self, dataset_id: str) -> Path:
        return self.base_dir / dataset_id

    def _metadata_path(self, dataset_id: str) -> Path:
        return self._dataset_dir(dataset_id) / "metadata.json"

    def _uploads_dir(self, dataset_id: str) -> Path:
        return self._dataset_dir(dataset_id) / UPLOADS_SUBDIR

    def _resolve_stored_file(self, dataset_id: str, filename: str) -> Path:
        """Return the stored path for one dataset file, tolerating the pre-uploads layout."""
        current = self._uploads_dir(dataset_id) / filename
        if current.exists():
            return current
        # A directory written before the uploads subdirectory existed. Nothing could be
        # created through the API back then, but a hand-placed fixture may still be flat.
        return self._dataset_dir(dataset_id) / filename

    def _paths_from_metadata(self, metadata: dict[str, object]) -> dict[str, Path]:
        dataset_id = str(metadata["id"])
        return {
            "timeseries": self._resolve_stored_file(dataset_id, str(metadata["timeseries_file"])),
            "datamodel": self._resolve_stored_file(dataset_id, str(metadata["datamodel_file"])),
        }

    def _parsing_session(self, dataset_id: str) -> SessionState:
        """Return a throwaway session whose workspace is this dataset's own directory.

        Parsing runs through the ordinary ingest path so a pooled dataset is validated
        exactly as an uploaded one is — including the traversal guard, which now passes
        because the file genuinely sits inside the workspace it is resolved against.
        """
        state = SessionState()
        state.workspace_dir = self._dataset_dir(dataset_id)
        return state

    def _build_metadata(
        self,
        dataset_id: str,
        dataset_name: str,
        timeseries_file: str,
        datamodel_file: str,
    ) -> dict[str, object]:
        state = self._parsing_session(dataset_id)
        timeseries_result = _parse_timeseries(state, timeseries_file)
        _parse_datamodel(state, datamodel_file)
        sensors = _list_sensors(state).get("sensors", [])

        coverage_summary: dict[str, float] = {}
        for sensor in sensors:
            if not isinstance(sensor, dict):
                continue
            sensor_name = sensor.get("name")
            sensor_coverage = sensor.get("data_coverage_pct")
            if isinstance(sensor_name, str) and isinstance(sensor_coverage, (int, float)):
                coverage_summary[sensor_name] = float(sensor_coverage)

        coverage_values = list(coverage_summary.values())
        avg_coverage = float(sum(coverage_values) / len(coverage_values)) if coverage_values else 0.0
        resolved_name = _safe_name(state.get_project_name(), dataset_name)

        return {
            "id": dataset_id,
            "name": resolved_name,
            "timeseries_file": timeseries_file,
            "datamodel_file": datamodel_file,
            "uploaded_at": state.updated_at.isoformat() if state.updated_at is not None else "",
            "sensor_count": len(coverage_summary),
            "date_range": {
                "start": str(timeseries_result["start"]),
                "end": str(timeseries_result["end"]),
            },
            "coverage_summary": coverage_summary,
            "coverage_pct": avg_coverage,
        }

    def _load_metadata(self, dataset_id: str) -> dict[str, object]:
        path = self._metadata_path(dataset_id)
        if not path.exists():
            raise KeyError(f"Unknown dataset_id '{dataset_id}'")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Dataset metadata for '{dataset_id}' is invalid")
        return payload

    def create_dataset(
        self,
        name: str | None,
        timeseries_filename: str,
        timeseries_bytes: bytes,
        datamodel_filename: str,
        datamodel_bytes: bytes,
    ) -> dict[str, object]:
        """Create a dataset entry from uploaded files and persist metadata."""
        dataset_id = uuid4().hex
        dataset_dir = self._dataset_dir(dataset_id)
        dataset_dir.mkdir(parents=True, exist_ok=False)

        uploads_dir = self._uploads_dir(dataset_id)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        timeseries_file = f"timeseries{_safe_suffix(timeseries_filename, '.csv')}"
        datamodel_file = f"datamodel{_safe_suffix(datamodel_filename, '.json')}"
        (uploads_dir / timeseries_file).write_bytes(timeseries_bytes)
        (uploads_dir / datamodel_file).write_bytes(datamodel_bytes)

        try:
            metadata = self._build_metadata(
                dataset_id=dataset_id,
                dataset_name=_safe_name(name, dataset_id),
                timeseries_file=timeseries_file,
                datamodel_file=datamodel_file,
            )
        except Exception:
            shutil.rmtree(dataset_dir, ignore_errors=True)
            raise

        self._metadata_path(dataset_id).write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return metadata

    def list_datasets(self) -> list[dict[str, object]]:
        """List all datasets sorted by upload timestamp descending."""
        datasets: list[dict[str, object]] = []
        for candidate in self.base_dir.iterdir():
            if not candidate.is_dir():
                continue
            metadata_path = candidate / "metadata.json"
            if not metadata_path.exists():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                datasets.append(payload)

        return sorted(datasets, key=lambda item: str(item.get("uploaded_at", "")), reverse=True)

    def get_dataset(self, dataset_id: str) -> dict[str, object]:
        """Return dataset metadata by identifier."""
        return self._load_metadata(dataset_id)

    def get_dataset_paths(self, dataset_id: str) -> dict[str, Path]:
        """Return resolved file paths for timeseries and datamodel assets."""
        metadata = self._load_metadata(dataset_id)
        paths = self._paths_from_metadata(metadata)
        if not paths["timeseries"].exists() or not paths["datamodel"].exists():
            raise ValueError(f"Dataset '{dataset_id}' is missing one or more stored files")
        return paths

    def copy_into_session(self, dataset_id: str, state: SessionState) -> dict[str, str]:
        """Copy one pooled dataset into a session's uploads directory and return the filenames.

        Loading a shared dataset gives the session its own copy rather than pointing it at
        the pool. Two reasons: the ingest loader resolves files inside the session workspace
        and refuses anything outside it, and every later operation on that session — cleaning,
        undo, re-parse — expects the source file to be where an uploaded one would be. A
        session reading straight out of the pool would also let one session's cleaning surprise
        another.
        """
        paths = self.get_dataset_paths(dataset_id)
        destination = Path(state.get_data_dir()) / UPLOADS_SUBDIR
        destination.mkdir(parents=True, exist_ok=True)
        names: dict[str, str] = {}
        for key, source in paths.items():
            shutil.copy2(source, destination / source.name)
            names[key] = source.name
        return names

    def delete_dataset(self, dataset_id: str) -> None:
        """Remove one dataset directory and all stored files."""
        dataset_dir = self._dataset_dir(dataset_id)
        if not dataset_dir.exists():
            raise KeyError(f"Unknown dataset_id '{dataset_id}'")
        shutil.rmtree(dataset_dir)

    def get_dataset_preview(self, dataset_id: str, limit: int = 20) -> dict[str, object]:
        """Return a small timeseries preview suitable for inline UI rendering."""
        if limit <= 0:
            raise ValueError("Preview limit must be a positive integer")
        safe_limit = min(limit, 200)

        metadata = self._load_metadata(dataset_id)
        self.get_dataset_paths(dataset_id)  # raises if either stored file is missing
        state = self._parsing_session(dataset_id)
        parse_result = _parse_timeseries(state, str(metadata["timeseries_file"]))
        if state.timeseries_df is None:
            raise ValueError(f"Dataset '{dataset_id}' could not be parsed for preview")

        preview_df = state.timeseries_df.head(safe_limit).copy()
        preview_df.insert(0, "timestamp", preview_df.index.map(lambda value: pd.Timestamp(value).isoformat()))
        preview_df = preview_df.reset_index(drop=True)
        preview_df = preview_df.where(pd.notna(preview_df), None)

        def _json_ready(value: object) -> object:
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            if isinstance(value, datetime):
                return value.isoformat()
            if hasattr(value, "item"):
                try:
                    value = value.item()  # type: ignore[assignment]
                except Exception:
                    return str(value)
            return value

        rows = [
            {
                key: _json_ready(value)
                for key, value in row.items()
            }
            for row in preview_df.to_dict(orient="records")
        ]

        return {
            "dataset_id": dataset_id,
            "columns": list(preview_df.columns),
            "rows": rows,
            "preview_rows": len(rows),
            "total_rows": int(len(state.timeseries_df)),
            "start": str(parse_result["start"]),
            "end": str(parse_result["end"]),
            "timestep_minutes": int(parse_result["timestep_minutes"]),
        }


dataset_pool_manager = DatasetPoolManager()
