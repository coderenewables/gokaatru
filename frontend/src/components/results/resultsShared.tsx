// Shared presentational primitives for the Results view.
//
// Mirrors the local MetricTile / UnavailableSection helpers from
// SensorReviewView.tsx, extracted so each Results section can reuse them
// without duplication. Read-only: these render already-computed state only.

export function MetricTile({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className={`metric-tile ${highlight ? "metric-highlight" : ""}`}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function UnavailableSection({
  title,
  requirement,
}: {
  title: string;
  requirement: string;
}) {
  return (
    <section className="path-panel sensor-overview-unavailable">
      <h3>{title}</h3>
      <p className="muted">Not available for this session yet. {requirement}</p>
    </section>
  );
}
