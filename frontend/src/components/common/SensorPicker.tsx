// Sensor picker (spec §2.6): single- or multi-select over the loaded sensors.
import clsx from "clsx";

import type { SensorRow, SensorType } from "../../types/analysis";

type FilterKind = "speed" | "direction" | "temperature" | "pressure" | "all";

interface SensorPickerProps {
  sensors: SensorRow[];
  /** Which sensor_type to list. */
  kind?: FilterKind;
  /** Selected sensor name(s). */
  value: string | string[];
  /** Single (default) or multi select. */
  multiple?: boolean;
  onChange: (value: string | string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
}

function filterSensors(sensors: SensorRow[], kind: FilterKind): SensorRow[] {
  if (kind === "all") return sensors;
  const map: Record<Exclude<FilterKind, "all">, SensorType> = {
    speed: "wind_speed",
    direction: "wind_direction",
    temperature: "temperature",
    pressure: "pressure",
  };
  return sensors.filter((s) => s.sensor_type === map[kind]);
}

export function SensorPicker({
  sensors,
  kind = "speed",
  value,
  multiple = false,
  onChange,
  placeholder = "Select sensor…",
  disabled = false,
  id,
}: SensorPickerProps) {
  const options = filterSensors(sensors, kind).sort((a, b) => b.height_m - a.height_m);

  if (multiple) {
    const selected = Array.isArray(value) ? value : value ? [value] : [];
    const toggle = (name: string) => {
      const next = selected.includes(name)
        ? selected.filter((v) => v !== name)
        : [...selected, name];
      onChange(next);
    };
    return (
      <div className="sensor-picker sensor-picker-multi" id={id}>
        {options.length === 0 ? (
          <p className="muted">No {kind} sensors loaded.</p>
        ) : (
          options.map((s) => (
            <label key={s.name} className={clsx("sensor-chip", { selected: selected.includes(s.name) })}>
              <input
                type="checkbox"
                checked={selected.includes(s.name)}
                onChange={() => toggle(s.name)}
                disabled={disabled}
              />
              <span className="sensor-chip-name">{s.name}</span>
              <span className="sensor-chip-height">{s.height_m}m</span>
            </label>
          ))
        )}
      </div>
    );
  }

  const single = Array.isArray(value) ? value[0] ?? "" : value;
  return (
    <select
      id={id}
      className="sensor-select"
      value={single}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      <option value="">{placeholder}</option>
      {options.map((s) => (
        <option key={s.name} value={s.name}>
          {s.name} ({s.height_m}m · {s.data_coverage_pct.toFixed(0)}%)
        </option>
      ))}
    </select>
  );
}
