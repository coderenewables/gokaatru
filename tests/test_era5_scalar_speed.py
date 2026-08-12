"""Regression tests for D12 — ERA5 scalar speed interpolation convention.

The fix removed dead code (unreachable vector-speed branch) and made the
scalar speed convention explicit in the docstring, comments, and response.
No numeric change — behaviour is identical before and after.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from server.tools.era5 import _interpolate_era5_to_site


class TestEra5ScalarSpeedConvention:
    """D12: scalar speed interpolation must be documented and dead code removed."""

    def test_dead_branch_removed(self) -> None:
        """The unreachable 'if Spd_100m not in result.columns' branch must be gone."""
        source = inspect.getsource(_interpolate_era5_to_site)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_str = ast.dump(node.test)
                # The dead branch tested "Spd_100m" not in *result*.columns
                # The legitimate guard tests "Spd_100m" not in *frame*.columns
                if "Spd_100m" in test_str and "result" in test_str:
                    pytest.fail(
                        "Dead branch 'if Spd_100m not in result.columns' still present "
                        "in _interpolate_era5_to_site — it should have been removed in D12"
                    )

    def test_docstring_mentions_scalar(self) -> None:
        """The private function docstring must mention scalar speed interpolation."""
        doc = _interpolate_era5_to_site.__doc__
        assert doc is not None
        assert "scalar" in doc.lower(), (
            "Docstring of _interpolate_era5_to_site should mention scalar speed "
            "interpolation convention"
        )

    def test_response_includes_speed_interpolation_key(self) -> None:
        """The response dict construction must include 'speed_interpolation'."""
        source = inspect.getsource(_interpolate_era5_to_site)
        assert '"speed_interpolation"' in source or "'speed_interpolation'" in source, (
            "Return dict of _interpolate_era5_to_site must include "
            "'speed_interpolation': 'scalar'"
        )
