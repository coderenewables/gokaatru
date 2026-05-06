import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, brighthubApi } from "../lib/api";
import { usePageTitle } from "../hooks/usePageTitle";
import type {
  BrightHubImportLocationRequest,
  BrightHubImportLocationResponse,
  BrightHubMeasurementLocation,
  BrightHubReanalysisNode,
  BrightHubReanalysisNodesResponse,
} from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable, type DataTableColumn } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { LoadingState } from "../components/common/LoadingState";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";

// ---------------------------------------------------------------------------
// Location table columns
// ---------------------------------------------------------------------------

const locationColumns: DataTableColumn<BrightHubMeasurementLocation>[] = [
  { key: "name", header: "Name", cell: (r) => r.name || "Unnamed" },
  { key: "uuid", header: "UUID", cell: (r) => <code>{r.uuid}</code> },
  {
    key: "lat",
    header: "Latitude",
    cell: (r) => (r.latitude_ddeg !== null ? r.latitude_ddeg.toFixed(4) : "—"),
  },
  {
    key: "lon",
    header: "Longitude",
    cell: (r) => (r.longitude_ddeg !== null ? r.longitude_ddeg.toFixed(4) : "—"),
  },
  {
    key: "type",
    header: "Type",
    cell: (r) => (r.measurement_station_type_id !== null ? String(r.measurement_station_type_id) : "—"),
  },
];

