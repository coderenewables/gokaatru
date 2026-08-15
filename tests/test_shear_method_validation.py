"""Tests for D33 — shear_method Literal constraint, alias normalisation, and conservative fallback."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from server.api.schemas import CalculateUncertaintyRequest
from server.state.session import SessionState
from server.tools.uncertainty import _calculate_uncertainty

# ---------------------------------------------------------------------------
# Pydantic schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """CalculateUncertaintyRequest must only accept the four valid shear_method literals."""

    def _base(self, **overrides: object) -> dict[str, object]:
        defaults: dict[str, object] = {
            "measurement_uncertainty_pct": 2.0,
            "measurement_height_m": 80.0,
            "hub_height_m": 120.0,
            "shear_method": "simple_power_law",
            "mcp_r_squared": 0.85,
            "concurrent_hours": 8760.0,
        }
        defaults.update(overrides)
        return defaults

    def test_power_law_alias_accepted(self) -> None:
        """'power_law' is a valid Literal member and should parse without error."""
        req = CalculateUncertaintyRequest(**self._base(shear_method="power_law"))
        assert req.shear_method == "power_law"

    def test_log_law_accepted(self) -> None:
        req = CalculateUncertaintyRequest(**self._base(shear_method="log_law"))
        assert req.shear_method == "log_law"

    def test_simple_power_law_accepted(self) -> None:
        req = CalculateUncertaintyRequest(**self._base(shear_method="simple_power_law"))
        assert req.shear_method == "simple_power_law"

    def test_calculate_shear_accepted(self) -> None:
        req = CalculateUncertaintyRequest(**self._base(shear_method="calculate_shear"))
        assert req.shear_method == "calculate_shear"

    def test_invalid_shear_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalculateUncertaintyRequest(**self._base(shear_method="invalid_method"))


# ---------------------------------------------------------------------------
# Internal function: alias mapping and k_shear values
# ---------------------------------------------------------------------------


def _make_state() -> SessionState:
    state = SessionState()
    state.reset()
    return state


class TestShearMethodNormalization:
    """_calculate_uncertainty must normalise aliases and use conservative k_shear."""

    def test_power_law_maps_to_k_shear_003(self) -> None:
        """'power_law' is normalised to 'simple_power_law' → k_shear = 0.03."""
        result = _calculate_uncertainty(
            _make_state(),
            measurement_uncertainty_pct=2.0,
            measurement_height_m=80.0,
            hub_height_m=120.0,
            shear_method="power_law",
            mcp_r_squared=0.85,
            concurrent_hours=8760.0,
        )
        # Expected u_vert for k_shear=0.03: 0.03 * |ln(120/80)| * 100 = 0.03 * 0.4055 * 100 = 1.2164
        expected = round(0.03 * abs(math.log(120.0 / 80.0)) * 100.0, 2)
        assert result["components"]["vertical_extrapolation"] == expected
        # inputs reports original method
        assert result["inputs"]["shear_method"] == "power_law"

    def test_log_law_uses_k_shear_005(self) -> None:
        """'log_law' → k_shear = 0.05 (conservative)."""
        result = _calculate_uncertainty(
            _make_state(),
            measurement_uncertainty_pct=2.0,
            measurement_height_m=80.0,
            hub_height_m=120.0,
            shear_method="log_law",
            mcp_r_squared=0.85,
            concurrent_hours=8760.0,
        )
        expected = round(0.05 * abs(math.log(120.0 / 80.0)) * 100.0, 2)
        assert result["components"]["vertical_extrapolation"] == expected
        assert result["inputs"]["shear_method"] == "log_law"

    def test_simple_power_law_uses_k_shear_003(self) -> None:
        result = _calculate_uncertainty(
            _make_state(),
            measurement_uncertainty_pct=2.0,
            measurement_height_m=80.0,
            hub_height_m=120.0,
            shear_method="simple_power_law",
            mcp_r_squared=0.85,
            concurrent_hours=8760.0,
        )
        expected = round(0.03 * abs(math.log(120.0 / 80.0)) * 100.0, 2)
        assert result["components"]["vertical_extrapolation"] == expected

    def test_calculate_shear_with_shear_std(self) -> None:
        """When shear_method='calculate_shear' and shear_std > 0, k_shear = shear_std."""
        result = _calculate_uncertainty(
            _make_state(),
            measurement_uncertainty_pct=2.0,
            measurement_height_m=80.0,
            hub_height_m=120.0,
            shear_method="calculate_shear",
            mcp_r_squared=0.85,
            concurrent_hours=8760.0,
            shear_std=0.10,
        )
        expected = round(0.10 * abs(math.log(120.0 / 80.0)) * 100.0, 2)
        assert result["components"]["vertical_extrapolation"] == expected

    def test_calculate_shear_zero_std_falls_to_003(self) -> None:
        """When shear_std=0 with calculate_shear, the condition fails and we get k_shear=0.03."""
        result = _calculate_uncertainty(
            _make_state(),
            measurement_uncertainty_pct=2.0,
            measurement_height_m=80.0,
            hub_height_m=120.0,
            shear_method="calculate_shear",
            mcp_r_squared=0.85,
            concurrent_hours=8760.0,
            shear_std=0.0,
        )
        expected = round(0.03 * abs(math.log(120.0 / 80.0)) * 100.0, 2)
        assert result["components"]["vertical_extrapolation"] == expected

    def test_no_k_shear_zero_one(self) -> None:
        """The old default k_shear=0.01 path should no longer be reachable.

        Every valid shear_method should give k_shear >= 0.03.
        """
        for method in ("simple_power_law", "power_law", "log_law"):
            result = _calculate_uncertainty(
                _make_state(),
                measurement_uncertainty_pct=2.0,
                measurement_height_m=80.0,
                hub_height_m=120.0,
                shear_method=method,
                mcp_r_squared=0.85,
                concurrent_hours=8760.0,
            )
            u_vert = result["components"]["vertical_extrapolation"]
            # k_shear = u_vert / (|ln(120/80)| * 100) must be >= 0.03
            factor = abs(math.log(120.0 / 80.0)) * 100.0
            k = u_vert / factor
            assert k >= 0.03, f"{method} produced k_shear={k}, expected >= 0.03"
