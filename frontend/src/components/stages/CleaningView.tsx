// Stage 2 — Data cleaning (spec §4 / Stage 2 insert).
//
// Two areas:
//  1. "Review sensors" — a modal with per-sensor stats (max/min/mean/Weibull),
//     wind roses per height, a combined diurnal profile of all speed sensors,
//     the temperature diurnal profile, and the measured shear profile.
//  2. "Cleaning rules" — standard wind filters (range, icing, stuck sensor,
//     tower shadow, spike) plus a custom Windographer-style expression builder
//     supporting AND/OR combinations, applied as flag-and-remove (→ NA) rules.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { PlotFrame } from "../common/PlotFrame";
import { SensorPicker } from "../common/SensorPicker";
import { RunButton } from "../common/RunButton";
import type { CleaningLogEntry } from "../../lib/api";

// ---------------------------------------------------------------------------
// Standard wind filters (Windographer-style presets)
// ---------------------------------------------------------------------------

interface StandardFilter {
  id: string;
  label: string;
  description: string;
  ruleType: string;
  /** Params may reference the selected sensor via {sensor}. */
  buildParams: (sensor: string) => Record<string, unknown>;
}

const STANDARD_FILTERS: StandardFilter[] = [
  {
    id: "range",
    label: "Range check (0–50 m/s)",
    description: "Flag values below 0 or above 50 m/s.",
    ruleType: "range_check",
    buildParams: () => ({ min: 0, max: 50 }),
  },
  {
    id: "icing",
    label: "Icing filter",
    description: "Flag frozen-sensor readings (SD=0 & temp < 2 °C).",
    ruleType: "icing_filter",
    buildParams: () => ({ temp_threshold_c: 2 }),
  },
  {
    id: "stuck",
    label: "Stuck sensor",
    description: "Flag runs of 6+ identical consecutive readings.",
    ruleType: "stuck_sensor",
    buildParams: () => ({ consecutive_count: 6 }),
  },
  {
    id: "shadow",
    label: "Tower shadow (170–190°)",
    description: "Flag readings from the tower-shadow sector.",
    ruleType: "tower_shadow",
    buildParams: () => ({ exclude_sectors: [170, 190] }),
  },
  {
    id: "spike",
    label: "Spike filter",
    description: "Flag spikes beyond 4σ of the rolling mean.",
    ruleType: "spike_filter",
    buildParams: () => ({ window_size: 6, sigma_threshold: 4 }),
  },
];

const OPS = ["<", "<=", ">", ">=", "==", "!="] as const;

interface Condition {
  column: string;
  op: (typeof OPS)[number];
  value: string;
}

