// Site overview map (spec §2.6) using Leaflet + OpenStreetMap tiles.
//
// Renders the mast, ERA5 nodes, and MERRA-2 nodes from the GET /map/site
// GeoJSON FeatureCollection. Tile layer provides the base map; markers are
// color-coded by feature type.
import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

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
  height?: number;
}

const MAST_COLOR = "#083434";
const ERA5_COLOR = "#c86a2a";
const MERRA2_COLOR = "#5f716a";

function asGeoJson(value: unknown): SiteGeoJson | null {
  if (typeof value !== "object" || value === null) return null;
  const obj = value as Record<string, unknown>;
  if (obj.type !== "FeatureCollection" || !Array.isArray(obj.features)) return null;
  return obj as unknown as SiteGeoJson;
}

// Leaflet needs explicit icon URLs; build colored circle divIcons so we don't
// depend on the asset-bundled default marker images.
function makeIcon(color: string, shape: "circle" | "square" = "circle"): L.DivIcon {
  const radius = 9;
  const inner =
    shape === "circle"
      ? `border-radius:50%`
      : `border-radius:2px;transform:rotate(45deg)`;
  return L.divIcon({
    className: "",
    html: `<span style="display:block;width:${radius * 2}px;height:${radius * 2}px;background:${color};border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,0.6);${inner}"></span>`,
    iconSize: [radius * 2, radius * 2],
    iconAnchor: [radius, radius],
  });
}

const MAST_ICON = makeIcon(MAST_COLOR, "square");
const ERA5_ICON = makeIcon(ERA5_COLOR);
const MERRA2_ICON = makeIcon(MERRA2_COLOR);

interface PointFeature {
  kind: "mast" | "era5_node" | "merra2_node";
  lat: number;
  lon: number;
  name: string;
  distanceKm?: number;
  bearing?: string;
}

function toPoints(gj: SiteGeoJson): PointFeature[] {
  return gj.features
    .filter((f) => f.geometry?.type === "Point" && Array.isArray(f.geometry.coordinates))
    .map((f) => {
      const [lon, lat] = f.geometry.coordinates as [number, number];
      const kind =
        f.properties?.type === "mast"
          ? "mast"
          : f.properties?.type === "merra2_node"
            ? "merra2_node"
            : "era5_node";
      return {
        kind,
        lat,
        lon,
        name: typeof f.properties?.name === "string" ? f.properties.name : kind,
        distanceKm: typeof f.properties?.distance_km === "number" ? f.properties.distance_km : undefined,
        bearing: typeof f.properties?.bearing === "string" ? f.properties.bearing : undefined,
      };
    });
}

// Fit the map bounds whenever the points change.
function FitBounds({ points }: { points: PointFeature[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const latlngs = points.map((p) => [p.lat, p.lon] as [number, number]);
    const bounds = L.latLngBounds(latlngs).pad(0.3);
    map.fitBounds(bounds, { animate: false });
  }, [map, points]);
  return null;
}

export function MiniMap({ geojson, height = 320 }: MiniMapProps) {
  const points = useMemo(() => {
    const gj = asGeoJson(geojson);
    return gj ? toPoints(gj) : [];
  }, [geojson]);

  if (points.length === 0) {
    return <p className="muted">No site map available.</p>;
  }

  // Center on the mast if present, else the first point.
  const center: [number, number] =
    points.find((p) => p.kind === "mast") != null
      ? [points.find((p) => p.kind === "mast")!.lat, points.find((p) => p.kind === "mast")!.lon]
      : [points[0].lat, points[0].lon];

  return (
    <div className="mini-map-wrap" style={{ height }}>
      <MapContainer center={center} zoom={10} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={points} />
        {points.map((p, i) => {
          const icon = p.kind === "mast" ? MAST_ICON : p.kind === "merra2_node" ? MERRA2_ICON : ERA5_ICON;
          return (
            <Marker key={`${p.kind}-${i}`} position={[p.lat, p.lon]} icon={icon}>
              <Popup>
                <strong>{p.name}</strong>
                {p.distanceKm != null ? <div>{p.distanceKm.toFixed(1)} km</div> : null}
                {p.bearing ? <div>bearing {p.bearing}</div> : null}
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
}
