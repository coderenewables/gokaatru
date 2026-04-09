import { useEffect } from "react";

import { circleMarker, latLngBounds } from "leaflet";
import "leaflet/dist/leaflet.css";
import { Circle, GeoJSON, LayersControl, MapContainer, TileLayer, useMap } from "react-leaflet";

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

function DistanceRings({ center }: { center: [number, number] }) {
  return (
    <>
      {[10, 25, 50].map((radiusKm) => (
        <Circle
          key={radiusKm}
          center={center}
          radius={radiusKm * 1000}
          pathOptions={{
            color: "#0b7a6f",
            weight: 1,
            opacity: 0.35,
            dashArray: "6 4",
            fill: false,
          }}
        />
      ))}
    </>
  );
}

export function GeoJsonMapRuntime({ featureCollection }: GeoJsonMapRuntimeProps) {
  const mastFeature = featureCollection.features.find(
    (feature) => feature.properties.type === "mast" && feature.geometry.type === "Point" && feature.geometry.coordinates.length >= 2,
  );
  const mastCenter: [number, number] | null = mastFeature
    ? [Number(mastFeature.geometry.coordinates[1]), Number(mastFeature.geometry.coordinates[0])]
    : null;

  return (
    <div className="map-card">
      <MapContainer className="geojson-map" center={[20, 0]} zoom={2} scrollWheelZoom={false}>
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Street">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Terrain">
            <TileLayer
              attribution='Map data &copy; OpenStreetMap, Tiles &copy; Stadia Maps'
              url="https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}.png"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Satellite">
            <TileLayer
              attribution="&copy; Esri"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />
          </LayersControl.BaseLayer>
        </LayersControl>
        <GeoJSON
          data={featureCollection as never}
          pointToLayer={(feature, latlng) => {
            const isMast = (feature.properties as Record<string, unknown>).type === "mast";
            return circleMarker(latlng, {
              radius: isMast ? 10 : 6,
              color: isMast ? "#c86a2a" : "#0b7a6f",
              weight: isMast ? 3 : 2,
              fillColor: isMast ? "#fffaf0" : "#f3efe3",
              fillOpacity: 0.95,
            });
          }}
          onEachFeature={(feature, layer) => {
            const properties = (feature.properties ?? {}) as Record<string, unknown>;
            if (properties.type === "era5_node") {
              layer.bindTooltip(`${String(properties.distance_km)} km ${String(properties.bearing)}`, {
                permanent: true,
                direction: "top",
                className: "map-node-label",
              });
            }
            const label = Object.entries(properties)
              .map(([key, value]) => `${key}: ${String(value)}`)
              .join("<br />");
            layer.bindPopup(label || "Feature");
          }}
        />
        <FitBounds featureCollection={featureCollection} />
        {mastCenter ? <DistanceRings center={mastCenter} /> : null}
      </MapContainer>
    </div>
  );
}