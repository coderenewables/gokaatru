import { useQuery } from "@tanstack/react-query";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent } from "dockview-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, unwrap } from "../api";
import { dropOnChart, useCharts } from "../charts/store";
import { WorkbenchDnd } from "../dnd";
import { useSelection } from "../selection/store";
import { useTheme } from "../theme/theme";
import { useHistory } from "../history/useHistory";
import { CampaignSwitcher } from "./CampaignSwitcher";
import { type Command, CommandPalette } from "./CommandPalette";
import { Campaign } from "./context";
import { keyCommand } from "./keys";
import { PANELS, type PanelId, addDefaultLayout, forgetLayout, saveLayout, storedLayout } from "./layout";
import { panelComponents } from "./panels";
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

  const components = useMemo(panelComponents, []);
  const open = useMemo(() => ({ sessionId, projectId }), [sessionId, projectId]);

  // A selection and the charts' channels belong to one campaign: opening another starts clean.
  useEffect(() => {
    useSelection.getState().clearAll();
    useCharts.getState().reset();
  }, [sessionId]);

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

  const history = useHistory(sessionId);
  const [palette, setPalette] = useState(false);
  const { undo, redo } = history;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const command = keyCommand(event);
      if (command === null) return;
      event.preventDefault();
      if (command === "palette") setPalette(true);
      else if (command === "undo") undo();
      else redo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  const showPanel = useCallback((id: PanelId) => {
    const current = dockview.current;
    if (!current) return;
    const panel = current.getPanel(id) ?? current.addPanel({ id, component: id, title: PANELS[id] });
    panel.api.setActive();
  }, []);

  const commands: Command[] = [
    { id: "undo", label: "Undo the last change", run: undo, disabled: !history.canUndo },
    { id: "redo", label: "Redo", run: redo, disabled: !history.canRedo },
    { id: "clear", label: "Clear the selection", run: () => useSelection.getState().clearAll() },
    ...(Object.keys(PANELS) as PanelId[]).map((id) => ({
      id: `show-${id}`,
      label: `Show the ${PANELS[id]} panel`,
      run: () => showPanel(id),
    })),
    { id: "reset", label: "Reset the layout", run: resetLayout },
    { id: "theme", label: theme === "dark" ? "Use the light theme" : "Use the dark theme", run: toggleTheme },
  ];
  const log = history.log;
  const stale = log?.stale_artifacts ?? [];

  return (
    <div className="gk-app">
      <header className="gk-header">
        <a className="gk-brand" href="/workbench/">GoKaatru Workbench</a>
        <nav aria-label="Where you are" className="gk-crumbs">
          <span>{project.data?.name ?? "No project"}</span>
          <span aria-hidden="true">›</span>
          {project.data && projectId ? (
            <CampaignSwitcher projectId={projectId} sessionId={sessionId} campaigns={project.data.campaigns} />
          ) : (
            <span>{campaign?.name ?? summary.data?.project_name ?? "Campaign"}</span>
          )}
        </nav>
        <nav aria-label="Phases" className="gk-phases">
          <span className="gk-phase" aria-current="page">Prepare</span>
          <a className="gk-phase gk-phase-link" href="/" title="Model, Run and Interrogate stay in the current interface until Phase 3">
            Model, Run, Interrogate
          </a>
        </nav>
        <div className="gk-header-actions">
          <button
            type="button"
            className="gk-header-button"
            onClick={undo}
            disabled={!history.canUndo}
            aria-keyshortcuts="Control+Z"
            title="Undo the last change (Ctrl+Z)"
          >
            Undo
          </button>
          <button
            type="button"
            className="gk-header-button"
            onClick={redo}
            disabled={!history.canRedo}
            aria-keyshortcuts="Control+Shift+Z Control+Y"
            title="Redo (Ctrl+Shift+Z)"
          >
            Redo
          </button>
          <button
            type="button"
            className="gk-header-button"
            onClick={() => setPalette(true)}
            aria-keyshortcuts="Control+K"
            title="Every command (Ctrl+K)"
          >
            Commands
          </button>
          <button type="button" className="gk-header-button" onClick={resetLayout}>
            Reset layout
          </button>
          <button type="button" className="gk-header-button" onClick={toggleTheme} aria-pressed={theme === "dark"}>
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
        </div>
      </header>
      <main className="gk-main">
        <Campaign.Provider value={open}>
          <WorkbenchDnd onDrop={dropOnChart}>
            <DockviewReact
              className="dockview-theme-light gk-dockview"
              components={components}
              defaultTabComponent={TabTitle}
              rightHeaderActionsComponent={GroupActions}
              onReady={onReady}
            />
          </WorkbenchDnd>
        </Campaign.Provider>
      </main>
      <footer className="gk-status" aria-label="Status">
        {summary.isError ? (
          <span role="alert">The campaign could not be read: {String(summary.error.message)}</span>
        ) : (
          <>
            <span>{summary.data?.timeseries_loaded ? "Records loaded" : "No records loaded"}</span>
            <span>{summary.data?.datamodel_loaded ? "Data model loaded" : "No data model"}</span>
            {log && (
              <>
                <span>{log.total === 1 ? "1 action" : `${log.total} actions`}</span>
                <span>data version {log.data_version}</span>
              </>
            )}
            {history.prefix && <span title={history.prefix.fixed_prefix_hash}>prefix {history.prefix.fixed_prefix_hash.slice(0, 8)}</span>}
            {stale.length > 0 && (
              <span className="gk-stale" title={log?.warning ?? undefined}>
                {stale.length === 1 ? "1 result stale" : `${stale.length} results stale`}
              </span>
            )}
            <span aria-live="polite" className="gk-status-said">
              {history.said}
            </span>
          </>
        )}
      </footer>
      {palette && <CommandPalette commands={commands} onClose={() => setPalette(false)} />}
    </div>
  );
}
