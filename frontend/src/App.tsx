import { Suspense, lazy, useEffect } from "react";

import { AppHeader } from "./components/AppHeader";
import { HomeView } from "./components/HomeView";
import { PhaseTabs } from "./components/PhaseTabs";
import { useWorkspaceStore } from "./store/useWorkspaceStore";

const SetupView = lazy(() => import("./components/SetupView").then((module) => ({ default: module.SetupView })));
const WorkflowView = lazy(() => import("./components/WorkflowView").then((module) => ({ default: module.WorkflowView })));
const WindKitExplorerView = lazy(() => import("./components/WindKitExplorerView").then((module) => ({ default: module.WindKitExplorerView })));
const CopilotView = lazy(() => import("./components/CopilotView").then((module) => ({ default: module.CopilotView })));
const CompareView = lazy(() => import("./components/CompareView").then((module) => ({ default: module.CompareView })));

function WorkspaceViewFallback() {
  return (
    <section className="panel placeholder-panel">
      <p className="panel-kicker">Loading view</p>
      <h2>Preparing workspace surface</h2>
      <p className="workspace-subtitle">Loading the selected analysis tab and its supporting tools.</p>
    </section>
  );
}

export default function App() {
  const session = useWorkspaceStore((state) => state.session);
  const sessionStatus = useWorkspaceStore((state) => state.sessionStatus);
  const sessionError = useWorkspaceStore((state) => state.sessionError);
  const activeTab = useWorkspaceStore((state) => state.activeTab);
  const summary = useWorkspaceStore((state) => state.summary);
  const busyLabel = useWorkspaceStore((state) => state.busyLabel);
  const bootstrapSession = useWorkspaceStore((state) => state.bootstrapSession);
  const refreshWorkspace = useWorkspaceStore((state) => state.refreshWorkspace);
  const restoreSession = useWorkspaceStore((state) => state.restoreSession);
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab);
  const apiBaseUrl = useWorkspaceStore((state) => state.apiBaseUrl);

  useEffect(() => {
    if (session === null && sessionStatus === "idle") {
      void restoreSession();
    }
  }, [restoreSession, session, sessionStatus]);

  if (session === null) {
    return (
      <HomeView
        apiBaseUrl={apiBaseUrl}
        busyLabel={busyLabel}
        onStart={() => void bootstrapSession()}
        sessionError={sessionError}
        sessionStatus={sessionStatus}
      />
    );
  }

  return (
    <main className="app-shell workspace-shell">
      <AppHeader busyLabel={busyLabel} onRefresh={() => void refreshWorkspace()} session={session} summary={summary} />
      <PhaseTabs activeTab={activeTab} onChange={setActiveTab} />

      <Suspense fallback={<WorkspaceViewFallback />}>
        {activeTab === "setup" ? <SetupView /> : null}
        {activeTab === "workflow" ? <WorkflowView /> : null}
        {activeTab === "windkit" ? <WindKitExplorerView /> : null}
        {activeTab === "copilot" ? <CopilotView /> : null}
        {activeTab === "compare" ? <CompareView /> : null}
      </Suspense>
    </main>
  );
}