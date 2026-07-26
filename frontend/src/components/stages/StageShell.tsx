// Shared layout each stage view uses (spec §3.1 / §10 Phase C).
//
// Renders the Stepper + the selected stage header + a stage body slot + the
// Assets drawer + activity log. The stage body is rendered by the consuming
// stage view; for now a placeholder is shown until Phase D–E stage views land.
import { useState } from "react";

import { Stepper } from "../Stepper";
import { StageHeader } from "../common/StageHeader";
import { AssetsDrawer } from "../AssetsDrawer";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { STAGE_META, STAGE_ORDER } from "../../lib/stages";
import { DataLoadView } from "./DataLoadView";
import { ReanalysisView } from "./ReanalysisView";
import { ExploreView } from "./ExploreView";
import { ShearExtrapolationView } from "./ShearExtrapolationView";
import { ReanalysisExtrapolationView } from "./ReanalysisExtrapolationView";
import { LtcView } from "./LtcView";
import { ClippingView } from "./ClippingView";
import { EnsembleView } from "./EnsembleView";
import type { StageId } from "../../types/analysis";

interface StageShellProps {
  /** Optional override body; defaults to the Phase-C placeholder. */
  children?: React.ReactNode;
}

export function StageShell({ children }: StageShellProps) {
  const selectedStage = useWorkspaceStore((state) => state.selectedStage);
  const stageStatuses = useWorkspaceStore((state) => state.stageStatuses);
  const summary = useWorkspaceStore((state) => state.summary);
  const [assetsOpen, setAssetsOpen] = useState(true);

  const status = stageStatuses[selectedStage];
  const index = STAGE_ORDER.indexOf(selectedStage) + 1;
  const completedSteps = summary?.completed_steps ?? [];

  return (
    <>
      <Stepper />

      <section className="workspace-body">
        <div className="stage-pane">
          <StageHeader stage={selectedStage} status={status} index={index} />

          <div className="stage-body">
            {children ?? <StageBody stage={selectedStage} completedSteps={completedSteps} />}
          </div>
        </div>

        <AssetsDrawer open={assetsOpen} onToggle={() => setAssetsOpen((v) => !v)} />

        <ActivityLog />
      </section>
    </>
  );
}

function StageBody({
  stage,
  completedSteps,
}: {
  stage: StageId;
  completedSteps: string[];
}) {
  // All 8 stages now render their real view (Phases D + E complete).
  switch (stage) {
    case "data":
      return <DataLoadView />;
    case "reanalysis":
      return <ReanalysisView />;
    case "explore":
      return <ExploreView />;
    case "shear":
      return <ShearExtrapolationView />;
    case "reanalysis_extrapolation":
      return <ReanalysisExtrapolationView />;
    case "ltc":
      return <LtcView />;
    case "clipping":
      return <ClippingView />;
    case "ensemble":
      return <EnsembleView />;
    default:
      return <StagePlaceholder stage={stage} completedSteps={completedSteps} />;
  }
}

function StagePlaceholder({
  stage,
  completedSteps,
}: {
  stage: keyof typeof STAGE_META;
  completedSteps: string[];
}) {
  const meta = STAGE_META[stage];
  return (
    <div className="stage-placeholder">
      <h3>{meta.title}</h3>
      <p className="muted">
        This stage's view ships in Phase E (LTC, clipping, ensemble). The header, store, and stage-status
        logic are live.
      </p>
      <ul className="completed-steps-list" aria-label="Completed backend steps">
        {completedSteps.length === 0 ? (
          <li className="muted">No steps completed yet.</li>
        ) : (
          completedSteps.map((step) => <li key={step}>{step}</li>)
        )}
      </ul>
    </div>
  );
}

function ActivityLog() {
  const activity = useWorkspaceStore((state) => state.activity);
  return (
    <aside className="activity-log" aria-label="Activity log">
      <h3>Activity</h3>
      {activity.length === 0 ? (
        <p className="muted">No activity yet.</p>
      ) : (
        <ul>
          {activity.map((entry) => (
            <li key={entry.id} className={`activity-entry activity-${entry.status}`}>
              <div className="activity-row">
                <strong>{entry.label}</strong>
                <time>{new Date(entry.timestamp).toLocaleTimeString()}</time>
              </div>
              <span className="activity-detail">{entry.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
