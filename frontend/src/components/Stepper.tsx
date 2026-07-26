// The 8-stage Stepper (spec §3.1).
//
// Horizontal rail of stage chips colored by status. Clicking a stage that is
// not locked selects it (drives the StageShell). Locked stages show a tooltip
// naming the blocking upstream stage and are not clickable.
import clsx from "clsx";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { STAGE_META, STAGE_ORDER } from "../lib/stages";
import type { StageId, StageStatus } from "../types/analysis";

const STATUS_LABEL: Record<StageStatus, string> = {
  locked: "Locked",
  available: "Ready",
  in_progress: "Running",
  done: "Done",
  error: "Error",
};

function lockedReason(stage: StageId, statuses: Record<StageId, StageStatus>): string | null {
  const meta = STAGE_META[stage];
  for (const prereq of meta.prerequisiteStages) {
    if (statuses[prereq] !== "done") {
      return `Complete "${STAGE_META[prereq].title}" first`;
    }
  }
  return null;
}

export function Stepper() {
  const stageStatuses = useWorkspaceStore((state) => state.stageStatuses);
  const selectedStage = useWorkspaceStore((state) => state.selectedStage);
  const setSelectedStage = useWorkspaceStore((state) => state.setSelectedStage);

  return (
    <section className="stage-rail" aria-label="Workflow stages">
      {STAGE_ORDER.map((stageId, index) => {
        const meta = STAGE_META[stageId];
        const status = stageStatuses[stageId];
        const locked = status === "locked";
        const reason = locked ? lockedReason(stageId, stageStatuses) : null;
        const interactive = !locked;
        return (
          <button
            key={stageId}
            type="button"
            className={clsx("stage-chip", `stage-${status}`, { selected: selectedStage === stageId })}
            aria-label={meta.title}
            aria-disabled={locked}
            title={reason ?? meta.title}
            disabled={locked}
            onClick={interactive ? () => setSelectedStage(stageId) : undefined}
          >
            <span className="stage-chip-index">{index + 1}</span>
            <span className="stage-chip-title">{meta.title}</span>
            <span className={`stage-chip-status status-${status}`}>
              {STATUS_LABEL[status]}
            </span>
          </button>
        );
      })}
    </section>
  );
}
