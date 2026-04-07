import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, analysisApi, configApi, resultsApi, sessionsApi } from "../lib/api";
import type { Era5ExtractResponse, Era5InterpolationResponse, Era5Node, SiteMapResponse } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { GeoJsonMap } from "../components/common/GeoJsonMap";
import { LoadingState } from "../components/common/LoadingState";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";

type ExtractProgress = {
  total: number;
  completed: number;
  currentNodeLabel: string | null;
  status: string;
  errorMessage?: string;
};

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

function nodeLabel(node: Era5Node) {
  return `${node.latitude.toFixed(2)}, ${node.longitude.toFixed(2)}`;
}

function extractErrorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 502) {
    return "EarthDataHub interrupted the ERA5 download before the payload completed. Retry extraction. If it fails again, shorten the date range and try again.";
  }
  if (error instanceof ApiError && typeof error.detail === "string") {
    return error.detail;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "ERA5 extraction failed. Retry the download and check the selected node range.";
}

export function ReanalysisPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const activeDateRange = useWorkspaceStore((state) => state.activeDateRange);
  const setActiveDateRange = useWorkspaceStore((state) => state.setActiveDateRange);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [extractResults, setExtractResults] = useState<Era5ExtractResponse[]>([]);
  const [latestInterpolation, setLatestInterpolation] = useState<Era5InterpolationResponse | null>(null);
  const [extractProgress, setExtractProgress] = useState<ExtractProgress | null>(null);

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

  const era5NodesQuery = useQuery({
    queryKey: ["era5-nodes", sessionId],
    queryFn: async () => persistedNodes(await resultsApi.getSiteMap(sessionId ?? "")),
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

  useEffect(() => {
    if (mapQuery.data && sessionId !== null) {
      queryClient.setQueryData(["era5-nodes", sessionId], persistedNodes(mapQuery.data));
    }
  }, [mapQuery.data, queryClient, sessionId]);

  const nodes = useMemo(() => era5NodesQuery.data ?? [], [era5NodesQuery.data]);

  const findNodesMutation = useMutation({
    mutationFn: () => analysisApi.findEra5Nodes(sessionId ?? "", { latitude: Number(latitude), longitude: Number(longitude) }),
    onSuccess: (result) => {
      setLatestError(null);
      if (sessionId !== null) {
        queryClient.setQueryData(["era5-nodes", sessionId], result.nodes);
      }
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["site-map", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const extractAllMutation = useMutation({
    mutationFn: async () => {
      const results: Era5ExtractResponse[] = [];
      for (let index = 0; index < nodes.length; index += 1) {
        const node = nodes[index];
        const label = nodeLabel(node);
        setExtractProgress({
          total: nodes.length,
          completed: index,
          currentNodeLabel: label,
          status: `Downloading node ${index + 1} of ${nodes.length}`,
        });
        const result = await analysisApi.extractEra5(sessionId ?? "", {
          latitude: node.latitude,
          longitude: node.longitude,
          start_date: activeDateRange.startDate,
          end_date: activeDateRange.endDate,
        });
        results.push(result);
        setExtractProgress({
          total: nodes.length,
          completed: index + 1,
          currentNodeLabel: label,
          status: `Downloaded node ${index + 1} of ${nodes.length}`,
        });
      }
      return results;
    },
    onMutate: () => {
      setLatestError(null);
      setExtractProgress({
        total: nodes.length,
        completed: 0,
        currentNodeLabel: nodes[0] ? nodeLabel(nodes[0]) : null,
        status: nodes.length > 0 ? `Preparing to download ${nodes.length} ERA5 node datasets` : "Preparing download",
      });
    },
    onSuccess: (results) => {
      setLatestError(null);
      setExtractResults(results);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => {
      const message = extractErrorMessage(error);
      setLatestError(message);
      setExtractProgress((current) => ({
        total: current?.total ?? nodes.length,
        completed: current?.completed ?? 0,
        currentNodeLabel: current?.currentNodeLabel ?? null,
        status: "ERA5 extraction failed",
        errorMessage: message,
      }));
    },
    onSettled: (_data, error) => {
      if (error == null) {
        setExtractProgress(null);
      }
    },
  });

  const interpolateMutation = useMutation({
    mutationFn: () => analysisApi.interpolateEra5(sessionId ?? ""),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestInterpolation(result);
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
        <MetricCard
          label="Interpolation rows"
          value={latestInterpolation ? String(latestInterpolation.rows) : `${activeDateRange.startDate} to ${activeDateRange.endDate}`}
        />
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
            <button
              className="secondary-button"
              type="button"
              disabled={nodes.length === 0 || extractAllMutation.isPending}
              onClick={() => extractAllMutation.mutate()}
            >
              Extract All Nodes
            </button>
            <button className="secondary-button" type="button" disabled={extractAllMutation.isPending} onClick={() => interpolateMutation.mutate()}>
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

      <article className="content-card stack-gap">
        <span className="eyebrow">Interpolation result</span>
        {latestInterpolation ? (
          <dl className="definition-list compact-definition-list">
            <div>
              <dt>Rows</dt>
              <dd>{latestInterpolation.rows}</dd>
            </div>
            <div>
              <dt>Method</dt>
              <dd>{latestInterpolation.method}</dd>
            </div>
            <div>
              <dt>Variables</dt>
              <dd>{latestInterpolation.variables.join(", ")}</dd>
            </div>
          </dl>
        ) : (
          <EmptyState title="No interpolation result" detail="Run site interpolation to inspect the returned row count, method, and variable list." />
        )}
      </article>

      {extractProgress && (extractAllMutation.isPending || extractProgress.errorMessage) ? (
        <div className="progress-overlay" role="status" aria-live="polite" aria-label="ERA5 extraction progress">
          <div className="progress-overlay-card">
            {extractProgress.errorMessage ? (
              <>
                <strong>{extractProgress.status}</strong>
                <p>{extractProgress.currentNodeLabel ? `Last node: ${extractProgress.currentNodeLabel}` : "No active node"}</p>
                <ErrorBanner error={extractProgress.errorMessage} title="EarthDataHub download interrupted" />
                <button className="secondary-button" type="button" onClick={() => setExtractProgress(null)}>
                  Dismiss
                </button>
              </>
            ) : (
              <>
                <LoadingState label={extractProgress.status} />
                <strong>{extractProgress.currentNodeLabel ? `Node ${extractProgress.currentNodeLabel}` : "Starting ERA5 extraction"}</strong>
                <p>
                  {extractProgress.completed} of {extractProgress.total} node datasets completed.
                </p>
              </>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}