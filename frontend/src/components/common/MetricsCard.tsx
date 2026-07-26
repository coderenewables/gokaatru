// Metrics card (spec §2.6): render a metrics dict as labeled stat tiles.
//
// Used for LTC metrics (r_squared, rmse, mae, slope, ...) and uncertainty
// components. Values are formatted based on key name heuristics.
import type { LtcMetrics } from "../../types/analysis";

interface MetricsCardProps {
  title?: string;
  metrics: LtcMetrics | Record<string, unknown>;
  /** Highlight these keys (e.g. the headline metric for an algorithm). */
  highlight?: string[];
}

// Keys to skip (algorithm is shown in the title; internal bookkeeping elided).
const SKIP_KEYS = new Set(["algorithm", "concurrent_points", "total_corrected_points"]);

function formatValue(key: string, value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return value == null ? "—" : String(value);
  }
  const lower = key.toLowerCase();
  if (lower === "r_squared") return value.toFixed(3);
  if (lower === "bias" || lower === "mbe") return value.toFixed(3);
  if (lower === "slope" || lower === "dog_leg_slope" || lower === "variance_ratio") {
    return value.toFixed(3);
  }
  if (lower === "threshold" || lower.includes("uncertainty") || lower.includes("error")) {
    return value.toFixed(3);
  }
  if (lower === "count" || lower.includes("points") || lower === "best_iteration") {
    return String(Math.round(value));
  }
  return value.toFixed(3);
}

function prettyLabel(key: string): string {
  const map: Record<string, string> = {
    r_squared: "R²",
    rmse: "RMSE",
    mae: "MAE",
    mbe: "MBE",
    slope: "Slope",
    intercept: "Intercept",
    threshold: "Threshold",
    dog_leg_slope: "Dog-leg slope",
    variance_ratio: "Variance ratio",
    correlation: "Correlation",
    concurrent_points: "Concurrent pts",
    total_corrected_points: "Corrected pts",
    feature_importance: "Feature importance",
    train_error: "Train error",
    val_error: "Val. error",
    best_iteration: "Best iter",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

export function MetricsCard({ title, metrics, highlight = [] }: MetricsCardProps) {
  const source = (metrics as Record<string, unknown>) ?? {};
  const entries = Object.entries(source).filter(([key, value]) => {
    if (SKIP_KEYS.has(key)) return false;
    if (value != null && typeof value === "object") return false; // nested (e.g. feature_importance)
    return true;
  });

  return (
    <div className="metrics-card">
      {title ? <h4 className="metrics-title">{title}</h4> : null}
      {entries.length === 0 ? (
        <p className="muted">No metrics.</p>
      ) : (
        <dl className="metrics-grid">
          {entries.map(([key, value]) => (
            <div
              key={key}
              className={`metric-tile ${highlight.includes(key) ? "metric-highlight" : ""}`}
            >
              <dt>{prettyLabel(key)}</dt>
              <dd>{formatValue(key, value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
