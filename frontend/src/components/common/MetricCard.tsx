type MetricCardProps = {
  label: string;
  value: string;
  detail?: string;
  tone?: "default" | "accent";
};

export function MetricCard({ label, value, detail, tone = "default" }: MetricCardProps) {
  return (
    <article className={tone === "accent" ? "metric-card metric-card-accent" : "metric-card"}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {detail ? <p className="metric-detail muted-text">{detail}</p> : null}
    </article>
  );
}