// Analysis Engine — the shell for the five sweep views (design doc §9).
//
// Sub-tabs rather than one long page: designing a sweep, watching it and interrogating
// its results are three different activities, and a user is only ever doing one.
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";

import { SweepDesigner } from "./SweepDesigner";
import { SweepMonitor } from "./SweepMonitor";
import { SpreadExplorer } from "./SpreadExplorer";
import { SensitivityView } from "./SensitivityView";
import { GateReportView } from "./GateReportView";
import { SpreadSummaryView } from "./SpreadSummaryView";
import { useSweepStore } from "../../store/useSweepStore";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";

type SweepTab = "design" | "monitor" | "explore" | "gates" | "sensitivity" | "summary";

const TABS: Array<{ id: SweepTab; label: string }> = [
  { id: "design", label: "Design" },
  { id: "monitor", label: "Run" },
  { id: "explore", label: "Spread" },
  { id: "gates", label: "Gates" },
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

  // Results live in the session on disk, not in this store, so a page reload leaves the
  // table empty while a finished sweep sits in `data/sessions/<id>/sweeps/`. Restore the
  // newest one on mount: an analyst who has already run a sweep should find its spread
  // waiting, not an empty state and a picker they have to know to use.
  useEffect(() => {
    if (!sessionId) return;
    void (async () => {
      await refreshSweeps(apiBaseUrl, sessionId);
      const current = useSweepStore.getState();
      if (current.phase !== "idle" || current.rows.length > 0) return;
      const newest = current.sweeps[0];
      if (newest) await openSweep(apiBaseUrl, sessionId, newest.sweep_id);
    })();
  }, [apiBaseUrl, openSweep, refreshSweeps, sessionId]);

  // Follow the run: launching moves to the monitor, finishing moves to the spread.
  // Keyed on the *transition* out of "running", so restoring a saved sweep loads its
  // rows without yanking someone off the Design tab they deliberately opened.
  const previousPhase = useRef(phase);
  useEffect(() => {
    const was = previousPhase.current;
    previousPhase.current = phase;
    if (phase === "running") {
      setTab("monitor");
      return;
    }
    if (was !== "running" || phase !== "complete" || rows.length === 0) return;
    // An empty spread is not worth landing on. When every scenario was excluded, the
    // gate report is the screen that actually answers why.
    const anyAdmissible = rows.some((row) => row.status === "ok" && row.admissible);
    setTab(anyAdmissible ? "explore" : "gates");
  }, [phase, rows]);

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
        {tab === "gates" ? <GateReportView /> : null}
        {tab === "sensitivity" ? <SensitivityView /> : null}
        {tab === "summary" ? <SpreadSummaryView /> : null}
      </div>
    </div>
  );
}
