"""test_phase6_state — Verification tests for Phase 6 session management.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from server.state.manager import _CLONE_EXCLUDED, SessionManager
from server.state.session import SessionState


def test_create_session_creates_workspace_structure(tmp_path: Path) -> None:
    """Verify a new managed session creates its workspace root, subdirectories, and runconfig file."""
    manager = SessionManager(base_dir=tmp_path / "sessions")

    state = manager.create_session()

    assert state.session_id is not None
    assert state.workspace_dir == tmp_path / "sessions" / state.session_id
    assert state.created_at is not None
    assert state.updated_at is not None
    assert (state.workspace_dir / "uploads").is_dir()
    assert (state.workspace_dir / "earthdatahub_cache").is_dir()
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


def _assigned_target_attributes() -> set[str]:
    """Names of every ``target.<attr> = ...`` in ``_clone_session_state``."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(SessionManager._clone_session_state)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "target"
                ):
                    names.add(target.attr)
    return names


def test_fork_session_copies_every_session_field() -> None:
    """Every SessionState attribute is either cloned or deliberately excluded.

    A field added to SessionState and missed by _clone_session_state is silently
    dropped by fork_session. This fails until the new field is classified.
    """
    attributes = set(vars(SessionState()))
    cloned = _assigned_target_attributes()
    excluded = set(_CLONE_EXCLUDED)

    assert attributes - cloned - excluded == set()
    assert cloned | excluded <= attributes
    assert not cloned & excluded

def test_forked_session_keeps_timezone_and_data_version(tmp_path: Path) -> None:
    """A fork inherits the site UTC offset and its staleness stamps, not defaults."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    source = manager.create_session()
    source.timezone = ZoneInfo("Asia/Kolkata")
    source.data_version = {"shear": "v3"}
    source.derived_versions = {"shear_table": "v3"}

    target = SessionState()
    manager._clone_session_state(source, target)

    assert target.timezone == ZoneInfo("Asia/Kolkata")
    assert target.data_version == {"shear": "v3"}
    assert target.derived_versions == {"shear_table": "v3"}
    # Deep copies: mutating the fork must not reach back into its parent.
    target.data_version["shear"] = "v4"
    assert source.data_version == {"shear": "v3"}
