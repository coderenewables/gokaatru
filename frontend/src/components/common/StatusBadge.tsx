import clsx from "clsx";

type StatusBadgeProps = {
  tone?: "ok" | "warn" | "idle";
  text: string;
};

export function StatusBadge({ tone = "idle", text }: StatusBadgeProps) {
  return <span className={clsx("status-badge", `status-${tone}`)}>{text}</span>;
}