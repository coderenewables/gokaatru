// Primary navigation: Data import / Canvas / Stepper / Analysis Engine / Results /
// Copilot / Sensor Overview / Compare / How To.
import clsx from "clsx";

import { useWorkspaceStore } from "../store/useWorkspaceStore";

type TabId =
  | "import"
  | "setup"
  | "workflow"
  | "engine"
  | "results"
  | "copilot"
  | "compare"
  | "howto"
  | "sensor_review";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "import", label: "Data import" },
  { id: "workflow", label: "Canvas" },
  { id: "setup", label: "Stepper" },
  { id: "engine", label: "Analysis Engine" },
  { id: "results", label: "Results" },
  { id: "copilot", label: "Copilot" },
  { id: "sensor_review", label: "Sensor Overview" },
  { id: "compare", label: "Compare" },
  { id: "howto", label: "How To" },
];

export function PhaseTabs() {
  const activeTab = useWorkspaceStore((state) => state.activeTab);
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab);

  return (
    <nav className="phase-tabs" aria-label="Primary view">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={clsx("phase-tab", { active: activeTab === tab.id })}
          aria-current={activeTab === tab.id ? "page" : undefined}
          onClick={() => setActiveTab(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}

export type { TabId };
