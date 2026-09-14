// App shell (spec §3.1). Thin root that gates on session existence and switches
// between the five primary views. All phases (A–G) now ship real views.
import { Suspense, useEffect } from "react";

import { AppHeader } from "./components/AppHeader";
import { PhaseRail } from "./components/PhaseRail";
import { CommandPalette } from "./components/CommandPalette";
import { ReanalysisProgressOverlay } from "./components/ReanalysisProgressOverlay";
import { HomeView } from "./components/HomeView";
import { PrepareView } from "./components/PrepareView";
import { RunView } from "./components/RunView";
import { InterrogateView } from "./components/InterrogateView";
import { WorkflowView } from "./components/WorkflowView";
import { CopilotView } from "./components/CopilotView";
import { HowToView } from "./components/HowToView";
import { useWorkspaceStore } from "./store/useWorkspaceStore";

function ViewFallback() {
  return <div className="view-fallback muted">Loading view…</div>;
}

export default function App() {
  const session = useWorkspaceStore((state) => state.session);
  const sessionStatus = useWorkspaceStore((state) => state.sessionStatus);
  const activePhase = useWorkspaceStore((state) => state.activePhase);
  const howToOpen = useWorkspaceStore((state) => state.howToOpen);
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
      <ReanalysisProgressOverlay />
      <CommandPalette />
      <AppHeader />
      <PhaseRail />
      <Suspense fallback={<ViewFallback />}>
        {howToOpen ? (
          <HowToView />
        ) : (
          <>
            {activePhase === "prepare" ? <PrepareView /> : null}
            {activePhase === "run" ? <RunView /> : null}
            {activePhase === "interrogate" ? <InterrogateView /> : null}
            {activePhase === "canvas" ? <WorkflowView /> : null}
            {activePhase === "copilot" ? <CopilotView /> : null}
          </>
        )}
      </Suspense>
    </main>
  );
}
