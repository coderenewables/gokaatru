import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analysisApi, configApi, resultsApi, sessionsApi } from "../lib/api";
import type { Era5ExtractResponse, Era5Node, SiteMapResponse } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { GeoJsonMap } from "../components/common/GeoJsonMap";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";

function recordValue(record: Record<string, unknown> | null, key: string) {
  return record ? record[key] : undefined;
}

function persistedNodes(featureCollection: SiteMapResponse | undefined) {
  return (featureCollection?.features ?? [])
    .filter((feature) => feature.properties.type === "era5_node")
    .map((feature) => ({
      latitude: Number(feature.geometry.coordinates[1]),
      longitude: Number(feature.geometry.coordinates[0]),
      distance_km: Number(feature.properties.distance_km ?? 0),
      bearing: String(feature.properties.bearing ?? ""),
    }));
}

export function ReanalysisPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const activeDateRange = useWorkspaceStore((state) => state.activeDateRange);
  const setActiveDateRange = useWorkspaceStore((state) => state.setActiveDateRange);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [latestNodes, setLatestNodes] = useState<Era5Node[] | null>(null);
  const [extractResults, setExtractResults] = useState<Era5ExtractResponse[]>([]);

  const summaryQuery = useQuery({
    queryKey: ["session-summary", sessionId],
    queryFn: () => sessionsApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const configQuery = useQuery({
    queryKey: ["runconfig", sessionId],
    queryFn: () => configApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const mapQuery = useQuery({
    queryKey: ["site-map", sessionId],
    queryFn: () => resultsApi.getSiteMap(sessionId ?? ""),
    enabled: sessionId !== null && summaryQuery.data?.completed_steps.includes("era5_nodes") === true,
    staleTime: 15_000,
  });

  useEffect(() => {
    const location = typeof configQuery.data?.location === "object" && configQuery.data?.location !== null && !Array.isArray(configQuery.data.location)
      ? (configQuery.data.location as Record<string, unknown>)
      : null;
    if (typeof recordValue(location, "latitude") === "number" && latitude === "") {
      setLatitude(String(recordValue(location, "latitude")));
    }
    if (typeof recordValue(location, "longitude") === "number" && longitude === "") {
      setLongitude(String(recordValue(location, "longitude")));
    }
  }, [configQuery.data, latitude, longitude]);

  const nodes = useMemo(() => latestNodes ?? persistedNodes(mapQuery.data), [latestNodes, mapQuery.data]);

  const findNodesMutation = useMutation({
    mutationFn: () => analysisApi.findEra5Nodes(sessionId ?? "", { latitude: Number(latitude), longitude: Number(longitude) }),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestNodes(result.nodes);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["site-map", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const extractAllMutation = useMutation({
    mutationFn: async () =>
      Promise.all(
        nodes.map((node) =>
          analysisApi.extractEra5(sessionId ?? "", {
            latitude: node.latitude,
            longitude: node.longitude,
            start_date: activeDateRange.startDate,
            end_date: activeDateRange.endDate,
          }),
        ),
      ),
    onSuccess: (results) => {
      setLatestError(null);
      setExtractResults(results);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const interpolateMutation = useMutation({
    mutationFn: () => analysisApi.interpolateEra5(sessionId ?? ""),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["site-map", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="Reanalysis" detail="Find surrounding ERA5 nodes, extract hourly data, and interpolate it to the site." />
        <EmptyState title="Session required" detail="Create a session before running reanalysis discovery and extraction." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="Reanalysis" detail="Drive the full ERA5 workflow from site coordinates through extracted node datasets and site interpolation." />

      <div className="metric-grid">
        <MetricCard label="Node count" value={String(nodes.length)} tone="accent" />
        <MetricCard label="Extracted datasets" value={String(extractResults.length)} />
        <MetricCard label="Interpolated" value={summaryQuery.data?.era5_interpolated_loaded ? "Ready" : "Pending"} />
        <MetricCard label="Date range" value={`${activeDateRange.startDate} to ${activeDateRange.endDate}`} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Site coordinate and extraction range</span>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Latitude</span>
              <input value={latitude} onChange={(event) => setLatitude(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Longitude</span>
              <input value={longitude} onChange={(event) => setLongitude(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Start date</span>
              <input
                type="date"
                value={activeDateRange.startDate}
                onChange={(event) => setActiveDateRange({ ...activeDateRange, startDate: event.target.value })}
              />
            </label>
            <label className="form-field">
              <span>End date</span>
              <input
                type="date"
                value={activeDateRange.endDate}
                onChange={(event) => setActiveDateRange({ ...activeDateRange, endDate: event.target.value })}
              />
            </label>
          </div>
          <div className="button-row wrap">
            <button className="primary-button" type="button" onClick={() => findNodesMutation.mutate()}>
              Find ERA5 Nodes
            </button>
            <button className="secondary-button" type="button" disabled={nodes.length === 0} onClick={() => extractAllMutation.mutate()}>
              Extract All Nodes
            </button>
            <button className="secondary-button" type="button" onClick={() => interpolateMutation.mutate()}>
              Interpolate Site
            </button>
          </div>
        </article>

        <GeoJsonMap
          featureCollection={mapQuery.data}
          emptyTitle="Map unavailable"
          emptyDetail="Find ERA5 nodes first to render the mast and node markers."
        />
      </div>

      <article className="content-card stack-gap">
        <span className="eyebrow">ERA5 node table</span>
        <DataTable<Era5Node>
          columns={[
            { key: "lat", header: "Latitude", cell: (row) => row.latitude.toFixed(4) },
            { key: "lon", header: "Longitude", cell: (row) => row.longitude.toFixed(4) },
            { key: "distance", header: "Distance", cell: (row) => `${row.distance_km.toFixed(1)} km` },
            { key: "bearing", header: "Bearing", cell: (row) => row.bearing },
          ]}
          rows={nodes}
          getRowKey={(row) => `${row.latitude}-${row.longitude}`}
          emptyTitle="No nodes loaded"
          emptyDetail="Run node discovery to populate the surrounding ERA5 support nodes."
        />
      </article>

      <article className="content-card stack-gap">
        <span className="eyebrow">Extraction results</span>
        <DataTable<Era5ExtractResponse>
          columns={[
            { key: "node", header: "Node", cell: (row) => `${row.latitude.toFixed(2)}, ${row.longitude.toFixed(2)}` },
            { key: "rows", header: "Rows", cell: (row) => row.rows },
            { key: "cached", header: "Cached", cell: (row) => (row.cached ? "Yes" : "No") },
            { key: "vars", header: "Variables", cell: (row) => row.variables.join(", ") },
          ]}
          rows={extractResults}
          getRowKey={(row) => `${row.latitude}-${row.longitude}-${row.start}`}
          emptyTitle="No ERA5 datasets extracted"
          emptyDetail="After node extraction, each loaded node dataset will be summarized here."
        />
      </article>
    </section>
  );
}