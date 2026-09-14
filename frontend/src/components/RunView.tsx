// Run phase (design doc: Run) — the Sweep Designer and the Run Monitor on one screen.
// They were separate sub-tabs of the old Analysis Engine, but the leaf counter is the
// whole decision and the progress bar is the same object a minute later. Composes
// SweepDesigner and SweepMonitor unchanged; only the entry point is new.
import { useEffect } from "react";

import { SweepDesigner } from "./sweep/SweepDesigner";
import { SweepMonitor } from "./sweep/SweepMonitor";
import { useSweepStore } from "../store/useSweepStore";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

export function RunView() {
  const apiBaseUrl = useWorkspaceStore((state) => state.apiBaseUrl);
  const session = useWorkspaceStore((state) => state.session);
  const phase = useSweepStore((state) => state.phase);
  const refreshSweeps = useSweepStore((state) => state.refreshSweeps);
  const openSweep = useSweepStore((state) => state.openSweep);
  const sessionId = session?.session_id ?? "";

  // Restore a saved sweep on first entry, same as the old Analysis Engine did, so an
  // analyst who already ran a sweep finds its monitor state waiting rather than idle.
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

  return (
    <div className="run-view">
      <SweepDesigner />
      {phase !== "idle" ? <SweepMonitor /> : null}
    </div>
  );
}
