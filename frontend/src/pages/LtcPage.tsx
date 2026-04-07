import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analysisApi, resultsApi, uploadsApi } from "../lib/api";
import type { ClippingAnalysisResponse, HomogeneityAnalysisResponse, HomogeneityApplyResponse, LtcResultSummary } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";

const ltcAlgorithms = [
  "linear_least_squares",
  "total_least_squares",
  "speedsort",
  "variance_ratio",
  "xgboost",
];

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

  const speedSensors = useMemo(
    () => (sensorsQuery.data?.sensors ?? []).filter((sensor) => sensor.sensor_type === "wind_speed").sort((left, right) => right.height_m - left.height_m),
    [sensorsQuery.data],
  );

  useEffect(() => {
    if (speedSensors[0] && !shortCol) {
      setShortCol(speedSensors[0].name);
      setMeasuredCol(speedSensors[0].name);
      setUncMeasurementHeight(String(speedSensors[0].height_m));
    }
  }, [shortCol, speedSensors]);

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
        <MetricCard label="Latest uncertainty" value={latestUncertainty ? `${latestUncertainty.total_uncertainty_pct}%` : "Not run"} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Run LTC</span>
          <label className="form-field">
            <span>Algorithm</span>
            <select value={selectedLtcAlgorithm} onChange={(event) => setSelectedLtcAlgorithm(event.target.value)}>
              {ltcAlgorithms.map((algorithm) => (
                <option key={algorithm} value={algorithm}>
                  {algorithm}
                </option>
              ))}
            </select>
          </label>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Measured short column</span>
              <input value={shortCol} onChange={(event) => setShortCol(event.target.value)} list="measured-speed-columns" />
            </label>
            <label className="form-field">
              <span>Long reference column</span>
              <input value={longCol} onChange={(event) => setLongCol(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Measured direction column</span>
              <input value={shortDirCol} onChange={(event) => setShortDirCol(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Reference direction column</span>
              <input value={longDirCol} onChange={(event) => setLongDirCol(event.target.value)} />
            </label>
          </div>
          <datalist id="measured-speed-columns">
            {speedSensors.map((sensor) => (
              <option key={sensor.name} value={sensor.name} />
            ))}
          </datalist>
          <div className="button-row wrap">
            <button className="primary-button" type="button" onClick={() => runLtcMutation.mutate()}>
              Run {selectedLtcAlgorithm}
            </button>
            <input value={measuredCol} onChange={(event) => setMeasuredCol(event.target.value)} placeholder="Measured column for ensemble" />
            <button className="secondary-button" type="button" onClick={() => runEnsembleMutation.mutate()}>
              Run Ensemble
            </button>
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

      <article className="content-card stack-gap">
        <span className="eyebrow">LTC metrics comparison</span>
        <DataTable<LtcResultSummary>
          columns={[
            { key: "algorithm", header: "Algorithm", cell: (row) => row.algorithm },
            { key: "rows", header: "Rows", cell: (row) => row.rows },
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

      <div className="panel-grid panel-grid-two">
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
              <span>Hub height (m)</span>
              <input value={uncHubHeight} onChange={(event) => setUncHubHeight(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Shear method</span>
              <input value={uncShearMethod} onChange={(event) => setUncShearMethod(event.target.value)} />
            </label>
            <label className="form-field">
              <span>R²</span>
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
          <button className="primary-button" type="button" onClick={() => uncertaintyMutation.mutate()}>
            Calculate Uncertainty
          </button>
          {latestUncertainty ? (
            <div className="definition-list compact-definition-list">
              <div>
                <dt>Total</dt>
                <dd>{latestUncertainty.total_uncertainty_pct}%</dd>
              </div>
              <div>
                <dt>P90</dt>
                <dd>{latestUncertainty.p_factors.p90}</dd>
              </div>
              <div>
                <dt>MCP component</dt>
                <dd>{latestUncertainty.components.mcp}%</dd>
              </div>
            </div>
          ) : null}
        </article>
      </div>
    </section>
  );
}