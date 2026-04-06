"""test_phase6_state — Verification tests for Phase 6 session management.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.state.manager import SessionManager


def test_create_session_creates_workspace_structure(tmp_path: Path) -> None:
    """Verify a new managed session creates its workspace root, subdirectories, and runconfig file."""
    manager = SessionManager(base_dir=tmp_path / "sessions")

    state = manager.create_session()

    assert state.session_id is not None
    assert state.workspace_dir == tmp_path / "sessions" / state.session_id
    assert state.created_at is not None
    assert state.updated_at is not None
    assert (state.workspace_dir / "uploads").is_dir()
    assert (state.workspace_dir / "era5_cache").is_dir()
    assert (state.workspace_dir / "ltc_results").is_dir()
    assert (state.workspace_dir / "runconfig.json").is_file()
    assert state.get_data_dir() == str(state.workspace_dir)


def test_reset_session_preserves_workspace_metadata(tmp_path: Path) -> None:
    """Verify resetting a managed session clears workflow data while keeping its identity and workspace."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    state = manager.create_session()
    created_at = state.created_at
    assert state.workspace_dir is not None

    state.project_name = "North Ridge"
    state.runconfig["hub_height_m"] = 150.0
    result_file = state.workspace_dir / "ltc_results" / "result.csv"
    result_file.write_text("demo\n", encoding="utf-8")

    reset_state = manager.reset_session(state.session_id or "")

    assert reset_state is state
    assert reset_state.session_id == state.session_id
    assert reset_state.workspace_dir == tmp_path / "sessions" / (state.session_id or "")
    assert reset_state.created_at == created_at
    assert reset_state.updated_at is not None
    assert reset_state.project_name is None
    assert reset_state.runconfig == {}
    assert not result_file.exists()
    assert (reset_state.workspace_dir / "runconfig.json").is_file()


def test_delete_session_removes_workspace(tmp_path: Path) -> None:
    """Verify deleting a managed session removes both the registry entry and its workspace directory."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    state = manager.create_session()
    assert state.workspace_dir is not None

    manager.delete_session(state.session_id or "")

    assert not state.workspace_dir.exists()
    with pytest.raises(KeyError):
        manager.get_session(state.session_id or "")
