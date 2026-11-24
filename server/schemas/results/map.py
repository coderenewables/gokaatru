"""Results of the map operations: GeoJSON (P1-19)."""
from __future__ import annotations

from pydantic import ConfigDict, Field

from server.schemas.results._base import Number, Result


class PointGeometry(Result):
    type: str
    #: [longitude, latitude]
    coordinates: list[Number]


class MarkerProperties(Result):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    #: ``mast``, ``era5_node`` or ``merra2_node``.
    type: str
    marker_color: str | None = Field(None, alias="marker-color")
    distance_km: Number = None
    bearing: str | None = None


class Marker(Result):
    type: str
    geometry: PointGeometry
    properties: MarkerProperties


class MarkerCollection(Result):
    type: str
    features: list[Marker]


class GetMastMarkerResult(Marker):
    pass


class GetEra5NodeMarkersResult(MarkerCollection):
    pass


class GetSiteOverviewMapResult(MarkerCollection):
    pass
