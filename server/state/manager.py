"""manager — Session registry for browser workspaces.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from server.state.session import SessionState


class SessionManager:
    """Manage workspace-scoped SessionState instances for browser clients."""

    def __init__(self, base_dir: Path | None = None) -> None:
        """Initialize the session registry rooted at the configured sessions directory."""
        self.base_dir = Path("data") / "sessions" if base_dir is None else Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, SessionState] = {}

    def _workspace_dir(self, session_id: str) -> Path:
        """Return the workspace directory path for a given session identifier."""
        return self.base_dir / session_id

    def _prepare_workspace(self, workspace_dir: Path) -> None:
        """Create the required directory structure and runconfig file for a workspace."""
        workspace_dir.mkdir(parents=True, exist_ok=True)
        for child in ("uploads", "era5_cache", "ltc_results"):
            (workspace_dir / child).mkdir(parents=True, exist_ok=True)
        runconfig_path = workspace_dir / "runconfig.json"
        if not runconfig_path.exists():
            runconfig_path.write_text("{}\n", encoding="utf-8")

    def _clear_workspace(self, workspace_dir: Path) -> None:
        """Remove and recreate a workspace directory while preserving its root path."""
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        self._prepare_workspace(workspace_dir)

    def create_session(self) -> SessionState:
        """Create a new managed SessionState with its own workspace directory."""
        session_id = uuid4().hex
        workspace_dir = self._workspace_dir(session_id)
        self._prepare_workspace(workspace_dir)
        state = SessionState()
        state.session_id = session_id
        state.workspace_dir = workspace_dir
        state.touch()
        self._sessions[session_id] = state
        return state

    def get_session(self, session_id: str) -> SessionState:
        """Return an existing managed session or raise when the id is unknown."""
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Unknown session_id '{session_id}'")
        return state

    def reset_session(self, session_id: str) -> SessionState:
        """Clear a managed session's in-memory and on-disk workspace data while keeping its identity."""
        state = self.get_session(session_id)
        workspace_dir = state.workspace_dir
        if workspace_dir is None:
            raise ValueError(f"Session '{session_id}' does not have a workspace directory")
        self._clear_workspace(workspace_dir)
        state.reset(preserve_workspace=True)
        return state

    def delete_session(self, session_id: str) -> None:
        """Remove a managed session from memory and delete its workspace directory."""
        state = self.get_session(session_id)
        if state.workspace_dir is not None and state.workspace_dir.exists():
            shutil.rmtree(state.workspace_dir)
        del self._sessions[session_id]

    def list_sessions(self) -> list[dict[str, str | None]]:
        """Return summaries for all active managed sessions in the current process."""
        summaries: list[dict[str, str | None]] = []
        for state in self._sessions.values():
            summaries.append(
                {
                    "session_id": state.session_id,
                    "workspace_dir": str(state.workspace_dir) if state.workspace_dir is not None else None,
                    "created_at": state.created_at.isoformat() if state.created_at is not None else None,
                    "updated_at": state.updated_at.isoformat() if state.updated_at is not None else None,
                }
            )
        return sorted(summaries, key=lambda summary: summary["created_at"] or "")


session_manager = SessionManager()
