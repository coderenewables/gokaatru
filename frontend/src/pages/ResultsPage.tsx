import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";

import { configApi, exportsApi, resultsApi, uploadsApi } from "../lib/api";
import type { LtcResultSummary, PlotResult } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { GeoJsonMap } from "../components/common/GeoJsonMap";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { PlotlyFigure } from "../components/common/PlotlyFigure";
import type { JsonValue } from "../lib/types";

function uncertaintyPlotPayload(plotResult: ReturnType<typeof useWorkspaceStore.getState>["latestUncertainty"]) {
  if (!plotResult) {
    return null;
  }
  return {
    total_pct: plotResult.total_uncertainty_pct,
    measurement_pct: plotResult.components.measurement,
    vertical_pct: plotResult.components.vertical_extrapolation,
    mcp_pct: plotResult.components.mcp,
    future_pct: plotResult.components.future_variability,
  };
}

function draftSection(value: JsonValue | undefined) {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

export function ResultsPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const latestUncertainty = useWorkspaceStore((state) => state.latestUncertainty);
  const resultsDraftValue = useWorkspaceStore((state) => state.formDrafts.results);
  const patchFormDraft = useWorkspaceStore((state) => state.patchFormDraft);
  const [latestError, setLatestError] = useState<unknown>(null);
  const [customPlot, setCustomPlot] = useState<PlotResult | null>(null);

  const resultsDraft = useMemo(() => draftSection(resultsDraftValue), [resultsDraftValue]);

  const plotName = typeof resultsDraft.plotName === "string" ? resultsDraft.plotName : "weibull";
  const sensorName = typeof resultsDraft.sensorName === "string" ? resultsDraft.sensorName : "";
  const speedSensor = typeof resultsDraft.speedSensor === "string" ? resultsDraft.speedSensor : "";
  const directionSensor = typeof resultsDraft.directionSensor === "string" ? resultsDraft.directionSensor : "";
  const sensorNames = typeof resultsDraft.sensorNames === "string" ? resultsDraft.sensorNames : "";
  const sensorA = typeof resultsDraft.sensorA === "string" ? resultsDraft.sensorA : "";
  const sensorB = typeof resultsDraft.sensorB === "string" ? resultsDraft.sensorB : "";

  const sensorsQuery = useQuery({
    queryKey: ["results-sensors", sessionId],
    queryFn: () => uploadsApi.getSensors(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const runconfigQuery = useQuery({
    queryKey: ["runconfig", sessionId],
    queryFn: () => configApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const ltcResultsQuery = useQuery({
    queryKey: ["ltc-results", sessionId],
    queryFn: () => resultsApi.getLtcResults(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const siteMapQuery = useQuery({
    queryKey: ["site-map", sessionId],
    queryFn: () => resultsApi.getSiteMap(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const annualMeansQuery = useQuery({
    queryKey: ["annual-means-plot", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "annual_means", {}),
    enabled: sessionId !== null && (ltcResultsQuery.data?.results.length ?? 0) > 0,
    staleTime: 10_000,
  });

  const comparisonPlotQuery = useQuery({
    queryKey: ["ltc-comparison-plot", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_comparison", {}),
    enabled: sessionId !== null && (ltcResultsQuery.data?.results.length ?? 0) > 0,
    staleTime: 10_000,
  });

  const uncertaintyPlotQuery = useQuery({
    queryKey: ["uncertainty-plot", sessionId, latestUncertainty?.total_uncertainty_pct],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "uncertainty_breakdown", uncertaintyPlotPayload(latestUncertainty) ?? {}),
    enabled: sessionId !== null && latestUncertainty !== null,
    staleTime: 10_000,
  });

  const exportMutation = useMutation({
    mutationFn: () => resultsApi.exportRunconfig(sessionId ?? ""),
    onSuccess: () => setLatestError(null),
    onError: (error) => setLatestError(error),
  });

  const customPlotMutation = useMutation({
    mutationFn: () =>
      resultsApi.getPlot(sessionId ?? "", plotName, {
        sensor_name: sensorName,
        speed_sensor: speedSensor,
        direction_sensor: directionSensor,
        sensor_names: sensorNames,
        sensor_a: sensorA,
        sensor_b: sensorB,
      }),
    onSuccess: (result) => {
      setLatestError(null);
      setCustomPlot(result);
    },
    onError: (error) => setLatestError(error),
  });

  const speedSensors = useMemo(
    () => (sensorsQuery.data?.sensors ?? []).filter((sensor) => sensor.sensor_type === "wind_speed"),
    [sensorsQuery.data],
  );
  const directionSensors = useMemo(
    () => (sensorsQuery.data?.sensors ?? []).filter((sensor) => sensor.sensor_type === "wind_direction"),
    [sensorsQuery.data],
  );

  useEffect(() => {
    if (speedSensors[0] && resultsDraft.initialized !== true) {
      patchFormDraft("results", {
        plotName: "weibull",
        sensorName: speedSensors[0].name,
        speedSensor: speedSensors[0].name,
        sensorNames: speedSensors[0].name,
        sensorA: speedSensors[0].name,
        sensorB: speedSensors[1]?.name ?? "",
        directionSensor: directionSensors[0]?.name ?? "",
        initialized: true,
      });
    }
  }, [directionSensors, patchFormDraft, resultsDraft.initialized, speedSensors]);

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="Results" detail="Inspect generated plots, maps, runconfig exports, and result file paths." />
        <EmptyState title="Session required" detail="Create a session before requesting plots, maps, or exports." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="Results" detail="Render the stored outputs, browse generated files, and request on-demand Plotly figures from the backend." />

      <div className="metric-grid">
        <MetricCard label="Result files" value={String((ltcResultsQuery.data?.results ?? []).filter((result) => result.result_file).length)} tone="accent" />
        <MetricCard label="Annual means plot" value={annualMeansQuery.data ? "Ready" : "Pending"} />
        <MetricCard label="Site map" value={siteMapQuery.data ? `${siteMapQuery.data.features.length} features` : "Pending"} />
        <MetricCard label="Export path" value={exportMutation.data?.file_path ?? "Not exported"} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <div className="panel-grid panel-grid-two">
        <PlotlyFigure
          plot={annualMeansQuery.data}
          emptyTitle="Annual means unavailable"
          emptyDetail="Run at least one LTC algorithm before requesting the annual means figure."
        />
        <PlotlyFigure
          plot={comparisonPlotQuery.data}
          emptyTitle="LTC comparison unavailable"
          emptyDetail="LTC comparison requires at least one stored correction result."
        />
      </div>

      <div className="panel-grid panel-grid-two">
        <GeoJsonMap
          featureCollection={siteMapQuery.data}
          emptyTitle="Site map unavailable"
          emptyDetail="Set coordinates and find ERA5 nodes to render the site overview map."
        />
        <PlotlyFigure
          plot={uncertaintyPlotQuery.data}
          emptyTitle="Uncertainty output unavailable"
          emptyDetail="Run the uncertainty calculation in the LTC page to render the breakdown figure here."
        />
      </div>

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Custom plot request</span>
          <label className="form-field">
            <span>Plot endpoint</span>
            <select value={plotName} onChange={(event) => patchFormDraft("results", { plotName: event.target.value })}>
              <option value="weibull">weibull</option>
              <option value="windrose">windrose</option>
              <option value="diurnal">diurnal</option>
              <option value="scatter">scatter</option>
              <option value="timeseries">timeseries</option>
            </select>
          </label>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Sensor name</span>
              <input value={sensorName} onChange={(event) => patchFormDraft("results", { sensorName: event.target.value })} />
            </label>
            <label className="form-field">
              <span>Speed sensor</span>
              <input value={speedSensor} onChange={(event) => patchFormDraft("results", { speedSensor: event.target.value })} />
            </label>
            <label className="form-field">
              <span>Direction sensor</span>
              <input value={directionSensor} onChange={(event) => patchFormDraft("results", { directionSensor: event.target.value })} />
            </label>
            <label className="form-field">
              <span>Sensor names CSV</span>
              <input value={sensorNames} onChange={(event) => patchFormDraft("results", { sensorNames: event.target.value })} />
            </label>
            <label className="form-field">
              <span>Sensor A</span>
              <input value={sensorA} onChange={(event) => patchFormDraft("results", { sensorA: event.target.value })} />
            </label>
            <label className="form-field">
              <span>Sensor B</span>
              <input value={sensorB} onChange={(event) => patchFormDraft("results", { sensorB: event.target.value })} />
            </label>
          </div>
          <button className="primary-button" type="button" onClick={() => customPlotMutation.mutate()}>
            Render Custom Plot
          </button>
        </article>

        <PlotlyFigure
          plot={customPlot}
          emptyTitle="No custom plot requested"
          emptyDetail="Choose a plot endpoint and render it here against the current session data."
        />
      </div>

      <article className="content-card stack-gap">
        <div className="split-header-row">
          <span className="eyebrow">Runconfig and generated files</span>
          <div className="button-row wrap">
            <button className="secondary-button" type="button" onClick={() => exportMutation.mutate()}>
              Export Runconfig
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => window.open(exportsApi.downloadRunconfig(sessionId), "_blank", "noopener")}
            >
              Download Runconfig JSON
            </button>
          </div>
        </div>
        <DataTable<LtcResultSummary>
          columns={[
            { key: "algorithm", header: "Algorithm", cell: (row) => row.algorithm },
            { key: "file", header: "Result file", cell: (row) => row.result_file ?? "Not written" },
            { key: "rows", header: "Rows", cell: (row) => row.rows },
          ]}
          rows={ltcResultsQuery.data?.results ?? []}
          getRowKey={(row) => row.algorithm}
          emptyTitle="No generated result files"
          emptyDetail="Stored LTC result file paths will appear here once algorithms have been run."
        />
        <pre className="code-block">{JSON.stringify(exportMutation.data?.runconfig ?? runconfigQuery.data ?? {}, null, 2)}</pre>
      </article>
    </section>
  );
}