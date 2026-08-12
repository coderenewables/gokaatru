"""Regression tests for D22 — path confinement for data_io ingest functions.

Prevents directory-traversal and arbitrary-filesystem reads by confining file
paths to the session uploads directory, mirroring the windkit_file_path pattern.
Absolute paths are accepted only if they resolve inside the confinement base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.state.session import SessionState
from server.tools.data_io import (
    _confined_file_path,
    _parse_datamodel,
    _read_tabular_file,
)


class TestConfinedFilePath:
    """D22: _confined_file_path rejects traversal and escapes from the base."""

    def test_rejects_system_path(self) -> None:
        """Absolute paths outside the session base must be rejected."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _confined_file_path(state, "/etc/passwd")

    def test_rejects_traversal(self) -> None:
        """Relative paths with '..' that escape the base must be rejected."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _confined_file_path(state, "../../etc/passwd")

    def test_rejects_deep_traversal(self) -> None:
        """Nested traversal must also be rejected."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _confined_file_path(state, "foo/../../../etc/shadow")

    def test_accepts_absolute_path_within_base(self) -> None:
        """Absolute paths that resolve inside the base directory are accepted."""
        state = SessionState()
        base = Path(state.get_data_dir()) / "uploads"
        base.mkdir(parents=True, exist_ok=True)
        absolute_base = base.resolve()
        # Construct a path that is definitely inside the base
        inside = absolute_base / "test_file.csv"
        path = _confined_file_path(state, str(inside), subdir="uploads")
        assert path == inside

    def test_accepts_relative_path_within_base(self) -> None:
        """Simple relative filenames inside the base are accepted."""
        state = SessionState()
        path = _confined_file_path(state, "data.csv", subdir="uploads")
        expected = (Path(state.get_data_dir()) / "uploads" / "data.csv").resolve()
        assert path == expected


class TestReadTabularFileConfinement:
    """D22: _read_tabular_file must not read arbitrary filesystem paths."""

    def test_rejects_system_path(self) -> None:
        """System paths outside session must raise 'Input file is not available'."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _read_tabular_file(state, "/etc/passwd")

    def test_rejects_traversal(self) -> None:
        """Traversal paths must raise 'Input file is not available'."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _read_tabular_file(state, "../../etc/passwd")

    def test_nonexistent_in_session_raises_unified_error(self) -> None:
        """A non-existent file within session must also raise the same message
        (no existence oracle)."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _read_tabular_file(state, "nonexistent_file.csv")


class TestParseDatamodelConfinement:
    """D22: _parse_datamodel must not read arbitrary filesystem paths."""

    def test_rejects_system_path(self) -> None:
        """System paths outside session must raise 'Input file is not available'."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _parse_datamodel(state, "/etc/passwd")

    def test_rejects_traversal(self) -> None:
        """Traversal paths must raise 'Input file is not available'."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _parse_datamodel(state, "../../etc/passwd")

    def test_nonexistent_in_session_raises_unified_error(self) -> None:
        """A non-existent file within session must also raise the same message."""
        state = SessionState()
        with pytest.raises(ValueError, match="Input file is not available"):
            _parse_datamodel(state, "nonexistent_datamodel.json")