function reanalysisNodeColumns(dataset: string): DataTableColumn<BrightHubReanalysisNode>[] {
  return [
    { key: "dataset", header: "Dataset", cell: () => dataset },
    {
      key: "lat",
      header: "Latitude",
      cell: (r) => r.latitude_ddeg.toFixed(4),
    },
    {
      key: "lon",
      header: "Longitude",
      cell: (r) => r.longitude_ddeg.toFixed(4),
    },
    {
      key: "dist",
      header: "Distance²",
      cell: (r) => (r.distance_sq != null ? r.distance_sq.toFixed(6) : "—"),
    },
  ];
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export function BrightHubPage() {
  usePageTitle("BrightHub");
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const queryClient = useQueryClient();

  // Login form state
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [latestError, setLatestError] = useState<unknown>(null);

  // Selected location
  const [selectedLocation, setSelectedLocation] = useState<BrightHubMeasurementLocation | null>(null);
  const [reanalysisNodes, setReanalysisNodes] = useState<BrightHubReanalysisNodesResponse | null>(null);

  // Import options dialog
  const [dialogLocation, setDialogLocation] = useState<BrightHubMeasurementLocation | null>(null);
  const [importOptions, setImportOptions] = useState({
    apply_cleaning_log: true,
    apply_cleaning_rules: false,
    apply_calibration: false,
    apply_deadband_offset: false,
    apply_orientation_offset: false,
  });

  // ERA5 source selection
  const [era5Source, setEra5Source] = useState<"brighthub" | "earthdatahub">("earthdatahub");

  // Auth status query
  const authStatusQuery = useQuery({
    queryKey: ["brighthub-status", sessionId],
    queryFn: () => brighthubApi.status(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const isAuthenticated = authStatusQuery.data?.authenticated === true;

  // Locations query (only after auth)
  const locationsQuery = useQuery({
    queryKey: ["brighthub-locations", sessionId],
    queryFn: () => brighthubApi.getLocations(sessionId ?? ""),
    enabled: sessionId !== null && isAuthenticated,
    staleTime: 30_000,
  });

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: () => brighthubApi.login(sessionId ?? "", clientId, clientSecret),
    onSuccess: () => {
      setLatestError(null);
      setClientSecret("");
      void queryClient.invalidateQueries({ queryKey: ["brighthub-status", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["brighthub-locations", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  // Logout mutation
  const logoutMutation = useMutation({
    mutationFn: () => brighthubApi.logout(sessionId ?? ""),
    onSuccess: () => {
      setLatestError(null);
      setSelectedLocation(null);
      setReanalysisNodes(null);
      setDataModel(null);
      void queryClient.invalidateQueries({ queryKey: ["brighthub-status", sessionId] });
      void queryClient.removeQueries({ queryKey: ["brighthub-locations", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  // Reanalysis node lookup
  const reanalysisNodesMutation = useMutation({
    mutationFn: (loc: BrightHubMeasurementLocation) => {
      if (loc.latitude_ddeg === null || loc.longitude_ddeg === null) {
        return Promise.reject(new Error("Location has no coordinates."));
      }
      return brighthubApi.getReanalysisNodes(sessionId ?? "", loc.latitude_ddeg, loc.longitude_ddeg);
    },
    onSuccess: (data) => {
      setReanalysisNodes(data);
      setLatestError(null);
    },
    onError: (error) => setLatestError(error),
  });

  // Reanalysis download
  const downloadMutation = useMutation({
    mutationFn: (params: { dataset: string; nodes: BrightHubReanalysisNode[]; source?: string }) =>
      brighthubApi.downloadReanalysis(sessionId ?? "", params.dataset, params.nodes, params.source ?? "brighthub"),
    onSuccess: () => setLatestError(null),
    onError: (error) => setLatestError(error),
  });

  // Data model fetch
  const [dataModel, setDataModel] = useState<Record<string, unknown> | null>(null);
  const dataModelMutation = useMutation({
    mutationFn: (uuid: string) => brighthubApi.getDataModel(sessionId ?? "", uuid),
    onSuccess: (data) => {
      setDataModel(data.data_model);
      setLatestError(null);
    },
    onError: (error) => setLatestError(error),
  });

  // Import location (timeseries + datamodel) into session
  const [importResult, setImportResult] = useState<BrightHubImportLocationResponse | null>(null);
  const importMutation = useMutation({
    mutationFn: (req: BrightHubImportLocationRequest) =>
      brighthubApi.importLocation(sessionId ?? "", req),
    onSuccess: (data) => {
      setImportResult(data);
      setLatestError(null);
      // Invalidate session summary so completed_steps updates across the app
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["runconfig", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="BrightHub" detail="Authenticate with BrightHub to browse datasets, measurement locations, and reanalysis data (ERA5 & MERRA-2)." />
        <EmptyState title="No active session" detail="Create a session from the header to start." />
      </section>
    );
  }

  function handleSelectLocation(loc: BrightHubMeasurementLocation) {
    // Show the import options dialog instead of importing immediately
    setDialogLocation(loc);
  }

  function handleConfirmImport() {
    if (!dialogLocation) return;
    setSelectedLocation(dialogLocation);
    setReanalysisNodes(null);
    setDataModel(null);
    setImportResult(null);
    setDialogLocation(null);
    importMutation.mutate({
      uuid: dialogLocation.uuid,
      name: dialogLocation.name,
      latitude_ddeg: dialogLocation.latitude_ddeg,
      longitude_ddeg: dialogLocation.longitude_ddeg,
      ...importOptions,
    });
  }

  function handleReimport() {
    if (!selectedLocation) return;
    setDialogLocation(selectedLocation);
  }

  const locations = locationsQuery.data?.locations ?? [];
  const era5Nodes = reanalysisNodes?.era5_nodes ?? [];
  const merra2Nodes = reanalysisNodes?.merra2_nodes ?? [];

  return (
    <section className="page-section">
      <PageHeader
        title="BrightHub"
        detail="Authenticate with BrightHub to browse measurement locations and access ERA5 & MERRA-2 reanalysis data."
        actions={
          isAuthenticated ? (
            <button className="ghost-button" type="button" onClick={() => logoutMutation.mutate()}>
              Logout
            </button>
          ) : null
        }
      />

      {latestError ? <ErrorBanner error={latestError} /> : null}

      {/* Auth status */}
      <div className="metric-grid">
        <MetricCard
          label="BrightHub"
          value={isAuthenticated ? "Authenticated" : "Not connected"}
          tone={isAuthenticated ? "accent" : "default"}
        />
        <MetricCard label="Locations" value={String(locations.length)} />
        {selectedLocation ? (
          <MetricCard label="Selected" value={selectedLocation.name || selectedLocation.uuid} />
        ) : null}
      </div>

      {/* What is BrightHub */}
      {!isAuthenticated && (
        <article className="content-card brighthub-info-card">
          <span className="eyebrow">What is BrightHub?</span>
          <p>
            BrightHub is a wind energy data platform that provides access to measurement station timeseries, calibrated sensor data, and co-located ERA5 / MERRA-2 reanalysis nodes.
            Connecting here lets you import site data directly into your analysis session — no file uploads required.
          </p>
          <p className="muted-text brighthub-info-note">
            You will need a BrightHub account with a Client ID and Client Secret. Contact your data provider if you do not have credentials.
          </p>
        </article>
      )}

      {/* Login form */}
      {!isAuthenticated ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">BrightHub API Key Login</span>
          <p className="muted-text">
            Enter your BrightHub API Key (Client ID) and Client Secret to authenticate.
          </p>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              loginMutation.mutate();
            }}
          >
            <label className="form-field">
              <span>Client ID (API Key)</span>
              <input
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="Your BrightHub Client ID"
                required
                autoComplete="username"
              />
            </label>
            <label className="form-field">
              <span>Client Secret</span>
              <input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder="Your BrightHub Client Secret"
                required
                autoComplete="current-password"
              />
            </label>
            <div className="form-actions">
              <button
                className="primary-button"
                type="submit"
                disabled={loginMutation.isPending || !clientId || !clientSecret}
              >
                {loginMutation.isPending ? "Signing in…" : "Sign In"}
              </button>
            </div>
          </form>
        </article>
      ) : null}

      {/* Measurement locations table */}
      {isAuthenticated ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">Measurement Locations</span>
          {locationsQuery.isLoading ? (
            <LoadingState label="Loading locations from BrightHub" />
          ) : (
            <DataTable
              columns={locationColumns}
              rows={locations}
              getRowKey={(r) => r.uuid}
              emptyTitle="No locations"
              emptyDetail="No measurement locations were returned by BrightHub."
              onRowClick={(loc) => handleSelectLocation(loc)}
            />
          )}
        </article>
      ) : null}

      {/* Selected location detail */}
      {selectedLocation ? (
        <article className="content-card stack-gap">
          <div className="section-header">
            <div>
              <span className="eyebrow">Selected Location</span>
              <h3>{selectedLocation.name || "Unnamed"}</h3>
              <p className="muted-text">{selectedLocation.uuid}</p>
            </div>
            <div className="page-header-actions">
              <button
                className="secondary-button"
                type="button"
                disabled={importMutation.isPending}
                onClick={() => handleReimport()}
              >
                {importMutation.isPending ? "Importing…" : "Re-import Data"}
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={dataModelMutation.isPending}
                onClick={() => dataModelMutation.mutate(selectedLocation.uuid)}
              >
                {dataModelMutation.isPending ? "Loading…" : "View Data Model"}
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={
                  reanalysisNodesMutation.isPending ||
                  selectedLocation.latitude_ddeg === null ||
                  selectedLocation.longitude_ddeg === null
                }
                onClick={() => reanalysisNodesMutation.mutate(selectedLocation)}
              >
                {reanalysisNodesMutation.isPending ? "Searching…" : "Find Reanalysis Nodes"}
              </button>
            </div>
          </div>

          {/* Import progress / result */}
          {importMutation.isPending ? (
            <LoadingState label="Downloading timeseries and data model from BrightHub…" />
          ) : null}

          {importResult ? (
            <div className="success-banner">
              <strong>Imported successfully</strong> — {importResult.timeseries_rows.toLocaleString()} rows,{" "}
              {importResult.datamodel_heights.length} sensor height(s)
              {importResult.project_name ? `, project: ${importResult.project_name}` : ""}
              {importResult.timeseries_start && importResult.timeseries_end
                ? ` (${importResult.timeseries_start.slice(0, 10)} → ${importResult.timeseries_end.slice(0, 10)})`
                : ""}
            </div>
          ) : null}

          <div className="metric-grid">
            <MetricCard
              label="Latitude"
              value={selectedLocation.latitude_ddeg !== null ? selectedLocation.latitude_ddeg.toFixed(4) : "—"}
            />
            <MetricCard
              label="Longitude"
              value={selectedLocation.longitude_ddeg !== null ? selectedLocation.longitude_ddeg.toFixed(4) : "—"}
            />
            {importResult ? (
              <>
                <MetricCard label="Rows" value={importResult.timeseries_rows.toLocaleString()} tone="accent" />
                <MetricCard label="Heights" value={importResult.datamodel_heights.map((h) => `${h}m`).join(", ") || "—"} />
              </>
            ) : null}
          </div>

          {/* Data model preview */}
          {dataModel ? (
            <details className="details-block" open>
              <summary>Data Model</summary>
              <pre className="code-preview">{JSON.stringify(dataModel, null, 2)}</pre>
            </details>
          ) : null}
        </article>
      ) : null}

      {/* Reanalysis nodes */}
      {reanalysisNodes ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">Reanalysis Nodes</span>

          <div className="metric-grid">
            <MetricCard label="ERA5 nodes" value={String(era5Nodes.length)} tone="accent" />
            <MetricCard label="MERRA-2 nodes" value={String(merra2Nodes.length)} />
          </div>

          {era5Nodes.length > 0 ? (
            <>
              <h4>ERA5 Nodes</h4>
              <DataTable
                columns={reanalysisNodeColumns("ERA5")}
                rows={era5Nodes}
                getRowKey={(r, i) => `era5-${i}`}
                emptyTitle="No ERA5 nodes"
                emptyDetail="No ERA5 nodes found near this location."
              />
              <div className="source-toggle">
                <span className="toggle-label">ERA5 Source:</span>
                <label className="radio-field">
                  <input
                    type="radio"
                    name="era5Source"
                    value="earthdatahub"
                    checked={era5Source === "earthdatahub"}
                    onChange={() => setEra5Source("earthdatahub")}
                  />
                  <span>EarthDataHub</span>
                </label>
                <label className="radio-field">
                  <input
                    type="radio"
                    name="era5Source"
                    value="brighthub"
                    checked={era5Source === "brighthub"}
                    onChange={() => setEra5Source("brighthub")}
                  />
                  <span>BrightHub</span>
                </label>
              </div>
              <button
                className="secondary-button"
                type="button"
                disabled={downloadMutation.isPending}
                onClick={() => downloadMutation.mutate({ dataset: "ERA5", nodes: era5Nodes, source: era5Source })}
              >
                {downloadMutation.isPending ? "Downloading…" : `Download ERA5 Data (${era5Source === "earthdatahub" ? "EarthDataHub" : "BrightHub"})`}
              </button>
            </>
          ) : null}

          {merra2Nodes.length > 0 ? (
            <>
              <h4>MERRA-2 Nodes</h4>
              <DataTable
                columns={reanalysisNodeColumns("MERRA-2")}
                rows={merra2Nodes}
                getRowKey={(r, i) => `merra2-${i}`}
                emptyTitle="No MERRA-2 nodes"
                emptyDetail="No MERRA-2 nodes found near this location."
              />
              <button
                className="secondary-button"
                type="button"
                disabled={downloadMutation.isPending}
                onClick={() => downloadMutation.mutate({ dataset: "MERRA-2", nodes: merra2Nodes, source: "brighthub" })}
              >
                {downloadMutation.isPending ? "Downloading…" : "Download MERRA-2 Data (BrightHub)"}
              </button>
            </>
          ) : null}

          {downloadMutation.isSuccess ? (
            <div className="success-banner">
              Downloaded {downloadMutation.data.items.length} node(s) from {downloadMutation.data.dataset} via{" "}
              {downloadMutation.data.source === "earthdatahub" ? "EarthDataHub" : "BrightHub"}.
              {downloadMutation.data.items.map((item, idx) => (
                <span key={idx}>
                  {" "}
                  ({item.latitude.toFixed(2)}, {item.longitude.toFixed(2)}: {item.rows ?? "?"} rows)
                </span>
              ))}
            </div>
          ) : null}
        </article>
      ) : null}

      {/* Import options dialog */}
      {dialogLocation ? (
        <div className="dialog-overlay" onClick={() => setDialogLocation(null)}>
          <div className="dialog-card" onClick={(e) => e.stopPropagation()}>
            <h3>Import Options</h3>
            <p className="muted-text">
              Importing <strong>{dialogLocation.name || "Unnamed"}</strong>{" "}
              <code>{dialogLocation.uuid}</code>
            </p>

            <div className="stack-gap" style={{ marginTop: "1rem" }}>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={importOptions.apply_cleaning_log}
                  onChange={(e) =>
                    setImportOptions((prev) => ({ ...prev, apply_cleaning_log: e.target.checked }))
                  }
                />
                <span>Apply cleaning log</span>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={importOptions.apply_cleaning_rules}
                  onChange={(e) =>
                    setImportOptions((prev) => ({ ...prev, apply_cleaning_rules: e.target.checked }))
                  }
                />
                <span>Apply cleaning rules</span>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={importOptions.apply_calibration}
                  onChange={(e) =>
                    setImportOptions((prev) => ({ ...prev, apply_calibration: e.target.checked }))
                  }
                />
                <span>Apply calibration slope &amp; offset</span>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={importOptions.apply_deadband_offset}
                  onChange={(e) =>
                    setImportOptions((prev) => ({ ...prev, apply_deadband_offset: e.target.checked }))
                  }
                />
                <span>Apply wind vane deadband offset</span>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={importOptions.apply_orientation_offset}
                  onChange={(e) =>
                    setImportOptions((prev) => ({ ...prev, apply_orientation_offset: e.target.checked }))
                  }
                />
                <span>Apply device orientation offset</span>
              </label>
            </div>

            <div className="form-actions" style={{ marginTop: "1.5rem" }}>
              <button className="primary-button" type="button" onClick={() => handleConfirmImport()}>
                Import
              </button>
              <button className="secondary-button" type="button" onClick={() => setDialogLocation(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
