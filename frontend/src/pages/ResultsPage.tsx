import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analysisApi, configApi, exportsApi, resultsApi, uploadsApi } from "../lib/api";
import { usePageTitle } from "../hooks/usePageTitle";
import type { LtcResultSummary, PlotResult, RunScenarioRequest, Scenario } from "../lib/types";
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
  usePageTitle("Results");
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const latestUncertainty = useWorkspaceStore((state) => state.latestUncertainty);
  const resultsDraftValue = useWorkspaceStore((state) => state.formDrafts.results);
  const patchFormDraft = useWorkspaceStore((state) => state.patchFormDraft);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [customPlot, setCustomPlot] = useState<PlotResult | null>(null);
  const [scenarioName, setScenarioName] = useState("");
  const [importedRunconfig, setImportedRunconfig] = useState<Record<string, JsonValue> | null>(null);
  const [importScenarioName, setImportScenarioName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const scenariosQuery = useQuery({
    queryKey: ["scenarios", sessionId],
    queryFn: () => analysisApi.listScenarios(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const scenarioCount = scenariosQuery.data?.scenarios.length ?? 0;

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

  const scenarioComparisonQuery = useQuery({
    queryKey: ["scenario-comparison", sessionId, scenarioCount],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "scenario_comparison", {}),
    enabled: sessionId !== null && scenarioCount >= 2,
    staleTime: 10_000,
  });

  const exportMutation = useMutation({
    mutationFn: () => resultsApi.exportRunconfig(sessionId ?? ""),
    onSuccess: () => setLatestError(null),
    onError: (error) => setLatestError(error),
  });

  const saveScenarioMutation = useMutation({
    mutationFn: (name: string) => analysisApi.saveScenario(sessionId ?? "", name),
    onSuccess: () => {
      setLatestError(null);
      setScenarioName("");
      void queryClient.invalidateQueries({ queryKey: ["scenarios", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["scenario-comparison", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const deleteScenarioMutation = useMutation({
    mutationFn: (index: number) => analysisApi.deleteScenario(sessionId ?? "", index),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["scenarios", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["scenario-comparison", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const runScenarioMutation = useMutation({
    mutationFn: (body: RunScenarioRequest) => analysisApi.runScenario(sessionId ?? "", body),
    onSuccess: () => {
      setLatestError(null);
      setImportedRunconfig(null);
      setImportScenarioName("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      void queryClient.invalidateQueries({ queryKey: ["scenarios", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["scenario-comparison", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["runconfig", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["ltc-results", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const handleRunconfigFile = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result as string) as Record<string, JsonValue>;
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          setLatestError("Runconfig must be a JSON object");
          return;
        }
        setImportedRunconfig(parsed);
        if (!importScenarioName) {
          const pname = typeof parsed.project_name === "string" ? parsed.project_name : file.name.replace(/\.json$/i, "");
          setImportScenarioName(pname);
        }
        setLatestError(null);
      } catch {
        setLatestError("Invalid JSON file");
      }
    };
    reader.readAsText(file);
  }, [importScenarioName]);

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
  const latestScenario = scenarioCount > 0 ? scenariosQuery.data?.scenarios[scenarioCount - 1] ?? null : null;
  const latestScenarioMean = latestScenario?.results.long_term_mean_speed ?? null;

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
        <MetricCard label="LT Mean Speed" value={latestScenarioMean !== null ? `${latestScenarioMean.toFixed(2)} m/s` : "—"} tone="accent" />
        <MetricCard label="Total Uncertainty" value={latestUncertainty ? `${latestUncertainty.total_uncertainty_pct.toFixed(2)}%` : "—"} />
        <MetricCard label="P90 Factor" value={latestUncertainty ? latestUncertainty.p_factors.p90.toFixed(4) : "—"} />
        <MetricCard label="Scenarios" value={String(scenarioCount)} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <article className="content-card stack-gap">
        <div className="split-header-row">
          <span className="eyebrow">Scenario comparison</span>
          <div className="button-row wrap">
            <input
              type="text"
              className="scenario-name-input"
              placeholder="Scenario name"
              value={scenarioName}
              onChange={(event) => setScenarioName(event.target.value)}
            />
            <button
              className="primary-button"
              type="button"
              disabled={!scenarioName.trim() || latestUncertainty === null}
              onClick={() => saveScenarioMutation.mutate(scenarioName.trim())}
            >
              Save Current as Scenario
            </button>
          </div>
        </div>
        {scenarioCount > 0 ? (
          <>
            <PlotlyFigure
              plot={scenarioComparisonQuery.data}
              emptyTitle="Scenarios saved"
              emptyDetail="Save at least 2 scenarios to see the comparison chart."
            />
            <DataTable<Scenario>
              columns={[
                { key: "name", header: "Scenario", cell: (row) => row.name },
                { key: "lt_mean", header: "LT Mean (m/s)", cell: (row) => row.results.long_term_mean_speed.toFixed(2) },
                { key: "unc", header: "Uncertainty %", cell: (row) => row.results.total_uncertainty_pct.toFixed(2) },
                { key: "p75", header: "P75", cell: (row) => row.results.p75.toFixed(4) },
                { key: "p90", header: "P90", cell: (row) => row.results.p90.toFixed(4) },
                { key: "shear", header: "Shear Method", cell: (row) => row.config.shear_method },
                { key: "ltc", header: "LTC Algorithm", cell: (row) => row.config.ltc_algorithm },
                { key: "hub", header: "Hub Height", cell: (row) => `${row.config.hub_height_m} m` },
                {
                  key: "delete",
                  header: "",
                  cell: (_row, index) => (
                    <button className="ghost-button table-action" type="button" onClick={() => deleteScenarioMutation.mutate(index)}>
                      Remove
                    </button>
                  ),
                },
              ]}
              rows={scenariosQuery.data?.scenarios ?? []}
              getRowKey={(row, index) => `${row.name}-${index}`}
              emptyTitle="No scenarios saved"
              emptyDetail=""
            />
          </>
        ) : (
          <EmptyState
            title="No scenarios yet"
            detail="Complete the LTC workflow with uncertainty, then save the current result as a named scenario. Save multiple scenarios to compare shear methods, algorithms, or hub heights."
          />
        )}
      </article>

      <article className="content-card stack-gap">
        <span className="eyebrow">Import &amp; run scenario from config</span>
        <p className="muted-text">Upload a runconfig JSON file, then execute the LTC → ensemble → uncertainty pipeline and save the result as a named scenario.</p>
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Runconfig JSON file</span>
            <input ref={fileInputRef} type="file" accept=".json,application/json" onChange={handleRunconfigFile} />
          </label>
          <label className="form-field">
            <span>Scenario name</span>
            <input
              type="text"
              className="scenario-name-input"
              placeholder="Name for imported scenario"
              value={importScenarioName}
              onChange={(event) => setImportScenarioName(event.target.value)}
            />
          </label>
        </div>
        {importedRunconfig !== null ? (
          <details>
            <summary>Preview imported config ({Object.keys(importedRunconfig).length} keys)</summary>
            <pre className="code-block" style={{ maxHeight: "12rem", overflow: "auto" }}>{JSON.stringify(importedRunconfig, null, 2)}</pre>
          </details>
        ) : null}
        <button
          className="primary-button"
          type="button"
          disabled={importedRunconfig === null || !importScenarioName.trim() || runScenarioMutation.isPending}
          onClick={() => {
            if (!importedRunconfig || !importScenarioName.trim()) return;
            runScenarioMutation.mutate({
              name: importScenarioName.trim(),
              runconfig: importedRunconfig,
              ltc_algorithms: ["speedsort"],
            });
          }}
        >
          {runScenarioMutation.isPending ? "Running pipeline…" : "Run Scenario from Config"}
        </button>
        {runScenarioMutation.isSuccess ? (
          <p className="success-text">Scenario "{runScenarioMutation.data.name}" saved with {runScenarioMutation.data.steps_completed.length} steps completed.</p>
        ) : null}
      </article>

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