export function CleaningView() {
  const sensors = useWorkspaceStore((state) => state.sensors);
  const summary = useWorkspaceStore((state) => state.summary);
  const applyCleaning = useWorkspaceStore((state) => state.applyCleaning);
  const undoCleaning = useWorkspaceStore((state) => state.undoCleaning);
  const refreshCleaningLog = useWorkspaceStore((state) => state.refreshCleaningLog);

  const [statsOpen, setStatsOpen] = useState(false);
  const [log, setLog] = useState<CleaningLogEntry[]>([]);

  // standard-filter state
  const [stdSensor, setStdSensor] = useState("");

  // expression builder state
  const [targetSensor, setTargetSensor] = useState("");
  const [combinator, setCombinator] = useState<"and" | "or">("and");
  const [conditions, setConditions] = useState<Condition[]>([{ column: "", op: "<", value: "" }]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const speedSensors = useMemo(() => sensors.filter((s) => s.sensor_type === "wind_speed"), [sensors]);
  const tempSensors = useMemo(() => sensors.filter((s) => s.sensor_type === "temperature"), [sensors]);
  const allColumns = useMemo(() => sensors.map((s) => s.name).sort(), [sensors]);

  const loadLog = async () => setLog(await refreshCleaningLog());
  useEffect(() => {
    void loadLog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary?.cleaning_rules_applied]);

  const buildExpression = (): string => {
    const parts = conditions
      .filter((c) => c.column && c.value.trim() !== "")
      .map((c) => `${c.column} ${c.op} ${Number(c.value)}`);
    return parts.join(` ${combinator} `);
  };

  const runStandardFilter = async (filter: StandardFilter) => {
    if (!stdSensor) return;
    await applyCleaning({
      rule_type: filter.ruleType,
      sensor: stdSensor,
      params: filter.buildParams(stdSensor),
    });
    await loadLog();
  };

  const applyExpression = async () => {
    if (!targetSensor) return;
    const expression = buildExpression();
    if (!expression) return;
    await applyCleaning({
      rule_type: "expression_filter",
      sensor: targetSensor,
      params: { expression },
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    });
    await loadLog();
  };

  const updateCondition = (index: number, patch: Partial<Condition>) =>
    setConditions((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));

  const addCondition = () =>
    setConditions((prev) => [...prev, { column: "", op: "<", value: "" }]);

  const removeCondition = (index: number) =>
    setConditions((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));

  const expression = buildExpression();

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Review sensors</h3>
        <p className="muted">
          Inspect per-sensor statistics (max / min / mean / Weibull), wind roses per height, combined
          diurnal profiles, the temperature diurnal profile, and the measured shear profile.
        </p>
        <RunButton label="Open sensor review" onClick={() => setStatsOpen(true)} />
      </section>

      <section className="path-panel">
        <h3>Standard wind filters</h3>
        <div className="form-grid">
          <label className="form-field">
            <span>Sensor</span>
            <SensorPicker sensors={sensors} kind="speed" value={stdSensor} onChange={(v) => setStdSensor(v as string)} />
          </label>
        </div>
        <div className="standard-filters">
          {STANDARD_FILTERS.map((filter) => (
            <div key={filter.id} className="standard-filter">
              <div className="standard-filter-text">
                <strong>{filter.label}</strong>
                <span className="muted">{filter.description}</span>
              </div>
              <RunButton
                label="Run"
                variant="secondary"
                onClick={() => runStandardFilter(filter)}
                disabled={!stdSensor}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="path-panel">
        <h3>Custom filter (AND / OR)</h3>
        <p className="muted">
          Build a Windographer-style expression. Matching records on the target sensor are flagged and
          replaced with NA. Example: <code>Spd_170m &lt; 0 or Spd_170m &gt; 100</code>
        </p>
        <div className="form-grid">
          <label className="form-field">
            <span>Target sensor (cleaned)</span>
            <SensorPicker sensors={sensors} kind="all" value={targetSensor} onChange={(v) => setTargetSensor(v as string)} />
          </label>
          <label className="form-field">
            <span>Combine with</span>
            <select value={combinator} onChange={(e) => setCombinator(e.target.value as "and" | "or")}>
              <option value="and">AND (all must match)</option>
              <option value="or">OR (any may match)</option>
            </select>
          </label>
          <label className="form-field">
            <span>Start date (optional)</span>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label className="form-field">
            <span>End date (optional)</span>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
        </div>

        <div className="condition-list">
          {conditions.map((condition, index) => (
            <div key={index} className="condition-row">
              <select
                value={condition.column}
                onChange={(e) => updateCondition(index, { column: e.target.value })}
              >
                <option value="">Column…</option>
                {allColumns.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <select value={condition.op} onChange={(e) => updateCondition(index, { op: e.target.value as Condition["op"] })}>
                {OPS.map((op) => (
                  <option key={op} value={op}>
                    {op}
                  </option>
                ))}
              </select>
              <input
                type="number"
                step="any"
                placeholder="value"
                value={condition.value}
                onChange={(e) => updateCondition(index, { value: e.target.value })}
              />
              <button type="button" className="icon-button" onClick={() => removeCondition(index)} aria-label="Remove condition">
                ✕
              </button>
            </div>
          ))}
          <button type="button" className="link-button" onClick={addCondition}>
            + Add condition
          </button>
        </div>

        {expression ? (
          <p className="expression-preview">
            <code>{expression}</code>
          </p>
        ) : null}
        <div className="path-actions">
          <RunButton label="Apply filter" onClick={applyExpression} disabled={!targetSensor || !expression} />
        </div>
      </section>

      <section className="path-panel">
        <h3>Cleaning log ({log.length})</h3>
        {log.length === 0 ? (
          <p className="muted">No cleaning rules applied yet.</p>
        ) : (
          <ul className="cleaning-log">
            {log.map((entry, index) => (
              <li key={index} className="cleaning-log-entry">
                <div className="cleaning-log-text">
                  <strong>{entry.rule_type}</strong>
                  <span className="muted">
                    {entry.sensor} · {entry.records_affected} record(s)
                  </span>
                </div>
                <button type="button" className="link-button" onClick={() => void undoCleaning(index).then(loadLog)}>
                  Undo
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {statsOpen ? (
        <SensorStatsModal
          speedSensors={speedSensors.map((s) => s.name)}
          tempSensors={tempSensors.map((s) => s.name)}
          sensors={sensors}
          onClose={() => setStatsOpen(false)}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats modal
// ---------------------------------------------------------------------------

function SensorStatsModal({
  speedSensors,
  tempSensors,
  sensors,
  onClose,
}: {
  speedSensors: string[];
  tempSensors: string[];
  sensors: import("../../types/analysis").SensorRow[];
  onClose: () => void;
}) {
  const loadSensorStatistics = useWorkspaceStore((state) => state.loadSensorStatistics);
  const [stats, setStats] = useState<Record<string, import("../../types/analysis").SensorStatistics>>({});

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const out: Record<string, import("../../types/analysis").SensorStatistics> = {};
      for (const sensor of sensors) {
        try {
          out[sensor.name] = await loadSensorStatistics(sensor.name);
        } catch {
          /* skip sensors without stats */
        }
        if (cancelled) return;
      }
      if (!cancelled) setStats(out);
    };
    void run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sensors]);

  const allSpeed = speedSensors.join(", ");
  const allTemp = tempSensors.join(", ");
  const rows = sensors.filter((s) => stats[s.name]);

  // Pair each speed sensor with the direction sensor at the same height so the
  // wind rose (which needs both) can be plotted side by side with the Weibull.
  const dirByHeight = new Map<number, string>();
  for (const s of sensors) {
    if (s.sensor_type === "wind_direction" && !dirByHeight.has(s.height_m)) {
      dirByHeight.set(s.height_m, s.name);
    }
  }
  const heightRows = sensors
    .filter((s) => s.sensor_type === "wind_speed")
    .sort((a, b) => b.height_m - a.height_m)
    .map((s) => ({ speed: s.name, direction: dirByHeight.get(s.height_m) ?? "", height: s.height_m }));

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card sensor-stats-modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>Sensor review</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="modal-body">
          <section>
            <h3>Statistics (all sensors)</h3>
            <div className="stats-table-wrap">
              <table className="stats-table">
                <thead>
                  <tr>
                    <th>Sensor</th>
                    <th>Min</th>
                    <th>Mean</th>
                    <th>Max</th>
                    <th>Weibull k</th>
                    <th>Weibull A</th>
                    <th>Coverage %</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((sensor) => {
                    const s = stats[sensor.name];
                    return (
                      <tr key={sensor.name}>
                        <td>{sensor.name}</td>
                        <td>{fmt(s.min_value)}</td>
                        <td>{fmt(s.mean)}</td>
                        <td>{fmt(s.max_value)}</td>
                        <td>{fmt(s.weibull_k)}</td>
                        <td>{fmt(s.weibull_A)}</td>
                        <td>{fmt(s.coverage_pct)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {speedSensors.length > 0 ? (
            <section>
              <h3>Diurnal profile — all speed sensors</h3>
              <PlotFrame plotName="diurnal" params={{ sensor_names: allSpeed }} height={320} />
            </section>
          ) : null}

          {tempSensors.length > 0 ? (
            <section>
              <h3>Temperature diurnal profile</h3>
              <PlotFrame plotName="diurnal" params={{ sensor_names: allTemp }} height={320} />
            </section>
          ) : null}

          <section>
            <h3>Shear profile</h3>
            <PlotFrame plotName="shear_profile" params={{}} height={320} />
          </section>

          <section>
            <h3>Weibull &amp; wind rose per height</h3>
            {heightRows.map(({ speed, direction, height }) => (
              <div key={speed} className="height-pair">
                <h4 className="height-pair-title">{height}m — {speed}</h4>
                <div className="height-pair-plots">
                  <div className="height-pair-cell">
                    <PlotFrame plotName="weibull" params={{ sensor_name: speed }} height={300} />
                  </div>
                  <div className="height-pair-cell">
                    {direction ? (
                      <PlotFrame
                        plotName="windrose"
                        params={{ speed_sensor: speed, direction_sensor: direction }}
                        height={300}
                      />
                    ) : (
                      <p className="muted">No direction sensor at {height}m — wind rose unavailable.</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </section>
        </div>
      </div>
    </div>
  );
}

function fmt(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
}
