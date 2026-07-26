// Stage 4 — Vertical extrapolation: measured → hub (spec §4 / Stage 4).
//
// Power-law (shear α) or log-law (roughness z₀). Pick ≥2 height sensors,
// compute the timeseries + 12×24 lookup table, then extrapolate to hub height.
// The extrapolate call also extrapolates all reanalysis nodes (Stage 5 by-product).
import { useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { SensorPicker } from "../common/SensorPicker";
import { RunButton } from "../common/RunButton";

type ShearMethod = "power_law" | "log_law";

export function ShearExtrapolationView() {
  const sensors = useWorkspaceStore((state) => state.sensors);
  const config = useWorkspaceStore((state) => state.config);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const invokeSessionOperation = useWorkspaceStore((state) => state.invokeSessionOperation);
  const summary = useWorkspaceStore((state) => state.summary);

  const [method, setMethod] = useState<ShearMethod>(config.shear.method === "log_law" ? "log_law" : "power_law");
  const [sensorPair, setSensorPair] = useState<string[]>(config.shear.speedSensorPair);
  const [aggregation, setAggregation] = useState(config.shear.aggregation);
  const [hubHeight, setHubHeight] = useState(config.site.hubHeightM);
  const [extrapolateResult, setExtrapolateResult] = useState<Record<string, unknown> | null>(null);

  const speedSensors = useMemo(() => sensors.filter((s) => s.sensor_type === "wind_speed"), [sensors]);

  const calculate = async () => {
    if (sensorPair.length < 2) return;
    updateConfigValue("shear.method", method);
    updateConfigValue("shear.speedSensorPair", sensorPair);
    updateConfigValue("shear.aggregation", aggregation);
    const heightSensors = JSON.stringify(sensorPair);
    if (method === "power_law") {
      await invokeSessionOperation("Shear timeseries", "POST", "/shear/calculate", {
        height_sensors: heightSensors,
      });
      await invokeSessionOperation("Shear table", "POST", "/shear/table", { aggregation });
    } else {
      await invokeSessionOperation("Roughness timeseries", "POST", "/roughness/calculate", {
        height_sensors: heightSensors,
      });
      await invokeSessionOperation("Roughness table", "POST", "/roughness/table", { aggregation });
    }
  };

  const extrapolate = async () => {
    updateConfigValue("site.hubHeightM", hubHeight);
    const result = await invokeSessionOperation<Record<string, unknown>>(
      "Extrapolate to hub",
      "POST",
      "/extrapolation/hub",
      { hub_height_m: hubHeight, shear_model: method },
    );
    setExtrapolateResult(result);
  };

  const methodCounts = (extrapolateResult?.method_counts ?? null) as
    | { direct?: number; interpolated?: number; extrapolated?: number }
    | null;
  const extrapolatedShare =
    methodCounts && (methodCounts.extrapolated ?? 0) > 0
      ? ((methodCounts.extrapolated ?? 0) /
          ((methodCounts.direct ?? 0) + (methodCounts.interpolated ?? 0) + (methodCounts.extrapolated ?? 0))) *
        100
      : 0;

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Method & sensors</h3>
        <div className="form-grid">
          <label className="form-field">
            <span>Method</span>
            <select value={method} onChange={(e) => setMethod(e.target.value as ShearMethod)}>
              <option value="power_law">Power law (shear α)</option>
              <option value="log_law">Log law (roughness z₀)</option>
            </select>
          </label>
          <label className="form-field">
            <span>Aggregation</span>
            <select value={aggregation} onChange={(e) => setAggregation(e.target.value as typeof aggregation)}>
              <option value="mean">Mean</option>
              <option value="median">Median</option>
              <option value="momm">MoMM</option>
            </select>
          </label>
          <label className="form-field">
            <span>Hub height (m)</span>
            <input
              type="number"
              step="0.1"
              value={hubHeight}
              onChange={(e) => setHubHeight(Number(e.target.value))}
            />
          </label>
        </div>
        <div className="form-field">
          <span>Height sensors (≥2)</span>
          <SensorPicker
            sensors={speedSensors}
            kind="speed"
            multiple
            value={sensorPair}
            onChange={(v) => setSensorPair(v as string[])}
          />
        </div>
        <div className="path-actions">
          <RunButton
            label={`Compute ${method === "power_law" ? "shear" : "roughness"} + table`}
            onClick={calculate}
            disabled={sensorPair.length < 2}
          />
        </div>
        {method === "power_law" ? (
          <p className="muted">{summary?.shear_table_ready ? "✓ Shear table ready" : "Shear table not built."}</p>
        ) : (
          <p className="muted">
            {summary?.roughness_table_ready ? "✓ Roughness table ready" : "Roughness table not built."}
          </p>
        )}
      </section>

      <section className="plot-grid">
        <div className="plot-cell">
          <h4>{method === "power_law" ? "Shear table" : "Roughness table"}</h4>
          <PlotFrame
            plotName="shear_table"
            params={{ table_type: method === "power_law" ? "shear" : "roughness" }}
            height={340}
          />
        </div>
        <div className="plot-cell">
          <h4>Shear profile</h4>
          <PlotFrame plotName="shear_profile" params={{}} height={340} />
        </div>
      </section>

      <section className="path-panel">
        <h3>Extrapolate to hub height</h3>
        <p className="muted">
          Produces Spd_{hubHeight}m_hub on the measured timeseries and extrapolates all reanalysis nodes
          (Stage 5 by-product).
        </p>
        <RunButton label="Extrapolate to hub" onClick={extrapolate} />
        {methodCounts ? (
          <div className="method-counts">
            <dl className="metrics-grid">
              <MethodTile label="Direct" value={methodCounts.direct ?? 0} />
              <MethodTile label="Interpolated" value={methodCounts.interpolated ?? 0} />
              <MethodTile label="Extrapolated" value={methodCounts.extrapolated ?? 0} />
            </dl>
            {extrapolatedShare > 50 ? (
              <p className="status-warn">
                ⚠ {extrapolatedShare.toFixed(0)}% extrapolated — flag for bankable EYAs.
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function MethodTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric-tile">
      <dt>{label}</dt>
      <dd>{value.toLocaleString()}</dd>
    </div>
  );
}
