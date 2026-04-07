import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useNavigate } from "react-router-dom";

import { healthApi, sessionsApi } from "../../lib/api";
import type { ApiHealthResponse, SessionSummaryResponse } from "../../lib/types";
import { findNextIncompletePath } from "../../lib/workflow";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { MetricCard } from "../common/MetricCard";
import { StatusBadge } from "../common/StatusBadge";
import { StepNav } from "./StepNav";

function InspectorPanel({ health, summary }: { health?: ApiHealthResponse; summary?: SessionSummaryResponse }) {
  return (
    <aside className="inspector-panel">
      <div className="section-header">
        <div>
          <h2>Inspector</h2>
          <p>Runconfig and session-derived status from the shared backend state.</p>
        </div>
      </div>
      <div className="inspector-stack">
        <div className="content-card">
          <span className="eyebrow">API health</span>
          <StatusBadge tone={health?.status === "ok" ? "ok" : "warn"} text={health?.service ?? "Unavailable"} />
        </div>
        <div className="content-card">
          <span className="eyebrow">Completed steps</span>
          {summary?.completed_steps.length ? (
            <div className="tag-row">
              {summary.completed_steps.map((step) => (
                <span key={step} className="tag-pill">
                  {step}
                </span>
              ))}
            </div>
          ) : (
            <p className="muted-text">No workflow milestones completed yet.</p>
          )}
        </div>
        <div className="content-card">
          <span className="eyebrow">Runconfig snapshot</span>
          <dl className="definition-list">
            <div>
              <dt>Project</dt>
              <dd>{summary?.project_name ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Measurement</dt>
              <dd>{summary?.measurement_type ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Hub height</dt>
              <dd>{summary?.hub_height_m ? `${summary.hub_height_m} m` : "Not set"}</dd>
            </div>
            <div>
              <dt>Next route</dt>
              <dd>{findNextIncompletePath(summary)}</dd>
            </div>
          </dl>
        </div>
      </div>
    </aside>
  );
}

export function AppShell() {
  const navigate = useNavigate();
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const resetWorkspace = useWorkspaceStore((state) => state.resetWorkspace);
  const setSessionId = useWorkspaceStore((state) => state.setSessionId);
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: healthApi.get,
    staleTime: 30_000,
  });

  const summaryQuery = useQuery({
    queryKey: ["session-summary", sessionId],
    queryFn: () => sessionsApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const createSessionMutation = useMutation({
    mutationFn: sessionsApi.create,
    onSuccess: (response) => {
      setSessionId(response.session_id);
      void queryClient.invalidateQueries({ queryKey: ["session-summary"] });
    },
  });

  const resetSessionMutation = useMutation({
    mutationFn: () => sessionsApi.reset(sessionId ?? ""),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-summary", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["site-map", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["ltc-results", sessionId] });
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: () => sessionsApi.remove(sessionId ?? ""),
    onSuccess: () => {
      resetWorkspace();
      void queryClient.invalidateQueries({ queryKey: ["session-summary"] });
    },
  });

  const hasProjectName = typeof summaryQuery.data?.project_name === "string" && summaryQuery.data.project_name.trim().length > 0;
  const projectName = hasProjectName ? summaryQuery.data?.project_name ?? "" : "Project not named";
  const headerCopy = hasProjectName
    ? "Manage the workflow, inspect session state, and continue the next analysis step."
    : "Set the project name and site metadata from the Site page, then save the metadata to update this header.";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">GoKaatru workflow app</p>
          <h1>{projectName}</h1>
          <p className="header-copy">{headerCopy}</p>
        </div>
        <div className="header-actions">
          <div className="session-chip">
            <span>Session ID</span>
            <strong>{sessionId ?? "none"}</strong>
          </div>
          <div className="session-chip">
            <span>API</span>
            <strong>{healthQuery.data?.status ?? "checking"}</strong>
          </div>
          <button className="secondary-button" type="button" disabled={!sessionId} onClick={() => navigate("/site")}>
            {hasProjectName ? "Edit Metadata" : "Name Project"}
          </button>
          <button className="primary-button" type="button" onClick={() => createSessionMutation.mutate()}>
            {sessionId ? "Replace Session" : "Create Session"}
          </button>
          <button className="secondary-button" type="button" disabled={!sessionId} onClick={() => resetSessionMutation.mutate()}>
            Reset
          </button>
          <button className="ghost-button" type="button" disabled={!sessionId} onClick={() => deleteSessionMutation.mutate()}>
            Delete
          </button>
        </div>
      </header>

      <div className="layout-grid">
        <StepNav summary={summaryQuery.data} />
        <main className="page-panel">
          <div className="metric-grid">
            <MetricCard label="API" value={healthQuery.data?.service ?? "Unavailable"} tone="accent" />
            <MetricCard label="Workflow steps" value={String(summaryQuery.data?.completed_steps.length ?? 0)} />
            <MetricCard label="LTC runs" value={String(summaryQuery.data?.ltc_algorithms.length ?? 0)} />
            <MetricCard
              label="Hub height"
              value={summaryQuery.data?.hub_height_m ? `${summaryQuery.data.hub_height_m} m` : "Not set"}
            />
          </div>
          <Outlet />
        </main>
        <InspectorPanel health={healthQuery.data} summary={summaryQuery.data} />
      </div>
    </div>
  );
}