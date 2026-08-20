// Analysis Engine — the shell for the five sweep views (design doc §9).
//
// Sub-tabs rather than one long page: designing a sweep, watching it and interrogating
// its results are three different activities, and a user is only ever doing one.
import { useEffect, useState } from "react";
import clsx from "clsx";

import { SweepDesigner } from "./SweepDesigner";
import { SweepMonitor } from "./SweepMonitor";
import { SpreadExplorer } from "./SpreadExplorer";
import { SensitivityView } from "./SensitivityView";
import { SpreadSummaryView } from "./SpreadSummaryView";
import { useSweepStore } from "../../store/useSweepStore";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";

type SweepTab = "design" | "monitor" | "explore" | "sensitivity" | "summary";

const TABS: Array<{ id: SweepTab; label: string }> = [
  { id: "design", label: "Design" },
  { id: "monitor", label: "Run" },
  { id: "explore", label: "Spread" },
  { id: "sensitivity", label: "Sensitivity" },
  { id: "summary", label: "Summary & export" },
];

export function AnalysisEngineView() {
  const apiBaseUrl = useWorkspaceStore((state) => state.apiBaseUrl);
  const session = useWorkspaceStore((state) => state.session);

  const phase = useSweepStore((state) => state.phase);
  const rows = useSweepStore((state) => state.rows);
  const sweeps = useSweepStore((state) => state.sweeps);
  const manifest = useSweepStore((state) => state.manifest);
  const refreshSweeps = useSweepStore((state) => state.refreshSweeps);
  const openSweep = useSweepStore((state) => state.openSweep);

  const [tab, setTab] = useState<SweepTab>("design");
  const sessionId = session?.session_id ?? "";

  useEffect(() => {
    if (sessionId) void refreshSweeps(apiBaseUrl, sessionId);
  }, [apiBaseUrl, refreshSweeps, sessionId]);

  // Follow the run: launching moves to the monitor, finishing moves to the spread.
  useEffect(() => {
    if (phase === "running") setTab("monitor");
  }, [phase]);
  useEffect(() => {
    if (phase === "complete" && rows.length > 0) setTab("explore");
  }, [phase, rows.length]);

  return (
    <div className="analysis-engine-view">
      <header className="analysis-engine-header">
        <nav className="sweep-tabs" aria-label="Analysis engine views">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={clsx("sweep-tab", { active: tab === entry.id })}
              aria-current={tab === entry.id ? "page" : undefined}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </nav>
        {sweeps.length > 0 ? (
          <label className="sweep-picker">
            Saved sweeps
            <select
              value={manifest?.sweep_id ?? ""}
              onChange={(event) => {
                if (event.target.value) void openSweep(apiBaseUrl, sessionId, event.target.value);
              }}
            >
              <option value="">Select…</option>
              {sweeps.map((entry) => (
                <option key={entry.sweep_id} value={entry.sweep_id}>
                  {entry.sweep_id} · {entry.counts.admissible}/{entry.counts.completed} admissible
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </header>

      <div className="analysis-engine-body">
        {tab === "design" ? <SweepDesigner /> : null}
        {tab === "monitor" ? <SweepMonitor /> : null}
        {tab === "explore" ? <SpreadExplorer /> : null}
        {tab === "sensitivity" ? <SensitivityView /> : null}
        {tab === "summary" ? <SpreadSummaryView /> : null}
      </div>
    </div>
  );
}
