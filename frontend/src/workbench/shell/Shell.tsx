import { useQuery } from "@tanstack/react-query";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent } from "dockview-react";
import { useCallback, useMemo, useRef } from "react";

import { api, unwrap } from "../api";
import { useTheme } from "../theme/theme";
import { PANELS, type PanelId, addDefaultLayout, forgetLayout, saveLayout, storedLayout } from "./layout";
import { emptyPanel } from "./panels";
import { GroupActions, TabTitle } from "./tabs";

export interface ShellProps {
  sessionId: string;
  projectId: string | null;
}

/** The workbench shell for one open campaign: header, docked panels, status bar. */
export function Shell({ sessionId, projectId }: ShellProps) {
  const [theme, toggleTheme] = useTheme();
  const dockview = useRef<DockviewApi | null>(null);

  const summary = useQuery({
    queryKey: ["session", sessionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
  });
  const project = useQuery({
    queryKey: ["project", projectId],
    enabled: projectId !== null,
    queryFn: async () =>
      unwrap(await api.GET("/api/projects/{project_id}", { params: { path: { project_id: projectId ?? "" } } })),
  });
  const campaign = project.data?.campaigns.find((item) => item.session_id === sessionId);

  const components = useMemo(
    () => Object.fromEntries(Object.entries(PANELS).map(([id, title]) => [id, emptyPanel(id as PanelId, title)])),
    [],
  );

  const onReady = useCallback((event: DockviewReadyEvent) => {
    dockview.current = event.api;
    const saved = storedLayout();
    let restored = false;
    if (saved) {
      try {
        event.api.fromJSON(saved);
        restored = true;
      } catch {
        forgetLayout();
      }
    }
    if (!restored) addDefaultLayout(event.api);
    event.api.onDidLayoutChange(() => saveLayout(event.api));
  }, []);

  const resetLayout = useCallback(() => {
    const current = dockview.current;
    if (!current) return;
    forgetLayout();
    addDefaultLayout(current);
    saveLayout(current);
  }, []);

  return (
    <div className="gk-app">
      <header className="gk-header">
        <a className="gk-brand" href="/workbench/">GoKaatru Workbench</a>
        <nav aria-label="Where you are" className="gk-crumbs">
          <span>{project.data?.name ?? "No project"}</span>
          <span aria-hidden="true">›</span>
          <span>{campaign?.name ?? summary.data?.project_name ?? "Campaign"}</span>
        </nav>
        <nav aria-label="Phases" className="gk-phases">
          <span className="gk-phase" aria-current="page">Prepare</span>
          <a className="gk-phase gk-phase-link" href="/" title="Model, Run and Interrogate stay in the current interface until Phase 3">
            Model, Run, Interrogate
          </a>
        </nav>
        <div className="gk-header-actions">
          <button type="button" className="gk-header-button" onClick={resetLayout}>
            Reset layout
          </button>
          <button type="button" className="gk-header-button" onClick={toggleTheme} aria-pressed={theme === "dark"}>
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
        </div>
      </header>
      <main className="gk-main">
        <DockviewReact
          className="dockview-theme-light gk-dockview"
          components={components}
          defaultTabComponent={TabTitle}
          rightHeaderActionsComponent={GroupActions}
          onReady={onReady}
        />
      </main>
      <footer className="gk-status" aria-label="Status">
        {summary.isError ? (
          <span role="alert">The campaign could not be read: {String(summary.error.message)}</span>
        ) : (
          <>
            <span>{summary.data?.timeseries_loaded ? "Records loaded" : "No records loaded"}</span>
            <span>{summary.data?.datamodel_loaded ? "Data model loaded" : "No data model"}</span>
          </>
        )}
      </footer>
    </div>
  );
}
