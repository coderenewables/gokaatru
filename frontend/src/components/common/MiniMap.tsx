// Lightweight SVG minimap (spec §2.6) fed by the GET /map/site GeoJSON.
//
// Renders the mast marker plus ERA5 node markers on a normalized lat/lon grid.
// No Leaflet dependency — purely for site-overview context. Distances/bearings
// are labelled from the GeoJSON properties.
import { useMemo } from "react";

interface GeoJsonFeature {
  type: "Feature";
  geometry: { type: string; coordinates: [number, number] | number[] };
  properties: Record<string, unknown>;
}
interface SiteGeoJson {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
}

interface MiniMapProps {
  geojson: unknown;
  width?: number;
  height?: number;
}

const MAST_COLOR = "#083434";
const NODE_COLOR = "#c86a2a";

function asGeoJson(value: unknown): SiteGeoJson | null {
  if (typeof value !== "object" || value === null) return null;
  const obj = value as Record<string, unknown>;
  if (obj.type !== "FeatureCollection" || !Array.isArray(obj.features)) return null;
  return obj as unknown as SiteGeoJson;
}

export function MiniMap({ geojson, width = 320, height = 220 }: MiniMapProps) {
  const points = useMemo(() => {
    const gj = asGeoJson(geojson);
    if (!gj) return [];
    return gj.features
      .filter((f) => f.geometry?.type === "Point" && Array.isArray(f.geometry.coordinates))
      .map((f) => {
        const [lon, lat] = f.geometry.coordinates as [number, number];
        const kind = f.properties?.type === "mast" ? "mast" : "node";
        return {
          kind,
          lon,
          lat,
          name: typeof f.properties?.name === "string" ? f.properties.name : kind,
          distanceKm: typeof f.properties?.distance_km === "number" ? f.properties.distance_km : undefined,
          bearing: typeof f.properties?.bearing === "string" ? f.properties.bearing : undefined,
        };
      });
  }, [geojson]);

  if (points.length === 0) {
    return <p className="muted">No site map available.</p>;
  }

  const lons = points.map((p) => p.lon);
  const lats = points.map((p) => p.lat);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  // Degenerate bounds (single point) → center.
  const spanLon = maxLon - minLon || 0.01;
  const spanLat = maxLat - minLat || 0.01;
  // Pad by 15%.
  const padX = spanLon * 0.15;
  const padY = spanLat * 0.15;
  const x0 = minLon - padX;
  const x1 = maxLon + padX;
  const y0 = minLat - padY;
  const y1 = maxLat + padY;

  const padding = 24;
  const project = (lon: number, lat: number): [number, number] => {
    const x = padding + ((lon - x0) / (x1 - x0)) * (width - 2 * padding);
    // SVG y grows downward; invert lat.
    const y = padding + ((y1 - lat) / (y1 - y0)) * (height - 2 * padding);
    return [x, y];
  };

  return (
    <svg className="mini-map" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Site overview map">
      <rect x="0" y="0" width={width} height={height} className="mini-map-bg" />
      {points.map((p, i) => {
        const [cx, cy] = project(p.lon, p.lat);
        const color = p.kind === "mast" ? MAST_COLOR : NODE_COLOR;
        return (
          <g key={`${p.name}-${i}`}>
            {p.kind === "mast" ? (
              <rect x={cx - 5} y={cy - 5} width={10} height={10} fill={color} />
            ) : (
              <circle cx={cx} cy={cy} r={5} fill={color} />
            )}
            <text x={cx + 8} y={cy + 3} className="mini-map-label">
              {p.name}
              {p.distanceKm != null ? ` (${p.distanceKm.toFixed(1)} km)` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
