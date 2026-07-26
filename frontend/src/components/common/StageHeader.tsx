// Stage header (spec §2.6): title, description, status badge.
import type { StageId, StageStatus } from "../../types/analysis";
import { STAGE_META } from "../../lib/stages";

interface StageHeaderProps {
  stage: StageId;
  status: StageStatus;
  /** Optional index (1-based) for the stepper badge. */
  index?: number;
  actions?: React.ReactNode;
}

const STATUS_LABELS: Record<StageStatus, string> = {
  locked: "Locked",
  available: "Ready",
  in_progress: "Running",
  done: "Done",
  error: "Error",
};

export function StageHeader({ stage, status, index, actions }: StageHeaderProps) {
  const meta = STAGE_META[stage];
  const locked = status === "locked";
  return (
    <header className={`stage-header stage-header-${status}`}>
      <div className="stage-header-titles">
        <h2>
          {index !== undefined ? <span className="stage-index">{index}</span> : null}
          {meta.title}
        </h2>
        <p className="stage-description">{meta.description}</p>
      </div>
      <div className="stage-header-meta">
        <span className={`status-pill status-${status}`}>{STATUS_LABELS[status]}</span>
        {actions ? <div className="stage-header-actions">{actions}</div> : null}
      </div>
      {locked ? (
        <p className="stage-locked-hint muted">
          Complete an upstream stage first to unlock this one.
        </p>
      ) : null}
    </header>
  );
}
