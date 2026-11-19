"""project — a session's state on disk, so a project survives a restart (decisions/0010).

A project is a session workspace with three parts:

- ``uploads/``: the raw input files, kept untouched. Each one's SHA-256 is recorded in the
  catalogue, and opening a project refuses if a recorded file was changed or removed.
- ``working/``: every DataFrame the session holds, as Parquet named by its content hash, so
  an unchanged frame is never rewritten and two identical frames are stored once.
- ``catalogue.sqlite``: the raw-file hashes, which frame each state field points at, and
  every other state field as JSON.

``SessionState`` stays the in-memory view; ``save`` writes it and ``load`` restores it.
Credentials are never written (``EXCLUDED_FIELDS``).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from server.core.scenario_result import ENGINE_VERSION
from server.schemas.common import Coordinate
from server.state.session import SessionProxy, SessionState, get_active_session

CATALOGUE_NAME = "catalogue.sqlite"
WORKING_DIR = "working"
RAW_DIR = "uploads"
SCHEMA_VERSION = 1

#: Fields that are never written, and why.
EXCLUDED_FIELDS: dict[str, str] = {
    "session_id": "identity; the workspace directory carries it",
    "workspace_dir": "identity; it is where the project is",
    "updated_at": "bookkeeping, set again on every change",
    "brighthub_token": "a credential, held in memory only",
    "earthdatahub_pat": "a credential, held in memory only",
    "workflow_execution": "the status of a run in flight, meaningless after a restart",
    "persist_result_files": "a per-run switch a sweep sets on its forks, not project state",
}

_FRAME = "__frame__"
_MAP = "__map__"
_SET = "__set__"
_TUPLE = "__tuple__"
_DATETIME = "__datetime__"
_TIMESTAMP = "__timestamp__"
_COORDINATE = "__coordinate__"
_TIMEZONE = "__timezone__"
_FLOAT = "__float__"


class ProjectIntegrityError(ValueError):
    """A raw input recorded in the catalogue was changed or removed outside GoKaatru."""


# The interface sends several changing requests at once, each saving the same project. Two
# saves interleaved could each delete frame files the other had just recorded, so saves and
# loads of one workspace take turns.
_WORKSPACE_LOCKS: dict[Path, threading.Lock] = {}
_WORKSPACE_LOCKS_GUARD = threading.Lock()


def _workspace_lock(workspace_dir: Path) -> threading.Lock:
    with _WORKSPACE_LOCKS_GUARD:
        return _WORKSPACE_LOCKS.setdefault(Path(workspace_dir).resolve(), threading.Lock())


def _resolved(state: SessionState) -> SessionState:
    # The proxy has no fields of its own: saved as-is, it would write an empty project.
    return get_active_session() if isinstance(state, SessionProxy) else state


def persisted_fields(state: SessionState) -> list[str]:
    return sorted(name for name in vars(_resolved(state)) if name not in EXCLUDED_FIELDS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _frame_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    digest.update(json.dumps([str(column) for column in frame.columns]).encode("utf-8"))
    digest.update(json.dumps([str(dtype) for dtype in frame.dtypes]).encode("utf-8"))
    digest.update(str(frame.index.dtype).encode("utf-8"))
    return digest.hexdigest()


class _Encoder:
    """Turn state into JSON, setting every DataFrame aside to be written as Parquet."""

    def __init__(self) -> None:
        self.frames: dict[str, pd.DataFrame] = {}

    def encode(self, value: Any, path: str) -> Any:
        if isinstance(value, pd.DataFrame):
            self.frames[path] = value
            return {_FRAME: path}
        if isinstance(value, pd.Timestamp):
            return {_TIMESTAMP: value.isoformat()}
        if isinstance(value, datetime):
            return {_DATETIME: value.isoformat()}
        if isinstance(value, Coordinate):
            return {_COORDINATE: value.model_dump()}
        if isinstance(value, (timezone, ZoneInfo)):
            return {_TIMEZONE: _encode_timezone(value)}
        if isinstance(value, dict):
            if all(isinstance(key, str) for key in value):
                return {key: self.encode(item, f"{path}.{key}") for key, item in value.items()}
            return {
                _MAP: [
                    [self.encode(key, f"{path}.key{index}"), self.encode(item, f"{path}.{index}")]
                    for index, (key, item) in enumerate(value.items())
                ]
            }
        if isinstance(value, set):
            return {_SET: sorted(self.encode(item, path) for item in value)}
        if isinstance(value, tuple):
            return {_TUPLE: [self.encode(item, f"{path}[{index}]") for index, item in enumerate(value)]}
        if isinstance(value, list):
            return [self.encode(item, f"{path}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, (int, np.integer)):
            return int(value)
        if isinstance(value, (float, np.floating)):
            number = float(value)
            return number if math.isfinite(number) else {_FLOAT: repr(number)}
        if value is None or isinstance(value, str):
            return value
        raise TypeError(f"State at '{path}' holds a {type(value).__name__}, which the project store cannot save")


def _encode_timezone(value: timezone | ZoneInfo) -> dict[str, object]:
    if isinstance(value, ZoneInfo):
        return {"zone": value.key}
    offset = value.utcoffset(None)
    return {"offset_minutes": int(offset.total_seconds() // 60) if offset is not None else 0}


def _decode(value: Any, frames: dict[str, pd.DataFrame]) -> Any:
    if isinstance(value, list):
        return [_decode(item, frames) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        (tag, payload), = value.items()
        if tag == _FRAME:
            return frames[payload]
        if tag == _TIMESTAMP:
            return pd.Timestamp(payload)
        if tag == _DATETIME:
            return datetime.fromisoformat(payload)
        if tag == _COORDINATE:
            return Coordinate(**payload)
        if tag == _TIMEZONE:
            if "zone" in payload:
                return ZoneInfo(payload["zone"])
            return timezone(timedelta(minutes=payload["offset_minutes"]))
        if tag == _MAP:
            return {_hashable(_decode(key, frames)): _decode(item, frames) for key, item in payload}
        if tag == _SET:
            return {_hashable(_decode(item, frames)) for item in payload}
        if tag == _TUPLE:
            return tuple(_decode(item, frames) for item in payload)
        if tag == _FLOAT:
            return float(payload)
    return {key: _decode(item, frames) for key, item in value.items()}


def _hashable(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


class ProjectStore:
    """The on-disk half of one session."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.catalogue_path = self.workspace_dir / CATALOGUE_NAME
        self.working_dir = self.workspace_dir / WORKING_DIR
        self.raw_dir = self.workspace_dir / RAW_DIR

    def _connect(self) -> sqlite3.Connection:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.catalogue_path)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS raw_files (
                name TEXT PRIMARY KEY, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (field TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS frames (
                path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, columns TEXT NOT NULL, rows INTEGER NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        return connection

    def has_snapshot(self) -> bool:
        if not self.catalogue_path.exists():
            return False
        with closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM state").fetchone()[0] > 0

    # -- raw inputs --------------------------------------------------------------------

    def record_raw(self, name: str) -> str:
        """Record (or re-record, after a deliberate re-upload) one raw file's hash."""
        path = self.raw_dir / name
        sha = _sha256_file(path)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO raw_files (name, sha256, bytes, recorded_at) VALUES (?, ?, ?, ?)",
                (name, sha, path.stat().st_size, datetime.now(timezone.utc).isoformat()),
            )
        return sha

    def raw_files(self) -> dict[str, str]:
        if not self.catalogue_path.exists():
            return {}
        with closing(self._connect()) as connection:
            return dict(connection.execute("SELECT name, sha256 FROM raw_files ORDER BY name").fetchall())

    def verify_raw(self) -> dict[str, object]:
        """Refuse a project whose recorded raw inputs no longer match their hashes."""
        changed, missing = [], []
        for name, sha in self.raw_files().items():
            path = self.raw_dir / name
            if not path.exists():
                missing.append(name)
            elif _sha256_file(path) != sha:
                changed.append(name)
        if changed or missing:
            parts = []
            if changed:
                parts.append(f"changed since they were recorded: {', '.join(changed)}")
            if missing:
                parts.append(f"missing: {', '.join(missing)}")
            raise ProjectIntegrityError(
                "The project's raw inputs do not match the catalogue (" + "; ".join(parts) + "). "
                "Every result was computed from the recorded files, so the project is not opened "
                "rather than shown with results the inputs no longer support."
            )
        return {"raw_files_verified": len(self.raw_files())}

    # -- working state -----------------------------------------------------------------

    def save(self, state: SessionState) -> dict[str, object]:
        """Write the session's state; frames already on disk with the same content are reused."""
        with _workspace_lock(self.workspace_dir):
            return self._save(_resolved(state))

    def _save(self, state: SessionState) -> dict[str, object]:
        encoder = _Encoder()
        encoded = {name: encoder.encode(getattr(state, name), name) for name in persisted_fields(state)}
        self.working_dir.mkdir(parents=True, exist_ok=True)
        written = reused = 0
        frame_rows: list[tuple[str, str, str, int]] = []
        for path, frame in encoder.frames.items():
            sha = _frame_hash(frame)
            target = self.working_dir / f"{sha}.parquet"
            if target.exists():
                reused += 1
            else:
                stored = frame.copy(deep=False)
                stored.columns = [str(column) for column in frame.columns]
                temporary = target.with_name(f"{sha}.{uuid4().hex}.tmp")
                stored.to_parquet(temporary)
                os.replace(temporary, target)
                written += 1
            # Parquet keeps the index but not non-string column labels or the columns' name.
            columns = json.dumps(
                {"labels": _Encoder().encode(list(frame.columns), "columns"), "name": frame.columns.name}
            )
            frame_rows.append((path, sha, columns, int(len(frame))))

        recorded = 0
        known = self.raw_files()
        if self.raw_dir.exists():
            for path in sorted(self.raw_dir.iterdir()):
                if path.is_file() and path.name not in known:
                    self.record_raw(path.name)
                    recorded += 1

        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM state")
            connection.execute("DELETE FROM frames")
            connection.executemany(
                "INSERT INTO state (field, value) VALUES (?, ?)",
                [(name, json.dumps(value)) for name, value in encoded.items()],
            )
            connection.executemany("INSERT INTO frames (path, sha256, columns, rows) VALUES (?, ?, ?, ?)", frame_rows)
            connection.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                [("saved_at", datetime.now(timezone.utc).isoformat()), ("engine_version", ENGINE_VERSION)],
            )
        live = {sha for _, sha, _, _ in frame_rows}
        for stale in self.working_dir.glob("*.parquet"):
            if stale.stem not in live:
                stale.unlink()
        return {"frames_written": written, "frames_reused": reused, "raw_files_recorded": recorded}

    def load(self, state: SessionState) -> bool:
        """Restore a saved session into ``state``. Returns False when nothing was saved."""
        with _workspace_lock(self.workspace_dir):
            return self._load(_resolved(state))

    def _load(self, state: SessionState) -> bool:
        if not self.has_snapshot():
            return False
        self.verify_raw()
        with closing(self._connect()) as connection:
            fields = dict(connection.execute("SELECT field, value FROM state").fetchall())
            frame_rows = connection.execute("SELECT path, sha256, columns FROM frames").fetchall()
        frames: dict[str, pd.DataFrame] = {}
        for path, sha, columns in frame_rows:
            frame = pd.read_parquet(self.working_dir / f"{sha}.parquet")
            meta = json.loads(columns)
            frame.columns = pd.Index(_decode(meta["labels"], {}), name=meta["name"])
            frames[path] = frame
        for name, value in fields.items():
            setattr(state, name, _decode(json.loads(value), frames))
        return True
