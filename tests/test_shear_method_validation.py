"""Tests for D33 — shear_method Literal constraint, alias normalisation, and conservative fallback."""

from __future__ import annotations

import math
import typing

import pytest
from pydantic import ValidationError

from server.api.schemas import CalculateUncertaintyRequest
from server.state.session import SessionState
from server.tools.uncertainty import VALID_SHEAR_METHODS, _calculate_uncertainty

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

    def test_analyst_supplied_accepted(self) -> None:
        req = CalculateUncertaintyRequest(**self._base(shear_method="analyst_supplied"))
        assert req.shear_method == "analyst_supplied"

    def test_invalid_shear_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CalculateUncertaintyRequest(**self._base(shear_method="invalid_method"))

    def test_schema_literal_matches_tool_whitelist(self) -> None:
        """The HTTP Literal and the MCP-path whitelist must name the same methods."""
        literal = typing.get_args(CalculateUncertaintyRequest.model_fields["shear_method"].annotation)
        assert set(literal) == set(VALID_SHEAR_METHODS)


class TestUnknownShearMethodRefused:
    """The MCP path has no Pydantic layer; an unknown name must raise, not take 0.03."""

    @pytest.mark.parametrize("method", ["invalid_method", "", "Log_Law", "roughness"])
    def test_unknown_method_raises(self, method: str) -> None:
        with pytest.raises(ValueError, match="Unknown shear_method"):
            _calculate_uncertainty(
                _make_state(),
                measurement_uncertainty_pct=2.0,
                measurement_height_m=80.0,
                hub_height_m=120.0,
                shear_method=method,
                mcp_r_squared=0.85,
                concurrent_hours=8760.0,
            )

    def test_unknown_method_refused_even_when_hub_interpolated(self) -> None:
        with pytest.raises(ValueError, match="Unknown shear_method"):
            _calculate_uncertainty(
                _make_state(),
                measurement_uncertainty_pct=2.0,
                measurement_height_m=80.0,
                hub_height_m=120.0,
                shear_method="invalid_method",
                mcp_r_squared=0.85,
                concurrent_hours=8760.0,
                is_interpolation=True,
            )


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
        """Fitted k_shear = min(shear_std, 0.03) (interim D2): a 0.10 scatter is capped at 0.03.

        Before 2026-11-14 this was k_shear = shear_std = 0.10 (u_vert 4.05); the cap brings
        it to 1.22, the same value as the assumed power law.
        """
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
        expected = round(0.03 * abs(math.log(120.0 / 80.0)) * 100.0, 2)
        assert result["components"]["vertical_extrapolation"] == expected
        assert result["inputs"]["k_shear"] == 0.03
        assert result["inputs"]["k_shear_basis"] == "measured_dispersion_capped"

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


class TestVerticalUncertaintyOrdering:
    """Interim D2 rule: measuring the shear never scores worse than assuming it."""

    @pytest.mark.parametrize(("measurement_m", "hub_m"), [(80.0, 120.0), (100.0, 150.0)])
    def test_fitted_le_assumed_le_analyst_supplied(self, measurement_m: float, hub_m: float) -> None:
        shared = dict(
            measurement_uncertainty_pct=2.0,
            measurement_height_m=measurement_m,
            hub_height_m=hub_m,
            mcp_r_squared=0.85,
            concurrent_hours=8760.0,
        )
        # A realistic 10-minute scatter (0.11) sits above the cap, so the fitted branch is
        # limited to the assumed constant rather than running on its own dispersion.
        fitted = _calculate_uncertainty(
            _make_state(), shear_method="calculate_shear", shear_std=0.11, **shared
        )
        assumed = _calculate_uncertainty(_make_state(), shear_method="simple_power_law", **shared)
        analyst = _calculate_uncertainty(_make_state(), shear_method="analyst_supplied", **shared)
        u_fitted = fitted["components"]["vertical_extrapolation"]
        u_assumed = assumed["components"]["vertical_extrapolation"]
        u_analyst = analyst["components"]["vertical_extrapolation"]
        assert u_fitted <= u_assumed <= u_analyst
        assert analyst["inputs"]["k_shear"] == 0.05
        assert analyst["inputs"]["k_shear_basis"] == "analyst_supplied"
