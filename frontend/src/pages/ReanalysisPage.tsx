import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, analysisApi, brighthubApi, configApi, resultsApi, sessionsApi } from "../lib/api";
import type {
  BrightHubReanalysisDownloadResponse,
  BrightHubReanalysisNode,
  BrightHubReanalysisNodesResponse,
  Era5ExtractResponse,
  Era5InterpolationResponse,
  Era5Node,
  SiteMapResponse,
} from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { GeoJsonMap } from "../components/common/GeoJsonMap";
import { LoadingState } from "../components/common/LoadingState";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { PlotlyFigure } from "../components/common/PlotlyFigure";

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
  return "Reanalysis extraction failed. Retry the download and check the selected node range.";
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

  // Unified reanalysis state
  const [era5Source, setEra5Source] = useState<"earthdatahub" | "brighthub">("earthdatahub");
  const [bhNodes, setBhNodes] = useState<BrightHubReanalysisNodesResponse | null>(null);
  const [bhDownloadResults, setBhDownloadResults] = useState<BrightHubReanalysisDownloadResponse[]>([]);

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

  const hasInterpolation = latestInterpolation !== null || summaryQuery.data?.era5_interpolated_loaded === true;

  const era5ComparisonQuery = useQuery({
    queryKey: ["era5-comparison", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "era5_comparison", {}),
    enabled: sessionId !== null && hasInterpolation,
    staleTime: 15_000,
  });

  const era5OverlayQuery = useQuery({
    queryKey: ["era5-overlay", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "era5_measured_overlay", {}),
    enabled: sessionId !== null && hasInterpolation,
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

  // BrightHub auth status
  const bhStatusQuery = useQuery({
    queryKey: ["brighthub-status", sessionId],
    queryFn: () => brighthubApi.status(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });
  const isBhAuthenticated = bhStatusQuery.data?.authenticated === true;

  // Unified Download: find nodes + extract/download all data in one step
  const downloadMutation = useMutation({
    mutationFn: async () => {
      const lat = Number(latitude);
      const lon = Number(longitude);
      const sid = sessionId ?? "";
      const era5Results: Era5ExtractResponse[] = [];
      const bhResults: BrightHubReanalysisDownloadResponse[] = [];
      let bhNodesResult: BrightHubReanalysisNodesResponse | null = null;

      if (era5Source === "earthdatahub") {
        // ── Step 1: Find ERA5 nodes from EarthDataHub ──
        setExtractProgress({ total: 0, completed: 0, currentNodeLabel: null, status: "Finding ERA5 nodes (EarthDataHub)…" });
        const edhResult = await analysisApi.findEra5Nodes(sid, { latitude: lat, longitude: lon });
        const foundNodes = edhResult.nodes;
        if (sessionId !== null) {
          queryClient.setQueryData(["era5-nodes", sessionId], foundNodes);
        }

        // ── Step 1b: Find MERRA-2 nodes from BrightHub if authenticated ──
        if (isBhAuthenticated) {
          setExtractProgress({ total: foundNodes.length, completed: 0, currentNodeLabel: null, status: "Finding MERRA-2 nodes (BrightHub)…" });
          bhNodesResult = await brighthubApi.getReanalysisNodes(sid, lat, lon);
        }

        // ── Step 2: Extract each ERA5 node from EarthDataHub ──
        for (let i = 0; i < foundNodes.length; i += 1) {
          const node = foundNodes[i];
          const label = nodeLabel(node);
          setExtractProgress({
            total: foundNodes.length,
            completed: i,
            currentNodeLabel: label,
            status: `ERA5 · Downloading node ${i + 1} of ${foundNodes.length} (EarthDataHub)`,
          });
          const result = await analysisApi.extractEra5(sid, {
            latitude: node.latitude,
            longitude: node.longitude,
            start_date: activeDateRange.startDate,
            end_date: activeDateRange.endDate,
          });
          era5Results.push(result);
        }

        // ── Step 3: Download MERRA-2 from BrightHub ──
        if (isBhAuthenticated && bhNodesResult && bhNodesResult.merra2_nodes.length > 0) {
          setExtractProgress((prev) => ({
            total: prev?.total ?? 0, completed: prev?.total ?? 0, currentNodeLabel: null,
            status: `MERRA-2 · Downloading ${bhNodesResult!.merra2_nodes.length} nodes (BrightHub)`,
          }));
          const bhMerra = await brighthubApi.downloadReanalysis(sid, "MERRA-2", bhNodesResult.merra2_nodes, "brighthub");
          bhResults.push(bhMerra);
        }
      } else {
        // ── BrightHub source ──
        if (!isBhAuthenticated) throw new Error("BrightHub authentication required for BrightHub ERA5 source.");

        // Step 1: Find ERA5 + MERRA-2 nodes from BrightHub
        setExtractProgress({ total: 0, completed: 0, currentNodeLabel: null, status: "Finding nodes (BrightHub)…" });
        bhNodesResult = await brighthubApi.getReanalysisNodes(sid, lat, lon);

        // Step 2: Download ERA5 from BrightHub
        if (bhNodesResult.era5_nodes.length > 0) {
          setExtractProgress({
            total: bhNodesResult.era5_nodes.length, completed: 0, currentNodeLabel: null,
            status: `ERA5 · Downloading ${bhNodesResult.era5_nodes.length} nodes (BrightHub)`,
          });
          const bhEra5 = await brighthubApi.downloadReanalysis(sid, "ERA5", bhNodesResult.era5_nodes, "brighthub");
          bhResults.push(bhEra5);
        }

        // Step 3: Download MERRA-2 from BrightHub
        if (bhNodesResult.merra2_nodes.length > 0) {
          setExtractProgress({
            total: bhNodesResult.era5_nodes.length, completed: bhNodesResult.era5_nodes.length, currentNodeLabel: null,
            status: `MERRA-2 · Downloading ${bhNodesResult.merra2_nodes.length} nodes (BrightHub)`,
          });
          const bhMerra = await brighthubApi.downloadReanalysis(sid, "MERRA-2", bhNodesResult.merra2_nodes, "brighthub");
          bhResults.push(bhMerra);
        }
      }

      return { era5Results, bhResults, bhNodesResult };
    },
    onMutate: () => {
      setLatestError(null);
      setExtractProgress({ total: 0, completed: 0, currentNodeLabel: null, status: "Preparing reanalysis download…" });
    },
    onSuccess: ({ era5Results, bhResults, bhNodesResult }) => {
      setLatestError(null);
      setExtractResults(era5Results);
      setBhDownloadResults(bhResults);
      setBhNodes(bhNodesResult);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["site-map", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["era5-nodes", sessionId] });
    },
    onError: (error) => {
      const message = extractErrorMessage(error);
      setLatestError(message);
      setExtractProgress((current) => ({
        total: current?.total ?? 0, completed: current?.completed ?? 0,
        currentNodeLabel: current?.currentNodeLabel ?? null,
        status: "Reanalysis download failed", errorMessage: message,
      }));
    },
    onSettled: (_data, error) => {
      if (error == null) setExtractProgress(null);
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

  const isBusy = downloadMutation.isPending;
  const merraNodeCount = bhNodes?.merra2_nodes.length ?? 0;

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="Reanalysis" detail="Find surrounding ERA5 and MERRA-2 nodes, extract hourly data, and interpolate to the site." />
        <EmptyState title="Session required" detail="Create a session before running reanalysis discovery and extraction." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="Reanalysis" detail="ERA5 and MERRA-2 reanalysis data — select source, find nodes, and extract in one step." />

      <div className="metric-grid">
        <MetricCard label="ERA5 source" value={era5Source === "earthdatahub" ? "EarthDataHub" : "BrightHub"} tone="accent" />
        <MetricCard label="ERA5 nodes" value={String(nodes.length)} />
        <MetricCard label="MERRA-2 nodes" value={String(merraNodeCount)} />
        <MetricCard label="Interpolated" value={summaryQuery.data?.era5_interpolated_loaded ? "Ready" : "Pending"} />
        <MetricCard label="BrightHub" value={isBhAuthenticated ? "Connected" : "Not connected"} tone={isBhAuthenticated ? "accent" : "default"} />
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

          <div className="source-toggle">
            <span className="toggle-label">ERA5 source:</span>
            <label className="radio-field">
              <input type="radio" name="era5Source" value="earthdatahub" checked={era5Source === "earthdatahub"} onChange={() => setEra5Source("earthdatahub")} />
              <span>EarthDataHub</span>
            </label>
            <label className="radio-field">
              <input
                type="radio"
                name="era5Source"
                value="brighthub"
                checked={era5Source === "brighthub"}
                onChange={() => setEra5Source("brighthub")}
                disabled={!isBhAuthenticated}
              />
              <span>BrightHub{!isBhAuthenticated ? " (not connected)" : ""}</span>
            </label>
          </div>
          <div className="content-note">
            <small>MERRA-2 source: <strong>BrightHub</strong>{!isBhAuthenticated ? " — log in on the BrightHub page to enable MERRA-2 downloads" : ""}</small>
          </div>

          <div className="button-row wrap">
            <button
              className="primary-button"
              type="button"
              disabled={isBusy || !latitude || !longitude}
              onClick={() => downloadMutation.mutate()}
            >
              {downloadMutation.isPending ? "Downloading…" : "Download Reanalysis Data"}
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={isBusy}
              onClick={() => interpolateMutation.mutate()}
            >
              Interpolate Site
            </button>
          </div>
        </article>

        <GeoJsonMap
          featureCollection={mapQuery.data}
          emptyTitle="Map unavailable"
          emptyDetail="Find nodes first to render the mast and node markers."
        />
      </div>

      {/* ERA5 node table */}
      {nodes.length > 0 ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">ERA5 nodes ({era5Source === "earthdatahub" ? "EarthDataHub" : "BrightHub"})</span>
          <DataTable<Era5Node>
            columns={[
              { key: "lat", header: "Latitude", cell: (row) => row.latitude.toFixed(4) },
              { key: "lon", header: "Longitude", cell: (row) => row.longitude.toFixed(4) },
              { key: "distance", header: "Distance", cell: (row) => `${row.distance_km.toFixed(1)} km` },
              { key: "bearing", header: "Bearing", cell: (row) => row.bearing },
            ]}
            rows={nodes}
            getRowKey={(row) => `${row.latitude}-${row.longitude}`}
            emptyTitle="No ERA5 nodes"
            emptyDetail=""
          />
        </article>
      ) : null}

      {/* MERRA-2 node table */}
      {bhNodes && bhNodes.merra2_nodes.length > 0 ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">MERRA-2 nodes (BrightHub)</span>
          <DataTable<BrightHubReanalysisNode>
            columns={[
              { key: "lat", header: "Latitude", cell: (row) => row.latitude_ddeg.toFixed(4) },
              { key: "lon", header: "Longitude", cell: (row) => row.longitude_ddeg.toFixed(4) },
              { key: "dist", header: "Distance²", cell: (row) => (row.distance_sq != null ? row.distance_sq.toFixed(6) : "—") },
            ]}
            rows={bhNodes.merra2_nodes}
            getRowKey={(_, i) => `bh-merra2-${i}`}
            emptyTitle="No MERRA-2 nodes"
            emptyDetail=""
          />
        </article>
      ) : null}

      {/* EarthDataHub extraction results */}
      {extractResults.length > 0 ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">ERA5 extraction results (EarthDataHub)</span>
          <DataTable<Era5ExtractResponse>
            columns={[
              { key: "node", header: "Node", cell: (row) => `${row.latitude.toFixed(2)}, ${row.longitude.toFixed(2)}` },
              { key: "rows", header: "Rows", cell: (row) => row.rows },
              { key: "cached", header: "Cached", cell: (row) => (row.cached ? "Yes" : "No") },
              { key: "vars", header: "Variables", cell: (row) => row.variables.join(", ") },
            ]}
            rows={extractResults}
            getRowKey={(row) => `${row.latitude}-${row.longitude}-${row.start}`}
            emptyTitle="No datasets"
            emptyDetail=""
          />
        </article>
      ) : null}

      {/* BrightHub download results */}
      {bhDownloadResults.length > 0 ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">Download results (BrightHub)</span>
          {bhDownloadResults.map((result, idx) => (
            <div key={idx} className="content-note">
              <strong>{result.dataset}</strong> via {result.source === "earthdatahub" ? "EarthDataHub" : "BrightHub"}
              {" — "}
              {result.items.length} node(s):
              {result.items.map((item, i) => (
                <span key={i}>
                  {" "}({item.latitude.toFixed(2)}, {item.longitude.toFixed(2)}: {item.rows ?? "?"} rows)
                </span>
              ))}
            </div>
          ))}
        </article>
      ) : null}

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

      {hasInterpolation ? (
        <div className="panel-grid panel-grid-two">
          <PlotlyFigure
            plot={era5ComparisonQuery.data}
            emptyTitle="ERA5 node comparison"
            emptyDetail="Loading node annual profiles."
          />
          <PlotlyFigure
            plot={era5OverlayQuery.data}
            emptyTitle="Measured vs ERA5"
            emptyDetail="Overlay concurrent measured and ERA5 monthly means."
          />
        </div>
      ) : null}

      {extractProgress && (downloadMutation.isPending || extractProgress.errorMessage) ? (
        <div className="progress-overlay" role="status" aria-live="polite" aria-label="Reanalysis extraction progress">
          <div className="progress-overlay-card">
            {extractProgress.errorMessage ? (
              <>
                <strong>{extractProgress.status}</strong>
                <p>{extractProgress.currentNodeLabel ? `Last node: ${extractProgress.currentNodeLabel}` : "No active node"}</p>
                <ErrorBanner error={extractProgress.errorMessage} title="Download interrupted" />
                <button className="secondary-button" type="button" onClick={() => setExtractProgress(null)}>
                  Dismiss
                </button>
              </>
            ) : (
              <>
                <LoadingState label={extractProgress.status} />
                <strong>{extractProgress.currentNodeLabel ? `Node ${extractProgress.currentNodeLabel}` : "Starting reanalysis extraction"}</strong>
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