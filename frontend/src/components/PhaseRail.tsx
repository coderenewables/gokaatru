// Primary navigation: Prepare / Run / Interrogate / Canvas / Copilot (design doc:
// "Ten tabs became three phases"). Canvas and Copilot stay independent rail entries;
// Compare is retired from the top level — its capability lives inside Canvas now.
import clsx from "clsx";

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { PhaseId } from "../store/useWorkspaceStore";

const PHASES: Array<{ id: PhaseId; label: string; sub: string }> = [
  { id: "prepare", label: "Prepare", sub: "import · cleaning · reanalysis" },
  { id: "run", label: "Run", sub: "axes · cost · monitor" },
  { id: "interrogate", label: "Interrogate", sub: "spread · gates · export" },
  { id: "canvas", label: "Canvas", sub: "editable DAG" },
  { id: "copilot", label: "Copilot", sub: "ask the workspace" },
];

export function PhaseRail() {
  const activePhase = useWorkspaceStore((state) => state.activePhase);
  const setActivePhase = useWorkspaceStore((state) => state.setActivePhase);

  return (
    <nav className="phase-rail" aria-label="Primary view">
      {PHASES.map((phase) => (
        <button
          key={phase.id}
          type="button"
          className={clsx("phase-rail-item", { active: activePhase === phase.id })}
          aria-current={activePhase === phase.id ? "page" : undefined}
          onClick={() => setActivePhase(phase.id)}
        >
          <span className="phase-rail-label">{phase.label}</span>
          <span className="phase-rail-sub">{phase.sub}</span>
        </button>
      ))}
    </nav>
  );
}
