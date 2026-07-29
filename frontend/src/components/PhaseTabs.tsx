// Primary navigation (spec §3.1): Stepper / Canvas / WindKit / Copilot / Compare.
import clsx from "clsx";

import { useWorkspaceStore } from "../store/useWorkspaceStore";

type TabId = "setup" | "workflow" | "windkit" | "copilot" | "compare" | "howto" | "sensor_review";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "setup", label: "Stepper" },
  { id: "workflow", label: "Canvas" },
  { id: "windkit", label: "WindKit" },
  { id: "copilot", label: "Copilot" },
  { id: "compare", label: "Compare" },
  { id: "sensor_review", label: "Sensor Overview" },
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
