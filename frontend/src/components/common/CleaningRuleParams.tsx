import type { JsonValue, SensorRecord } from "../../lib/types";

type CleaningRuleParamsProps = {
  ruleType: string;
  params: Record<string, JsonValue>;
  onParamsChange: (params: Record<string, JsonValue>) => void;
  sensors: SensorRecord[];
};

function numberValue(value: JsonValue | undefined, fallback: number) {
  return typeof value === "number" ? value : fallback;
}

export function CleaningRuleParams({ ruleType, params, onParamsChange, sensors }: CleaningRuleParamsProps) {
  const updateParam = (key: string, value: JsonValue) => onParamsChange({ ...params, [key]: value });
  const updateShadow = (index: number, value: number) => {
    const base = Array.isArray(params.exclude_sectors) ? [...params.exclude_sectors] : [170, 190];
    base[index] = value;
    onParamsChange({ ...params, exclude_sectors: base });
  };
  void sensors;

  switch (ruleType) {
    case "range_check":
      return (
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Minimum (m/s)</span>
            <input
              type="number"
              step="0.1"
              value={numberValue(params.min, 0)}
              onChange={(event) => updateParam("min", Number(event.target.value))}
            />
          </label>
          <label className="form-field">
            <span>Maximum (m/s)</span>
            <input
              type="number"
              step="0.1"
              value={numberValue(params.max, 50)}
              onChange={(event) => updateParam("max", Number(event.target.value))}
            />
          </label>
        </div>
      );
    case "icing_filter":
      return (
        <label className="form-field">
          <span>Temperature threshold (°C)</span>
          <input
            type="number"
            step="0.5"
            value={numberValue(params.temp_threshold_c, 2)}
            onChange={(event) => updateParam("temp_threshold_c", Number(event.target.value))}
          />
          <small className="field-help">
            Records with SD=0 and temperature below this threshold will be flagged as icing.
          </small>
        </label>
      );
    case "stuck_sensor":
      return (
        <label className="form-field">
          <span>Consecutive identical readings</span>
          <input
            type="number"
            min="2"
            step="1"
            value={numberValue(params.consecutive_count, 6)}
            onChange={(event) => updateParam("consecutive_count", Number(event.target.value))}
          />
        </label>
      );
    case "tower_shadow":
      return (
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Exclude from (°)</span>
            <input
              type="number"
              min="0"
              max="360"
              value={numberValue(Array.isArray(params.exclude_sectors) ? params.exclude_sectors[0] : undefined, 170)}
              onChange={(event) => updateShadow(0, Number(event.target.value))}
            />
          </label>
          <label className="form-field">
            <span>Exclude to (°)</span>
            <input
              type="number"
              min="0"
              max="360"
              value={numberValue(Array.isArray(params.exclude_sectors) ? params.exclude_sectors[1] : undefined, 190)}
              onChange={(event) => updateShadow(1, Number(event.target.value))}
            />
          </label>
          <small className="field-help full-width">
            Wind direction sector to exclude due to mast wake and tower shadow effects.
          </small>
        </div>
      );
    case "spike_filter":
      return (
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Window size (records)</span>
            <input
              type="number"
              min="2"
              value={numberValue(params.window_size, 6)}
              onChange={(event) => updateParam("window_size", Number(event.target.value))}
            />
          </label>
          <label className="form-field">
            <span>Sigma threshold</span>
            <input
              type="number"
              step="0.5"
              value={numberValue(params.sigma_threshold, 4)}
              onChange={(event) => updateParam("sigma_threshold", Number(event.target.value))}
            />
          </label>
        </div>
      );
    case "timestamp_gap_fill":
      return <p className="muted-text">No parameters required. Missing timestamps will be filled with NaN rows.</p>;
    case "custom_period_exclude":
      return <p className="muted-text">Use the Start date and End date fields above to define the exclusion period.</p>;
    default:
      return null;
  }
}