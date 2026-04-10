import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { configApi, analysisApi, resultsApi, uploadsApi } from "../lib/api";
import type { ExtrapolationResponse, SensorRecord } from "../lib/types";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { HelpTooltip } from "../components/common/HelpTooltip";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { PlotlyFigure } from "../components/common/PlotlyFigure";
import type { JsonValue } from "../lib/types";

function speedSensorsOnly(sensors: SensorRecord[] | undefined) {
  return (sensors ?? []).filter((sensor) => sensor.sensor_type === "wind_speed").sort((left, right) => right.height_m - left.height_m);
}

export function SitePage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const selectedSensors = useWorkspaceStore((state) => state.selectedSensors);
  const setSelectedSensors = useWorkspaceStore((state) => state.setSelectedSensors);
  const queryClient = useQueryClient();
  const [latestError, setLatestError] = useState<unknown>(null);
  const [latestExtrapolation, setLatestExtrapolation] = useState<ExtrapolationResponse | null>(null);
  const [tableAggregation, setTableAggregation] = useState("mean");

  const configQuery = useQuery({
    queryKey: ["runconfig", sessionId],
    queryFn: () => configApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  const hubHeight = typeof configQuery.data?.hub_height_m === "number" ? String(configQuery.data.hub_height_m) : "";

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

  const shearProfileQuery = useQuery({
    queryKey: ["shear-profile", sessionId],
    queryFn: () => resultsApi.getPlot(sessionId ?? "", "shear_profile", {}),
    enabled: sessionId !== null && summaryQuery.data?.shear_table_ready === true,
    staleTime: 15_000,
  });

  const extrapolationPlotQuery = useQuery({
    queryKey: ["extrapolation-preview", sessionId, latestExtrapolation?.column_name, selectedSensors.join(",")],
    queryFn: () =>
      resultsApi.getPlot(sessionId ?? "", "timeseries", {
        sensor_names: [...selectedSensors, latestExtrapolation?.column_name ?? ""].filter(Boolean).join(","),
      }),
    enabled: sessionId !== null && latestExtrapolation !== null,
    staleTime: 15_000,
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
        <PageHeader title="Vertical Extrapolation" detail="Compute shear, then extrapolate measured and reanalysis data to hub height." />
        <EmptyState title="Session required" detail="Create a session before running shear or extrapolation calculations." />
      </section>
    );
  }

  return (
    <section className="page-section">
      <PageHeader title="Vertical Extrapolation" detail="Build shear lookup table from measured heights, then extrapolate measured and reanalysis data to hub height." />

      <div className="metric-grid">
        <MetricCard label="Selected speed sensors" value={String(selectedSensors.length)} tone="accent" />
        <MetricCard label="Hub height" value={hubHeight ? `${hubHeight} m` : "Not set"} />
        <MetricCard label="Shear table" value={summaryQuery.data?.shear_table_ready ? "Ready" : "Pending"} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      <article className="content-card stack-gap">
        <span className="eyebrow">Shear and extrapolation inputs</span>
        <label className="form-field">
          <span>
            Aggregation
            <HelpTooltip text="MoMM (Mean of Monthly Means) accounts for seasonal and diurnal data gaps. Use mean for well-covered datasets and momm for partial years." />
          </span>
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

      <div className="panel-grid panel-grid-two">
        <PlotlyFigure
          plot={shearPlotQuery.data}
          emptyTitle="Shear heatmap unavailable"
          emptyDetail="Calculate shear and build the table to render the month-hour heatmap."
        />
        <PlotlyFigure
          plot={shearProfileQuery.data}
          emptyTitle="Shear profile unavailable"
          emptyDetail="Build the shear table to inspect the fitted mean speed profile across heights."
        />
      </div>

      <div className="panel-grid panel-grid-two">
        {latestExtrapolation ? (
          <article className="content-card stack-gap">
            <span className="eyebrow">Hub-height extrapolation result</span>
            <div className="metric-grid">
              <MetricCard label="Column" value={latestExtrapolation.column_name} />
              <MetricCard label="Extrapolated" value={String(latestExtrapolation.method_counts.extrapolated)} />
              <MetricCard label="Interpolated" value={String(latestExtrapolation.method_counts.interpolated)} />
              <MetricCard label="Direct" value={String(latestExtrapolation.method_counts.direct)} />
            </div>
            <PlotlyFigure plot={extrapolationPlotQuery.data} emptyTitle="Loading" emptyDetail="" />
          </article>
        ) : (
          <EmptyState
            title="Hub-height comparison unavailable"
            detail="Run hub-height extrapolation to compare the extrapolated series against the measured heights."
          />
        )}
      </div>
    </section>
  );
}