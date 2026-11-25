"""Results of the uncertainty operations (P1-19)."""
from __future__ import annotations

from pydantic import ConfigDict, Field

from server.schemas.results._base import Number, Result, Staleness


class Components(Result):
    measurement: Number
    vertical_extrapolation: Number
    mcp: Number
    future_variability: Number


class Combination(Result):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    method: str
    component_correlation: Number
    correlated_components: list[str]
    total_at_rho_0_5_pct: Number = Field(alias="total_at_rho_0.5_pct")
    sensitivity_ratio: Number
    note: str


class PFactors(Result):
    basis: str
    p50: Number
    p75: Number
    p90: Number
    p99: Number
    note: str


class UncertaintyInputs(Result):
    measurement_height_m: Number
    hub_height_m: Number
    shear_method: str
    #: Null for an interpolated hub or invalid heights (``k_shear_basis`` says which).
    k_shear: Number
    k_shear_basis: str
    mcp_r_squared: Number
    concurrent_months: Number
    concurrent_months_used: Number
    concurrent_months_cap: Number
    iav_pct: Number
    iav_source: str
    project_life_years: Number
    algorithm: str
    is_interpolation: bool


class McpSamplingCap(Result):
    cap_months: Number
    months_available: Number
    cap_applied: bool
    u_mcp_pct: Number
    u_mcp_uncapped_pct: Number
    credit_withheld_pct: Number
    note: str
    warning: str | None = None


class DensityNormalisation(Result):
    applied: bool
    reference_density_kgm3: Number
    #: When not applied: why (no recorded site density).
    reason: str | None = None
    #: When applied: the IEC 61400-12-1 wind-speed normalisation for a pitch-regulated turbine.
    method: str | None = None
    turbine_regulation: str | None = None
    site_density_kgm3: Number = None
    speed_factor: Number = None
    note: str | None = None


class PowerCurveSummary(Result):
    name: str
    rated_kw: Number
    rotor_diameter_m: Number
    specific_power_w_m2: Number
    cut_in_mps: Number
    cut_out_mps: Number
    basis: str
    indicative_capacity_factor: Number


class ConversionGuidance(Result):
    steps: list[str]
    worked_example: str
    do_not: str
    not_included: str
    factor_is_specific: str


class EnergySensitivity(Result):
    """S = d(ln AEP)/d(ln U) on the long-term series; unavailable, with the reason, before
    there is one."""

    available: bool
    reason: str | None = None
    factor: Number = None
    density_normalisation: DensityNormalisation | None = None
    definition: str | None = None
    measured_on: str | None = None
    records: int | None = None
    mean_speed_mps: Number = None
    indicative_gross_aep_mwh: Number = None
    aep_basis: str | None = None
    power_curve: PowerCurveSummary | None = None
    how_to_convert: ConversionGuidance | None = None


class CalculateUncertaintyResult(Staleness):
    total_uncertainty_pct: Number
    components: Components
    combination: Combination
    basis: str
    p_factors: PFactors
    inputs: UncertaintyInputs
    mcp_sampling_cap: McpSamplingCap
    energy_sensitivity: EnergySensitivity


class ComputeEnergySensitivityResult(EnergySensitivity, Staleness):
    status: str
    #: ``latest_uncertainty`` when the conversion used the session's last uncertainty result.
    speed_uncertainty_source: str | None = None
