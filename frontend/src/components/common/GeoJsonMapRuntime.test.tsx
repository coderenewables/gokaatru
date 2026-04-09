import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GeoJsonMapRuntime } from "./GeoJsonMapRuntime";

vi.mock("leaflet/dist/leaflet.css", () => ({}));

vi.mock("leaflet", () => ({
  circleMarker: vi.fn(() => ({ bindPopup: vi.fn(), bindTooltip: vi.fn() })),
  latLngBounds: vi.fn(),
}));

vi.mock("react-leaflet", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  const BaseLayer = ({ name, children }: { name: string; children: React.ReactNode }) => (
    <div data-testid="base-layer">{name}{children}</div>
  );
  const LayersControl = Object.assign(
    ({ children }: { children: React.ReactNode }) => <div data-testid="layers-control">{children}</div>,
    { BaseLayer },
  );
  return {
    Circle: ({ radius }: { radius: number }) => <div data-testid="distance-ring">{radius}</div>,
    GeoJSON: ({ data }: { data: { features: unknown[] } }) => <div data-testid="geojson">{data.features.length}</div>,
    LayersControl,
    MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="map-container">{children}</div>,
    TileLayer: ({ url }: { url: string }) => <div data-testid="tile-layer">{url}</div>,
    useMap: () => ({ fitBounds: vi.fn() }),
  };
});

describe("GeoJsonMapRuntime", () => {
  it("renders three mast distance rings when a mast feature is present", () => {
    render(
      <GeoJsonMapRuntime
        featureCollection={{
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [56.78, 12.34] },
              properties: { type: "mast", name: "Measurement Mast" },
            },
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [56.9, 12.45] },
              properties: { type: "era5_node", distance_km: 10, bearing: "NE" },
            },
          ],
        }}
      />,
    );

    expect(screen.getAllByTestId("distance-ring")).toHaveLength(3);
    expect(screen.getAllByTestId("base-layer").map((node) => node.textContent)).toEqual(
      expect.arrayContaining(["Streethttps://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", "Terrainhttps://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}.png", "Satellitehttps://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"]),
    );
  });
});