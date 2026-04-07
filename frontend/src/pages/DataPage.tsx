import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { analysisApi, uploadsApi } from "../lib/api";
import type { CleaningLogEntry, JsonValue, SensorCoverageResponse, SensorRecord } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { DataTable } from "../components/common/DataTable";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { FileDropzone } from "../components/common/FileDropzone";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";

type CoverageRow = SensorRecord & SensorCoverageResponse;

const cleaningRuleHelp: Record<string, string> = {
  range_check: '{"min": 0, "max": 50}',
  icing_filter: '{"temp_threshold_c": 2}',
  stuck_sensor: '{"consecutive_count": 6}',
  tower_shadow: '{"exclude_sectors": [170, 190]}',
  spike_filter: '{"window_size": 6, "sigma_threshold": 4}',
  timestamp_gap_fill: "{}",
  custom_period_exclude: '{}',
};

export function DataPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [lastUploadPath, setLastUploadPath] = useState<string | null>(null);
  const [ruleType, setRuleType] = useState("range_check");
  const [sensorName, setSensorName] = useState("");
  const [paramsText, setParamsText] = useState(cleaningRuleHelp.range_check);
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
    },
    onError: (error) => setLatestError(error),
  });

  const applyCleaningMutation = useMutation({
    mutationFn: () =>
      analysisApi.applyCleaning(sessionId ?? "", {
        rule_type: ruleType,
        sensor: sensorName,
        params: paramsText ? (JSON.parse(paramsText) as JsonValue) : {},
        start_date: startDate,
        end_date: endDate,
      }),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["cleaning-log", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const undoCleaningMutation = useMutation({
    mutationFn: (entryIndex: number) => analysisApi.undoCleaning(sessionId ?? "", entryIndex),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["cleaning-log", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["sensors-coverage", sessionId] });
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
          <span className="eyebrow">Apply cleaning rule</span>
          <label className="form-field">
            <span>Rule type</span>
            <select value={ruleType} onChange={(event) => {
              setRuleType(event.target.value);
              setParamsText(cleaningRuleHelp[event.target.value] ?? "{}");
            }}>
              {Object.keys(cleaningRuleHelp).map((rule) => (
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
          <label className="form-field">
            <span>Params JSON</span>
            <textarea rows={4} value={paramsText} onChange={(event) => setParamsText(event.target.value)} />
          </label>
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
          emptyTitle="No sensors yet"
          emptyDetail="Upload both timeseries and datamodel files to populate the sensor inventory and coverage table."
        />
      </article>

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
                <button className="ghost-button table-action" type="button" onClick={() => undoCleaningMutation.mutate(cleaningLogQuery.data?.entries.indexOf(row) ?? -1)}>
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