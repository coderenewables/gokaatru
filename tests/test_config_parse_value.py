"""Regression test for D18 — _parse_config_value accepts NaN/Infinity producing invalid JSON.

Verifies that _parse_config_value rejects non-standard JSON literals (NaN,
Infinity, -Infinity) and that _save_run_config uses allow_nan=False as a
belt-and-suspenders guard.
"""

from __future__ import annotations

import json
import math

import pytest

from server.tools.config import _parse_config_value


# ---------------------------------------------------------------------------
# 1. Non-standard literals are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_parse_rejects_non_finite(bad: str) -> None:
    """NaN, Infinity, and values that overflow to infinity must be rejected."""
    with pytest.raises(ValueError, match="must be finite|may not be"):
        _parse_config_value(bad)


# ---------------------------------------------------------------------------
# 2. Normal JSON values still parse correctly
# ---------------------------------------------------------------------------


def test_parse_json_number() -> None:
    assert _parse_config_value("42") == 42
    assert _parse_config_value("3.14") == pytest.approx(3.14)


def test_parse_json_string() -> None:
    assert _parse_config_value('"hello"') == "hello"


def test_parse_json_bool_null() -> None:
    assert _parse_config_value("true") is True
    assert _parse_config_value("false") is False
    assert _parse_config_value("null") is None


def test_parse_plain_string_passthrough() -> None:
    """Non-JSON strings should pass through unchanged."""
    assert _parse_config_value("hello world") == "hello world"


# ---------------------------------------------------------------------------
# 3. json.dumps allow_nan guard
# ---------------------------------------------------------------------------


def test_save_run_config_rejects_nan(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """_save_run_config must not write NaN to disk even if it slips into state.runconfig."""
    import server.main  # noqa: F401
    from server.state.session import SessionState
    from server.tools.config import _save_run_config

    state = SessionState()
    state.reset()
    state.workspace_dir = tmp_path / "workspace"
    state.workspace_dir.mkdir()
    state.session_id = "test_nan_guard"

    # Bypass _parse_config_value and inject a NaN directly into the runconfig
    # (simulates a code path that sets a value without going through the parser)
    state.runconfig = {"project_name": "test", "bad_value": float("nan")}

    with pytest.raises(ValueError):
        _save_run_config(state)
