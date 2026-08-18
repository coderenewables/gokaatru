// Stage 2 — Data cleaning (spec §4 / Stage 2 insert).
//
// Two areas:
//  1. "Review sensors" — a browser tab with per-sensor stats (max/min/mean/Weibull),
//     wind roses per height, a combined diurnal profile of all speed sensors,
//     the temperature diurnal profile, and the measured shear profile.
//  2. "Cleaning rules" — standard wind filters (range, icing, stuck sensor,
//     tower shadow) plus a custom Windographer-style expression builder
//     supporting AND/OR combinations, applied as flag-and-remove (→ NA) rules.
import { useEffect, useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
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
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab);

  const [log, setLog] = useState<CleaningLogEntry[]>([]);

  // standard-filter state
  const [stdSensor, setStdSensor] = useState("");

  // expression builder state
  const [targetSensor, setTargetSensor] = useState("");
  const [combinator, setCombinator] = useState<"and" | "or">("and");
  const [conditions, setConditions] = useState<Condition[]>([{ column: "", op: "<", value: "" }]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

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
        <RunButton label="Open sensor review" onClick={() => setActiveTab("sensor_review")} />
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

    </div>
  );
}
