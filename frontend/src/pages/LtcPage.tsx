import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analysisApi, configApi, exportsApi, resultsApi, uploadsApi } from "../lib/api";
import { PlotlyFigure } from "../components/common/PlotlyFigure";
import { algorithmHelp } from "../lib/algorithmHelp";
import type { ClippingAnalysisResponse, HomogeneityAnalysisResponse, HomogeneityApplyResponse, LtcResultSummary } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { HelpTooltip } from "../components/common/HelpTooltip";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";

const ltcAlgorithms = [
  "linear_least_squares",
  "total_least_squares",
  "speedsort",
  "variance_ratio",
  "xgboost",
];

const fallbackReferenceColumns = ["Spd_100m", "Dir_100m", "sp", "t2m", "d2m"];

function getLatestResult(results: LtcResultSummary[]) {
  return results.length > 0 ? results[results.length - 1] : null;
}

function getNumericMetric(metrics: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = metrics[key];
    if (typeof value === "number") {
      return value;
    }
  }
  return null;
}

export function LtcPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const selectedLtcAlgorithm = useWorkspaceStore((state) => state.selectedLtcAlgorithm);
  const selectedLtcSource = useWorkspaceStore((state) => state.selectedLtcSource);
  const setSelectedLtcAlgorithm = useWorkspaceStore((state) => state.setSelectedLtcAlgorithm);
  const setSelectedLtcSource = useWorkspaceStore((state) => state.setSelectedLtcSource);
  const latestUncertainty = useWorkspaceStore((state) => state.latestUncertainty);
  const setLatestUncertainty = useWorkspaceStore((state) => state.setLatestUncertainty);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [shortCol, setShortCol] = useState("");
  const [longCol, setLongCol] = useState("Spd_100m");
  const [shortDirCol, setShortDirCol] = useState("");
  const [longDirCol, setLongDirCol] = useState("Dir_100m");
  const [measuredCol, setMeasuredCol] = useState("");
  const [clippingSpeedCol, setClippingSpeedCol] = useState("corrected_wind_speed");
  const [homogeneityMethod, setHomogeneityMethod] = useState("annual");
  const [cutoffYear, setCutoffYear] = useState("");
  const [uncMeasurementPct, setUncMeasurementPct] = useState("2.0");
  const [uncMeasurementHeight, setUncMeasurementHeight] = useState("100");
  const [uncHubHeight, setUncHubHeight] = useState("150");
  const [uncShearMethod, setUncShearMethod] = useState("simple_power_law");
  const [uncRsq, setUncRsq] = useState("0.9");
  const [uncHours, setUncHours] = useState("8760");
  const [uncIav, setUncIav] = useState("6");
  const [uncShearStd, setUncShearStd] = useState("0");
  const [latestClipping, setLatestClipping] = useState<ClippingAnalysisResponse | null>(null);
  const [latestHomogeneity, setLatestHomogeneity] = useState<HomogeneityAnalysisResponse | null>(null);
  const [latestHomogeneityApply, setLatestHomogeneityApply] = useState<HomogeneityApplyResponse | null>(null);
  const [focusedAlgorithm, setFocusedAlgorithm] = useState<string | null>(null);

  const configQuery = useQuery({
    queryKey: ["ltc-config", sessionId],
    queryFn: () => configApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 30_000,
  });

  const sensorsQuery = useQuery({
    queryKey: ["ltc-sensors", sessionId],
    queryFn: () => uploadsApi.getSensors(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const ltcResultsQuery = useQuery({
    queryKey: ["ltc-results", sessionId],
    queryFn: () => resultsApi.getLtcResults(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const ensembleQuery = useQuery({
    queryKey: ["ensemble-results", sessionId],
    queryFn: () => resultsApi.getEnsembleResults(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const referenceColumns = useMemo(() => ensembleQuery.data?.reference_columns ?? fallbackReferenceColumns, [ensembleQuery.data]);

  const referenceSpeedColumns = useMemo(() => {
    const columns = referenceColumns.filter((column) => column.startsWith("Spd_"));
    return columns.length > 0 ? columns : ["Spd_100m"];
  }, [referenceColumns]);

  const referenceDirectionColumns = useMemo(() => {
    const columns = referenceColumns.filter((column) => column.startsWith("Dir_"));
    return columns.length > 0 ? columns : ["Dir_100m"];
  }, [referenceColumns]);

  const speedSensors = useMemo(
    () => (sensorsQuery.data?.sensors ?? []).filter((sensor) => sensor.sensor_type === "wind_speed").sort((left, right) => right.height_m - left.height_m),
    [sensorsQuery.data],
  );

  const directionSensors = useMemo(
    () =>
      (sensorsQuery.data?.sensors ?? [])
        .filter((sensor) => sensor.sensor_type === "wind_direction")
        .sort((left, right) => right.height_m - left.height_m),
    [sensorsQuery.data],
  );

  const ltcResults = ltcResultsQuery.data?.results ?? [];
  const fallbackLatestResult = getLatestResult(ltcResults);
  const activeResult = useMemo(() => {
    if (focusedAlgorithm === null) {
      return fallbackLatestResult;
    }
    return ltcResults.find((result) => result.algorithm === focusedAlgorithm) ?? fallbackLatestResult;
  }, [fallbackLatestResult, focusedAlgorithm, ltcResults]);
  const activeAlgorithm = activeResult?.algorithm ?? null;

  const ltcScatterQuery = useQuery({
    queryKey: ["ltc-scatter", sessionId, activeAlgorithm],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_scatter", { algorithm: activeAlgorithm }),
    enabled: sessionId !== null && activeAlgorithm !== null,
    staleTime: 10_000,
  });

  const ltcResidualsQuery = useQuery({
    queryKey: ["ltc-residuals", sessionId, activeAlgorithm],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_residuals", { algorithm: activeAlgorithm }),
    enabled: sessionId !== null && activeAlgorithm !== null,
    staleTime: 10_000,
  });

  const ltcMonthlyQuery = useQuery({
    queryKey: ["ltc-monthly", sessionId, ltcResults.length],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_monthly", {}),
    enabled: sessionId !== null && ltcResults.length >= 1,
    staleTime: 10_000,
  });

  const ltcConvergenceQuery = useQuery({
    queryKey: ["ltc-convergence", sessionId, ltcResults.length, ensembleQuery.data?.available],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_convergence", {}),
    enabled: sessionId !== null && ltcResults.length >= 1,
    staleTime: 10_000,
  });

  const uncertaintyTornadoQuery = useQuery({
    queryKey: ["uncertainty-tornado", sessionId, latestUncertainty?.total_uncertainty_pct],
    queryFn: () =>
      resultsApi.getPlot(sessionId ?? "", "uncertainty_tornado", {
        total_pct: latestUncertainty?.total_uncertainty_pct ?? 0,
        measurement_pct: latestUncertainty?.components.measurement ?? 0,
        vertical_pct: latestUncertainty?.components.vertical_extrapolation ?? 0,
        mcp_pct: latestUncertainty?.components.mcp ?? 0,
        future_pct: latestUncertainty?.components.future_variability ?? 0,
      }),
    enabled: sessionId !== null && latestUncertainty !== null,
    staleTime: 10_000,
  });

  useEffect(() => {
    if (speedSensors[0] && !shortCol) {
      setShortCol(speedSensors[0].name);
      setMeasuredCol(speedSensors[0].name);
      setUncMeasurementHeight(String(speedSensors[0].height_m));
    }
  }, [shortCol, speedSensors]);

  useEffect(() => {
    if (configQuery.data?.hub_height_m !== undefined && configQuery.data.hub_height_m !== null) {
      setUncHubHeight(String(configQuery.data.hub_height_m));
    }
  }, [configQuery.data?.hub_height_m]);

  useEffect(() => {
    if (directionSensors[0] && !shortDirCol) {
      setShortDirCol(directionSensors[0].name);
    }
  }, [directionSensors, shortDirCol]);

  useEffect(() => {
    if (!referenceSpeedColumns.includes(longCol)) {
      setLongCol(referenceSpeedColumns[0]);
    }
  }, [longCol, referenceSpeedColumns]);

  useEffect(() => {
    if (!referenceDirectionColumns.includes(longDirCol)) {
      setLongDirCol(referenceDirectionColumns[0]);
    }
  }, [longDirCol, referenceDirectionColumns]);

  useEffect(() => {
    if (activeResult === null) {
      return;
    }
    const metrics = activeResult.metrics as Record<string, unknown>;
    const rSquared = getNumericMetric(metrics, ["r_squared", "r2"]);
    const concurrentHours = getNumericMetric(metrics, ["concurrent_points", "n_concurrent"]);
    if (rSquared !== null) {
      setUncRsq(rSquared.toFixed(4));
    }
    if (concurrentHours !== null) {
      setUncHours(String(Math.round(concurrentHours)));
    }
  }, [activeResult]);

  const runLtcMutation = useMutation({
    mutationFn: () =>
      analysisApi.runLtc(sessionId ?? "", selectedLtcAlgorithm, {
        short_col: shortCol,
        long_col: longCol,
        short_dir_col: shortDirCol,
        long_dir_col: longDirCol,
      }),
    onSuccess: () => {
      setLatestError(null);
      setFocusedAlgorithm(selectedLtcAlgorithm);
      void queryClient.invalidateQueries({ queryKey: ["ltc-results", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const runEnsembleMutation = useMutation({
    mutationFn: () => analysisApi.runEnsemble(sessionId ?? "", measuredCol),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["ensemble-results", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const clippingMutation = useMutation({
    mutationFn: () => analysisApi.runClipping(sessionId ?? "", { speed_col: clippingSpeedCol, source: selectedLtcSource }),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestClipping(result);
    },
    onError: (error) => setLatestError(error),
  });

  const homogeneityMutation = useMutation({
    mutationFn: () => analysisApi.analyzeHomogeneity(sessionId ?? "", homogeneityMethod),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestHomogeneity(result);
      if (result.datasets[0]) {
        setCutoffYear(String(result.datasets[0].recommended_start_year));
      }
    },
    onError: (error) => setLatestError(error),
  });

  const applyHomogeneityMutation = useMutation({
    mutationFn: () => analysisApi.applyHomogeneity(sessionId ?? "", Number(cutoffYear)),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestHomogeneityApply(result);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const uncertaintyMutation = useMutation({
    mutationFn: () =>
      analysisApi.calculateUncertainty(sessionId ?? "", {
        measurement_uncertainty_pct: Number(uncMeasurementPct),
        measurement_height_m: Number(uncMeasurementHeight),
        hub_height_m: Number(uncHubHeight),
        shear_method: uncShearMethod,
        mcp_r_squared: Number(uncRsq),
        concurrent_hours: Number(uncHours),
        algorithm: selectedLtcAlgorithm,
        iav_pct: Number(uncIav),
        shear_std: Number(uncShearStd),
        is_interpolation: false,
      }),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestUncertainty(result);
    },
    onError: (error) => setLatestError(error),
  });

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="LTC" detail="Run correction algorithms, ensemble blending, clipping, homogeneity, and uncertainty analysis." />
        <EmptyState title="Session required" detail="Create a session before running long-term correction workflows." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="LTC" detail="Run deterministic and ML LTC algorithms, compare outputs, and execute the downstream risk-analysis actions." />

      <div className="metric-grid">
        <MetricCard label="LTC runs" value={String(ltcResultsQuery.data?.results.length ?? 0)} tone="accent" />
        <MetricCard label="Ensemble" value={ensembleQuery.data?.available ? "Ready" : "Pending"} />
        <MetricCard label="Algorithm" value={selectedLtcAlgorithm} />
        <MetricCard
          label="Latest uncertainty"
          value={latestUncertainty ? `${latestUncertainty.total_uncertainty_pct.toFixed(2)}%` : "Not run"}
        />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Run LTC</span>
          <label className="form-field">
            <span>
              Algorithm
              <HelpTooltip text="Select the long-term correction algorithm to run against the concurrent measured and reference data." />
            </span>
            <select value={selectedLtcAlgorithm} onChange={(event) => setSelectedLtcAlgorithm(event.target.value)}>
              {ltcAlgorithms.map((algorithm) => (
                <option key={algorithm} value={algorithm}>
                  {algorithm}
                </option>
              ))}
            </select>
            <small className="field-help">
              {algorithmHelp[selectedLtcAlgorithm]?.description}
              <br />
              <strong>When to use:</strong> {algorithmHelp[selectedLtcAlgorithm]?.recommended}
            </small>
          </label>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Measured short column</span>
              <select value={shortCol} onChange={(event) => setShortCol(event.target.value)}>
                <option value="">Select measured wind column</option>
                {speedSensors.map((sensor) => (
                  <option key={sensor.name} value={sensor.name}>
                    {sensor.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Long reference column</span>
              <select value={longCol} onChange={(event) => setLongCol(event.target.value)}>
                {referenceSpeedColumns.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Measured direction column</span>
              <select value={shortDirCol} onChange={(event) => setShortDirCol(event.target.value)}>
                <option value="">Select measured direction column</option>
                {directionSensors.map((sensor) => (
                  <option key={sensor.name} value={sensor.name}>
                    {sensor.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Reference direction column</span>
              <select value={longDirCol} onChange={(event) => setLongDirCol(event.target.value)}>
                {referenceDirectionColumns.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="button-row wrap">
            <button className="primary-button" type="button" onClick={() => runLtcMutation.mutate()}>
              Run {selectedLtcAlgorithm}
            </button>
            <select
              aria-label="Measured column for ensemble"
              value={measuredCol}
              onChange={(event) => setMeasuredCol(event.target.value)}
            >
              <option value="">Select measured wind column</option>
              {speedSensors.map((sensor) => (
                <option key={sensor.name} value={sensor.name}>
                  {sensor.name}
                </option>
              ))}
            </select>
            <button className="secondary-button" type="button" onClick={() => runEnsembleMutation.mutate()}>
              Run Ensemble
            </button>
            {ensembleQuery.data?.available ? (
              <button
                className="secondary-button"
                type="button"
                onClick={() => window.open(exportsApi.downloadEnsemble(sessionId), "_blank", "noopener")}
              >
                Export Ensemble CSV
              </button>
            ) : null}
          </div>
        </article>

        <article className="content-card stack-gap">
          <span className="eyebrow">Risk-analysis actions</span>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Clipping speed column</span>
              <input value={clippingSpeedCol} onChange={(event) => setClippingSpeedCol(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Clipping source</span>
              <select value={selectedLtcSource} onChange={(event) => setSelectedLtcSource(event.target.value)}>
                <option value="ensemble">ensemble</option>
                {(ltcResultsQuery.data?.results ?? []).map((result) => (
                  <option key={result.algorithm} value={result.algorithm}>
                    {result.algorithm}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              <span>Homogeneity method</span>
              <select value={homogeneityMethod} onChange={(event) => setHomogeneityMethod(event.target.value)}>
                <option value="annual">annual</option>
                <option value="monthly">monthly</option>
              </select>
            </label>
            <label className="form-field">
              <span>Cutoff year</span>
              <input value={cutoffYear} onChange={(event) => setCutoffYear(event.target.value)} />
            </label>
          </div>
          <div className="button-row wrap">
            <button className="secondary-button" type="button" onClick={() => clippingMutation.mutate()}>
              Run Clipping
            </button>
            <button className="secondary-button" type="button" onClick={() => homogeneityMutation.mutate()}>
              Analyze Homogeneity
            </button>
            <button className="secondary-button" type="button" onClick={() => applyHomogeneityMutation.mutate()}>
              Apply Cutoff
            </button>
          </div>
        </article>
      </div>

      {activeAlgorithm ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">Latest run — {activeAlgorithm}</span>
          <div className="panel-grid panel-grid-two">
            <PlotlyFigure plot={ltcScatterQuery.data} emptyTitle="Scatter loading" emptyDetail="" />
            <PlotlyFigure plot={ltcResidualsQuery.data} emptyTitle="Residuals loading" emptyDetail="" />
          </div>
        </article>
      ) : null}

      <article className="content-card stack-gap">
        <span className="eyebrow">LTC comparison</span>
        <div className="panel-grid panel-grid-two">
          <PlotlyFigure
            plot={ltcMonthlyQuery.data}
            emptyTitle="Monthly comparison"
            emptyDetail="Run at least one algorithm to compare corrected monthly means."
          />
          <PlotlyFigure
            plot={ltcConvergenceQuery.data}
            emptyTitle="Convergence"
            emptyDetail="Run at least one algorithm to inspect long-term convergence."
          />
        </div>
      </article>

      <article className="content-card stack-gap">
        <span className="eyebrow">LTC metrics comparison</span>
        <DataTable<LtcResultSummary>
          columns={[
            { key: "algorithm", header: "Algorithm", cell: (row) => row.algorithm },
            { key: "rows", header: "Rows", cell: (row) => row.rows },
            {
              key: "diagnostics",
              header: "Diagnostics",
              cell: (row) => (
                <button className="ghost-button table-action" type="button" onClick={() => setFocusedAlgorithm(row.algorithm)}>
                  View
                </button>
              ),
            },
            {
              key: "export",
              header: "Export",
              cell: (row) => (
                <button
                  className="ghost-button table-action"
                  type="button"
                  onClick={() => window.open(exportsApi.downloadLtc(sessionId, row.algorithm), "_blank", "noopener")}
                >
                  CSV
                </button>
              ),
            },
            {
              key: "metrics",
              header: "Metrics",
              cell: (row) => (
                <div className="metric-pill-row">
                  {Object.entries(row.metrics).map(([key, value]) => (
                    <span key={key} className="tag-pill">{`${key}: ${String(value)}`}</span>
                  ))}
                </div>
              ),
            },
          ]}
          rows={ltcResultsQuery.data?.results ?? []}
          getRowKey={(row) => row.algorithm}
          emptyTitle="No LTC results"
          emptyDetail="Run one of the LTC algorithms to populate the comparison table."
        />
      </article>

      <article className="content-card stack-gap">
        <span className="eyebrow">Clipping and homogeneity</span>
        {latestClipping ? (
          <div className="stack-gap">
            <p className="muted-text">
              Optimal start year {latestClipping.optimal_start_year}, minimum uncertainty {latestClipping.min_uncertainty.toFixed(3)}
            </p>
            <DataTable<(typeof latestClipping.analysis_data)[number]>
              columns={[
                { key: "start", header: "Start year", cell: (row) => row.start_year },
                { key: "years", header: "Years", cell: (row) => row.n_years },
                { key: "combined", header: "Combined", cell: (row) => row.combined_uncertainty.toFixed(4) },
              ]}
              rows={latestClipping.analysis_data.slice(0, 6)}
              getRowKey={(row) => String(row.start_year)}
              emptyTitle="No clipping data"
              emptyDetail=""
            />
          </div>
        ) : latestHomogeneity ? (
          <DataTable<(typeof latestHomogeneity.datasets)[number]>
            columns={[
              { key: "name", header: "Dataset", cell: (row) => row.name },
              { key: "year", header: "Recommended start", cell: (row) => row.recommended_start_year },
              { key: "p", header: "Pettitt p", cell: (row) => row.pettitt_p_value.toFixed(4) },
              { key: "trend", header: "Trend/year", cell: (row) => row.trend_per_year.toFixed(4) },
            ]}
            rows={latestHomogeneity.datasets}
            getRowKey={(row) => row.name}
            emptyTitle="No homogeneity data"
            emptyDetail=""
          />
        ) : (
          <EmptyState title="No clipping or homogeneity result" detail="Run either action to inspect its returned diagnostics here." />
        )}
        {latestHomogeneityApply ? (
          <p className="muted-text">Rows before {latestHomogeneityApply.rows_before}, after {latestHomogeneityApply.rows_after}</p>
        ) : null}
      </article>

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Uncertainty form</span>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Measurement %</span>
              <input value={uncMeasurementPct} onChange={(event) => setUncMeasurementPct(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Measurement height (m)</span>
              <input value={uncMeasurementHeight} onChange={(event) => setUncMeasurementHeight(event.target.value)} />
            </label>
            <label className="form-field">
              <span>
                Hub height (m)
                <HelpTooltip text="The target hub height for the uncertainty estimate. This is auto-filled from the site configuration when available." />
              </span>
              <input value={uncHubHeight} onChange={(event) => setUncHubHeight(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Shear method</span>
              <select value={uncShearMethod} onChange={(event) => setUncShearMethod(event.target.value)}>
                <option value="simple_power_law">Simple Power Law</option>
                <option value="log_law">Log Law</option>
                <option value="momm_power_law">MoMM Power Law</option>
              </select>
            </label>
            <label className="form-field">
              <span>
                R²
                <HelpTooltip text="R-squared from the MCP concurrent regression. Higher R² reduces the MCP uncertainty component." />
              </span>
              <input value={uncRsq} onChange={(event) => setUncRsq(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Concurrent hours</span>
              <input value={uncHours} onChange={(event) => setUncHours(event.target.value)} />
            </label>
            <label className="form-field">
              <span>IAV %</span>
              <input value={uncIav} onChange={(event) => setUncIav(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Shear std</span>
              <input value={uncShearStd} onChange={(event) => setUncShearStd(event.target.value)} />
            </label>
          </div>
          <small className="field-help">Auto-populated from {activeAlgorithm ?? "latest"} LTC result. Override to customize.</small>
          <button className="primary-button" type="button" onClick={() => uncertaintyMutation.mutate()}>
            Calculate Uncertainty
          </button>
        </article>

        <article className="content-card stack-gap">
          <span className="eyebrow">Uncertainty tornado</span>
          <PlotlyFigure plot={uncertaintyTornadoQuery.data} emptyTitle="Run uncertainty first" emptyDetail="" />
          {latestUncertainty ? (
            <div className="metric-grid">
              <MetricCard label="Total" value={`${latestUncertainty.total_uncertainty_pct.toFixed(2)}%`} tone="accent" />
              <MetricCard label="P75" value={latestUncertainty.p_factors.p75.toFixed(4)} />
              <MetricCard label="P90" value={latestUncertainty.p_factors.p90.toFixed(4)} />
              <MetricCard label="P99" value={latestUncertainty.p_factors.p99.toFixed(4)} />
            </div>
          ) : null}
        </article>
      </div>
    </section>
  );
}