// App shell (spec §3.1). Thin root that gates on session existence and switches
// between the five primary views. All phases (A–G) now ship real views.
import { Suspense, useEffect } from "react";

import { AppHeader } from "./components/AppHeader";
import { PhaseTabs } from "./components/PhaseTabs";
import { HomeView } from "./components/HomeView";
import { StageShell } from "./components/stages/StageShell";
import { WorkflowView } from "./components/WorkflowView";
import { CopilotView } from "./components/CopilotView";
import { CompareView } from "./components/CompareView";
import { WindKitExplorerView } from "./components/WindKitExplorerView";
import { useWorkspaceStore } from "./store/useWorkspaceStore";

function ViewFallback() {
  return <div className="view-fallback muted">Loading view…</div>;
}

export default function App() {
  const session = useWorkspaceStore((state) => state.session);
  const sessionStatus = useWorkspaceStore((state) => state.sessionStatus);
  const activeTab = useWorkspaceStore((state) => state.activeTab);
  const restoreSession = useWorkspaceStore((state) => state.restoreSession);

  useEffect(() => {
    if (session === null && sessionStatus === "idle") {
      void restoreSession();
    }
  }, [restoreSession, session, sessionStatus]);

  if (session === null) {
    return <HomeView />;
  }

  return (
    <main className="app-shell">
      <AppHeader />
      <PhaseTabs />
      <Suspense fallback={<ViewFallback />}>
        {activeTab === "setup" ? <StageShell /> : null}
        {activeTab === "workflow" ? <WorkflowView /> : null}
        {activeTab === "windkit" ? <WindKitExplorerView /> : null}
        {activeTab === "copilot" ? <CopilotView /> : null}
        {activeTab === "compare" ? <CompareView /> : null}
      </Suspense>
    </main>
  );
}
