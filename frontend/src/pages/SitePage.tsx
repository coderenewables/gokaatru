import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { configApi, analysisApi, resultsApi, uploadsApi } from "../lib/api";
import type { ExtrapolationResponse, SensorRecord } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { PlotlyFigure } from "../components/common/PlotlyFigure";

function numericString(value: unknown) {
  return typeof value === "number" ? String(value) : "";
}

function recordValue(record: Record<string, unknown> | null, key: string) {
  return record ? record[key] : undefined;
}

function speedSensorsOnly(sensors: SensorRecord[] | undefined) {
  return (sensors ?? []).filter((sensor) => sensor.sensor_type === "wind_speed").sort((left, right) => right.height_m - left.height_m);
}

export function SitePage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const selectedSensors = useWorkspaceStore((state) => state.selectedSensors);
  const setSelectedSensors = useWorkspaceStore((state) => state.setSelectedSensors);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [projectName, setProjectName] = useState("");
  const [measurementType, setMeasurementType] = useState("mast");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [elevation, setElevation] = useState("");
  const [hubHeight, setHubHeight] = useState("");
  const [tableAggregation, setTableAggregation] = useState("mean");
  const [latestExtrapolation, setLatestExtrapolation] = useState<ExtrapolationResponse | null>(null);

  const configQuery = useQuery({
    queryKey: ["runconfig", sessionId],
    queryFn: () => configApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const summaryQuery = useQuery({
    queryKey: ["analysis-summary", sessionId],
    queryFn: () => configApi.getSummary(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const sensorsQuery = useQuery({
    queryKey: ["site-speed-sensors", sessionId],
    queryFn: async () => uploadsApi.getSensors(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const availableSpeedSensors = useMemo(() => speedSensorsOnly(sensorsQuery.data?.sensors), [sensorsQuery.data]);

  useEffect(() => {
    if (!configQuery.data) {
      return;
    }
    const location = typeof configQuery.data.location === "object" && configQuery.data.location !== null && !Array.isArray(configQuery.data.location)
      ? (configQuery.data.location as Record<string, unknown>)
      : null;
    setProjectName(typeof configQuery.data.project_name === "string" ? configQuery.data.project_name : "");
    setMeasurementType(typeof configQuery.data.measurement_type === "string" ? configQuery.data.measurement_type : "mast");
    setLatitude(typeof recordValue(location, "latitude") === "number" ? String(recordValue(location, "latitude")) : "");
    setLongitude(typeof recordValue(location, "longitude") === "number" ? String(recordValue(location, "longitude")) : "");
    setElevation(typeof recordValue(location, "elevation_m") === "number" ? String(recordValue(location, "elevation_m")) : "0");
    setHubHeight(numericString(configQuery.data.hub_height_m));
  }, [configQuery.data]);

  useEffect(() => {
    if (selectedSensors.length === 0 && availableSpeedSensors.length >= 2) {
      setSelectedSensors(availableSpeedSensors.slice(0, 3).map((sensor) => sensor.name));
    }
  }, [availableSpeedSensors, selectedSensors.length, setSelectedSensors]);

  const heightSensorsJson = useMemo(() => {
    const pairs = availableSpeedSensors.filter((sensor) => selectedSensors.includes(sensor.name)).reduce<Record<string, string>>((accumulator, sensor) => {
      accumulator[String(sensor.height_m)] = sensor.name;
      return accumulator;
    }, {});
    return JSON.stringify(pairs);
  }, [availableSpeedSensors, selectedSensors]);

  const shearPlotQuery = useQuery({
    queryKey: ["shear-plot", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "shear_table", { table_type: "shear" }),
    enabled: sessionId !== null && summaryQuery.data?.shear_table_ready === true,
    staleTime: 15_000,
  });

  const roughnessPlotQuery = useQuery({
    queryKey: ["roughness-plot", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "shear_table", { table_type: "roughness" }),
    enabled: sessionId !== null && summaryQuery.data?.roughness_table_ready === true,
    staleTime: 15_000,
  });

  const saveMetadataMutation = useMutation({
    mutationFn: () =>
      configApi.update(sessionId ?? "", {
        updates: [
          { key: "project_name", value: projectName },
          { key: "measurement_type", value: measurementType },
          { key: "location.latitude", value: Number(latitude) },
          { key: "location.longitude", value: Number(longitude) },
          { key: "location.elevation_m", value: Number(elevation || 0) },
          { key: "hub_height_m", value: Number(hubHeight) },
        ],
      }),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["runconfig", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const calculateShearMutation = useMutation({
    mutationFn: () => analysisApi.calculateShear(sessionId ?? "", heightSensorsJson),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const buildShearTableMutation = useMutation({
    mutationFn: () => analysisApi.buildShearTable(sessionId ?? "", tableAggregation),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["shear-plot", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const calculateRoughnessMutation = useMutation({
    mutationFn: () => analysisApi.calculateRoughness(sessionId ?? "", heightSensorsJson),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const buildRoughnessTableMutation = useMutation({
    mutationFn: () => analysisApi.buildRoughnessTable(sessionId ?? "", tableAggregation),
    onSuccess: () => {
      setLatestError(null);
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["roughness-plot", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  const extrapolateMutation = useMutation({
    mutationFn: () => analysisApi.extrapolateHub(sessionId ?? "", { hub_height_m: Number(hubHeight), shear_model: "power_law" }),
    onSuccess: (result) => {
      setLatestError(null);
      setLatestExtrapolation(result);
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
    onError: (error) => setLatestError(error),
  });

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="Site" detail="Edit run metadata, compute shear and roughness, and extrapolate to hub height." />
        <EmptyState title="Session required" detail="Create a session before editing site metadata or running extrapolation actions." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="Site" detail="Manage the runconfig, build lookup tables, and create the measured hub-height series used downstream." />

      <div className="metric-grid">
        <MetricCard label="Project" value={summaryQuery.data?.project_name ? String(summaryQuery.data.project_name) : "Untitled"} tone="accent" />
        <MetricCard label="Selected speed sensors" value={String(selectedSensors.length)} />
        <MetricCard label="Shear table" value={summaryQuery.data?.shear_table_ready ? "Ready" : "Pending"} />
        <MetricCard label="Roughness table" value={summaryQuery.data?.roughness_table_ready ? "Ready" : "Pending"} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <div className="panel-grid panel-grid-two">
        <article className="content-card stack-gap">
          <span className="eyebrow">Project metadata</span>
          <div className="form-grid two-col">
            <label className="form-field">
              <span>Project name</span>
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Measurement type</span>
              <select value={measurementType} onChange={(event) => setMeasurementType(event.target.value)}>
                <option value="mast">mast</option>
                <option value="lidar">lidar</option>
                <option value="sodar">sodar</option>
              </select>
            </label>
            <label className="form-field">
              <span>Latitude</span>
              <input value={latitude} onChange={(event) => setLatitude(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Longitude</span>
              <input value={longitude} onChange={(event) => setLongitude(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Elevation (m)</span>
              <input value={elevation} onChange={(event) => setElevation(event.target.value)} />
            </label>
            <label className="form-field">
              <span>Hub height (m)</span>
              <input value={hubHeight} onChange={(event) => setHubHeight(event.target.value)} />
            </label>
          </div>
          <button className="primary-button" type="button" onClick={() => saveMetadataMutation.mutate()}>
            Save Metadata
          </button>
        </article>

        <article className="content-card stack-gap">
          <span className="eyebrow">Shear and extrapolation inputs</span>
          <label className="form-field">
            <span>Aggregation</span>
            <select value={tableAggregation} onChange={(event) => setTableAggregation(event.target.value)}>
              <option value="mean">mean</option>
              <option value="median">median</option>
              <option value="momm">momm</option>
            </select>
          </label>
          <div className="sensor-checkbox-grid">
            {availableSpeedSensors.map((sensor) => {
              const checked = selectedSensors.includes(sensor.name);
              return (
                <label key={sensor.name} className={checked ? "sensor-chip sensor-chip-selected" : "sensor-chip"}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      setSelectedSensors(
                        checked
                          ? selectedSensors.filter((name) => name !== sensor.name)
                          : [...selectedSensors, sensor.name],
                      );
                    }}
                  />
                  <span>{sensor.name}</span>
                  <small>{sensor.height_m} m</small>
                </label>
              );
            })}
          </div>
          <div className="button-row wrap">
            <button className="secondary-button" type="button" onClick={() => calculateShearMutation.mutate()}>
              Calculate Shear
            </button>
            <button className="secondary-button" type="button" onClick={() => buildShearTableMutation.mutate()}>
              Build Shear Table
            </button>
            <button className="secondary-button" type="button" onClick={() => calculateRoughnessMutation.mutate()}>
              Calculate Roughness
            </button>
            <button className="secondary-button" type="button" onClick={() => buildRoughnessTableMutation.mutate()}>
              Build Roughness Table
            </button>
            <button className="primary-button" type="button" onClick={() => extrapolateMutation.mutate()}>
              Extrapolate To Hub
            </button>
          </div>
          {latestExtrapolation ? (
            <div className="content-note">
              <strong>{latestExtrapolation.column_name}</strong>
              <p>
                direct {latestExtrapolation.method_counts.direct}, interpolated {latestExtrapolation.method_counts.interpolated}, extrapolated {latestExtrapolation.method_counts.extrapolated}
              </p>
            </div>
          ) : null}
        </article>
      </div>

      <div className="panel-grid panel-grid-two">
        <PlotlyFigure
          plot={shearPlotQuery.data}
          emptyTitle="Shear heatmap unavailable"
          emptyDetail="Calculate shear and build the table to render the month-hour heatmap."
        />
        <PlotlyFigure
          plot={roughnessPlotQuery.data}
          emptyTitle="Roughness heatmap unavailable"
          emptyDetail="Calculate roughness and build the roughness table to render the month-hour heatmap."
        />
      </div>
    </section>
  );
}