import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analysisApi, resultsApi, uploadsApi } from "../lib/api";
import type { CleaningLogEntry, JsonValue, SensorCoverageResponse, SensorRecord } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { CleaningRuleParams } from "../components/common/CleaningRuleParams";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { FileDropzone } from "../components/common/FileDropzone";
import { HelpTooltip } from "../components/common/HelpTooltip";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { PlotlyFigure } from "../components/common/PlotlyFigure";

type CoverageRow = SensorRecord & SensorCoverageResponse;

const cleaningRuleDefaults: Record<string, Record<string, JsonValue>> = {
  range_check: { min: 0, max: 50 },
  icing_filter: { temp_threshold_c: 2 },
  stuck_sensor: { consecutive_count: 6 },
  tower_shadow: { exclude_sectors: [170, 190] },
  spike_filter: { window_size: 6, sigma_threshold: 4 },
  timestamp_gap_fill: {},
  custom_period_exclude: {},
};

export function DataPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [lastUploadPath, setLastUploadPath] = useState<string | null>(null);
  const [ruleType, setRuleType] = useState("range_check");
  const [sensorName, setSensorName] = useState("");
  const [selectedSensor, setSelectedSensor] = useState<string | null>(null);
  const [cleaningParams, setCleaningParams] = useState<Record<string, JsonValue>>(cleaningRuleDefaults.range_check);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const sensorsQuery = useQuery({
    queryKey: ["sensors-coverage", sessionId],
    queryFn: async () => {
      const sensors = await uploadsApi.getSensors(sessionId ?? "");
      const coverage = await Promise.all(sensors.sensors.map((sensor) => uploadsApi.getCoverage(sessionId ?? "", sensor.name)));
      return sensors.sensors.map((sensor, index) => ({ ...sensor, ...coverage[index] }));
    },
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const cleaningLogQuery = useQuery({
    queryKey: ["cleaning-log", sessionId],
    queryFn: () => analysisApi.getCleaningLog(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const previewPlotQuery = useQuery({
    queryKey: ["timeseries-preview", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "timeseries_preview", {}),
    enabled: sessionId !== null && (sensorsQuery.data?.length ?? 0) > 0,
    staleTime: 15_000,
  });

  const coveragePlotQuery = useQuery({
    queryKey: ["coverage-timeline", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "coverage_timeline", {}),
    enabled: sessionId !== null && (sensorsQuery.data?.length ?? 0) > 0,
    staleTime: 15_000,
  });

  const cleaningOverlayQuery = useQuery({
    queryKey: ["cleaning-overlay", sessionId, sensorName, cleaningLogQuery.data?.entries.length],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "cleaning_overlay", { sensor_name: sensorName }),
    enabled: sessionId !== null && (cleaningLogQuery.data?.entries.length ?? 0) > 0 && sensorName !== "",
    staleTime: 10_000,
  });

  const sensorStatsQuery = useQuery({
    queryKey: ["sensor-stats", sessionId, selectedSensor],
    queryFn: () => analysisApi.getSensorStatistics(sessionId ?? "", selectedSensor ?? ""),
    enabled: sessionId !== null && selectedSensor !== null,
    staleTime: 15_000,
  });

  useEffect(() => {
    const firstSensor = sensorsQuery.data?.[0]?.name;
    if (firstSensor && !sensorName) {
      setSensorName(firstSensor);
    }
  }, [sensorName, sensorsQuery.data]);

  const uploadTimeseriesMutation = useMutation({
    mutationFn: (file: File) => uploadsApi.uploadTimeseries(sessionId ?? "", file, file.name),
    onSuccess: (result) => {
      setLatestError(null);
      setLastUploadPath(String(result.file_path));
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["timeseries-preview", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const uploadDatamodelMutation = useMutation({
    mutationFn: (file: File) => uploadsApi.uploadDatamodel(sessionId ?? "", file, file.name),
    onSuccess: (result) => {
      setLatestError(null);
      setLastUploadPath(String(result.file_path));
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["runconfig", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["site-map", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["timeseries-preview", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["coverage-timeline", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const applyCleaningMutation = useMutation({
    mutationFn: () =>
      analysisApi.applyCleaning(sessionId ?? "", {
        rule_type: ruleType,
        sensor: sensorName,
        params: cleaningParams,
        start_date: startDate,
        end_date: endDate,
      }),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["cleaning-log", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["timeseries-preview", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["cleaning-overlay", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const undoCleaningMutation = useMutation({
    mutationFn: (entryIndex: number) => analysisApi.undoCleaning(sessionId ?? "", entryIndex),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["cleaning-log", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["timeseries-preview", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["cleaning-overlay", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const averageCoverage = useMemo(() => {
    if (!sensorsQuery.data?.length) {
      return "0%";
    }
    const mean = sensorsQuery.data.reduce((sum, row) => sum + row.coverage_pct, 0) / sensorsQuery.data.length;
    return `${mean.toFixed(1)}%`;
  }, [sensorsQuery.data]);

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="Data" detail="Upload measured datasets, inspect sensor coverage, and manage cleaning rules." />
        <EmptyState title="Session required" detail="Create a browser session before uploading files or applying cleaning rules." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="Data" detail="Upload the timeseries and datamodel, review coverage, and apply session-scoped cleaning rules." />

      <div className="metric-grid">
        <MetricCard label="Sensors" value={String(sensorsQuery.data?.length ?? 0)} tone="accent" />
        <MetricCard label="Average coverage" value={averageCoverage} />
        <MetricCard label="Cleaning entries" value={String(cleaningLogQuery.data?.entries.length ?? 0)} />
        <MetricCard label="Latest upload" value={lastUploadPath ?? "None"} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Upload files</span>
          <FileDropzone
            label="Upload timeseries"
            helperText="Accepts CSV, TSV, or Excel-compatible timeseries files and parses them directly into session state."
            accept=".csv,.tsv,.txt,.xlsx,.xls"
            onSelect={(file) => uploadTimeseriesMutation.mutate(file)}
          />
          <FileDropzone
            label="Upload datamodel"
            helperText="Provide the IEA Task 43 datamodel JSON so the backend can build the height-to-sensor mapping."
            accept=".json"
            onSelect={(file) => uploadDatamodelMutation.mutate(file)}
          />
        </article>

        <article className="content-card stack-gap">
          <span className="eyebrow">Upload status</span>
          <p className="muted-text">
            Load the timeseries first, then the Task 43 datamodel so the backend can map heights to sensors and unlock
            inline previews.
          </p>
          <div className="definition-list compact-definition-list">
            <div>
              <dt>Timeseries</dt>
              <dd>{uploadTimeseriesMutation.isPending ? "Uploading" : "Ready for upload"}</dd>
            </div>
            <div>
              <dt>Datamodel</dt>
              <dd>{uploadDatamodelMutation.isPending ? "Uploading" : "Ready for upload"}</dd>
            </div>
          </div>
        </article>
      </div>

      {sensorsQuery.data?.length ? (
        <div className="panel-grid panel-grid-two">
          <PlotlyFigure
            plot={previewPlotQuery.data}
            emptyTitle="Upload data to preview"
            emptyDetail="The first 7 days of wind speed sensors will appear here."
          />
          <PlotlyFigure
            plot={coveragePlotQuery.data}
            emptyTitle="Coverage unavailable"
            emptyDetail="Upload both timeseries and datamodel to see the availability timeline."
          />
        </div>
      ) : null}

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Apply cleaning rule</span>
          <label className="form-field">
            <span>
              Rule type
              <HelpTooltip text="Select a data quality rule. Each rule targets a specific data issue: range violations, sensor icing, stuck values, tower wake, or statistical spikes." />
            </span>
            <select
              value={ruleType}
              onChange={(event) => {
                setRuleType(event.target.value);
                setCleaningParams(cleaningRuleDefaults[event.target.value] ?? {});
              }}
            >
              {Object.keys(cleaningRuleDefaults).map((rule) => (
                <option key={rule} value={rule}>
                  {rule}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span>Sensor</span>
            <select value={sensorName} onChange={(event) => setSensorName(event.target.value)}>
              <option value="">Select sensor</option>
              {(sensorsQuery.data ?? []).map((sensor) => (
                <option key={sensor.name} value={sensor.name}>
                  {sensor.name}
                </option>
              ))}
            </select>
          </label>
          <CleaningRuleParams
            ruleType={ruleType}
            params={cleaningParams}
            onParamsChange={setCleaningParams}
            sensors={sensorsQuery.data ?? []}
          />
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Start date</span>
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </label>
            <label className="form-field">
              <span>End date</span>
              <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
            </label>
          </div>
          <button className="primary-button" type="button" onClick={() => applyCleaningMutation.mutate()}>
            Apply Cleaning Rule
          </button>
        </article>

        <PlotlyFigure
          plot={cleaningOverlayQuery.data}
          emptyTitle="Apply a cleaning rule to compare"
          emptyDetail="The overlay shows raw vs cleaned data for the selected sensor."
        />
      </div>

      <article className="content-card stack-gap">
        <span className="eyebrow">Coverage table</span>
        <DataTable<CoverageRow>
          columns={[
            { key: "sensor", header: "Sensor", cell: (row) => row.name },
            { key: "height", header: "Height", cell: (row) => `${row.height_m} m` },
            { key: "type", header: "Type", cell: (row) => row.sensor_type },
            { key: "coverage", header: "Coverage", cell: (row) => `${row.coverage_pct.toFixed(1)}%` },
            { key: "largest-gap", header: "Largest gap", cell: (row) => `${row.largest_gap_minutes} min` },
          ]}
          rows={sensorsQuery.data ?? []}
          getRowKey={(row) => `${row.name}-${row.height_m}`}
          onRowClick={(row) => setSelectedSensor(row.name)}
          emptyTitle="No sensors yet"
          emptyDetail="Upload both timeseries and datamodel files to populate the sensor inventory and coverage table."
        />
      </article>

      {selectedSensor && sensorStatsQuery.data ? (
        <article className="content-card stack-gap sensor-detail-card">
          <span className="eyebrow">Sensor detail — {selectedSensor}</span>
          <div className="metric-grid">
            <MetricCard label="Mean" value={sensorStatsQuery.data.mean.toFixed(2)} />
            <MetricCard label="Weibull k" value={sensorStatsQuery.data.weibull_k.toFixed(2)} />
            <MetricCard label="Weibull A" value={sensorStatsQuery.data.weibull_A.toFixed(2)} />
            <MetricCard label="Coverage" value={`${sensorStatsQuery.data.coverage_pct.toFixed(1)}%`} tone="accent" />
          </div>
        </article>
      ) : null}

      <article className="content-card stack-gap">
        <span className="eyebrow">Cleaning log</span>
        <DataTable<CleaningLogEntry>
          columns={[
            { key: "rule", header: "Rule", cell: (row) => row.rule_type },
            { key: "sensor", header: "Sensor", cell: (row) => row.sensor || "All" },
            { key: "records", header: "Records", cell: (row) => row.records_affected },
            { key: "period", header: "Period", cell: (row) => `${row.start_date || "start"} to ${row.end_date || "end"}` },
            {
              key: "undo",
              header: "Action",
              cell: (row) => (
                <button
                  className="ghost-button table-action"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    undoCleaningMutation.mutate(cleaningLogQuery.data?.entries.indexOf(row) ?? -1);
                  }}
                >
                  Undo
                </button>
              ),
            },
          ]}
          rows={cleaningLogQuery.data?.entries ?? []}
          getRowKey={(row, index) => `${row.rule_type}-${row.applied_at}-${index}`}
          emptyTitle="No cleaning rules applied"
          emptyDetail="Applied rule entries will appear here and can be undone one at a time."
        />
      </article>
    </section>
  );
}