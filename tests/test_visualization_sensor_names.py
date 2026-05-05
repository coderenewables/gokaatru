"""Regression tests for visualization sensor_names argument parsing."""
from __future__ import annotations

import pytest

from server.tools.visualization import _sensor_names


def test_sensor_names_accepts_json_array_string() -> None:
    """Support inspector multi-select payloads encoded as JSON arrays."""
    parsed = _sensor_names('["Spd_62m", "Spd_58m", "Spd_SW_45m"]')
    assert parsed == ["Spd_62m", "Spd_58m", "Spd_SW_45m"]


def test_sensor_names_accepts_csv_string() -> None:
    """Keep backward compatibility for existing comma-separated payloads."""
    parsed = _sensor_names("Spd_62m, Spd_58m, Spd_SW_45m")
    assert parsed == ["Spd_62m", "Spd_58m", "Spd_SW_45m"]


def test_sensor_names_rejects_empty_payload() -> None:
    """Reject empty selections with a clear error."""
    with pytest.raises(ValueError, match="At least one sensor name is required"):
        _sensor_names("[]")