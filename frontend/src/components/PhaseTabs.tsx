import clsx from "clsx";

const tabs = [
  { id: "setup", label: "Setup" },
  { id: "workflow", label: "Workflow" },
  { id: "windkit", label: "WindKit" },
  { id: "copilot", label: "Copilot" },
  { id: "compare", label: "Compare" },
] as const;

interface PhaseTabsProps {
  activeTab: string;
  onChange: (tab: "setup" | "workflow" | "windkit" | "copilot" | "compare") => void;
}

export function PhaseTabs({ activeTab, onChange }: PhaseTabsProps) {
  return (
    <nav className="phase-tabs" aria-label="Workspace phases">
      {tabs.map((tab) => (
        <button
          className={clsx("phase-tab", activeTab === tab.id && "phase-tab-active")}
          key={tab.id}
          onClick={() => onChange(tab.id)}
          type="button"
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}