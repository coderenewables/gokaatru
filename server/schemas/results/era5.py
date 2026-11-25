"""Results of the ERA5 and EarthDataHub operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class ComputeEra5WindSpeedResult(Result):
    status: str
    mean_speed: Number
    record_count: int


class CredentialResult(Result):
    status: str
    configured: bool


class EarthdatahubClearCredentialResult(CredentialResult):
    pass


class EarthdatahubSetCredentialResult(CredentialResult):
    pass


class EarthdatahubStatusResult(Result):
    configured: bool


class ExtractEra5DataResult(Result):
    status: str
    latitude: Number
    longitude: Number
    rows: int
    start: str
    end: str
    variables: list[str]
    cached: bool


class Era5Node(Result):
    latitude: Number
    longitude: Number
    distance_km: Number
    #: A compass point, from the site to the node.
    bearing: str


class FindEra5NodesResult(Result):
    nodes: list[Era5Node]
    grid_resolution_deg: Number


class SkippedVariable(Result):
    variable: str
    missing_from_nodes: list[str]


class InterpolateEra5ToSiteResult(Result):
    status: str
    rows: int
    method: str
    #: The interpolation each variable actually used, by variable.
    method_by_variable: dict[str, str]
    method_is_mixed: bool
    variables: list[str]
    skipped_variables: list[SkippedVariable]
    speed_interpolation: str
    reference_source: str
    reference_height_m: Number
    speed_column: str
    direction_column: str
    nodes_used: int
    reference_source_note: str
    #: Present when a variable was skipped because a node does not carry it.
    warning: str | None = None
