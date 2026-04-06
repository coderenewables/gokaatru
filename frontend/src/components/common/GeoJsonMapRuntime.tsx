import { useEffect } from "react";

import { circleMarker, latLngBounds } from "leaflet";
import "leaflet/dist/leaflet.css";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";

import type { SiteMapResponse } from "../../lib/types";

type GeoJsonMapRuntimeProps = {
  featureCollection: SiteMapResponse;
};

function FitBounds({ featureCollection }: { featureCollection: SiteMapResponse }) {
  const map = useMap();

  useEffect(() => {
    const points = featureCollection.features
      .filter((feature) => feature.geometry.type === "Point" && feature.geometry.coordinates.length >= 2)
      .map((feature) => [feature.geometry.coordinates[1], feature.geometry.coordinates[0]] as [number, number]);

    if (points.length === 0) {
      return;
    }

    map.fitBounds(latLngBounds(points), { padding: [24, 24] });
  }, [featureCollection, map]);

  return null;
}

export function GeoJsonMapRuntime({ featureCollection }: GeoJsonMapRuntimeProps) {
  return (
    <div className="map-card">
      <MapContainer className="geojson-map" center={[20, 0]} zoom={2} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <GeoJSON
          data={featureCollection as never}
          pointToLayer={(_feature, latlng) =>
            circleMarker(latlng, {
              radius: 7,
              color: "#0b7a6f",
              weight: 2,
              fillColor: "#f3efe3",
              fillOpacity: 0.95,
            })
          }
          onEachFeature={(feature, layer) => {
            const properties = (feature.properties ?? {}) as Record<string, unknown>;
            const label = Object.entries(properties)
              .map(([key, value]) => `${key}: ${String(value)}`)
              .join("<br />");
            layer.bindPopup(label || "Feature");
          }}
        />
        <FitBounds featureCollection={featureCollection} />
      </MapContainer>
    </div>
  );
}